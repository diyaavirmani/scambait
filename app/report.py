"""The case report for Indian cyber-crime authorities (1930 / NCRP).

write_report(case_id) gathers the case facts, the transcript, the identifiers taken from the chat and the payees Kane
proved on payment pages, and asks the brain for a report (rt.brain.report). Only when Cerebras is down (an outage, not
a rate limit) and an OpenAI key is set does the OpenAI Responses API write it instead. The answer is checked (only
validated identifiers survive), saved to DATA_DIR/reports/<case id>/report.json, recorded as case evidence with its
SHA-256, its summary becomes the case summary, and then "case.updated" announces it. One run at a time per case.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from app.brain import ID_KINDS, REPORT_PROMPT, REPORT_RISKS, REPORT_SCHEMA, SCAM_TYPES, BrainError, report_input
from app.bus import emit
from app.cases import CASE_ID_RE
from app.intel import normalise
from app.models import utc_now
from app.runtime import get_runtime

log = logging.getLogger("scambait.report")

MAX_MESSAGES = 80         # the newest messages go to the model
MAX_MESSAGE_TEXT = 1500   # characters per message
MAX_POINTS = 8
EM_DASH = re.compile(r"\s*" + chr(0x2014) + r"\s*")

_running: set[str] = set()


def build_payload(case: dict, messages: list[dict], intel: list[dict], investigations: list[dict]) -> dict:
    """What the report is written from. validated_identifiers is the only list a report may name suspects from."""
    validated: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    for item in intel:
        key = (item["kind"], item.get("norm") or normalise(item["kind"], item["value"]))
        if item["kind"] in ID_KINDS and key not in index:
            index[key] = len(validated)
            validated.append({"kind": item["kind"], "value": item["value"], "source": "said in chat"})
    payees = []
    for inv in investigations:
        if inv.get("verdict") != "payment_request_found":
            continue
        payees.append({"page": inv.get("url", ""), "claims_to_be": inv.get("claims_to_be", ""),
                       "payee": inv.get("payee", ""), "payee_kind": inv.get("payee_kind", ""),
                       "amount": inv.get("amount", ""), "asked_for": list(inv.get("asked_for") or [])})
        kind, value = inv.get("payee_kind"), inv.get("payee")
        if kind in ID_KINDS and value:
            key = (kind, normalise(kind, value))
            if key in index:
                validated[index[key]]["source"] = "said in chat and proven by Kane"
            else:
                index[key] = len(validated)
                validated.append({"kind": kind, "value": value, "source": "proven by Kane"})
    transcript = [{"role": "suspect" if m["role"] == "scammer" else "decoy", "text": m["text"][:MAX_MESSAGE_TEXT],
                   "ts": m["ts"]} for m in messages[-MAX_MESSAGES:]]
    facts = {"id": case["id"], "channel": case["channel"], "status": case["status"], "verdict": case["verdict"],
             "scam_type": case["scam_type"], "summary": case["summary"], "opened_at": case["created_at"],
             "messages_from_suspect": sum(1 for m in messages if m["role"] == "scammer")}
    return {"case": facts, "transcript": transcript, "validated_identifiers": validated, "proven_payees": payees}


def _text(value: Any, limit: int) -> str:
    text = EM_DASH.sub(", ", value) if isinstance(value, str) else ""
    return " ".join(text.split())[:limit]


def clean(report: dict, payload: dict) -> dict:
    """The REPORT_SCHEMA fields only, with identifiers that are not in validated_identifiers dropped."""
    allowed = {(i["kind"], normalise(i["kind"], i["value"])): i["value"] for i in payload["validated_identifiers"]}
    ids, seen, dropped = [], set(), 0
    for item in report.get("suspect_identifiers") if isinstance(report.get("suspect_identifiers"), list) else []:
        kind = str(item.get("kind", "")).strip().lower() if isinstance(item, dict) else ""
        key = (kind, normalise(kind, str(item.get("value", "")))) if kind else ("", "")
        if key[1] and key in allowed:
            if key not in seen:
                seen.add(key)
                ids.append({"kind": kind, "value": allowed[key]})
        else:
            dropped += 1
    if dropped:
        log.info("report for %s: dropped %d identifiers that were not validated", payload["case"]["id"], dropped)
    case_type = payload["case"].get("scam_type")
    scam_type = report.get("scam_type") if report.get("scam_type") in SCAM_TYPES else (
        case_type if case_type in SCAM_TYPES else "other")
    risk = str(report.get("risk", "")).strip().lower()
    points = report.get("key_points") if isinstance(report.get("key_points"), list) else []
    return {
        "summary": _text(report.get("summary"), 600),
        "scam_type": scam_type,
        "modus_operandi": _text(report.get("modus_operandi"), 1500),
        "key_points": [p for p in (_text(p, 300) for p in points) if p][:MAX_POINTS],
        "suspect_identifiers": ids,
        "risk": risk if risk in REPORT_RISKS else "high",
        "recommended_action": _text(report.get("recommended_action"), 600),
    }


async def _ask(rt, payload: dict) -> tuple[Optional[dict], str]:
    """(raw report, who wrote it), or (None, "") when no report can be written now."""
    case_id = payload["case"]["id"]
    try:
        return await rt.brain.report(payload), getattr(rt.brain, "mode", "brain")
    except BrainError as exc:
        if exc.kind != "outage" or rt.openai is None:
            log.warning("report for %s not written: %s", case_id, exc.kind)
            return None, ""
        log.warning("Cerebras is down (%s); writing the report for %s with OpenAI", exc, case_id)
    try:
        out = await rt.openai.responses_json(REPORT_PROMPT, report_input(payload), REPORT_SCHEMA, "case_report",
                                             step="report", case_id=case_id)
    except Exception as exc:
        log.warning("OpenAI report for %s failed: %s %s", case_id, type(exc).__name__, getattr(exc, "kind", ""))
        return None, ""
    return out, "openai"


def load_report(data_dir: str, case_id: str) -> Optional[dict]:
    """The saved report for a case, or None when none has been written (or the file is unreadable)."""
    if not CASE_ID_RE.match(case_id or ""):
        return None
    try:
        data = json.loads((Path(data_dir) / "reports" / case_id / "report.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _save(data_dir: str, case_id: str, body: bytes) -> Path:
    folder = Path(data_dir) / "reports" / case_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "report.json"
    partial = folder / "report.json.partial"
    partial.write_bytes(body)
    os.replace(partial, path)  # readers never see half a file
    return path


async def _write(case_id: str) -> dict:
    rt = get_runtime()
    store = rt.store
    case = await store.get_case(case_id)
    if case is None:
        return {}
    payload = build_payload(case, await store.list_messages(case_id), await store.list_intel(case_id),
                            await store.list_investigations(case_id))
    raw, source = await _ask(rt, payload)
    if not isinstance(raw, dict):
        return {}
    report = {**clean(raw, payload), "case_id": case_id, "generated_by": source, "generated_at": utc_now()}
    body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    path = _save(rt.settings.data_dir, case_id, body)
    await store.add_evidence(case_id, "report", str(path), hashlib.sha256(body).hexdigest())
    if report["summary"]:
        await store.update_case(case_id, summary=report["summary"])
    summary = report["summary"] or case["summary"]
    await emit("case.updated", {"summary": summary, "report": report}, case_id, case["channel"])
    return report


async def write_report(case_id: str) -> dict:
    """Write, save, record and announce the report. {} when it could not be written, or one is already being written."""
    if not CASE_ID_RE.match(case_id or "") or case_id in _running:
        return {}
    _running.add(case_id)
    try:
        return await _write(case_id)
    except Exception:
        log.exception("report for %s failed", case_id)
        return {}
    finally:
        _running.discard(case_id)
