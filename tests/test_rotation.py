"""Payee-rotation probe: the rotating practice site, the fresh-visitor re-checks Kane makes after it proves a payee,
and where a changed payee goes (the dashboard data, the networks hook, Meena's findings, the Intelligence list).

Kane is tests/fixtures/fake_kane.py: every run is a fresh browser, and on /lab/loan run n gets the n-th payee."""
import asyncio
import io
import json
import re
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cases, engine, meena, networks
from app import investigate as inv_mod
from app.brain import persona_messages
from app.config import Settings
from app.intel import normalise
from app.investigate import drain, rotation_checks, rotation_facts, start_investigation
from app.investigate.api import router as api_router
from app.lab import router as lab_router
from app.lab.sites import SITES, SITES_BY_KEY
from app.store import SCHEMA, Store

ROOT = Path(__file__).resolve().parent.parent
LAB_LOAN = "http://127.0.0.1:8000/lab/loan"
LAB_KYC = "http://127.0.0.1:8000/lab/kyc"
LOAN = SITES_BY_KEY["loan"]
P0, P1, P2 = LOAN.answer.payees


@pytest.fixture(autouse=True)
def fresh_networks():
    networks.reset()
    yield
    networks.reset()


@pytest.fixture
def kane_log(tmp_path, monkeypatch):
    log = tmp_path / "kane-calls.log"
    monkeypatch.setenv("FAKE_KANE_LOG", str(log))
    return log


def runs(log: Path, url: str = "/lab/loan") -> int:
    return log.read_text().count(url) if log.exists() else 0


def checks(rt, n: int) -> None:
    rt.settings = replace(rt.settings, kane_rotation_checks=n)


async def new_case(store, external="web:rot") -> str:
    return (await store.new_case("web", external))["id"]


# ---------- the practice site ----------
def lab_client() -> TestClient:
    app = FastAPI()
    app.include_router(lab_router)
    return TestClient(app)


def payee_shown(client: TestClient) -> str:
    """Walk the loan site like a visitor and read the payee on its payment step."""
    page = client.get("/lab/loan")
    for n in range(len(LOAN.steps) - 1):
        page = client.post(f"/lab/loan/{n}", data={f.name: "Meena Sharma" for f in LOAN.steps[n].fields},
                           follow_redirects=True)
    assert f"Step {len(LOAN.steps)} of {len(LOAN.steps)}" in page.text
    return re.search(r"Pay to UPI ID</th><td>([^<]+)</td>", page.text).group(1)


def test_each_fresh_visitor_sees_the_next_payee_and_reset_starts_again():
    first = lab_client()
    first.post("/lab/api/reset")
    seen = [payee_shown(c) for c in (first, lab_client(), lab_client(), lab_client())]
    assert seen == [P0, P1, P2, P0]
    assert payee_shown(first) == P0  # the same browser keeps its payee
    activity = first.get("/lab/api/activity").json()["loan"]
    assert activity["visitors"] == 4 and activity["payment_attempts"] == 0
    assert [(x["visitor"], x["payee"]) for x in activity["payees_shown"]] == [(1, P0), (2, P1), (3, P2), (4, P0)]
    first.post("/lab/api/reset")
    after = first.get("/lab/api/activity").json()["loan"]
    assert after["visitors"] == 0 and after["payees_shown"] == []
    assert payee_shown(first) == P0  # a cookie from before the reset is a new visitor
    assert payee_shown(lab_client()) == P1


def test_sites_that_do_not_rotate_set_no_cookie_and_log_no_payees():
    client = lab_client()
    client.post("/lab/api/reset")
    assert "lab_visitor" not in client.get("/lab/kyc").headers.get("set-cookie", "")
    assert "payees_shown" not in client.get("/lab/api/activity").json()["kyc"]
    assert [s.key for s in SITES if s.rotates] == ["loan"]


def test_the_rotating_answer_is_fictional_and_listed():
    a = LOAN.answer
    assert a.payee == P0 and len(set(a.payees)) == 3 and all(p.endswith("@demoupi") for p in a.payees)
    assert all(a.is_payee(p.upper()) for p in a.payees) and not a.is_payee("someone@demoupi")
    assert SITES_BY_KEY["kyc"].answer.is_payee("bharatunity.kyc@demoupi")
    client = lab_client()
    index = client.get("/lab").text
    assert all(p in index for p in a.payees) and "changes for each fresh visitor" in index
    listed = next(s for s in client.get("/lab/api/sites").json()["sites"] if s["key"] == "loan")
    assert listed["answer"]["payees"] == list(a.payees)


