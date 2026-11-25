"""Twilio voice webhooks: the call comes in, speech-mode turns, and call status updates.

Every request must carry a valid X-Twilio-Signature for PUBLIC_BASE_URL + path (never the Host header), signed with
TWILIO_AUTH_TOKEN; anything else, or a server without those settings, gets 403.

Speech mode (no OPENAI_API_KEY) uses Twilio's own speech recognition: each caller utterance is posted to /voice/turn
and runs a normal engine turn, and Meena's reply is spoken back. Twilio waits about 15 seconds for an answer, so a
turn that takes longer is not dropped: Meena says a short holding line and Twilio comes back for the reply.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response

from app import engine, meena
from app.bus import emit
from app.models import MAX_TEXT
from app.runtime import get_runtime
from app.voice import calls, persona, twiml

log = logging.getLogger("scambait.voice")
router = APIRouter()

TURN_WAIT_S = 9.0   # longest a webhook waits for Meena's reply before a holding line
MAX_QUIET = 3       # silent listens in a row before Meena hangs up

_turns: dict[str, asyncio.Task] = {}   # CallSid -> an engine turn still running after a holding line
_running: set[asyncio.Task] = set()    # every engine turn until it finishes, even after its call hung up
_hold_lines = itertools.cycle(persona.HOLD)


async def verified_form(request: Request, path: str) -> dict[str, str]:
    """The POST parameters, or 403 unless the Twilio signature matches."""
    s = get_runtime().settings
    if not s.twilio_auth_token or not s.public_base_url:
        log.warning("voice webhook refused: TWILIO_AUTH_TOKEN or PUBLIC_BASE_URL is not set")
        raise HTTPException(status_code=403, detail="Forbidden.")
    form = await request.form()
    params = [(k, v) for k, v in form.multi_items() if isinstance(v, str)]
    url = s.public_base_url + path + (f"?{request.url.query}" if request.url.query else "")
    if not twiml.signature_ok(s.twilio_auth_token, url, params, request.headers.get("X-Twilio-Signature", "")):
        log.warning("voice webhook refused: bad X-Twilio-Signature on %s", path)
        raise HTTPException(status_code=403, detail="Forbidden.")
    return dict(params)


def _url(path: str, **query) -> str:
    return get_runtime().settings.public_base_url + path + (f"?{urlencode(query)}" if query else "")


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


def _call_sid(form: dict[str, str]) -> str:
    sid = form.get("CallSid", "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="CallSid missing.")
    return sid


async def _spoken(case_id: str, text: str) -> None:
    """Store a line Meena says outside an engine turn, so the call transcript is complete."""
    await engine.record_persona_text(case_id, "call", text)


def _listen(text: str) -> str:
    return twiml.listen(text, action=_url("/voice/turn"), fallback=_url("/voice/turn", quiet=1))


@router.post("/voice/incoming")
async def incoming(request: Request) -> Response:
    form = await verified_form(request, "/voice/incoming")
    call_sid = _call_sid(form)
    rt = get_runtime()
    case = await rt.store.open_case("call", f"call:{call_sid}")
    calls.remember(call_sid, case["id"])
    await emit("call.status", {"status": "ringing", "call_sid": call_sid}, case["id"], "call")
    s = rt.settings
    if s.openai_api_key:
        log.info("call %s -> case %s (live voice)", call_sid, case["id"])
        params = {"case_id": case["id"], "token": twiml.stream_token(s.twilio_auth_token, case["id"])}
        return _xml(twiml.connect_stream(twiml.stream_url(s.public_base_url), params, _url("/voice/turn", quiet=1)))
    log.info("call %s -> case %s (speech mode)", call_sid, case["id"])
    await _spoken(case["id"], persona.GREETING)
    return _xml(_listen(persona.GREETING))


@router.post("/voice/turn")
async def turn(request: Request) -> Response:
    form = await verified_form(request, "/voice/turn")
    call_sid = _call_sid(form)
    case = await calls.case_for(call_sid) or await get_runtime().store.open_case("call", f"call:{call_sid}")
    calls.remember(call_sid, case["id"])
    task = _turns.pop(call_sid, None)
    if task is None:
        if case["status"] == "closed":
            await _spoken(case["id"], meena.GOODBYE)
            return _xml(twiml.hang_up(meena.GOODBYE))
        speech = form.get("SpeechResult", "").strip()[:MAX_TEXT]
        if not speech:
            quiet = request.query_params.get("quiet", "")
            return _xml(await _silence(case["id"], int(quiet) if quiet.isdigit() else 1))
        task = asyncio.create_task(engine.handle_message(case["id"], "call", speech))
        _running.add(task)
        task.add_done_callback(_running.discard)
    return _xml(await _answer(call_sid, case["id"], task))


async def _silence(case_id: str, quiet: int) -> str:
    if quiet >= MAX_QUIET:
        await _spoken(case_id, persona.NOBODY)
        return twiml.hang_up(persona.NOBODY)
    line = persona.STILL_THERE[(max(quiet, 1) - 1) % len(persona.STILL_THERE)]
    await _spoken(case_id, line)
    return twiml.listen(line, action=_url("/voice/turn"), fallback=_url("/voice/turn", quiet=max(quiet, 1) + 1))


async def _answer(call_sid: str, case_id: str, task: asyncio.Task) -> str:
    """Meena's reply once the engine turn is done; a holding line (and a redirect back here) while it is not."""
    done, _ = await asyncio.wait({task}, timeout=TURN_WAIT_S)
    if not done:
        _turns[call_sid] = task
        line = next(_hold_lines)
        await _spoken(case_id, line)
        return twiml.hold(line, redirect=_url("/voice/turn"))
    try:
        reply = task.result()
    except Exception:
        log.exception("call turn failed on %s", case_id)
        await _spoken(case_id, persona.LINE_TROUBLE)
        return _listen(persona.LINE_TROUBLE)
    if reply.closed:
        return twiml.hang_up(reply.text or meena.GOODBYE)
    return _listen(reply.text or meena.EMPTY)


@router.post("/voice/status")
async def status(request: Request, background: BackgroundTasks) -> Response:
    form = await verified_form(request, "/voice/status")
    call_sid = _call_sid(form)
    state = form.get("CallStatus", "").strip() or "unknown"
    case = await calls.case_for(call_sid)
    case_id = case["id"] if case else None
    data = {"status": state, "call_sid": call_sid}
    if form.get("CallDuration", "").isdigit():
        data["duration_s"] = int(form["CallDuration"])
    await emit("call.status", data, case_id, "call")
    if state in calls.TERMINAL:
        _turns.pop(call_sid, None)
        if case_id:
            calls.mark_hung_up(case_id)
            if not calls.streaming(case_id):  # a live stream ends its own call after storing its last lines
                background.add_task(calls.end_call, case_id)
    return Response(status_code=204)
