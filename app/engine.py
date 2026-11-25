"""One scammer message in, one Meena reply out.

For each message: store it, pull out identifiers (and hand every new link to the Kane investigator), then, one turn
at a time per case: judge the conversation until it is confirmed as a scam, pick Meena's mode, give her what she
knows (facts the scammer gave, and payment pages Kane proved that she has not talked about yet), guard her reply,
store it, and tell the dashboard. Every step's state lives in the database, so a restart loses nothing.

Order matters for the dashboard: a change is saved before the event that announces it, so a page that loads in
between never shows stale data.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from typing import Optional

from app import detect, meena
from app.brain import scripted_line
from app.bus import emit
from app.intel import extract, normalise
from app.models import MAX_TEXT, Reply
from app.runtime import get_runtime

log = logging.getLogger("scambait.engine")

WINDOW = 6            # messages the detector reads
CLOSE_AT = 20         # scammer messages before Meena says goodbye
GOODBYE_AFTER = 15    # a goodbye from the scammer ends it from here on
GOODBYE_RE = re.compile(r"\b(?:bye|goodbye|good\s+bye|alvida|tata)\b", re.IGNORECASE)

CODE_RE = re.compile(r"\b(?=[A-Za-z0-9-]{3,20}\b)(?=\S*[A-Za-z])(?=\S*\d)[A-Za-z0-9-]+\b")
NAME_RE = re.compile(r"\b(?:I am|I'm|my name is|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
ORG_RE = re.compile(r"\bfrom\s+([A-Z][A-Za-z&.]*(?:\s+[A-Z][A-Za-z&.]*){0,3})")
FACT_LABEL = {"upi": "UPI ID they gave", "phone": "Phone they gave", "bank_account": "Bank account they gave",
              "ifsc": "IFSC they gave", "url": "Link they sent", "apk": "App file they sent", "email": "Email they gave",
              "card": "Card number they gave", "amount": "Amount they asked for"}

_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()


def _lock(case_id: str) -> asyncio.Lock:
    return _locks.setdefault(case_id, asyncio.Lock())


def _spawn(coro) -> None:
    async def run():
        try:
            await coro
        except Exception:
            log.exception("background task failed")
    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def settle() -> None:
    """Tests: wait for background work started by the engine."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def opening_facts(text: str) -> list[str]:
    """Codes, names and organisations from the scammer's first message, so Meena can recall them later."""
    facts = [f"Code they gave: {m.group(0)}" for m in CODE_RE.finditer(text or "")]
    facts += [f"Name they gave: {m.group(1)}" for m in NAME_RE.finditer(text or "")]
    facts += [f"They said they are from: {m.group(1).rstrip('.')}" for m in ORG_RE.finditer(text or "")]
    return facts


async def facts_for(case_id: str, history: list[dict]) -> list[str]:
    store = get_runtime().store
    first = next((m["text"] for m in history if m["role"] == "scammer"), "")
    facts = opening_facts(first)
    facts += [f"{FACT_LABEL.get(i['kind'], i['kind'])}: {i['value']}" for i in await store.list_intel(case_id)]
    for inv in await store.list_investigations(case_id):
        if inv.get("verdict") == "payment_request_found":
            facts.append("Link they sent, checked: " + meena.finding_sentence(inv))
    seen, out = set(), []
    for f in facts:
        if f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out[:40]


async def _store_intel(case_id: str, channel: str, text: str, message_id: int) -> None:
    from app import networks
    from app.investigate import start_investigation
    store = get_runtime().store
    linked = False
    for item in extract(text):
        if await store.add_intel(case_id, item.kind, item.value, normalise(item.kind, item.value), message_id):
            await emit("intel.extracted", {"kind": item.kind, "value": item.value, "message_id": message_id},
                       case_id, channel)
            linked = linked or item.kind in networks.LINK_KINDS
            if item.kind == "url" and not normalise("url", item.value).endswith(".apk"):
                _spawn(start_investigation(item.value, case_id, channel))
    if linked:
        await networks.on_identifier_added(case_id, channel)


async def record_scammer_text(case_id: str, channel: str, text: str) -> tuple[int, int]:
    """Store what the scammer said (a chat message or a finished call utterance), announce it, and pull out its
    identifiers (new links go to Kane). Returns (message id, scammer message count)."""
    store = get_runtime().store
    text = (text or "").strip()[:MAX_TEXT]
    mid = await store.add_message(case_id, "scammer", text)
    turn = await store.count_messages(case_id, "scammer")
    await emit("message.received", {"role": "scammer", "text": text, "message_id": mid, "turn": turn}, case_id, channel)
    await _store_intel(case_id, channel, text, mid)
    if get_runtime().openai is not None:
        _spawn(_moderate(case_id, channel, text))
    return mid, turn


async def _moderate(case_id: str, channel: str, text: str) -> None:
    """OpenAI moderation on what the scammer said. A flag (threats, harassment) is noted on the case; a failed call
    never holds up the conversation."""
    from app.openai_client import OpenAIError
    try:
        res = await get_runtime().openai.moderate(text, case_id=case_id)
    except OpenAIError as exc:
        log.info("moderation skipped on %s: %s", case_id, exc)
        return
    if res.get("flagged"):
        await emit("case.updated", {"moderation": res.get("categories", [])}, case_id, channel)


