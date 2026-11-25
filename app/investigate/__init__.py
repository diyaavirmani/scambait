"""Kane investigator: Meena's hands on the web.

When a scammer sends a link, Kane CLI opens it in a real browser as a first-time victim, follows the page's steps
until it asks for money, a PIN, a card or an OTP, and stops there. It reports what the page claims to be, who it
would pay, how much and what it asked for, with a screenshot of every step. That turns intel the scammer only
said ("pay xyz@upi") into intel the scam page itself proves.

Flow: start_investigation() records a queued row and runs Kane in the background, one browser at a time.
Results are stored in the investigations table, the evidence pack is hashed into the evidence table, and
`kane.started` / `kane.finished` events go to the dashboard. Listeners registered with on_finding() are called
with each finished investigation (the persona uses this to bring the finding into its next reply).

Payee-rotation probe: real scam pages often show each new visitor a different mule account. So after a run proves
a payee, the same link is opened again as a fresh first-time visitor, KANE_ROTATION_CHECKS times (default 1, at most
2, 0 turns it off), one after another. Each re-check is a normal investigation (same browser lock, link safety check
and step guard) whose recheck_of is the first run; re-checks never start re-checks. After each one, rotation_facts()
is stored on every run of that link: the payees seen so far, in order, and whether the payee changed. A re-check
that shows a new payee is a finding of its own, so Meena can ask which account is right. With the replay
investigator (scripts/kane_replay.py), a re-check runs only when a real Kane run of that later visit was recorded,
so a replay never passes the first visit off as a second one.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.config import MAX_ROTATION_CHECKS
from app.investigate.kane import KaneResult, run_kane
from app.investigate.safety import check_link
from app.models import utc_now
from app.runtime import get_runtime

log = logging.getLogger("scambait.investigate")

DEFAULT_IDENTITY = {"name": "Meena Sharma", "city": "Jaipur", "phone": "9000000002"}
RECORDINGS = Path(__file__).resolve().parents[2] / "kane" / "recordings"  # scripts/kane_replay.py reads these

# Shaped by real Kane runs on the practice lab (docs/kane-log.md, catches 2 to 5):
# - forbidding the PIN while also asking Kane to fill in "anything else" made it give up on payment pages whose only
#   fields are PIN, card or CVV, so the payment page with its fields left empty is the stated finish line;
# - Kane may store values under its own names, so they are read by meaning too (catch 5);
# - an objective written in labelled parts was split by Kane into separate flows, and the flow that filled in forms
#   never saw the safety rule, so it typed a UPI PIN and pressed pay. The objective is one flow, the safety rule
#   comes first, and "PIN" appears only in the list of fields that must never be touched.
# app/investigate/guard.py still checks every step Kane reports, in case a run breaks the rule anyway.
OBJECTIVE = (
    "Safety rule for this whole test, before anything else: never type anything, not even a fake value, into a UPI "
    "PIN, card number, expiry, CVV, OTP or payment reference field, and never press a button that pays, deposits, "
    "transfers or submits payment. "
    "You are checking a suspected scam website for a fraud report, as a first-time visitor named {name} from "
    "{city}, phone {phone}. Press the site's ordinary buttons (such as Continue, Start, Login, Withdraw, Submit task "
    "or Check bill) and fill in only ordinary details: that name and phone, and an obviously fake value for other "
    "ordinary fields such as a date of birth, postal code or consumer number. "
    "When a page asks you to pay money or shows payment fields, that payment page is the end of the test: leave its "
    "fields empty, press nothing on it, download nothing, and read it. Store exactly four values with exactly these "
    "names: claims_to_be (what the site claims to be), payee (the UPI ID or bank account number it asks you to pay), "
    "amount (the amount it asks for) and asked_for (every personal detail any page asked for). Then finish the test "
    "as passed. Empty payment fields on that page are expected and are not a problem."
)

Listener = Callable[[dict], Awaitable[None]]
_listeners: list[Listener] = []
_browser: list = []  # [(loop, semaphore)]: one Chrome at a time, per event loop
_tasks: set = set()


def _browser_lock() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    for owner, sem in _browser:
        if owner is loop:
            return sem
    _browser[:] = [(loop, asyncio.Semaphore(1))]
    return _browser[0][1]


def is_replay(kane_cmd: str) -> bool:
    """True when KANE_CMD is scripts/kane_replay.py (recorded real runs) rather than the live Kane CLI."""
    return "kane_replay" in (kane_cmd or "")


def replay_recorded(url: str, visit: int) -> bool:
    """Whether scripts/kane_replay.py holds a real Kane run recorded on this fresh visit to this lab link: visit 1 is
    kane/recordings/<site>.ndjson, visit n is <site>.<n>.ndjson (KANE_RECORDINGS moves the folder)."""
    key = url.split("/lab/", 1)[1].split("/")[0].split("?")[0] if "/lab/" in url else ""
    name = f"{key}.ndjson" if visit == 1 else f"{key}.{visit}.ndjson"
    return bool(key) and (Path(os.getenv("KANE_RECORDINGS") or RECORDINGS) / name).is_file()


def rotation_checks(settings: Any) -> int:
    """How many fresh-visitor re-checks follow a proven payee: KANE_ROTATION_CHECKS, never above the cap."""
    return max(0, min(int(getattr(settings, "kane_rotation_checks", 0) or 0), MAX_ROTATION_CHECKS))


def build_objective(identity: Optional[dict] = None) -> str:
    return OBJECTIVE.format(**{**DEFAULT_IDENTITY, **(identity or {})})


def on_finding(fn: Listener) -> Listener:
    """Register a coroutine called with every finished investigation row."""
    if fn not in _listeners:
        _listeners.append(fn)
    return fn


def _as_list(v: Any) -> list[str]:
    """A list from Kane's final_state value. Kane may store a list as a JSON-encoded string ('["UPI PIN"]'):
    caught on the first real Kane run, where it came back as one item with brackets and quotes."""
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            v = json.loads(v)
        except ValueError:
            v = v.strip().strip("[]")
    if isinstance(v, list):
        return [str(x).strip().strip('"') for x in v if str(x).strip()]
    if isinstance(v, str):
        return [p.strip().strip('"') for p in re.split(r",|;|\band\b|\n", v) if p.strip()]
    return []


def _amount(v: Any) -> str:
    digits = re.sub(r"(?<=\d),(?=\d)", "", str(v or ""))
    m = re.search(r"\d+(?:\.\d+)?", digits)
    return m.group(0) if m else ""


def _pick(state: dict, exact: str, similar: tuple[str, ...], avoid: tuple[str, ...] = ()) -> Any:
    """The value stored under `exact`, else under the first key that contains one of `similar` and none of `avoid`.
    Kane does not always keep the names it is asked for (docs/kane-log.md, catch 5): it stored the payee as
    payee_bank_account or requested_upi_id and the claim as site_claim or site_name."""
    if state.get(exact) not in (None, ""):
        return state[exact]
    for key, value in state.items():
        if value in (None, "") or key == "url":
            continue
        if any(s in key for s in similar) and not any(a in key for a in avoid):
            return value
    return None


def _payee(state: dict) -> tuple[str, str]:
    """(payee, kind): the named value if it holds a valid UPI ID or account number, else any stored value that does."""
    from app.intel import extract
    raw = _pick(state, "payee", ("payee", "upi", "account", "beneficiary", "pay_to"), ("amount",))
    candidates = [raw] + [v for k, v in state.items() if k != "url" and v is not raw]
    for value in candidates:
        for c in extract(str(value or "")):
            if c.kind in ("upi", "bank_account"):
                return c.value, c.kind
    return (str(raw).strip() if raw else ""), ""


def normalise_finding(result: KaneResult) -> dict[str, Any]:
    """Pick the payee, amount and claims out of Kane's final_state and decide the verdict."""
    state = {str(k).lower(): v for k, v in (result.final_state or {}).items() if not str(k).startswith("_")}
    payee, payee_kind = _payee(state)
    claims = _pick(state, "claims_to_be", ("claim", "site_name", "brand", "pretend", "site"))
    amount = _pick(state, "amount", ("amount", "fee", "price", "total"))
    asked = _pick(state, "asked_for", ("asked", "requested", "details", "fields"),
                  ("amount", "upi", "payee", "account", "url"))
    finding = {
        "claims_to_be": str(claims or "").strip(),
        "payee": payee,
        "payee_kind": payee_kind,
        "amount": _amount(amount),
        "asked_for": _as_list(asked),
    }
    from app.investigate.guard import unsafe_actions
    unsafe = unsafe_actions(result.steps)
    if unsafe:
        verdict = "unsafe_run"  # Kane typed into a payment field or pressed pay: never counted as proof
    elif result.status == "passed":
        verdict = "payment_request_found" if payee else "no_payee_found"
    elif result.status == "failed":
        verdict = "payment_request_found" if payee_kind else "inconclusive"
    else:
        verdict = result.status
    finding["verdict"] = verdict
    finding["unsafe_actions"] = unsafe
    return finding


