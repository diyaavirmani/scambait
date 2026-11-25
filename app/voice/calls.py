"""Call bookkeeping shared by the webhooks and the media stream: which case a call belongs to, judging the call, and
ending it exactly once.

One server process (see app/main.py), so these in-memory maps are the whole truth for calls in progress. A call
whose map entry was lost in a restart is found again from its case (external_id "call:<CallSid>").
"""
from __future__ import annotations

import inspect
import logging
from typing import Optional

from app import detect
from app.bus import emit
from app.models import Verdict
from app.runtime import get_runtime

log = logging.getLogger("scambait.voice")

CALL_WINDOW = 12   # call lines the detector reads (spoken lines are shorter than chat messages)
SCAN_LIMIT = 500   # recent cases searched when a CallSid is not in memory
TERMINAL = frozenset({"completed", "failed", "busy", "no-answer", "canceled"})

_case_of: dict[str, str] = {}   # CallSid -> case id
_streaming: set[str] = set()    # cases with a live media stream open (the stream ends those calls itself)
_hung_up: set[str] = set()      # cases whose call Twilio reported as finished
_ended: set[str] = set()        # cases whose call has been ended


def remember(call_sid: str, case_id: str) -> None:
    if call_sid:
        _case_of[call_sid] = case_id


async def case_for(call_sid: str) -> Optional[dict]:
    """The case for a call, closed or not, or None."""
    if not call_sid:
        return None
    store = get_runtime().store
    case_id = _case_of.get(call_sid)
    case = await store.get_case(case_id) if case_id else None
    if case is not None:
        return case
    external = f"call:{call_sid}"
    for row in await store.list_cases(limit=SCAN_LIMIT):
        if row["external_id"] == external:
            remember(call_sid, row["id"])
            return row
    return None


def stream_opened(case_id: str) -> None:
    _streaming.add(case_id)


def stream_closed(case_id: str) -> None:
    _streaming.discard(case_id)


def streaming(case_id: str) -> bool:
    return case_id in _streaming


def mark_hung_up(case_id: str) -> None:
    _hung_up.add(case_id)


def hung_up(case_id: str) -> bool:
    return case_id in _hung_up


async def analyse(case_id: str) -> Optional[Verdict]:
    """Judge the latest call lines, save the verdict, then announce it. A confirmed scam stays a scam (as in chat),
    so it is not judged again. Returns the verdict, or None when nothing was judged. Never raises."""
    try:
        store = get_runtime().store
        case = await store.get_case(case_id)
        if case is None or case["verdict"] == "scam":
            return None
        window = [{"role": m["role"], "text": m["text"]} for m in (await store.list_messages(case_id))[-CALL_WINDOW:]]
        if not any(m["role"] == "scammer" for m in window):
            return None
        v = await detect.judge(window, case_id)
        verdict, scam_type = case["verdict"], case["scam_type"]
        if v.label != "unknown" or verdict == "unknown":
            verdict = v.label
            scam_type = v.scam_type if v.label == "scam" else ("not_a_scam" if v.label == "not_scam" else scam_type)
            await store.update_case(case_id, verdict=verdict, scam_type=scam_type)
        data = {"stage": "final", "verdict": v.label, "scam_type": v.scam_type, "risk": v.risk,
                "decided_by": v.decided_by, "p_scam": v.p_scam, "rule_score": v.rule_score, "red_flags": v.red_flags}
        for extra in ("p_cerebras", "p_decisions", "decisions_available"):  # the same fields the chat engine sends
            data[extra] = getattr(v, extra, None)
        await emit("scam.detected", data, case_id, "call")
        return v
    except Exception:
        log.exception("call analysis failed for %s", case_id)
        return None


async def run_report(case_id: str) -> None:
    """The end-of-call report, when app.report is there. Never raises."""
    try:
        from app.report import write_report
    except ImportError:
        log.info("no report module, skipping the call report for %s", case_id)
        return
    try:
        result = write_report(case_id)
        if inspect.isawaitable(result):
            await result
    except Exception:
        log.exception("call report failed for %s", case_id)


async def end_call(case_id: str) -> bool:
    """Final analysis, close the case, announce it, write the report. Only the first call per case does anything."""
    if not case_id or case_id in _ended:
        return False
    _ended.add(case_id)  # before any await, so a second caller returns at once
    store = get_runtime().store
    await analyse(case_id)
    try:
        await store.update_case(case_id, status="closed")
        case = await store.get_case(case_id)
        await emit("case.updated", {k: case[k] for k in ("status", "verdict", "scam_type", "summary")},
                   case_id, "call")
    except Exception:
        log.exception("could not close call case %s", case_id)
    await run_report(case_id)
    return True