async def record_persona_text(case_id: str, channel: str, text: str, **extra) -> int:
    """Store what Meena said outside a chat turn (for example on a phone call) and announce it."""
    mid = await get_runtime().store.add_message(case_id, "persona", text)
    await emit("persona.reply", {"text": text, "message_id": mid, "kane_findings_used": 0, **extra}, case_id, channel)
    return mid


async def handle_message(case_id: str, channel: str, text: str) -> Reply:
    rt = get_runtime()
    store = rt.store
    text = (text or "").strip()[:MAX_TEXT]
    mid, turn = await record_scammer_text(case_id, channel, text)

    async with _lock(case_id):
        case = await store.get_case(case_id)
        if case["status"] == "closed":
            return Reply(case_id=case_id, text=meena.GOODBYE, verdict=case["verdict"], scam_type=case["scam_type"],
                         turn=turn, closed=True)
        history = [{"role": m["role"], "text": m["text"]} for m in await store.list_messages(case_id)]

        verdict, scam_type = case["verdict"], case["scam_type"]
        if verdict != "scam":
            v = await detect.judge(history[-WINDOW:], case_id)
            if v.label != "unknown" or verdict == "unknown":
                verdict = v.label
                scam_type = v.scam_type if v.label == "scam" else ("not_a_scam" if v.label == "not_scam" else scam_type)
                await store.update_case(case_id, verdict=verdict, scam_type=scam_type)
            await emit("scam.detected", {"stage": "final", "verdict": v.label, "p_scam": v.p_scam,
                                         "scam_type": v.scam_type, "risk": v.risk, "decided_by": v.decided_by,
                                         "rule_score": v.rule_score, "red_flags": v.red_flags,
                                         "p_cerebras": v.p_cerebras, "p_decisions": v.p_decisions,
                                         "decisions_available": v.decisions_available}, case_id, channel)

        closing = turn >= CLOSE_AT or (turn >= GOODBYE_AFTER and bool(GOODBYE_RE.search(text)))
        mode = "wrap_up" if closing else ("neutral" if verdict == "not_scam" else "bait")
        findings = await store.unused_findings(case_id) if mode == "bait" else []
        have = {i["kind"] for i in await store.list_intel(case_id)}
        ctx = meena.Context(history=history, mode=mode, facts=await facts_for(case_id, history), findings=findings,
                            missing=[k for k in meena.WANTED if k not in have], language=meena.language_of(text))

        degraded, summary = False, ""
        try:
            out = await rt.brain.reply(ctx)
            raw, summary = out["reply"], out.get("summary", "")
        except Exception as exc:
            log.warning("Meena's model failed on %s: %s", case_id, type(exc).__name__)
            raw, degraded = scripted_line(ctx), True
        reply, flags = meena.guard(raw)
        if findings and not degraded and not any(meena.mentions_finding(reply, f) for f in findings):
            # The model left out what Kane proved. Ask once more, insisting; keep the first draft if that fails too.
            log.info("Meena's reply on %s left out the Kane finding; asking again", case_id)
            try:
                out = await rt.brain.reply(dataclasses.replace(ctx, insist=True))
                again, again_flags = meena.guard(out["reply"])
                if any(meena.mentions_finding(again, f) for f in findings):
                    reply, flags, summary = again, again_flags, out.get("summary", "") or summary
            except Exception as exc:
                log.warning("Meena's second try failed on %s: %s", case_id, type(exc).__name__)
        if flags:
            log.info("reply guard on %s: %s", case_id, flags)

        pmid = await store.add_message(case_id, "persona", reply)
        used = 0
        if findings and not degraded:
            from app.models import utc_now
            for f in findings:
                if meena.mentions_finding(reply, f):   # only what the reply really used; the rest waits a turn
                    await store.update_investigation(f["id"], used_at=utc_now())
                    used += 1
        await emit("persona.reply", {"text": reply, "message_id": pmid, "turn": turn, "mode": mode,
                                     "degraded": degraded, "kane_findings_used": used}, case_id, channel)

        updates = {}
        if summary:
            updates["summary"] = summary
        if closing:
            updates["status"] = "closed"
        if updates:
            await store.update_case(case_id, **updates)
            case = await store.get_case(case_id)
            await emit("case.updated", {k: case[k] for k in ("status", "verdict", "scam_type", "summary")},
                       case_id, channel)
            if closing:
                _spawn(_report(case_id))

    return Reply(case_id=case_id, text=reply, verdict=verdict if verdict in ("scam", "not_scam") else "unknown",
                 scam_type=scam_type, turn=turn, closed=closing, degraded=degraded)


async def end_case(case_id: Optional[str]) -> None:
    """Close a case from outside a conversation (for example the dashboard)."""
    if case_id:
        await get_runtime().store.update_case(case_id, status="closed")
        await emit("case.updated", {"status": "closed"}, case_id)
        _spawn(_report(case_id))


async def _report(case_id: str) -> None:
    from app.report import write_report
    await write_report(case_id)
