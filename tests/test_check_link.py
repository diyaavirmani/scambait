"""Check a message, before you pay: /api/check lists the links Kane may open, and POST /api/check/link asks Kane to
open one. Kane is the fake CLI from tests/fixtures; FAKE_KANE_LOG counts every run it is asked for."""
import json
import sqlite3
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import check, limits

LAB_KYC = "http://127.0.0.1:8000/lab/kyc"
KYC_SMS = "URGENT: your KYC is pending, account will be blocked today. Update: "


@pytest.fixture
def kane_log(tmp_path, monkeypatch):
    log = tmp_path / "kane-calls.log"
    monkeypatch.setenv("FAKE_KANE_LOG", str(log))
    return log


def make_client(settings):
    limits.reset()
    from app.main import create_app
    return TestClient(create_app(settings))


@pytest.fixture
def client(settings, kane_log):
    with make_client(settings) as c:
        yield c


@pytest.fixture
def live_client(settings, kane_log):
    with make_client(replace(settings, live_investigation=True)) as c:
        yield c


def wait_finished(client, inv_id):
    deadline = time.time() + 15
    while time.time() < deadline:
        row = client.get(f"/api/investigations/{inv_id}").json()
        if row["status"] not in ("queued", "running"):
            return row
        time.sleep(0.1)
    raise AssertionError("Kane did not finish")


def settle(client):
    """Wait until no Kane run is queued or running (a proven payee may be followed by a fresh-visit re-check)."""
    deadline = time.time() + 15
    while time.time() < deadline:
        invs = client.get("/api/investigations").json()["investigations"]
        if all(i["status"] not in ("queued", "running") for i in invs):
            return invs
        time.sleep(0.1)
    raise AssertionError("Kane did not settle")


def no_investigations(client, kane_log):
    assert client.get("/api/investigations").json()["investigations"] == []
    assert not kane_log.exists() or kane_log.read_text() == ""


def test_check_lists_links_and_opens_nothing(client, kane_log):
    body = client.post("/api/check", json={"text": KYC_SMS + LAB_KYC + " or https://bank-kyc.example/pay "
                                                   "or install https://x.example/Refund.apk"}).json()
    assert body["verdict"] == "scam" and body["scam_words"] == "a fake KYC update scam"
    assert body["links"] == [LAB_KYC]
    assert body["apks"] == ["https://x.example/Refund.apk"]
    assert body["links_not_opened"] == [{"url": "https://bank-kyc.example/pay", "reason": check.NOT_LIVE}]
    assert "investigations" not in body
    no_investigations(client, kane_log)


def test_check_offers_at_most_three_links(client):
    text = KYC_SMS + " ".join(f"http://127.0.0.1:8000/lab/kyc?n={n}" for n in range(5))
    body = client.post("/api/check", json={"text": text}).json()
    assert len(body["links"]) + len(body["links_not_opened"]) == check.MAX_LINKS


def test_link_is_investigated_and_the_finished_run_has_the_payee(client, settings, kane_log):
    r = client.post("/api/check/link", json={"url": "  " + LAB_KYC + " "})
    assert r.status_code == 200, r.text
    queued = r.json()
    assert queued["id"] and queued["case_id"] is None and queued["url"] == LAB_KYC
    assert "evidence_path" not in queued
    done = wait_finished(client, queued["id"])
    assert done["verdict"] == "payment_request_found" and done["payee"] == "bharatunity.kyc@demoupi"
    assert done["payee_kind"] == "upi" and done["amount"] == "10" and "Bharat Unity Bank" in done["claims_to_be"]
    assert done["evidence"] and done["evidence_sha256"] and "UPI PIN" in done["asked_for"]
    settle(client)
    calls = kane_log.read_text().split()
    assert calls and set(calls) == {LAB_KYC}
    # The page follows these events by investigation id; they are sent on the "check" channel with no case.
    with sqlite3.connect(settings.db_path) as db:
        rows = db.execute("SELECT type, channel, case_id, data FROM events WHERE type LIKE 'kane.%' ORDER BY id").fetchall()
    assert rows and all(ch == "check" and cid is None for _, ch, cid, _ in rows)
    mine = [(t, json.loads(d)) for t, _, _, d in rows if json.loads(d)["investigation_id"] == queued["id"]]
    assert [t for t, _ in mine] == ["kane.started", "kane.finished"]
    assert mine[-1][1]["payee"] == "bharatunity.kyc@demoupi"
    # Asking again for the same link gives the same investigation, not another Kane run.
    again = client.post("/api/check/link", json={"url": LAB_KYC}).json()
    settle(client)
    assert again["id"] == queued["id"] and kane_log.read_text().split() == calls


