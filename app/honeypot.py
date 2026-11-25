"""The honeypot API, in the public contract automated graders already use.

POST /api/honeypot
  request  {"sessionId", "message": {"sender": "scammer", "text", "timestamp"}, "conversationHistory", "metadata"}
  response {"status": "success"|"degraded", "reply", "meta": {"agentState": "engaging"|"completed",
           "sessionStatus": "active"|"closed", "persona", "turn", "confidence", "scamType", "agentNotes", "degraded"}}

One sessionId is one case ("api:<sessionId>"), so the dashboard follows it live. The server keeps the history, so
conversationHistory and metadata are accepted and ignored. Once a chat has ended, the next message with that
sessionId starts a new case. Needs x-api-key when API_KEY is set. A bad sessionId or a sender other than "scammer"
is a 400; an internal error is a 500 with {"status": "error"} and no details.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import engine
from app.auth import require_api_key
from app.models import SESSION_RE, Reply
from app.runtime import get_runtime

log = logging.getLogger("scambait.honeypot")
router = APIRouter()

MAX_INBOUND = 10_000  # accepted from clients; the engine keeps the first MAX_TEXT characters
PERSONA = "meena"
CONFIDENCE = {"scam": "high", "not_scam": "medium", "unknown": "low"}


class HoneypotMessage(BaseModel):
    sender: str
    text: str = Field(..., min_length=1, max_length=MAX_INBOUND)
    timestamp: Union[int, float, str, None] = None


class HoneypotRequest(BaseModel):
    sessionId: str
    message: HoneypotMessage
    conversationHistory: Optional[list[dict[str, Any]]] = None
    metadata: Optional[dict[str, Any]] = None


class HoneypotMeta(BaseModel):
    agentState: Literal["engaging", "completed"]
    sessionStatus: Literal["active", "closed"]
    persona: str
    turn: int
    confidence: str
    scamType: str
    agentNotes: str
    degraded: bool


class HoneypotResponse(BaseModel):
    status: Literal["success", "degraded"]
    reply: str
    meta: HoneypotMeta


def agent_notes(reply: Reply, intel: list[dict], investigations: list[dict]) -> str:
    """A short plain summary of the conversation so far."""
    kind = reply.scam_type if reply.scam_type not in ("", "unknown", "not_a_scam") else ""
    notes = [f"Verdict: {reply.verdict}" + (f" ({kind})." if kind else ".")]
    counts = Counter(i["kind"] for i in intel)
    if counts:
        notes.append("Identifiers collected: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) + ".")
    proven = sum(1 for i in investigations if i.get("verdict") == "payment_request_found" and not i.get("recheck_of"))
    if proven:
        notes.append(f"Kane proved {proven} payment page{'s' if proven > 1 else ''}.")
    if reply.degraded:
        notes.append("Scripted fallback reply: the model failed.")
    if reply.closed:
        notes.append("Conversation closed.")
    return " ".join(notes)


def build_response(reply: Reply, notes: str) -> HoneypotResponse:
    scam_type = (reply.scam_type or "").strip()
    return HoneypotResponse(
        status="degraded" if reply.degraded else "success",
        reply=reply.text,
        meta=HoneypotMeta(
            agentState="completed" if reply.closed else "engaging",
            sessionStatus="closed" if reply.closed else "active",
            persona=PERSONA,
            turn=reply.turn,
            confidence=CONFIDENCE.get(reply.verdict, "low"),
            scamType=scam_type.upper() if scam_type and scam_type != "unknown" else "UNKNOWN",
            agentNotes=notes,
            degraded=reply.degraded,
        ),
    )


@router.post("/api/honeypot", response_model=HoneypotResponse, dependencies=[Depends(require_api_key)])
async def honeypot(body: HoneypotRequest):
    if not SESSION_RE.match(body.sessionId):
        raise HTTPException(status_code=400, detail="Invalid sessionId (A-Z a-z 0-9 _ -, 1 to 64 characters).")
    if body.message.sender != "scammer":
        raise HTTPException(status_code=400, detail='message.sender must be "scammer".')
    try:
        store = get_runtime().store
        case = await store.open_case("api", f"api:{body.sessionId}")
        reply = await engine.handle_message(case["id"], "api", body.message.text)
        if reply.degraded:
            log.warning("honeypot reply on %s was a scripted fallback", reply.case_id)
        notes = agent_notes(reply, await store.list_intel(reply.case_id),
                            await store.list_investigations(reply.case_id))
        return build_response(reply, notes)
    except Exception:
        log.exception("honeypot turn failed")
        return JSONResponse({"status": "error"}, status_code=500)