# ---------- the setting ----------
@pytest.mark.parametrize("raw,want", [("", 1), ("0", 0), ("1", 1), ("2", 2), ("9", 2), ("-1", 1), ("x", 1)])
def test_kane_rotation_checks_defaults_to_one_and_is_capped_at_two(monkeypatch, raw, want):
    monkeypatch.setenv("KANE_ROTATION_CHECKS", raw)
    assert Settings().kane_rotation_checks == want
    assert rotation_checks(Settings(kane_rotation_checks=7)) == 2
    assert rotation_checks(Settings(kane_rotation_checks=-3)) == 0


# ---------- the investigator ----------
@pytest.mark.parametrize("n", [1, 2, 5])
async def test_a_proven_link_gets_exactly_the_configured_rechecks_and_they_never_chain(runtime, kane_log, n):
    checks(runtime, n)
    store = runtime.store
    cid = await new_case(store)
    first = await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    want = min(n, 2)
    assert runs(kane_log) == 1 + want
    rows = await store.list_investigations(cid)
    assert [r["recheck_of"] for r in rows] == [None] + [first["id"]] * want  # every re-check points at the first run
    assert [r["rotation"]["visit"] for r in rows] == list(range(1, want + 2))
    assert [r["payee"] for r in rows] == [P0, P1, P2][:want + 1]
    again = await start_investigation(LAB_LOAN, cid, "web", wait=True)  # the scammer sends the link again
    await drain()
    assert again["id"] == first["id"] and runs(kane_log) == 1 + want


async def test_a_recheck_run_directly_starts_no_recheck_of_its_own(runtime, kane_log):
    checks(runtime, 2)
    store = runtime.store
    cid = await new_case(store)
    first = await store.add_investigation(cid, LAB_LOAN)
    await store.update_investigation(first, status="passed", verdict="payment_request_found", payee=P0,
                                     payee_kind="upi")
    second = await store.add_investigation(cid, LAB_LOAN, recheck_of=first)
    row = await inv_mod.run_investigation(second, LAB_LOAN, cid, "web", recheck_of=first, visit=2)
    await drain()
    assert row["verdict"] == "payment_request_found" and runs(kane_log) == 1
    assert len(await store.list_investigations(cid)) == 2


async def test_zero_turns_the_probe_off(runtime, kane_log):
    checks(runtime, 0)
    cid = await new_case(runtime.store)
    row = await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    assert runs(kane_log) == 1 and len(await runtime.store.list_investigations(cid)) == 1
    assert row["recheck_of"] is None and row["rotation"] == {}
    finished = [e for e in await runtime.store.events_for_case(cid) if e.type == "kane.finished"]
    assert finished[0].data["rotation"] is None and finished[0].data["recheck_of"] is None
    client = api_client()
    assert client.get(f"/api/investigations/{row['id']}").json()["rotation"] is None


def api_client() -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    return TestClient(app)


async def test_a_different_payee_marks_the_rotation_in_events_and_the_api(runtime, kane_log):
    checks(runtime, 1)
    store = runtime.store
    cid = await new_case(store)
    await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    first, again = await store.list_investigations(cid)
    rot = again["rotation"]
    assert rot["rotated"] is True and rot["first_id"] == first["id"] and rot["rechecks"] == [again["id"]]
    assert [(p["payee"], p["visit"], p["investigation_id"]) for p in rot["payees"]] == [
        (P0, 1, first["id"]), (P1, 2, again["id"])]
    assert rot["proven_visits"] == 2 and rot["replayed"] is False
    assert (rot["visit"], rot["new_payee"]) == (2, True)
    head = first["rotation"]
    assert (head["visit"], head["new_payee"], head["rotated"]) == (1, False, True)

    events = await store.events_for_case(cid)
    assert [e.type for e in events] == ["kane.started", "kane.finished"] * 2
    assert events[2].data["recheck_of"] == first["id"]  # the re-check is marked from the start
    done = events[3].data
    assert done["investigation_id"] == again["id"] and done["recheck_of"] == first["id"]
    assert done["rotation"]["rotated"] is True and [p["payee"] for p in done["rotation"]["payees"]] == [P0, P1]

    client = api_client()
    body = client.get(f"/api/investigations/{again['id']}").json()
    assert body["recheck_of"] == first["id"] and body["rotation"]["new_payee"] is True
    assert client.get(f"/api/investigations/{first['id']}").json()["rotation"]["rotated"] is True
    listed = client.get("/api/investigations", params={"case_id": cid}).json()["investigations"]
    assert [i["recheck_of"] for i in listed] == [None, first["id"]]


