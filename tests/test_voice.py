"""Phone call webhooks over HTTP: the Twilio signature, TwiML in live and speech mode, speech-mode turns through the
engine (scripted brain), and the status callback ending a call. Nothing calls Twilio or a model."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import engine, meena
from app.runtime import get_runtime
from app.voice import calls, persona, twiml, webhooks

AUTH = "test-auth-token"
BASE = "https://bait.example"


def voice_app(settings) -> FastAPI:
    """Just the voice routes, on a runtime built inside the test client's event loop."""
    @asynccontextmanager
    async def lifespan(app):
        from app.brain import ScriptedBrain
        from app.bus import Bus
        from app.investigate import drain
        from app.runtime import Runtime, set_runtime
        from app.store import Store
        store = Store(settings.db_path)
        await store.init()
        set_runtime(Runtime(settings=settings, store=store, bus=Bus(store), brain=ScriptedBrain()))
        yield
        await engine.settle()
        await drain()
        await store.close()

    from app.voice import router
    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return app


@contextmanager
def running(settings, **overrides):
    s = replace(settings, twilio_auth_token=AUTH, public_base_url=BASE, **overrides)
    with TestClient(voice_app(s)) as client:
        yield client


@pytest.fixture
def reports(monkeypatch):
    seen = []

    async def fake_report(case_id):
        seen.append(case_id)
    monkeypatch.setattr(calls, "run_report", fake_report)
    return seen


@pytest.fixture
def client(settings, reports):
    with running(settings) as c:
        yield c


def post(client, path, params, query="", token=AUTH, signature=None):
    target = path + (f"?{query}" if query else "")
    sig = twiml.signature(token, BASE + target, params.items()) if signature is None else signature
    return client.post(target, data=params, headers={"X-Twilio-Signature": sig} if sig else {})


def db(client, method, *args):
    """Run a store call on the app's event loop."""
    return client.portal.call(getattr(get_runtime().store, method), *args)


def call_case(client, call_sid):
    return next(c for c in db(client, "list_cases") if c["external_id"] == f"call:{call_sid}")


def events(client, case_id, type_=None):
    evs = db(client, "events_for_case", case_id)
    return [e for e in evs if type_ is None or e.type == type_]


def spoken(xml_text):
    root = ET.fromstring(xml_text)
    return [p.text for p in root.iter("prosody")]


def test_signature_matches_twilio_documented_example():
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+14158675309", "Digits": "1234", "From": "+14158675309",
              "To": "+18005551212"}
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    assert twiml.signature("12345", url, params.items()) == "RSOYDt4T1cUTdK1PDd93/VVr8B8="
    assert twiml.signature_ok("12345", url, params.items(), "RSOYDt4T1cUTdK1PDd93/VVr8B8=")
    assert not twiml.signature_ok("12345", url, params.items(), "RSOYDt4T1cUTdK1PDd93/VVr8B8")
    assert not twiml.signature_ok("", url, params.items(), twiml.signature("", url, params.items()))


def test_webhooks_refuse_a_bad_or_missing_signature(client):
    form = {"CallSid": "CA1", "From": "+15550001111"}
    assert post(client, "/voice/incoming", form, signature="").status_code == 403
    assert post(client, "/voice/incoming", form, signature="bm90LWEtc2lnbmF0dXJl").status_code == 403
    assert post(client, "/voice/incoming", form, token="some-other-token").status_code == 403
    assert post(client, "/voice/turn", form, token="some-other-token").status_code == 403
    assert post(client, "/voice/status", {**form, "CallStatus": "completed"}, token="x").status_code == 403
    signed_for_other_path = twiml.signature(AUTH, BASE + "/voice/status", form.items())
    assert post(client, "/voice/incoming", form, signature=signed_for_other_path).status_code == 403
    assert db(client, "list_cases") == []


