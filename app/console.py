"""The browser scam console: play the scammer against Meena, no Telegram needed.

POST /api/console/messages {"session_id", "text"} -> {"case_id", "reply", "verdict", "scam_type", "turn", "closed",
"degraded"}. One browser session is one case ("web:<session_id>"), so the dashboard follows it live, including
Kane's investigation of any link sent here. CONSOLE_ENABLED=0 turns it off.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import engine, limits
from app.models import MAX_TEXT, SESSION_RE
from app.runtime import get_runtime

router = APIRouter()


class ConsoleMessage(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=MAX_TEXT)


@router.post("/api/console/messages")
async def console_message(body: ConsoleMessage, request: Request) -> dict:
    rt = get_runtime()
    if not rt.settings.console_enabled:
        raise HTTPException(status_code=404, detail="The scam console is turned off.")
    if not SESSION_RE.match(body.session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id (A-Z a-z 0-9 _ -, 1 to 64 characters).")
    if not limits.allow("console:" + (request.client.host if request.client else "?")):
        raise HTTPException(status_code=429, detail="Too many messages. Wait a minute and try again.")
    case = await rt.store.open_case("web", f"web:{body.session_id}")
    r = await engine.handle_message(case["id"], "web", body.text.strip())
    return {"case_id": r.case_id, "reply": r.text, "verdict": r.verdict, "scam_type": r.scam_type, "turn": r.turn,
            "closed": r.closed, "degraded": r.degraded}
