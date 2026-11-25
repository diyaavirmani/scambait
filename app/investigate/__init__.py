"""Kane investigator: Meena's hands on the web.

When a scammer sends a link, Kane CLI opens it in a real browser as a first-time victim, follows the page's steps
until it asks for money, a PIN, a card or an OTP, and stops there. It reports what the page claims to be, who it
would pay, how much and what it asked for, with a screenshot of every step. That turns intel the scammer only
said ("pay xyz@upi") into intel the scam page itself proves.

Flow: start_investigation() records a queued row and runs Kane in the background, one browser at a time.
Results are stored in the investigations table, the evidence pack is hashed into the evidence table, and
`kane.started` / `kane.finished` events go to the dashboard. Listeners registered with on_finding() are called
with each finished investigation (the persona uses this to bring the finding into its next reply).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.investigate.kane import KaneResult, run_kane
from app.investigate.safety import check_link
from app.models import utc_now
from app.runtime import get_runtime

log = logging.getLogger("scambait.investigate")

DEFAULT_IDENTITY = {"name": "Meena Sharma", "city": "Jaipur", "phone": "9000000002"}

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
    rt = get_runtime()
    s = rt.settings
    store = rt.store
    existing = await store.find_investigation(case_id, url)
    if existing is not None and existing["status"] not in ("error", "not_started"):
        return existing
    blocked = check_link(url, public_base_url=s.public_base_url, live=s.live_investigation)
    if blocked is None and not s.kane_enabled:
        blocked = "Kane investigations are turned off (KANE_ENABLED=0)."
    if blocked is not None:
        inv_id = await store.add_investigation(case_id, url, status="skipped")
        await store.update_investigation(inv_id, verdict="skipped", reason=blocked, finished_at=utc_now())
        row = await store.get_investigation(inv_id)
        await _emit(case_id, channel, "kane.finished", _event_data(row))
        return row
    inv_id = await store.add_investigation(case_id, url)
    row = await store.get_investigation(inv_id)
    task = _spawn(run_investigation(inv_id, url, case_id, channel))
    if wait:
        await task
        row = await store.get_investigation(inv_id)
    return row


async def run_investigation(inv_id: int, url: str, case_id: Optional[str], channel: str) -> dict:
    rt = get_runtime()
    s = rt.settings
    store = rt.store
    async with _browser_lock():
        await store.update_investigation(inv_id, status="running")
        await _emit(case_id, channel, "kane.started", {"investigation_id": inv_id, "url": url})
        result = await run_kane(build_objective(), url, cmd=s.kane_cmd, timeout_s=s.kane_timeout_s,
                                max_steps=s.kane_max_steps, headless=s.kane_headless, workdir=s.kane_workdir,
                                username=s.kane_username, access_key=s.kane_access_key)
    finding = normalise_finding(result)
    sha = _sha256(result.evidence_path) if result.evidence_path else ""
    summary = result.summary or result.one_liner
    final_state = dict(result.final_state or {})
    if is_replay(s.kane_cmd):
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
    row = await store.get_investigation(inv_id)
    await _emit(case_id, channel, "kane.finished", _event_data(row))
    for fn in list(_listeners):
        try:
            await fn(row)
        except Exception:
            log.exception("finding listener failed")
    return row


def _event_data(row: dict) -> dict:
    keys = ("id", "url", "status", "verdict", "claims_to_be", "payee", "payee_kind", "amount", "asked_for",
            "summary", "reason", "steps", "credits", "duration_s", "evidence_sha256")
    data = {k: row.get(k) for k in keys}
    data["investigation_id"] = data.pop("id")
    data["evidence"] = bool(row.get("evidence_path"))
    data["replayed"] = bool((row.get("final_state") or {}).get("_replayed"))
    return data


async def drain() -> None:
    """Tests and shutdown: wait for running investigations."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


__all__ = ["start_investigation", "run_investigation", "on_finding", "build_objective", "normalise_finding",
           "drain", "check_link"]
