"""The whole app over HTTP in offline mode: health, the scam console, check a message, cases, the evidence pack and
the Telegram webhook. Kane is the fake CLI from tests/fixtures; nothing calls a real model or Telegram."""
import csv
import io
import time

import pytest
from fastapi.testclient import TestClient

from app import limits


@pytest.fixture
def client(settings, monkeypatch):
    limits.reset()
    from app.main import create_app
    with TestClient(create_app(settings)) as c:
        yield c


def say(client, session, text):
    r = client.post("/api/console/messages", json={"session_id": session, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def wait_for_kane(client, case_id):
    deadline = time.time() + 15
    while time.time() < deadline:
        invs = client.get(f"/api/cases/{case_id}").json()["investigations"]
        if invs and all(i["status"] not in ("queued", "running") for i in invs):
            return invs
        time.sleep(0.2)
    raise AssertionError("Kane did not finish")


def test_health_reports_offline_mode(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["brain"]["mode"] == "offline"
    assert body["openai"] == {"configured": False, "decisions_available": False, "reason": "offline mode"}


def test_console_chat_with_kane_finding(client):
    first = say(client, "s1", "Dear customer, your Bharat Unity Bank account will be blocked today. "
                              "Update KYC now: http://127.0.0.1:8000/lab/kyc")
    assert first["verdict"] == "scam" and first["reply"]
    invs = wait_for_kane(client, first["case_id"])
    assert invs[0]["payee"] == "bharatunity.kyc@demoupi" and "evidence_path" not in invs[0]
    nxt = say(client, "s1", "Did you do it? Hurry.")
    assert "Bharat Unity Bank" in nxt["reply"] and nxt["case_id"] == first["case_id"]
    detail = client.get(f"/api/cases/{first['case_id']}").json()
    assert any(i["kind"] == "url" for i in detail["intel"])
    assert [e["type"] for e in detail["events"]].count("kane.finished") == 1


def test_console_limits_and_validation(client, monkeypatch):
    assert client.post("/api/console/messages", json={"session_id": "a b", "text": "hi"}).status_code == 400
    assert client.post("/api/console/messages", json={"session_id": "ok", "text": ""}).status_code == 422
    monkeypatch.setattr(limits, "PER_MINUTE", 1)
    say(client, "rl", "one")
    assert client.post("/api/console/messages", json={"session_id": "rl", "text": "two"}).status_code == 429


def test_check_a_message(client):
    scam = client.post("/api/check", json={"text": "URGENT: your KYC is pending, account will be blocked today. "
                                                   "Update: http://127.0.0.1:8000/lab/kyc"}).json()
    assert scam["verdict"] == "scam" and "KYC" in scam["headline"] and any("1930" in a for a in scam["advice"])
    assert "Contains a link" in scam["red_flags"] and scam["links"] == ["http://127.0.0.1:8000/lab/kyc"]
    legit = client.post("/api/check", json={"text": "Your OTP for HDFC Bank login is 482913. "
                                                    "Do not share it with anyone."}).json()
    assert legit["verdict"] == "not_scam" and legit["links"] == []
    apk = client.post("/api/check", json={"text": "Get your refund, install https://x.example/Refund.apk"}).json()
    assert apk["links"] == [] and apk["apks"] and any("APK" in f for f in apk["red_flags"])


def test_evidence_pack(client):
    first = say(client, "ex", "Your KYC is pending, pay Rs 10 to bharatunity.kyc@demoupi or visit "
                              "http://127.0.0.1:8000/lab/kyc, call +91 90000 00001")
    wait_for_kane(client, first["case_id"])
    r = client.get(f"/api/cases/{first['case_id']}/export.csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert r.headers["x-sha256"] and rows[0]["suspect_upi"] == "bharatunity.kyc@demoupi"
    assert rows[0]["suspect_mobile"] == "+919000000001" and "Kane CLI opened 1 link" in rows[0]["incident_details"]
    assert "@" not in rows[0]["incident_details"]  # banned in the NCRP form
    sources = {x["identifier"]: x["source"] for x in rows}
    assert sources["bharatunity.kyc@demoupi"] == "proven by Kane CLI and said in chat"
    pdf = client.get(f"/api/cases/{first['case_id']}/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    kinds = [e["kind"] for e in client.get(f"/api/cases/{first['case_id']}").json()["evidence"]]
    assert "pdf" in kinds and "csv" in kinds and "kane_evidence" in kinds


def test_unknown_case_is_404(client):
    assert client.get("/api/cases/c_000000000000").status_code == 404
    assert client.get("/api/cases/../../etc").status_code == 404


def test_telegram_webhook_needs_the_secret_and_runs_once(settings, monkeypatch):
    from dataclasses import replace

    from app import telegram
    sent = []

    async def fake_call(token, method, payload):
        sent.append((method, payload))
        return {"ok": True}
    monkeypatch.setattr(telegram, "call", fake_call)
    from app.main import create_app
    s = replace(settings, telegram_bot_token="t", telegram_webhook_secret="s3cret")
    with TestClient(create_app(s)) as c:
        update = {"update_id": 7, "message": {"chat": {"id": 42}, "from": {"is_bot": False},
                                              "text": "Your account will be blocked today, update KYC now"}}
        assert c.post("/telegram/webhook", json=update).status_code == 403
        hdr = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}
        assert c.post("/telegram/webhook", json=update, headers=hdr).json() == {"ok": True}
        assert c.post("/telegram/webhook", json=update, headers=hdr).json() == {"ok": True}
    replies = [p for m, p in sent if m == "sendMessage"]
    assert len(replies) == 1 and replies[0]["chat_id"] == 42 and replies[0]["text"]


def test_csv_cells_cannot_run_as_formulas():
    from app.evidence_pack import csv_cell
    assert csv_cell("+919000000001") == "+919000000001"
    assert csv_cell("=HYPERLINK(\"x\")").startswith("'") and csv_cell("+cmd|' /C calc'!A0").startswith("'")
    assert csv_cell("@SUM(A1)").startswith("'") and csv_cell("-2+3").startswith("'")