def _sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


async def _emit(case_id: Optional[str], channel: str, type_: str, data: dict) -> None:
    from app.bus import emit
    await emit(type_, data, case_id=case_id, channel=channel)


def _spawn(coro) -> asyncio.Task:
    async def runner():
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("investigation task failed")
    t = asyncio.create_task(runner())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def start_investigation(url: str, case_id: Optional[str] = None, channel: str = "api",
                              *, wait: bool = False) -> dict:
    """Queue Kane on a link (once per case and link). Returns the investigation row; with wait=True, the
    finished row. A link that may not be opened is stored as skipped with the reason."""
    store = get_runtime().store
    existing = await store.find_investigation(case_id, url)
    if existing is not None and existing["status"] not in ("error", "not_started"):
        return existing
    blocked = _blocked(url)
    if blocked is not None:
        return await _skip(url, case_id, channel, blocked)
    inv_id = await store.add_investigation(case_id, url)
    row = await store.get_investigation(inv_id)
    task = _spawn(run_investigation(inv_id, url, case_id, channel))
    if wait:
        await task
        row = await store.get_investigation(inv_id)
    return row


def _blocked(url: str) -> Optional[str]:
    """None when Kane may open the link now, otherwise why not."""
    s = get_runtime().settings
    blocked = check_link(url, public_base_url=s.public_base_url, live=s.live_investigation)
    if blocked is None and not s.kane_enabled:
        blocked = "Kane investigations are turned off (KANE_ENABLED=0)."
    return blocked


