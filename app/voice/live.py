"""The OpenAI live voice protocol (GPT-Live over a websocket), as far as this app uses it.

Client events: session.start (must come first: model, instructions, audio format, voice), session.input_audio.append
{audio}, session.instructions.append and session.commentary.append {delegation_id, content}, session.close.
Server events: session.started {session: {id}}, session.output_audio.delta {delta}, session.input_transcript.delta
and session.output_transcript.delta {delta, start_ms, end_ms}, session.closed {usage}, error {error}.

Audio is G.711 mu-law at 8 kHz in both directions, the format Twilio Media Streams uses, so payloads pass through
unchanged. Caller speech is transcribed by the session itself; the docs show no setting to turn it on or off.

Not in the protocol, so handled by the bridge: there is no "caller started speaking" event, no end-of-turn event and
no cancel event. Barge-in is spotted from the caller's transcript while Meena's audio is still queued at Twilio, an
utterance ends after a pause in its transcript, and an instruction to stop and listen stands in for a cancel (the
docs say an instruction sent mid-call can interrupt speech in progress).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

URL = "wss://api.openai.com/v1/live/sessions"
AUDIO_FORMAT = {"type": "audio/pcmu", "rate": 8000}
VOICE = "marin"         # the documented default voice
OPEN_TIMEOUT_S = 10

STARTED = "session.started"
AUDIO_OUT = "session.output_audio.delta"
CALLER_TEXT = "session.input_transcript.delta"
MEENA_TEXT = "session.output_transcript.delta"
CLOSED = "session.closed"
ERROR = "error"

# A live socket has: await send(str), async iteration over incoming messages, await close().
Connector = Callable[[str], Awaitable[Any]]


async def connect(api_key: str) -> Any:
    """Open the live voice websocket. Raises when it cannot (no access, bad key, network). The key is never logged."""
    from websockets.asyncio.client import connect as ws_connect
    return await ws_connect(URL, additional_headers={"Authorization": f"Bearer {api_key}"},
                            open_timeout=OPEN_TIMEOUT_S)


def start(model: str, instructions: str) -> dict:
    return {"type": "session.start", "event_id": "start",
            "session": {"model": model, "instructions": instructions,
                        "audio": {"format": dict(AUDIO_FORMAT), "output": {"voice": VOICE}}}}


def audio(payload: str) -> dict:
    return {"type": "session.input_audio.append", "audio": payload}


def instruction(text: str) -> dict:
    return {"type": "session.instructions.append", "delegation_id": None, "content": text}


def commentary(text: str) -> dict:
    return {"type": "session.commentary.append", "delegation_id": None, "content": text}


def close() -> dict:
    return {"type": "session.close"}