async def test_a_new_payee_reaches_networks_intelligence_and_meena(runtime, kane_log):
    checks(runtime, 1)
    store = runtime.store
    said = await new_case(store, "web:said")
    await store.add_intel(said, "upi", P1, normalise("upi", P1), None)  # another chat named the rotated payee
    cid = await new_case(store)
    await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    sent = [e for e in await store.events_after(0) if e.type == "network.updated"]
    assert sent and sent[-1].data["case_ids"] == [said, cid]

    first, again = await store.list_investigations(cid)
    assert [f["id"] for f in await store.unused_findings(cid)] == [first["id"], again["id"]]
    line = meena.finding_sentence(again)
    assert "different name to pay" in line and P1 in line and P0 in line and "which account" in line
    assert P0 in meena.finding_sentence(first) and "different" not in meena.finding_sentence(first)

    intel = (await cases.all_intel())["intel"]
    kane_only = [r for r in intel if r["case_id"] == cid and r["kind"] == "upi"]
    assert {r["value"] for r in kane_only} == {P0, P1} and all(r["proven"] and r["id"] < 0 for r in kane_only)
    assert any(r["case_id"] == said and r["value"] == P1 and r["proven"] for r in intel)


async def test_meena_gets_the_changed_payee_in_her_next_reply(runtime, kane_log):
    checks(runtime, 1)
    store = runtime.store
    cid = (await store.open_case("web", "web:meena"))["id"]
    r1 = await engine.handle_message(cid, "web", f"{LOAN.lure} {LAB_LOAN}")
    assert r1.verdict == "scam"
    await engine.settle()
    await drain()
    assert runs(kane_log) == 2
    await engine.handle_message(cid, "web", "Did you pay the fee? Hurry.")
    used = [e.data["kane_findings_used"] for e in await store.events_for_case(cid) if e.type == "persona.reply"]
    assert used == [0, 2]
    assert all(r["used_at"] for r in await store.list_investigations(cid))
    assert await store.unused_findings(cid) == []
    facts = await engine.facts_for(cid, [{"role": "scammer", "text": "x"}])
    assert any("different name to pay" in f and P1 in f for f in facts)


class ModelBrain:
    """A model that follows the re-check instruction (says the payee changed, asks which is right) from its
    `misses + 1`-th draft of a re-check turn; before that it only stalls."""
    mode = "cerebras"

    def __init__(self, misses: int):
        self.misses, self.calls = misses, []

    async def reply(self, ctx):
        self.calls.append(ctx)
        system = persona_messages(ctx)[0]["content"]
        turns = [c for c in self.calls if c.findings]
        if ctx.findings and "which account is the right one" in system and len(turns) > self.misses:
            return {"reply": f"Beta, now the page shows a different name to pay, {P1}. Which one is right?",
                    "summary": "loan fee scam"}
        return {"reply": "Hello? Tell me slowly, beta, my phone is slow.", "summary": "loan fee scam"}


async def _rotated_case(runtime) -> tuple[str, dict, dict]:
    """A chat whose loan link Kane proved and re-checked, with the first visit already talked about."""
    checks(runtime, 1)
    store = runtime.store
    cid = (await store.open_case("web", "web:model"))["id"]
    await engine.handle_message(cid, "web", f"{LOAN.lure} {LAB_LOAN}")
    await engine.settle()
    await drain()
    first, again = await store.list_investigations(cid)
    await store.update_investigation(first["id"], used_at="2026-11-25T00:00:00+00:00")
    return cid, first, again


@pytest.mark.parametrize("misses,used,calls", [(0, 1, 1), (1, 1, 2), (2, 0, 2)])
async def test_a_recheck_turn_asks_which_account_is_right(runtime, kane_log, misses, used, calls):
    cid, first, again = await _rotated_case(runtime)
    runtime.brain = brain = ModelBrain(misses)
    r = await engine.handle_message(cid, "web", "Did you pay the fee? Hurry.")
    assert [f["id"] for f in brain.calls[0].findings] == [again["id"]]
    assert len(brain.calls) == calls and brain.calls[-1].insist is (calls == 2)
    last = [e for e in await runtime.store.events_for_case(cid) if e.type == "persona.reply"][-1]
    assert last.data["kane_findings_used"] == used
    assert P1 not in r.text  # the guard masks the handle
    if used:
        assert "different name to pay" in r.text and await runtime.store.unused_findings(cid) == []
    else:  # left out twice: it waits for the next turn
        assert [f["id"] for f in await runtime.store.unused_findings(cid)] == [again["id"]]
        brain.misses = 0
        await engine.handle_message(cid, "web", "Hello?")
        assert await runtime.store.unused_findings(cid) == []


