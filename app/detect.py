"""Is this conversation a scam? Rules first, then the model, combined into one verdict.

- The model (brain.flag) decides when it is confident: scam at p >= 0.6, not a scam at p <= 0.35.
- In between, or when the model is unavailable, the rule score decides: scam at >= 0.45 (>= 0.5 without a model),
  not a scam below 0.15 with a safe cue such as "do not share".
- An error never becomes "not a scam": the verdict is "unknown" and Meena keeps engaging carefully.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import rules
from app.models import Verdict

log = logging.getLogger("scambait.detect")

MODEL_SCAM, MODEL_SAFE = 0.6, 0.35
RULES_SCAM, RULES_SCAM_ALONE, RULES_SAFE = 0.45, 0.5, 0.15


async def judge(window: list[dict], case_id: Optional[str] = None) -> Verdict:
    """window: the latest messages, oldest first, as {"role": "scammer"|"persona", "text": str}."""
    from app.runtime import get_runtime
    scammer = " ".join(m["text"] for m in window if m.get("role") == "scammer")
    latest = next((m["text"] for m in reversed(window) if m.get("role") == "scammer"), "")
    value, signs = rules.score(scammer)
    flags = [s.label for s in signs]
    kind = rules.scam_type(scammer)

    model: Optional[dict] = None
    try:
        model = await get_runtime().brain.flag(window, case_id)
    except Exception as exc:
        log.warning("scam flag unavailable: %s", type(exc).__name__)

    if model is not None and model.get("p_scam") is not None:
        p = float(model["p_scam"])
        model_type = model.get("scam_type") or "other"
        if p >= MODEL_SCAM:
            return Verdict(label="scam", p_scam=p, scam_type=model_type if model_type != "other" else kind,
                           risk=model.get("risk", "high"), decided_by="model", rule_score=value, red_flags=flags)
        if p <= MODEL_SAFE:
            return Verdict(label="not_scam", p_scam=p, scam_type="not_a_scam", risk="none", decided_by="model",
                           rule_score=value, red_flags=flags)
        threshold = RULES_SCAM
    else:
        p, threshold = None, RULES_SCAM_ALONE

    if value >= threshold:
        return Verdict(label="scam", p_scam=p, scam_type=kind, risk="high", decided_by="rules", rule_score=value,
                       red_flags=flags)
    if value < RULES_SAFE and rules.looks_safe(latest):
        return Verdict(label="not_scam", p_scam=p, scam_type="not_a_scam", risk="none", decided_by="rules",
                       rule_score=value, red_flags=flags)
    return Verdict(label="unknown", p_scam=p, scam_type=kind if value else "unknown", decided_by="none",
                   rule_score=value, red_flags=flags)
