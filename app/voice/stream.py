"""WS /voice/stream: one phone call between Twilio Media Streams and the live voice model.

Twilio sends connected, start (streamSid, callSid, customParameters), media (base64 mu-law 8 kHz), mark (echoed when
the audio we sent before it has played) and stop. The start parameters must carry the case id and its stream token
(app.voice.twiml.stream_token), or the socket is closed with 1008.

Caller audio goes to the live session as it arrives. Meena's audio goes back to Twilio as media, each chunk followed
by a mark, so the bridge knows what is still queued at Twilio. When the caller talks over queued audio, Twilio gets a
"clear" and the live session an instruction to stop and listen (barge-in).

Transcript deltas are emitted as transcript.partial. An utterance ends after PAUSE_S without a new delta, when the
other side starts talking, or when the call ends; it is stored (caller lines with engine.record_scammer_text, Meena's
with engine.record_persona_text) and then emitted as transcript.final. Every call_batch_seconds with new caller
lines the call is judged.

If the live session cannot be opened or drops, the socket is closed and Twilio carries on with the TwiML after
<Connect>: the speech fallback (/voice/turn). On Twilio's stop the call is over: last lines stored, call.status
ended, then app.voice.calls.end_call (final analysis, case closed, report).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app import engine
from app.bus import emit
from app.runtime import get_runtime
from app.voice import calls, live, persona, twiml

log = logging.getLogger("scambait.voice")
router = APIRouter()

START_TIMEOUT_S = 10.0   # wait for Twilio's start message
PAUSE_S = 0.8            # a gap this long in one speaker's transcript ends their utterance
TICK_S = 0.1
CLOSE_WAIT_S = 2.0       # wait for session.closed after session.close
MAX_UTTERANCE = 1500     # characters; a longer run of speech is stored in pieces
POLICY_VIOLATION = 1008
SPEAKERS = ("caller", "meena")

connector: live.Connector = live.connect   # tests swap in a fake live socket


class CallBridge:
    def __init__(self, twilio: WebSocket, settings: Any, connect: Optional[live.Connector] = None) -> None:
        self.twilio = twilio
        self.settings = settings
        self.connect = connect or connector
        self.live: Any = None
        self.live_ready = False       # session.started seen; no audio may be sent before it
        self.live_reason = ""
        self.stream_sid = self.call_sid = self.case_id = ""
        self.stopped = False          # Twilio sent stop: the call is over
        self.unplayed: set[str] = set()   # marks Twilio has not echoed yet: Meena's audio still queued
        self.marks = 0
        self.barge_ins = 0
        self.parts: dict[str, list[str]] = {s: [] for s in SPEAKERS}
        self.last_delta: dict[str, float] = {}
        self.caller_lines = 0
        self.judged_lines = 0
        self._live_lock = asyncio.Lock()

    async def run(self) -> None:
        start = await self._wait_for_start()
        if start is None or not await self._admit(start):
            await self._close_twilio(POLICY_VIOLATION)
            return
        calls.stream_opened(self.case_id)
        try:
            outcome = await self._converse()
        except Exception:
            log.exception("call %s: bridge failed", self.call_sid)
            outcome = "live"
        finally:
            calls.stream_closed(self.case_id)
        await self._finish(outcome)

    # ---------- start ----------
    async def _wait_for_start(self) -> Optional[dict]:
        async def read() -> Optional[dict]:
            while True:
                msg = json.loads(await self.twilio.receive_text())
                if msg.get("event") == "start":
                    return msg.get("start") or {}
                if msg.get("event") == "stop":
                    return None
        try:
            return await asyncio.wait_for(read(), START_TIMEOUT_S)
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError, RuntimeError, AttributeError):
            return None

    async def _admit(self, start: dict) -> bool:
        params = start.get("customParameters") or {}
        case_id, token = str(params.get("case_id") or ""), str(params.get("token") or "")
        self.stream_sid, self.call_sid = str(start.get("streamSid") or ""), str(start.get("callSid") or "")
        if not self.stream_sid or not twiml.stream_token_ok(self.settings.twilio_auth_token, case_id, token):
            log.warning("voice stream refused: missing stream id or bad stream token")
            return False
        case = await get_runtime().store.get_case(case_id)
        if case is None or case["channel"] != "call" or case["status"] == "closed":
            log.warning("voice stream refused: case %s is not an open call", case_id)
            return False
        self.case_id = case_id
        calls.remember(self.call_sid, case_id)
        return True

    # ---------- the call ----------
    async def _converse(self) -> str:
        """Run the call until one side ends it: "stop" (Twilio ended the call), "twilio" (Twilio's socket went away
        without a stop) or "live" (the live session could not start or ended)."""
        if not self.settings.openai_api_key:
            self.live_reason = "live voice is not configured"
            return "live"
        try:
            self.live = await self.connect(self.settings.openai_api_key)
        except Exception as exc:
            self.live_reason = "live voice unavailable"
            log.warning("call %s: live voice connect failed: %s", self.call_sid, type(exc).__name__)
            return "live"
        await self._send_live(live.start(self.settings.live_model, persona.phone_instructions()))
        from_twilio = asyncio.create_task(self._from_twilio())
        from_live = asyncio.create_task(self._from_live())
        helpers = [asyncio.create_task(self._flush_loop()), asyncio.create_task(self._batch_loop())]
        try:
            done, _ = await asyncio.wait({from_twilio, from_live}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception() is not None:
                    log.warning("call %s: bridge loop failed: %s", self.call_sid, type(task.exception()).__name__)
        finally:
            for task in (from_twilio, *helpers):
                task.cancel()
            await self._close_live(from_live)
            await asyncio.gather(from_twilio, *helpers, return_exceptions=True)
        for speaker in SPEAKERS:
            await self._flush(speaker)
        if self.stopped:
            return "stop"
        return "twilio" if from_twilio in done else "live"

    async def _finish(self, outcome: str) -> None:
        if outcome == "live":
            # Twilio is still on the line: closing the socket moves the call on to the speech fallback.
            log.warning("call %s: %s, falling back to speech mode", self.call_sid, self.live_reason or "live ended")
            await emit("call.status", {"status": "fallback", "call_sid": self.call_sid,
                                       "detail": self.live_reason or "live voice ended"}, self.case_id, "call")
            await self._close_twilio(1000)
            if calls.hung_up(self.case_id):
                await calls.end_call(self.case_id)
            return
        await emit("call.status", {"status": "ended", "call_sid": self.call_sid}, self.case_id, "call")
        if outcome == "stop" or calls.hung_up(self.case_id):
            await calls.end_call(self.case_id)
        log.info("call %s ended (audio chunks %d, barge-ins %d)", self.call_sid, self.marks, self.barge_ins)
        await self._close_twilio(1000)

    # ---------- Twilio -> live ----------
    async def _from_twilio(self) -> None:
        while True:
            try:
                raw = await self.twilio.receive_text()
            except (WebSocketDisconnect, RuntimeError, KeyError):
                return
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            event = msg.get("event") if isinstance(msg, dict) else None
            if event == "media":
                payload = (msg.get("media") or {}).get("payload")
                if payload and self.live_ready:
                    await self._send_live(live.audio(payload))
            elif event == "mark":
                self.unplayed.discard((msg.get("mark") or {}).get("name"))
            elif event == "stop":
                self.stopped = True
                return

    # ---------- live -> Twilio ----------
    async def _from_live(self) -> None:
        try:
            async for raw in self.live:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                kind = ev.get("type") if isinstance(ev, dict) else None
                if kind == live.STARTED:
                    await self._on_started(ev)
                elif kind == live.AUDIO_OUT:
                    await self._play(ev.get("delta"))
                elif kind == live.CALLER_TEXT:
                    await self._heard("caller", ev.get("delta"))
                elif kind == live.MEENA_TEXT:
                    await self._heard("meena", ev.get("delta"))
                elif kind == live.CLOSED:
                    self.live_reason = "live voice session closed"
                    return
                elif kind == live.ERROR:
                    err = ev.get("error") or {}
                    log.warning("call %s: live voice error %s", self.call_sid,
                                err.get("code") or err.get("type") or "unknown")
            self.live_reason = self.live_reason or "live voice connection closed"
        except Exception as exc:
            self.live_reason = f"live voice connection lost ({type(exc).__name__})"

    async def _on_started(self, ev: dict) -> None:
        self.live_ready = True
        log.info("call %s: live session %s started", self.call_sid, (ev.get("session") or {}).get("id") or "?")
        await emit("call.status", {"status": "live", "call_sid": self.call_sid}, self.case_id, "call")
        await self._send_live(live.commentary(persona.PICK_UP))

    async def _play(self, payload: Any) -> None:
        if not isinstance(payload, str) or not payload:
            return
        self.marks += 1
        name = f"meena-{self.marks}"
        await self._to_twilio({"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}})
        await self._to_twilio({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
        self.unplayed.add(name)

    async def _barge_in(self) -> None:
        """The caller talks over Meena: drop the audio Twilio has queued and tell the live session to stop."""
        self.unplayed.clear()
        self.barge_ins += 1
        await self._to_twilio({"event": "clear", "streamSid": self.stream_sid})
        await self._send_live(live.instruction(persona.STOP_AND_LISTEN))

    # ---------- transcripts ----------
    async def _heard(self, speaker: str, delta: Any) -> None:
        if not isinstance(delta, str) or not delta:
            return
        await emit("transcript.partial", {"speaker": speaker, "delta": delta, "call_sid": self.call_sid},
                   self.case_id, "call")
        other = "meena" if speaker == "caller" else "caller"
        if delta.strip() and self.parts[other]:
            await self._flush(other)  # one side starts, so the other side's line is finished
        if speaker == "caller" and delta.strip() and self.unplayed:
            await self._barge_in()
        self.parts[speaker].append(delta)
        self.last_delta[speaker] = asyncio.get_running_loop().time()
        if sum(len(p) for p in self.parts[speaker]) >= MAX_UTTERANCE:
            await self._flush(speaker)

    async def _flush(self, speaker: str) -> None:
        """Store one finished utterance, then announce it."""
        text = "".join(self.parts[speaker]).strip()
        self.parts[speaker] = []
        self.last_delta.pop(speaker, None)
        if not text:
            return
        try:
            if speaker == "caller":
                mid, _ = await engine.record_scammer_text(self.case_id, "call", text)
                self.caller_lines += 1
            else:
                mid = await engine.record_persona_text(self.case_id, "call", text)
        except Exception:
            log.exception("call %s: could not store a %s line", self.call_sid, speaker)
            return
        await emit("transcript.final", {"speaker": speaker, "text": text, "message_id": mid,
                                        "call_sid": self.call_sid}, self.case_id, "call")

    async def _flush_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(TICK_S)
            for speaker, at in list(self.last_delta.items()):
                if loop.time() - at >= PAUSE_S:
                    await self._flush(speaker)

    async def _batch_loop(self) -> None:
        every = max(1, int(self.settings.call_batch_seconds or 20))
        while True:
            await asyncio.sleep(every)
            if self.caller_lines > self.judged_lines:
                self.judged_lines = self.caller_lines
                await calls.analyse(self.case_id)

    # ---------- sockets ----------
    async def _send_live(self, msg: dict) -> None:
        if self.live is None:
            return
        try:
            async with self._live_lock:
                await self.live.send(json.dumps(msg))
        except Exception as exc:  # the live loop sees the closed socket and ends the call's live side
            log.debug("call %s: live send failed: %s", self.call_sid, type(exc).__name__)

    async def _to_twilio(self, msg: dict) -> None:
        try:
            await self.twilio.send_text(json.dumps(msg))
        except Exception as exc:  # Twilio hung up; the Twilio loop ends the call
            log.debug("call %s: Twilio send failed: %s", self.call_sid, type(exc).__name__)

    async def _close_live(self, from_live: asyncio.Task) -> None:
        if self.live is None:
            return
        if not from_live.done():
            await self._send_live(live.close())
            await asyncio.wait({from_live}, timeout=CLOSE_WAIT_S)  # late transcript deltas still arrive
            from_live.cancel()
        await asyncio.gather(from_live, return_exceptions=True)
        try:
            await self.live.close()
        except Exception:
            pass

    async def _close_twilio(self, code: int) -> None:
        try:
            await self.twilio.close(code=code)
        except Exception:
            pass


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await CallBridge(websocket, get_runtime().settings).run()
    except Exception:
        log.exception("voice stream failed")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
