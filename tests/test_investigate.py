"""Kane investigator: parsing Kane's NDJSON, the link safety policy, the background service and its API.

Kane itself is replaced by tests/fixtures/fake_kane.py, which prints the documented agent-mode contract."""
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.bus import Bus
from app.investigate import (build_objective, drain, normalise_finding, on_finding, start_investigation,
                             _listeners)
from app.investigate.api import router as api_router
from app.investigate.kane import build_command, parse_stream
from app.investigate.safety import check_link, is_lab_link
from app.runtime import Runtime, set_runtime
from app.store import Store

FAKE = Path(__file__).parent / "fixtures" / "fake_kane.py"
LAB_KYC = "http://127.0.0.1:8000/lab/kyc"


def ndjson(*objs) -> str:
    return "\n".join(json.dumps(o) for o in objs)


# ---------- parse_stream ----------
def test_parse_passed_run_with_final_state_and_evidence():
    out = ndjson({"type": "stream_start", "v": 1}, {"step": 1, "status": "running", "remark": "a"},
                 {"step": 1, "status": "done", "remark": "opened"}, {"step": 2, "status": "failed", "remark": "x"},
                 {"type": "run_end", "status": "passed", "summary": "ok", "credits_consumed": 4, "duration": 9.5,
                  "final_state": {"payee": "a@demoupi"}, "session_dir": "/tmp/s"}) + "\nnoise line\n"
    r = parse_stream(out, "evidence: view locally with `kane-cli evidence serve /tmp/s/evidence/p.zip`", 0)
    assert r.status == "passed" and r.passed
    assert r.final_state == {"payee": "a@demoupi"}
    assert r.credits == 4 and r.duration_s == 9.5
    assert r.evidence_path == "/tmp/s/evidence/p.zip"
    assert [s["status"] for s in r.steps] == ["done", "failed"]


def test_parse_failed_and_timeout_and_not_started():
    failed = parse_stream(ndjson({"type": "run_end", "status": "failed", "reason": "blocked"}), "", 1)
    assert failed.status == "failed" and failed.reason == "blocked"
    timed = parse_stream(ndjson({"type": "run_end", "status": "failed"}), "", 3)
    assert timed.status == "timeout"
    never = parse_stream("", 'Not authenticated [prod]. Run "kane-cli login" first.', 2)
    assert never.status == "not_started" and "login" in never.reason


def test_parse_uses_old_credits_field_and_ignores_unknown_lines():
    r = parse_stream("[1,2]\n{bad json\n" + ndjson({"type": "warning"}, {"type": "run_end", "status": "passed",
                                                                         "credits": 2}), "", 0)
    assert r.credits == 2 and r.status == "passed"


# ---------- objective and command ----------
def test_objective_forbids_paying_and_stores_named_values():
    text = build_objective().lower()
    for must in ("never type anything, not even a fake value, into a upi pin", "never press a button that pays",
                 "leave its fields empty, press nothing on it, download nothing", "payee (the upi id", "amount (",
                 "claims_to_be (", "asked_for (", "meena sharma"):
        assert must in text
    # Kane catches 2 and 3: a payment page whose only fields are PIN, card or CVV must not look like a blocker
    assert "empty payment fields on that page are expected" in text and "finish the test as passed" in text


def test_build_command_flags():
    cmd = build_command("obj", "http://x", cmd="kane-cli", timeout_s=90, max_steps=20)
    assert cmd[:3] == ["kane-cli", "run", "obj"]
    for flag in ("--agent", "--headless", "--url", "--timeout", "--max-steps"):
        assert flag in cmd
    assert "--username" not in build_command("o", "u", username="u")
    assert "--access-key" in build_command("o", "u", username="u", access_key="k")


# ---------- finding ----------
def test_normalise_finding_upi_and_bank():
    from app.investigate.kane import KaneResult
    upi = normalise_finding(KaneResult(status="passed", exit_code=0, final_state={
        "Payee": "UPI ID: bharatunity.kyc@demoupi", "amount": "Rs 10", "asked_for": "name, mobile and UPI PIN"}))
    assert upi["payee"] == "bharatunity.kyc@demoupi" and upi["payee_kind"] == "upi"
    assert upi["amount"] == "10" and upi["asked_for"] == ["name", "mobile", "UPI PIN"]
    assert upi["verdict"] == "payment_request_found"
    bank = normalise_finding(KaneResult(status="passed", exit_code=0,
                                        final_state={"payee": "000987654321", "amount": "₹33,210"}))
    assert bank["payee_kind"] == "bank_account" and bank["amount"] == "33210"
    none = normalise_finding(KaneResult(status="failed", exit_code=1, final_state={}))
    assert none["verdict"] == "inconclusive"


def test_final_state_from_the_first_real_kane_run():
    """Exact final_state real Kane CLI 0.10.8 returned for /lab/kyc on 24 Nov 2026: asked_for arrived as a
    JSON-encoded string and the amount with a rupee sign."""
    from app.investigate.kane import KaneResult
    real = {"url": "http://127.0.0.1:8000/lab/kyc/2", "claims_to_be": "Bharat Unity Bank",
            "payee": "bharatunity.kyc@demoupi", "amount": "₹10", "asked_for": "[\"UPI PIN\"]"}
    f = normalise_finding(KaneResult(status="passed", exit_code=0, final_state=real))
    assert f["asked_for"] == ["UPI PIN"]
    assert f["payee"] == "bharatunity.kyc@demoupi" and f["amount"] == "10"
    assert f["claims_to_be"] == "Bharat Unity Bank"