async def test_the_same_payee_on_a_fresh_visit_is_recorded_but_is_not_news(runtime, kane_log):
    checks(runtime, 1)
    store = runtime.store
    cid = await new_case(store)
    await start_investigation(LAB_KYC, cid, "web", wait=True)
    await drain()
    first, again = await store.list_investigations(cid)
    assert again["verdict"] == "payment_request_found" and again["payee"] == first["payee"]
    assert again["rotation"]["rotated"] is False and again["rotation"]["new_payee"] is False
    assert again["rotation"]["proven_visits"] == 2
    assert [f["id"] for f in await store.unused_findings(cid)] == [first["id"]]
    assert "same UPI ID" in meena.finding_sentence(again)


async def test_an_unsafe_recheck_is_caught_by_the_guard_and_ends_the_probe(runtime, kane_log, monkeypatch):
    monkeypatch.setenv("FAKE_KANE_UNSAFE_ON_VISIT", "2")
    checks(runtime, 2)
    store = runtime.store
    cid = await new_case(store)
    await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    assert runs(kane_log) == 2  # no third visit after a run that broke the safety rule
    first, again = await store.list_investigations(cid)
    assert again["verdict"] == "unsafe_run" and again["reason"].startswith("Safety rule broken")
    assert again["final_state"]["_unsafe_actions"] == ['type: Type "0000" into "UPI PIN"']
    assert again["rotation"]["rotated"] is False and [p["payee"] for p in again["rotation"]["payees"]] == [P0]
    assert [f["id"] for f in await store.unused_findings(cid)] == [first["id"]]
    assert all(r["norm"] != P1 for r in await networks.sightings(store))
    assert api_client().get(f"/api/investigations/{again['id']}").json()["unsafe_actions"]


async def test_each_recheck_passes_the_link_safety_check_again(runtime, kane_log, monkeypatch):
    checks(runtime, 2)
    calls = []

    def check_link(url, **kw):
        calls.append(url)
        return None if len(calls) == 1 else "The link's host does not resolve to a public address."
    monkeypatch.setattr(inv_mod, "check_link", check_link)
    store = runtime.store
    cid = await new_case(store)
    await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    assert runs(kane_log) == 1 and len(calls) == 2
    first, skipped = await store.list_investigations(cid)
    assert skipped["status"] == "skipped" and skipped["recheck_of"] == first["id"]
    assert skipped["reason"] == "Fresh-visit re-check not run: The link's host does not resolve to a public address."
    assert first["rotation"]["rechecks"] == [skipped["id"]] and first["rotation"]["rotated"] is False


async def test_rechecks_wait_for_the_one_browser(runtime, kane_log, monkeypatch):
    checks(runtime, 1)
    active, peak = [0], [0]
    real = inv_mod.run_kane

    async def counting(*args, **kwargs):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        try:
            await asyncio.sleep(0.05)
            return await real(*args, **kwargs)
        finally:
            active[0] -= 1
    monkeypatch.setattr(inv_mod, "run_kane", counting)
    store = runtime.store
    a, b = await new_case(store, "web:a"), await new_case(store, "web:b")
    await asyncio.gather(start_investigation(LAB_LOAN, a, "web"), start_investigation(LAB_KYC, b, "web"))
    await drain()
    assert peak[0] == 1
    assert runs(kane_log) == 2 and runs(kane_log, "/lab/kyc") == 2