async def _skip(url: str, case_id: Optional[str], channel: str, reason: str,
                recheck_of: Optional[int] = None) -> dict:
    store = get_runtime().store
    inv_id = await store.add_investigation(case_id, url, status="skipped", recheck_of=recheck_of)
    await store.update_investigation(inv_id, verdict="skipped", reason=reason, finished_at=utc_now())
    if recheck_of is not None:
        await _store_rotation(recheck_of)
    row = await store.get_investigation(inv_id)
    await _emit(case_id, channel, "kane.finished", _event_data(row))
    return row


async def run_investigation(inv_id: int, url: str, case_id: Optional[str], channel: str, *,
                            recheck_of: Optional[int] = None, visit: int = 1) -> dict:
    """Run Kane on one queued row and store what it proved. recheck_of and visit are set on a fresh-visitor
    re-check (visit 2 is the first re-check); only a first run can start re-checks."""
    rt = get_runtime()
    s = rt.settings
    store = rt.store
    replay = is_replay(s.kane_cmd)
    async with _browser_lock():
        await store.update_investigation(inv_id, status="running")
        await _emit(case_id, channel, "kane.started",
                    {"investigation_id": inv_id, "url": url, "recheck_of": recheck_of})
        result = await run_kane(build_objective(), url, cmd=s.kane_cmd, timeout_s=s.kane_timeout_s,
                                max_steps=s.kane_max_steps, headless=s.kane_headless, workdir=s.kane_workdir,
                                username=s.kane_username, access_key=s.kane_access_key,
                                env={"KANE_REPLAY_VISIT": str(visit)} if replay else None)
    finding = normalise_finding(result)
    sha = _sha256(result.evidence_path) if result.evidence_path else ""
    summary = result.summary or result.one_liner
    final_state = dict(result.final_state or {})
    if replay:
        # Hosts without Chrome replay a real recorded Kane run; it must never look like a live one.
        final_state["_replayed"] = True
        summary = "Replay of a real Kane CLI run recorded from the practice lab. " + summary
    reason = result.reason
    if finding["unsafe_actions"]:
        final_state["_unsafe_actions"] = finding["unsafe_actions"]
        reason = ("Safety rule broken: Kane typed into a payment field or pressed a pay button ("
                  + "; ".join(finding["unsafe_actions"])[:300] + "). Not counted as proof.")
    await store.update_investigation(
        inv_id, status=result.status, verdict=finding["verdict"], claims_to_be=finding["claims_to_be"],
        payee=finding["payee"], payee_kind=finding["payee_kind"], amount=finding["amount"],
        asked_for=finding["asked_for"], final_state=final_state, summary=summary,
        reason=reason, steps=result.steps, credits=result.credits, duration_s=result.duration_s,
        exit_code=result.exit_code, evidence_path=result.evidence_path, evidence_sha256=sha, finished_at=utc_now())
    if case_id and result.evidence_path and sha:
        try:
            await store.add_evidence(case_id, "kane_evidence", result.evidence_path, sha)
        except Exception:
            log.exception("evidence row failed")
    if recheck_of is not None:
        await _store_rotation(recheck_of)
    row = await store.get_investigation(inv_id)
    await _emit(case_id, channel, "kane.finished", _event_data(row))
    for fn in list(_listeners):
        try:
            await fn(row)
        except Exception:
            log.exception("finding listener failed")
    if recheck_of is None and row["verdict"] == "payment_request_found" and rotation_checks(s):
        _spawn(recheck_payee(row, channel))
    return row


