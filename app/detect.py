"""Is this conversation a scam? Three opinions, one verdict.

- Rules (app.rules) score the sender's text: no model, and the red flags people are shown.
- Cerebras (brain.flag) and OpenAI Decisions (rt.openai.decisions, when a key is set) are asked at the same time.
- Cerebras decides when it is sure: not a scam at p <= 0.2, a scam at p >= 0.8. In the band between, Decisions
  decides at 0.5. If only one model answered, its p decides at 0.5.
- With no model opinion the rules decide: a scam at >= 0.5, not a scam below 0.15 with a safe cue such as
  "do not share", otherwise unknown.
- An error never becomes "not a scam": a model that fails gives no opinion, and with none the rules can only say
  "not a scam" on a safe cue.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from app import rules
from app.models import Verdict

log = logging.getLogger("scambait.detect")

CEREBRAS_SAFE, CEREBRAS_SCAM = 0.2, 0.8
MODEL_THRESHOLD = 0.5            # Decisions in the band, or whichever model answered alone
RULES_SCAM, RULES_SAFE = 0.5, 0.15
VAGUE_TYPES = {None, "", "other", "unknown", "not_a_scam"}
SCAM_RISKS = ("low", "high", "critical")


async def _opinion(name: str, ask: Callable[[], Awaitable[Optional[dict]]]) -> Optional[dict]:
    """A model's answer with p_scam in 0..1, or None for no opinion (an error, None, or no p_scam)."""
    try:
        out = await ask()
        p = float(out["p_scam"]) if isinstance(out, dict) and out.get("p_scam") is not None else None
    except Exception as exc:
        log.warning("%s opinion unavailable: %s", name, type(exc).__name__)
        return None
    if p is None or p != p:  # p != p drops NaN
        return None
    return {**out, "p_scam": min(1.0, max(0.0, p))}


async def _nothing() -> None:
    return None


def _scam_type(first: dict, second: Optional[dict], rules_kind: str) -> str:
    for kind in (first.get("scam_type"), (second or {}).get("scam_type"), rules_kind):
        if kind not in VAGUE_TYPES:
            return kind
    return "other"


def _risk(first: dict, second: Optional[dict]) -> str:
    for risk in (first.get("risk"), (second or {}).get("risk")):
        if risk in SCAM_RISKS:
            return risk
    return "high"


async def judge(window: list[dict], case_id: Optional[str] = None) -> Verdict:
    """window: the latest messages, oldest first, as {"role": "scammer"|"persona", "text": str}."""
    from app.runtime import get_runtime
    rt = get_runtime()
    scammer = " ".join(m["text"] for m in window if m.get("role") == "scammer")
    latest = next((m["text"] for m in reversed(window) if m.get("role") == "scammer"), "")
    value, signs = rules.score(scammer)
    flags = [s.label for s in signs]
    kind = rules.scam_type(scammer)

    openai = getattr(rt, "openai", None)
    cerebras, decisions = await asyncio.gather(
        _opinion("Cerebras", lambda: rt.brain.flag(window, case_id)),
        _opinion("Decisions", lambda: openai.decisions(window, case_id=case_id)) if openai is not None else _nothing())
    p_c = cerebras["p_scam"] if cerebras else None
    p_d = decisions["p_scam"] if decisions else None
    common = {"rule_score": value, "red_flags": flags, "p_cerebras": p_c, "p_decisions": p_d,
              "decisions_available": None if openai is None else decisions is not None}

    source: Optional[dict] = None
    other: Optional[dict] = None
    by = "none"
    if cerebras and (p_c <= CEREBRAS_SAFE or p_c >= CEREBRAS_SCAM):
        source, other, by = cerebras, decisions, "cerebras"
    elif decisions:
        source, other, by = decisions, cerebras, "decisions"
    elif cerebras:
        source, other, by = cerebras, None, "cerebras"

    if source is not None:
        # Cerebras's own lines (0.2 and 0.8) sit either side of 0.5, so one test covers every case.
        p = source["p_scam"]
        if p >= MODEL_THRESHOLD:
            return Verdict(label="scam", p_scam=p, scam_type=_scam_type(source, other, kind),
                           risk=_risk(source, other), decided_by=by, **common)
        return Verdict(label="not_scam", p_scam=p, scam_type="not_a_scam", risk="none", decided_by=by, **common)

    if value >= RULES_SCAM:
        return Verdict(label="scam", scam_type=kind, risk="high", decided_by="rules", **common)
    if value < RULES_SAFE and rules.looks_safe(latest):
        return Verdict(label="not_scam", scam_type="not_a_scam", risk="none", decided_by="rules", **common)
    return Verdict(label="unknown", scam_type=kind if value else "unknown", decided_by="none", **common)
