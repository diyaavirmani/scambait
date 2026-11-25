"""Phone calls: a scammer rings the Twilio number and Meena answers.

Routes (add with app.include_router(router)):
- POST /voice/incoming  Twilio voice webhook. With OPENAI_API_KEY the call is bridged to the live voice model over a
                        media stream (live mode); without it Twilio's speech recognition feeds the chat engine
                        (speech mode). Speech mode is also the fallback if the live voice fails mid-call.
- POST /voice/turn      speech mode: one caller utterance in, Meena's spoken reply out.
- POST /voice/status    call status callback: announces each status and ends the call when it is over.
- WS   /voice/stream    live mode: Twilio Media Streams bridged to the live voice model (app/voice/stream.py).

Every POST needs a valid X-Twilio-Signature for PUBLIC_BASE_URL + path, signed with TWILIO_AUTH_TOKEN.
"""
from fastapi import APIRouter

from app.voice import stream, webhooks

router = APIRouter()
router.include_router(webhooks.router)
router.include_router(stream.router)

__all__ = ["router"]