async def test_a_replay_rechecks_only_from_a_recorded_later_visit(runtime, tmp_path, monkeypatch):
    """A replay must never pass the first recorded visit off as a second one."""
    rec = tmp_path / "rec"
    rec.mkdir()

    def recording(payee: str) -> str:
        return json.dumps({"type": "run_end", "status": "passed", "summary": "Reached the PIN.",
                           "final_state": {"payee": payee, "amount": "799"}})
    (rec / "loan.ndjson").write_text(recording(P0))
    monkeypatch.setenv("KANE_RECORDINGS", str(rec))
    replay = ROOT / "scripts" / "kane_replay.py"
    runtime.settings = replace(runtime.settings, kane_cmd=f"{sys.executable} {replay}", kane_rotation_checks=2)
    store = runtime.store
    only = await new_case(store, "web:one")
    await start_investigation(LAB_LOAN, only, "web", wait=True)
    await drain()
    (row,) = await store.list_investigations(only)
    assert row["final_state"]["_replayed"] is True and row["rotation"] == {}

    (rec / "loan.2.ndjson").write_text(recording(P1))  # a real second visit was recorded
    cid = await new_case(store, "web:two")
    await start_investigation(LAB_LOAN, cid, "web", wait=True)
    await drain()
    first, again = await store.list_investigations(cid)  # no loan.3 recording: no third visit
    assert again["recheck_of"] == first["id"] and again["payee"] == P1
    assert again["final_state"]["_replayed"] is True and again["summary"].startswith("Replay of a real Kane CLI run")
    assert again["rotation"]["replayed"] is True and again["rotation"]["rotated"] is True
    finished = [e for e in await store.events_for_case(cid) if e.type == "kane.finished"]
    assert all(e.data["replayed"] for e in finished)


def test_rotation_facts_count_each_payee_once_in_the_order_seen():
    def run(i, verdict="payment_request_found", payee=P0, kind="upi"):
        return {"id": i, "verdict": verdict, "payee": payee, "payee_kind": kind, "final_state": {}}
    facts = rotation_facts([run(1), run(2, "no_payee_found", ""), run(3, payee=P0.upper()), run(4, payee=P2)])
    assert facts["rechecks"] == [2, 3, 4] and facts["proven_visits"] == 3 and facts["rotated"] is True
    assert [(p["payee"], p["visit"]) for p in facts["payees"]] == [(P0, 1), (P2, 4)]
    assert rotation_facts([run(9)])["rotated"] is False


# ---------- storage ----------
async def test_a_database_made_before_the_rotation_columns_gets_them(tmp_path):
    path = tmp_path / "before.db"
    before = SCHEMA.replace("used_at TEXT, recheck_of INTEGER,\n    rotation TEXT NOT NULL DEFAULT '{}'\n",
                            "used_at TEXT\n")
    assert before != SCHEMA
    con = sqlite3.connect(path)
    con.executescript(before)
    con.execute("INSERT INTO investigations (url, status, created_at) VALUES ('http://x/lab/kyc', 'passed', 'now')")
    con.commit()
    con.close()
    for _ in range(2):  # init is safe to run again
        store = Store(str(path))
        await store.init()
        row = await store.get_investigation(1)
        assert row["recheck_of"] is None and row["rotation"] == {}
        await store.close()


# ---------- the lab check ----------
def test_the_lab_check_scores_the_rotating_site_on_two_different_payees(monkeypatch, capsys):
    import investigate as script  # scripts/investigate.py

    def run_with(loan_payees, shown):
        visits = iter(loan_payees)

        async def investigate(url, s, headless, keep_raw=False):
            site = SITES_BY_KEY[url.rsplit("/", 1)[1]]
            payee = next(visits) if site.rotates else site.answer.payee
            return {"url": url, "status": "passed", "payee": payee, "amount": str(site.answer.amount),
                    "unsafe_actions": [], "credits": 3, "_raw": ("", "")}

        activity = {s.key: {"payment_attempts": 0, "reached_payment_step": True} for s in SITES}
        activity["loan"]["payees_shown"] = [{"visitor": i + 1, "payee": p} for i, p in enumerate(shown)]
        monkeypatch.setattr(script, "investigate", investigate)
        monkeypatch.setattr(script, "_post", lambda url: None)
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(json.dumps(activity).encode()))
        code = asyncio.run(script.check_lab("http://lab", Settings(), True))
        rows = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        return code, next(r for r in rows if r.get("site") == "loan")

    code, loan = run_with([P0, P1], [P0, P1])
    assert code == 0 and loan["rotation_proven"] is True and loan["correct"] is True
    assert loan["visits"] == [[P0, "799", "passed"], [P1, "799", "passed"]] and loan["lab_showed"] == [P0, P1]
    code, loan = run_with([P0, P0], [P0, P0])  # the browser kept its cookie: no rotation seen
    assert code == 1 and loan["rotation_proven"] is False and loan["correct"] is False
    code, loan = run_with([P0, "made.up@demoupi"], [P0, P1])  # Kane misread the second page
    assert code == 1 and loan["correct"] is False