def test_webhooks_refuse_when_the_auth_token_is_not_set(settings, reports):
    with TestClient(voice_app(replace(settings, twilio_auth_token="", public_base_url=BASE))) as c:
        for path in ("/voice/incoming", "/voice/turn", "/voice/status"):
            assert post(c, path, {"CallSid": "CA1"}, token="").status_code == 403
        assert db(c, "list_cases") == []


def test_incoming_in_speech_mode_greets_and_listens(client):
    r = post(client, "/voice/incoming", {"CallSid": "CA100", "From": "+15550001111", "CallStatus": "ringing"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.text)
    gather = root.find("Gather")
    assert gather.get("input") == "speech" and gather.get("action") == BASE + "/voice/turn"
    assert gather.get("language") == "en-IN"
    say = gather.find("Say")
    assert say.get("voice") == twiml.SAY_VOICE and say.find("prosody").get("rate") == twiml.SAY_RATE
    assert spoken(r.text) == [persona.GREETING]
    assert root.find("Redirect").text == BASE + "/voice/turn?quiet=1"
    case = call_case(client, "CA100")
    assert case["channel"] == "call"
    ringing = events(client, case["id"], "call.status")
    assert ringing[0].data == {"status": "ringing", "call_sid": "CA100"} and ringing[0].channel == "call"
    assert [m["text"] for m in db(client, "list_messages", case["id"])] == [persona.GREETING]


def test_incoming_in_live_mode_connects_a_media_stream(settings, reports):
    with running(settings, openai_api_key="test-key") as c:
        r = post(c, "/voice/incoming", {"CallSid": "CA200"})
        assert r.status_code == 200
        root = ET.fromstring(r.text)
        stream = root.find("Connect/Stream")
        assert stream.get("url") == "wss://bait.example/voice/stream"
        params = {p.get("name"): p.get("value") for p in stream.findall("Parameter")}
        case = call_case(c, "CA200")
        assert params["case_id"] == case["id"]
        assert twiml.stream_token_ok(AUTH, case["id"], params["token"])
        assert root.find("Redirect").text == BASE + "/voice/turn?quiet=1"  # speech fallback if the stream ends
        assert root.find(".//Gather") is None
        assert events(c, case["id"], "call.status")[0].data["status"] == "ringing"


def test_turn_runs_the_engine_and_says_meenas_reply(client):
    post(client, "/voice/incoming", {"CallSid": "CA300"})
    text = "Madam your SIM card will be blocked today. Pay the fee to fakeinvest.demo@okaxis now."
    r = post(client, "/voice/turn", {"CallSid": "CA300", "SpeechResult": text, "Confidence": "0.91"})
    assert r.status_code == 200
    case = call_case(client, "CA300")
    msgs = db(client, "list_messages", case["id"])
    assert [m["role"] for m in msgs] == ["persona", "scammer", "persona"]
    assert msgs[1]["text"] == text
    root = ET.fromstring(r.text)
    assert root.find("Gather").get("action") == BASE + "/voice/turn"
    assert spoken(r.text) == [msgs[2]["text"]] and msgs[2]["text"]
    assert any(i["kind"] == "upi" for i in db(client, "list_intel", case["id"]))
    assert [e.data["role"] for e in events(client, case["id"], "message.received")] == ["scammer"]
    assert all(e.channel == "call" for e in events(client, case["id"]))


def test_turn_says_goodbye_and_hangs_up_when_the_chat_closes(client, monkeypatch):
    monkeypatch.setattr(engine, "CLOSE_AT", 1)
    post(client, "/voice/incoming", {"CallSid": "CA400"})
    r = post(client, "/voice/turn", {"CallSid": "CA400", "SpeechResult": "Pay the fine now or you will be arrested."})
    root = ET.fromstring(r.text)
    assert root.find("Hangup") is not None and root.find("Gather") is None
    assert spoken(r.text) == [meena.GOODBYE]
    assert call_case(client, "CA400")["status"] == "closed"
    again = post(client, "/voice/turn", {"CallSid": "CA400", "SpeechResult": "Hello?"})
    assert ET.fromstring(again.text).find("Hangup") is not None


def test_silence_asks_if_they_are_there_then_hangs_up(client):
    post(client, "/voice/incoming", {"CallSid": "CA500"})
    first = post(client, "/voice/turn", {"CallSid": "CA500"}, query="quiet=1")
    root = ET.fromstring(first.text)
    assert spoken(first.text) == [persona.STILL_THERE[0]]
    assert root.find("Redirect").text == BASE + "/voice/turn?quiet=2"
    last = post(client, "/voice/turn", {"CallSid": "CA500"}, query=f"quiet={webhooks.MAX_QUIET}")
    assert ET.fromstring(last.text).find("Hangup") is not None and spoken(last.text) == [persona.NOBODY]
    scammer = [m for m in db(client, "list_messages", call_case(client, "CA500")["id"]) if m["role"] == "scammer"]
    assert scammer == []


def test_a_slow_turn_holds_the_line_then_answers(settings, reports, monkeypatch):
    from app.brain import ScriptedBrain
    quick = ScriptedBrain.reply

    async def slow_reply(self, ctx):
        await asyncio.sleep(0.4)
        return await quick(self, ctx)
    monkeypatch.setattr(ScriptedBrain, "reply", slow_reply)
    monkeypatch.setattr(webhooks, "TURN_WAIT_S", 0.05)
    with running(settings) as c:
        post(c, "/voice/incoming", {"CallSid": "CA600"})
        r = post(c, "/voice/turn", {"CallSid": "CA600", "SpeechResult": "Sir this is the bank, share the OTP."})
        root = ET.fromstring(r.text)
        assert root.find("Gather") is None and root.find("Redirect").text == BASE + "/voice/turn"
        assert spoken(r.text)[0] in persona.HOLD
        for _ in range(40):
            r = post(c, "/voice/turn", {"CallSid": "CA600"})
            if ET.fromstring(r.text).find("Gather") is not None:
                break
        msgs = db(c, "list_messages", call_case(c, "CA600")["id"])
        assert [m["role"] for m in msgs].count("scammer") == 1
        fillers = (*persona.HOLD, persona.GREETING)
        replies = [m["text"] for m in msgs if m["role"] == "persona" and m["text"] not in fillers]
        assert len(replies) == 1 and spoken(r.text) == replies


def test_status_announces_and_ends_the_call_once(client, reports):
    post(client, "/voice/incoming", {"CallSid": "CA700"})
    case_id = call_case(client, "CA700")["id"]
    say = "This is the cyber police. Your Aadhaar is linked to money laundering. Pay the fine or you will be arrested."
    client.portal.call(engine.record_scammer_text, case_id, "call", say)

    r = post(client, "/voice/status", {"CallSid": "CA700", "CallStatus": "in-progress"})
    assert r.status_code == 204 and call_case(client, "CA700")["status"] == "open"
    r = post(client, "/voice/status", {"CallSid": "CA700", "CallStatus": "completed", "CallDuration": "42"})
    assert r.status_code == 204
    case = call_case(client, "CA700")
    assert case["status"] == "closed" and case["verdict"] == "scam"
    statuses = [e.data for e in events(client, case_id, "call.status")]
    assert {"status": "completed", "call_sid": "CA700", "duration_s": 42} in statuses
    detected = events(client, case_id, "scam.detected")
    assert len(detected) == 1 and detected[0].data["stage"] == "final" and detected[0].data["verdict"] == "scam"
    assert {"verdict", "scam_type", "risk", "decided_by", "p_scam"} <= set(detected[0].data)
    assert [e.data["status"] for e in events(client, case_id, "case.updated")] == ["closed"]
    assert reports == [case_id]

    post(client, "/voice/status", {"CallSid": "CA700", "CallStatus": "completed"})
    assert reports == [case_id] and len(events(client, case_id, "case.updated")) == 1


def test_status_for_an_unknown_call_only_announces(client, reports):
    r = post(client, "/voice/status", {"CallSid": "CA-unknown", "CallStatus": "busy"})
    assert r.status_code == 204 and reports == [] and db(client, "list_cases") == []
