"""Shared data shapes."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MAX_TEXT = 4000  # inbound text is cut to this before any regex or model call
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Every event the server sends. The dashboard must listen for all of them (tests/test_event_contract.py).
EVENT_TYPES = (
    "message.received",   # a scammer message was stored
    "persona.reply",      # Meena answered
    "scam.detected",      # a verdict on the conversation
    "intel.extracted",    # a new identifier (UPI ID, phone, account, link...)
    "case.updated",       # summary or status changed
    "kane.started",       # Kane began investigating a link
    "kane.finished",      # Kane's result for a link
    "call.status",        # a phone call rang, went live or ended
    "transcript.partial", # live call speech as it arrives
    "transcript.final",   # a finished call utterance
    "metrics.speed",      # how long a model call took
    "network.updated",    # cases linked by a shared identifier changed
)

IntelKind = Literal["upi", "phone", "bank_account", "ifsc", "url", "apk", "email", "card", "amount"]
VerdictLabel = Literal["scam", "not_scam", "unknown"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Event(BaseModel):
    id: Optional[int] = None
    ts: str = Field(default_factory=utc_now)
    case_id: Optional[str] = None
    channel: str = "web"
    type: str
    data: dict[str, Any] = {}


class Intel(BaseModel):
    kind: IntelKind
    value: str


class Verdict(BaseModel):
    label: VerdictLabel
    p_scam: Optional[float] = None   # the deciding model's probability (None when rules decided)
    scam_type: str = "unknown"
    risk: str = "unknown"
    decided_by: str = "none"   # cerebras | decisions | rules | none
    rule_score: float = 0.0
    red_flags: list[str] = []
    p_cerebras: Optional[float] = None
    p_decisions: Optional[float] = None
    decisions_available: Optional[bool] = None   # None: no OpenAI key; False: Decisions gave no answer this time


class Reply(BaseModel):
    case_id: str
    text: str
    verdict: VerdictLabel = "unknown"
    scam_type: str = "unknown"
    turn: int = 0
    closed: bool = False
    degraded: bool = False    # a scripted fallback answered because the model failed
