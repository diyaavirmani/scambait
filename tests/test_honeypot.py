"""POST /api/honeypot: the graders' contract, validation, the API key, closing, fallbacks and errors (offline)."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import engine, honeypot, limits
from app.runtime import get_runtime

META_KEYS = {"agentState", "sessionStatus", "persona", "turn", "confidence", "scamType", "agentNotes", "degraded"}


def make_client(settings):
    limits.reset()
    from app.main import create_app
    app = create_app(settings)
    if not any(getattr(r, "path", "") == "/api/honeypot" for r in app.routes):
        app.include_router(honeypot.router)
    return TestClient(app)


@pytest.fixture
def client(settings):
    with make_client(settings) as c:
        yield c


def body(text="Your account will be blocked today, update KYC now", session="grader-1", sender="scammer"):
    return {"sessionId": session, "message": {"sender": sender, "text": text, "timestamp": 1764000000000},
            "conversationHistory": [], "metadata": {"channel": "SMS", "language": "English", "locale": "IN"}}


def test_contract_shape(client):
    r = client.post("/api/honeypot", json=body())
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"status", "reply", "meta"} and set(j["meta"]) == META_KEYS
    assert j["status"] == "success" and j["reply"]
    m = j["meta"]
    assert m["agentState"] == "engaging" and m["sessionStatus"] == "active" and m["turn"] == 1
    assert m["scamType"] == "KYC_PHISHING" and m["confidence"] == "high" and m["degraded"] is False
    assert m["persona"] and m["agentNotes"].startswith("Verdict: scam")
    nxt = client.post("/api/honeypot", json=body("Pay to UPI fakeinvest.demo@okaxis and send screenshot")).json()
    assert nxt["meta"]["turn"] == 2 and "1 upi" in nxt["meta"]["agentNotes"]
    cases = [c for c in client.get("/api/cases").json()["cases"] if c["external_id"] == "api:grader-1"]
    assert len(cases) == 1 and cases[0]["channel"] == "api" and cases[0]["turns"] == 2


def test_optional_fields_can_be_left_out(client):
    loose = {"sessionId": "grader-2", "message": {"sender": "scammer", "text": "Hello madam",
                                                  "timestamp": "2026-11-25T10:00:00Z"}}
    r = client.post("/api/honeypot", json=loose)
    assert r.status_code == 200 and r.json()["meta"]["turn"] == 1


def test_validation(client):
    assert client.post("/api/honeypot", json=body(session="bad id")).status_code == 400
    assert client.post("/api/honeypot", json=body(session="x" * 65)).status_code == 400
    assert client.post("/api/honeypot", json=body(sender="user")).status_code == 400
    assert client.post("/api/honeypot", json=body(text="")).status_code == 422
    assert client.post("/api/honeypot", json={"sessionId": "s"}).status_code == 422
    assert client.get("/api/cases").json()["cases"] == []


def test_api_key_when_set(settings):
    with make_client(replace(settings, api_key="k3y")) as c:
        assert c.post("/api/honeypot", json=body()).status_code == 401
        assert c.post("/api/honeypot", json=body(), headers={"x-api-key": "nope"}).status_code == 401
        assert c.post("/api/honeypot", json=body(), headers={"x-api-key": "k3y"}).status_code == 200


def test_closing_after_the_chat_ends(client, monkeypatch):
    monkeypatch.setattr(engine, "CLOSE_AT", 3)
    metas = [client.post("/api/honeypot", json=body(t, session="ends")).json()["meta"]
             for t in ("Your KYC is pending, account blocked today", "Pay Rs 10 now", "Hurry madam")]
    assert [m["sessionStatus"] for m in metas] == ["active", "active", "closed"]
    assert metas[-1]["agentState"] == "completed" and "Conversation closed." in metas[-1]["agentNotes"]
    again = client.post("/api/honeypot", json=body("Hello?", session="ends")).json()["meta"]
    assert again["turn"] == 1 and again["sessionStatus"] == "active"  # a finished session starts a new case
    statuses = sorted(c["status"] for c in client.get("/api/cases").json()["cases"])
    assert statuses == ["closed", "open"]


def test_model_failure_is_reported_as_degraded(client, monkeypatch):
    async def broken(ctx):
        raise RuntimeError("model down")
    monkeypatch.setattr(get_runtime().brain, "reply", broken)
    j = client.post("/api/honeypot", json=body()).json()
    assert j["status"] == "degraded" and j["meta"]["degraded"] is True and j["reply"]


def test_internal_error_hides_details(client, monkeypatch):
    async def boom(case_id, channel, text):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(engine, "handle_message", boom)
    r = client.post("/api/honeypot", json=body())
    assert r.status_code == 500 and r.json() == {"status": "error"}
