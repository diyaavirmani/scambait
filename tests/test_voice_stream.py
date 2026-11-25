"""The live call bridge: Twilio Media Streams on one side, a fake live voice socket on the other. Checks audio both
ways, transcripts stored and emitted, barge-in, call analysis, the speech fallback and refused streams."""
import asyncio
import json
import time
from xml.etree import ElementTree as ET

import pytest
from starlette.websockets import WebSocketDisconnect

from app import engine
from app.voice import calls, live, stream, twiml
from tests.test_voice import AUTH, call_case, db, events, post, running

CALLER = ("Madam this is the cyber police. Your Aadhaar is linked to money laundering. "
          "Pay the fine to fakeinvest.demo@okaxis now or you will be arrested.")
MEENA_AUDIO = "TUVFTkEtQVVESU8="
CALLER_AUDIO = "Q0FMTEVSLUFVRElP"


class FakeLive:
    """Stands in for the live voice websocket: starts, greets in two transcript pieces plus audio, and turns the
    caller's audio into a transcript."""

    def __init__(self, caller_says=(CALLER,)):
        self.sent = []
        self.caller_says = list(caller_says)
        self.closed = False
        self._inbox = None

    def _queue(self):
        if self._inbox is None:
            self._inbox = asyncio.Queue()
        return self._inbox

    def push(self, **event):
        self._queue().put_nowait(json.dumps(event))

    async def send(self, text):
        msg = json.loads(text)
        self.sent.append(msg)
        kind = msg["type"]
        if kind == "session.start":
            self.push(type="session.started", session={"id": "sess_test"})
        elif kind == "session.commentary.append":
            self.push(type="session.output_transcript.delta", delta="Hello? ", start_ms=0, end_ms=400)
            self.push(type="session.output_transcript.delta", delta="Who is this?", start_ms=400, end_ms=900)
            self.push(type="session.output_audio.delta", delta=MEENA_AUDIO)
        elif kind == "session.input_audio.append" and self.caller_says:
            self.push(type="session.input_transcript.delta", delta=self.caller_says.pop(0), start_ms=1000, end_ms=6000)
        elif kind == "session.close":
            self.push(type="session.closed", usage={})

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self._queue().get()
        if raw is None:
            raise StopAsyncIteration
        return raw

    async def close(self):
        self.closed = True
        self._queue().put_nowait(None)


@pytest.fixture
def reports(monkeypatch):
    seen = []

    async def fake_report(case_id):
        seen.append(case_id)
    monkeypatch.setattr(calls, "run_report", fake_report)
    return seen


@pytest.fixture
def fake(monkeypatch):
    live_socket = FakeLive()
    keys = []

    async def connect(api_key):
        keys.append(api_key)
        return live_socket
    monkeypatch.setattr(stream, "connector", connect)
    live_socket.keys = keys
    return live_socket


def start_call(client, call_sid):
    """Ring the number in live mode; returns the case id and the stream parameters from the TwiML."""
    r = post(client, "/voice/incoming", {"CallSid": call_sid})
    params = {p.get("name"): p.get("value") for p in ET.fromstring(r.text).iter("Parameter")}
    return params["case_id"], params