# ---------- safety ----------
def test_lab_links_allowed_real_links_need_live_mode():
    assert check_link(LAB_KYC) is None
    assert check_link("https://scambait.example.com/lab/parcel", public_base_url="https://scambait.example.com") is None
    assert is_lab_link("http://localhost:8000/lab") is True
    assert "LIVE_INVESTIGATION" in check_link("https://kyc-update.example/verify")
    assert check_link("https://93.184.216.34/verify", live=True) is None


@pytest.mark.parametrize("url", [
    "https://evil.example/StockPro.apk", "http://127.0.0.1:8000/lab/x.apk", "ftp://x.example/a",
    "https://user:pw@x.example/", "http://10.0.0.5/login", "http://192.168.1.1/", "http://localhost:9000/admin",
    "https://x.example:8443/pay", "http://169.254.169.254/latest/meta-data", "javascript:alert(1)",
])
def test_dangerous_links_never_opened_even_in_live_mode(url):
    assert check_link(url, live=True, resolve=False) is not None


# ---------- service ----------
@pytest.fixture
async def env(tmp_path, monkeypatch):
    log = tmp_path / "kane-calls.log"
    monkeypatch.setenv("FAKE_KANE_LOG", str(log))
    store = Store(str(tmp_path / "inv.db"))
    await store.init()
    settings = Settings(kane_cmd=f"{sys.executable} {FAKE}", kane_workdir=str(tmp_path / "kane"),
                        kane_rotation_checks=0)
    set_runtime(Runtime(settings=settings, store=store, bus=Bus(store)))
    case = await store.new_case("telegram", "tg:7")
    yield store, case["id"], log
    await drain()
    await store.close()


async def test_lab_link_is_investigated_and_evidence_is_hashed(env):
    store, cid, log = env
    seen = []

    async def listener(row):
        seen.append(row)
    on_finding(listener)
    try:
        row = await start_investigation(LAB_KYC, cid, "telegram", wait=True)
    finally:
        _listeners.remove(listener)
    assert row["status"] == "passed"
    assert row["verdict"] == "payment_request_found"
    assert row["payee"] == "bharatunity.kyc@demoupi" and row["amount"] == "10"
    assert row["credits"] == 3 and len(row["evidence_sha256"]) == 64
    evidence = await store.list_evidence(cid)
    assert evidence[0]["kind"] == "kane_evidence" and evidence[0]["sha256"] == row["evidence_sha256"]
    types = [e.type for e in await store.events_for_case(cid)]
    assert types == ["kane.started", "kane.finished"]
    assert seen and seen[0]["id"] == row["id"]
    again = await start_investigation(LAB_KYC, cid, "telegram", wait=True)
    assert again["id"] == row["id"]
    assert log.read_text().count("/lab/kyc") == 1


async def test_real_link_is_skipped_without_live_mode_and_kane_never_runs(env):
    store, cid, log = env
    row = await start_investigation("https://kyc-update.example/verify", cid, "telegram", wait=True)
    assert row["status"] == "skipped" and "LIVE_INVESTIGATION" in row["reason"]
    assert not log.exists()


async def test_apk_link_is_recorded_not_opened(env):
    store, cid, log = env
    row = await start_investigation("http://127.0.0.1:8000/lab/StockPro.apk", cid, "telegram", wait=True)
    assert row["status"] == "skipped" and "APK" in row["reason"]
    assert not log.exists()


async def test_kane_not_logged_in_is_reported_and_can_be_retried(env):
    store, cid, log = env
    row = await start_investigation("http://127.0.0.1:8000/lab/nostart", cid, "telegram", wait=True)
    assert row["status"] == "not_started" and "login" in row["reason"]
    retry = await start_investigation("http://127.0.0.1:8000/lab/nostart", cid, "telegram", wait=True)
    assert retry["id"] != row["id"]


async def test_api_lists_and_hides_local_paths(env):
    store, cid, log = env
    await start_investigation(LAB_KYC, cid, "telegram", wait=True)
    app = FastAPI()
    app.include_router(api_router)
    client = TestClient(app)
    body = client.get("/api/investigations", params={"case_id": cid}).json()
    inv = body["investigations"][0]
    assert inv["evidence"] is True and "evidence_path" not in inv
    assert client.get(f"/api/investigations/{inv['id']}").json()["payee"] == "bharatunity.kyc@demoupi"
    assert client.get("/api/investigations/999").status_code == 404
    assert client.post("/api/investigations", json={"url": LAB_KYC, "case_id": "c_nope"}).status_code == 404
    assert inv["replayed"] is False


async def test_a_replayed_run_is_always_labelled(tmp_path, monkeypatch):
    """Hosts without Chrome replay recorded real Kane runs; the result must say so everywhere."""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "kyc.ndjson").write_text(json.dumps({"type": "run_end", "status": "passed", "summary": "Reached the PIN.",
                                                "final_state": {"payee": "bharatunity.kyc@demoupi", "amount": "10"}}))
    monkeypatch.setenv("KANE_RECORDINGS", str(rec))
    store = Store(str(tmp_path / "r.db"))
    await store.init()
    replay = Path(__file__).resolve().parent.parent / "scripts" / "kane_replay.py"
    set_runtime(Runtime(settings=Settings(kane_cmd=f"{sys.executable} {replay}", kane_workdir=str(tmp_path / "k")),
                        store=store, bus=Bus(store)))
    try:
        row = await start_investigation(LAB_KYC, None, "api", wait=True)
        assert row["payee"] == "bharatunity.kyc@demoupi"
        assert row["final_state"]["_replayed"] is True
        assert row["summary"].startswith("Replay of a real Kane CLI run")
    finally:
        await drain()
        await store.close()