async def recheck_payee(first: dict, channel: str) -> None:
    """The payee-rotation probe: open a link whose payee Kane proved again as a fresh first-time visitor, up to
    KANE_ROTATION_CHECKS times, one after another. Stops early when a visit may not be opened, Kane could not run,
    or a run broke the safety rule."""
    rt = get_runtime()
    s, store = rt.settings, rt.store
    url, case_id = first["url"], first["case_id"]
    for visit in range(2, rotation_checks(s) + 2):
        if is_replay(s.kane_cmd) and not replay_recorded(url, visit):
            return
        blocked = _blocked(url)  # checked again: a live host can start resolving somewhere else
        if blocked is not None:
            await _skip(url, case_id, channel, "Fresh-visit re-check not run: " + blocked, recheck_of=first["id"])
            return
        inv_id = await store.add_investigation(case_id, url, recheck_of=first["id"])
        row = await run_investigation(inv_id, url, case_id, channel, recheck_of=first["id"], visit=visit)
        if row["status"] not in ("passed", "failed") or row["verdict"] == "unsafe_run":
            return


def _payee_key(row: dict) -> tuple[str, str]:
    from app.intel import normalise
    kind = row.get("payee_kind") or ""
    return kind, normalise(kind, row.get("payee") or "")


def rotation_facts(family: list[dict]) -> dict:
    """What the visits to one link showed, from its first run and re-checks in order (pure, so easy to test):
    first_id, rechecks (re-check ids in order), payees (each different proven payee once, in the order first seen,
    as {payee, payee_kind, visit, investigation_id}), proven_visits (how many visits proved a payee), rotated (Kane
    saw more than one payee) and replayed (a visit replayed a recorded run). Stored on every run of the link, each
    with its own visit number and new_payee (this re-check showed a payee no earlier visit showed)."""
    payees, seen, proven = [], set(), 0
    for visit, row in enumerate(family, start=1):
        if row.get("verdict") != "payment_request_found" or not row.get("payee"):
            continue
        proven += 1
        key = _payee_key(row)
        if key not in seen:
            seen.add(key)
            payees.append({"payee": row["payee"], "payee_kind": row.get("payee_kind") or "", "visit": visit,
                           "investigation_id": row["id"]})
    return {"first_id": family[0]["id"], "rechecks": [r["id"] for r in family[1:]], "payees": payees,
            "proven_visits": proven, "rotated": len(payees) > 1,
            "replayed": any(bool((r.get("final_state") or {}).get("_replayed")) for r in family)}


async def _store_rotation(first_id: int) -> None:
    store = get_runtime().store
    family = await store.investigation_family(first_id)
    if not family:
        return
    facts = rotation_facts(family)
    firsts = {p["investigation_id"] for p in facts["payees"]}
    for visit, row in enumerate(family, start=1):
        await store.update_investigation(row["id"], rotation={
            **facts, "visit": visit, "new_payee": visit > 1 and row["id"] in firsts})


def _event_data(row: dict) -> dict:
    keys = ("id", "url", "status", "verdict", "claims_to_be", "payee", "payee_kind", "amount", "asked_for",
            "summary", "reason", "steps", "credits", "duration_s", "evidence_sha256", "recheck_of")
    data = {k: row.get(k) for k in keys}
    data["investigation_id"] = data.pop("id")
    data["evidence"] = bool(row.get("evidence_path"))
    data["replayed"] = bool((row.get("final_state") or {}).get("_replayed"))
    data["rotation"] = row.get("rotation") or None
    return data


async def drain() -> None:
    """Tests and shutdown: wait for running investigations."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


__all__ = ["start_investigation", "run_investigation", "recheck_payee", "rotation_facts", "on_finding",
           "build_objective", "normalise_finding", "drain", "check_link"]