def start_msg(call_sid, params):
    return {"event": "start", "sequenceNumber": "1", "streamSid": "MZ1",
            "start": {"streamSid": "MZ1", "callSid": call_sid, "accountSid": "AC1", "tracks": ["inbound"],
                      "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                      "customParameters": params}}


def media(payload):
    return {"event": "media", "streamSid": "MZ1", "media": {"track": "inbound", "chunk": "1", "payload": payload}}


def test_live_call_bridges_audio_transcripts_and_barge_in(settings, fake, reports):
    with running(settings, openai_api_key="test-key") as c:
        case_id, params = start_call(c, "CA900")
        with c.websocket_connect("/voice/stream") as ws:
            ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            ws.send_json(start_msg("CA900", params))
            assert ws.receive_json() == {"event": "media", "streamSid": "MZ1", "media": {"payload": MEENA_AUDIO}}
            mark = ws.receive_json()
            assert mark["event"] == "mark" and mark["streamSid"] == "MZ1" and mark["mark"]["name"]
            ws.send_json(media(CALLER_AUDIO))  # the caller talks before Twilio has played Meena's audio
            assert ws.receive_json() == {"event": "clear", "streamSid": "MZ1"}
            ws.send_json({"event": "stop", "sequenceNumber": "9", "streamSid": "MZ1", "stop": {"callSid": "CA900"}})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

        assert fake.keys == ["test-key"] and fake.closed
        first = fake.sent[0]
        assert first["type"] == "session.start"
        assert first["session"]["model"] == settings.live_model
        assert first["session"]["audio"]["format"] == {"type": "audio/pcmu", "rate": 8000}
        instructions = first["session"]["instructions"]
        assert "Meena" in instructions and "Never read out numbers" in instructions
        assert "Return JSON" not in instructions
        kinds = [m["type"] for m in fake.sent]
        assert {"type": "session.input_audio.append", "audio": CALLER_AUDIO} in fake.sent
        stop_at = kinds.index("session.instructions.append")
        assert kinds.index("session.input_audio.append") < stop_at  # barge-in told the live side to stop
        assert kinds[-1] == "session.close"

        msgs = db(c, "list_messages", case_id)
        assert [(m["role"], m["text"]) for m in msgs] == [("persona", "Hello? Who is this?"), ("scammer", CALLER)]
        finals = [e.data for e in events(c, case_id, "transcript.final")]
        assert [(f["speaker"], f["text"]) for f in finals] == [("meena", "Hello? Who is this?"), ("caller", CALLER)]
        assert all(f["message_id"] for f in finals)
        partials = [(e.data["speaker"], e.data["delta"]) for e in events(c, case_id, "transcript.partial")]
        assert partials == [("meena", "Hello? "), ("meena", "Who is this?"), ("caller", CALLER)]
        statuses = [e.data["status"] for e in events(c, case_id, "call.status")]
        assert statuses == ["ringing", "live", "ended"]
        assert any(i["kind"] == "upi" and i["value"] == "fakeinvest.demo@okaxis" for i in db(c, "list_intel", case_id))
        detected = events(c, case_id, "scam.detected")
        assert len(detected) == 1 and detected[0].data["verdict"] == "scam" and detected[0].data["stage"] == "final"
        case = call_case(c, "CA900")
        assert case["status"] == "closed" and case["verdict"] == "scam"
        assert reports == [case_id]

        # Twilio's completed callback after the stream ended the call changes nothing
        post(c, "/voice/status", {"CallSid": "CA900", "CallStatus": "completed"})
        assert reports == [case_id] and len(events(c, case_id, "case.updated")) == 1


def test_live_call_is_judged_in_batches_and_lines_end_on_a_pause(settings, fake, reports, monkeypatch):
    monkeypatch.setattr(stream, "PAUSE_S", 0.05)
    with running(settings, openai_api_key="test-key", call_batch_seconds=1) as c:
        case_id, params = start_call(c, "CA901")
        with c.websocket_connect("/voice/stream") as ws:
            ws.send_json(start_msg("CA901", params))
            ws.receive_json()
            ws.receive_json()
            ws.send_json({"event": "mark", "streamSid": "MZ1", "mark": {"name": "meena-1"}})  # Meena's line played
            ws.send_json(media(CALLER_AUDIO))
            deadline = time.time() + 5
            while time.time() < deadline and not events(c, case_id, "scam.detected"):
                time.sleep(0.1)
            assert [m["role"] for m in db(c, "list_messages", case_id)] == ["persona", "scammer"]
            assert events(c, case_id, "scam.detected")[0].data["verdict"] == "scam"
            assert call_case(c, "CA901")["verdict"] == "scam" and call_case(c, "CA901")["status"] == "open"
            ws.send_json({"event": "stop", "streamSid": "MZ1"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert "session.instructions.append" not in [m["type"] for m in fake.sent]  # no barge-in: audio had played
        assert len(events(c, case_id, "scam.detected")) == 1  # a confirmed scam is not judged again at the end
        assert call_case(c, "CA901")["status"] == "closed"


def test_stream_falls_back_to_speech_when_live_voice_cannot_open(settings, reports, monkeypatch):
    async def broken(api_key):
        raise OSError("no route")
    monkeypatch.setattr(stream, "connector", broken)
    with running(settings, openai_api_key="test-key") as c:
        case_id, params = start_call(c, "CA902")
        with c.websocket_connect("/voice/stream") as ws:
            ws.send_json(start_msg("CA902", params))
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1000
        fallback = [e.data for e in events(c, case_id, "call.status") if e.data["status"] == "fallback"]
        assert fallback and fallback[0]["detail"] == "live voice unavailable"
        assert call_case(c, "CA902")["status"] == "open" and reports == []
        # Twilio carries on with the TwiML after <Connect>: Meena keeps the caller talking in speech mode
        r = post(c, "/voice/turn", {"CallSid": "CA902", "SpeechResult": "Hello madam, I am from the bank."})
        assert ET.fromstring(r.text).find("Gather") is not None
        assert [m["role"] for m in db(c, "list_messages", case_id)][-2:] == ["scammer", "persona"]


@pytest.mark.parametrize("change", ["token", "case", "missing"])
def test_stream_refuses_a_bad_start(settings, fake, reports, change):
    with running(settings, openai_api_key="test-key") as c:
        case_id, params = start_call(c, "CA903")
        if change == "token":
            params = {**params, "token": "0" * 32}
        elif change == "case":
            params = {"case_id": "c_nope", "token": twiml.stream_token(AUTH, "c_nope")}
        else:
            params = {}
        with c.websocket_connect("/voice/stream") as ws:
            ws.send_json(start_msg("CA903", params))
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == stream.POLICY_VIOLATION
        assert fake.keys == [] and [e.data["status"] for e in events(c, case_id, "call.status")] == ["ringing"]


async def test_analyse_saves_the_verdict_before_announcing_it(runtime):
    case = await runtime.store.open_case("call", "call:CA950")
    assert await calls.analyse(case["id"]) is None  # nothing said yet
    await engine.record_scammer_text(case["id"], "call", CALLER)
    v = await calls.analyse(case["id"])
    assert v.label == "scam"
    saved = await runtime.store.get_case(case["id"])
    assert saved["verdict"] == "scam" and saved["scam_type"] == v.scam_type
    evs = [e for e in await runtime.store.events_for_case(case["id"]) if e.type == "scam.detected"]
    assert len(evs) == 1 and evs[0].data["p_scam"] is None and evs[0].data["decided_by"] == "rules"
    assert await calls.analyse(case["id"]) is None  # confirmed: not judged again


def test_live_protocol_messages():
    assert live.audio("abc") == {"type": "session.input_audio.append", "audio": "abc"}
    assert live.instruction("x") == {"type": "session.instructions.append", "delegation_id": None, "content": "x"}
    assert live.commentary("y")["type"] == "session.commentary.append"
    assert live.close() == {"type": "session.close"}
    assert twiml.stream_url("http://localhost:8000") == "ws://localhost:8000/voice/stream"
    assert twiml.stream_url("https://bait.example/app/") == "wss://bait.example/app/voice/stream"