def test_link_with_no_payment_page_is_not_called_safe(client):
    queued = client.post("/api/check/link", json={"url": "http://127.0.0.1:8000/lab/nothing-here"}).json()
    done = wait_finished(client, queued["id"])
    assert done["verdict"] != "payment_request_found" and not done["payee"]


@pytest.mark.parametrize("url", ["https://x.example/Refund.apk", "http://127.0.0.1:8000/lab/kyc/app.APK",
                                 "https://x.example/get?file=bank.apk"])
def test_apk_is_refused_and_never_investigated(live_client, kane_log, url):
    r = live_client.post("/api/check/link", json={"url": url})
    assert r.status_code == 400 and r.json()["detail"] == check.APK_REFUSED
    assert "install" in r.json()["detail"]
    no_investigations(live_client, kane_log)


@pytest.mark.parametrize("url", ["not a link", "ftp://127.0.0.1/lab/kyc", "javascript:alert(1)",
                                 "http://user:pw@127.0.0.1:8000/lab/kyc", "http://192.168.1.1/pay",
                                 "http://10.0.0.5/lab/kyc", "http://localhost:8000/admin", "http://[::1]/pay",
                                 "http://127.0.0.1:8000/lab/kyc/form.zip"])
def test_bad_or_private_links_are_refused(live_client, kane_log, url):
    r = live_client.post("/api/check/link", json={"url": url})
    assert r.status_code == 400 and r.json()["detail"]
    no_investigations(live_client, kane_log)


def test_real_links_are_refused_unless_live(client, kane_log):
    r = client.post("/api/check/link", json={"url": "https://bank-kyc.example/pay"})
    assert r.status_code == 400 and r.json()["detail"] == check.NOT_LIVE
    assert client.post("/api/check/link", json={"url": ""}).status_code == 422
    assert client.post("/api/check/link", json={"url": "http://x.example/" + "a" * 2000}).status_code == 422
    no_investigations(client, kane_log)


def test_kane_turned_off(settings, kane_log):
    with make_client(replace(settings, kane_enabled=False)) as c:
        body = c.post("/api/check", json={"text": KYC_SMS + LAB_KYC}).json()
        assert body["links"] == [] and body["links_not_opened"] == [{"url": LAB_KYC, "reason": check.KANE_OFF}]
        r = c.post("/api/check/link", json={"url": LAB_KYC})
        assert r.status_code == 503 and r.json()["detail"] == check.KANE_OFF
        no_investigations(c, kane_log)


def test_link_checks_are_rate_limited(client, kane_log, monkeypatch):
    monkeypatch.setattr(check, "LINK_PER_MINUTE", 2)
    assert client.post("/api/check/link", json={"url": "https://x.example/a.apk"}).status_code == 400
    assert client.post("/api/check/link", json={"url": LAB_KYC}).status_code == 200
    r = client.post("/api/check/link", json={"url": "http://127.0.0.1:8000/lab/trading"})
    assert r.status_code == 429 and "Wait a minute" in r.json()["detail"]
    assert kane_log.exists() is False or "/lab/trading" not in kane_log.read_text()


def test_message_checks_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(limits, "PER_MINUTE", 1)
    assert client.post("/api/check", json={"text": "hello"}).status_code == 200
    assert client.post("/api/check", json={"text": "hello"}).status_code == 429
