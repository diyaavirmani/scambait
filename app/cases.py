"""Case API for the dashboard.

GET  /api/cases               newest first, with the scammer message count
GET  /api/intel               every identifier across cases, newest first, each marked if Kane proved it, plus the
                              payees Kane proved on a case's scam page that nobody said in its chat (for example a
                              payee that changed on a fresh-visit re-check); those have a negative id and no message
GET  /api/cases/{id}          the case, its messages, identifiers (each marked if Kane proved it), events, evidence,
                              Kane investigations, and other cases that share an identifier with it
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.intel import normalise
from app.runtime import get_runtime

router = APIRouter()
CASE_ID_RE = re.compile(r"^c_[0-9a-f]{12}$")


async def load_case(case_id: str) -> dict:
    case = await get_runtime().store.get_case(case_id) if CASE_ID_RE.match(case_id or "") else None
    if case is None:
        raise HTTPException(status_code=404, detail="No such case.")
    return case


def proven_keys(investigations: list[dict]) -> set[tuple[str, str]]:
    return {(i["payee_kind"], normalise(i["payee_kind"], i["payee"])) for i in investigations
            if i.get("verdict") == "payment_request_found" and i.get("payee") and i.get("payee_kind")}


async def case_detail(case_id: str) -> dict:
    from app.investigate.api import _public
    from app.report import load_report
    rt = get_runtime()
    store = rt.store
    case = {**await load_case(case_id), "report": load_report(rt.settings.data_dir, case_id)}
    investigations = await store.list_investigations(case_id)
    proven = proven_keys(investigations)
    intel = [{**i, "proven": (i["kind"], i["norm"]) in proven} for i in await store.list_intel(case_id)]
    related = await store.cases_sharing(case_id)
    return {
        "case": case,
        "messages": await store.list_messages(case_id),
        "intel": intel,
        "events": [e.model_dump() for e in await store.events_for_case(case_id)],
        "evidence": [{k: e[k] for k in ("kind", "sha256", "created_at")} for e in await store.list_evidence(case_id)],
        "investigations": [_public(i) for i in investigations],
        "related": [{"case_id": r["case_id"], "kind": r["kind"]} for r in related],
    }


@router.get("/api/cases")
async def list_cases(limit: int = 100) -> dict:
    return {"cases": await get_runtime().store.list_cases(max(1, min(limit, 500)))}


@router.get("/api/intel")
async def all_intel(limit: int = 500) -> dict:
    store = get_runtime().store
    rows = await store._all(
        "SELECT i.*, c.scam_type, c.channel FROM intel i JOIN cases c ON c.id = i.case_id ORDER BY i.id DESC LIMIT ?",
        (max(1, min(limit, 2000)),))
    proven = proven_keys(await store.list_investigations(None, limit=1000))
    out = [{**r, "proven": (r["kind"], r["norm"]) in proven} for r in rows]
    said = {(r["case_id"], r["kind"], r["norm"]) for r in await store._all("SELECT case_id, kind, norm FROM intel")}
    kane = await store._all(
        "SELECT v.id, v.case_id, v.payee, v.payee_kind, COALESCE(v.finished_at, v.created_at) AS first_seen, "
        "c.scam_type, c.channel FROM investigations v JOIN cases c ON c.id = v.case_id "
        "WHERE v.verdict = 'payment_request_found' AND v.payee != '' AND v.payee_kind != '' ORDER BY v.id")
    for v in kane:
        key = (v["case_id"], v["payee_kind"], normalise(v["payee_kind"], v["payee"]))
        if key in said:
            continue
        said.add(key)  # once per case, however many runs showed it
        out.append({"id": -v["id"], "case_id": v["case_id"], "kind": v["payee_kind"], "value": v["payee"],
                    "norm": key[2], "message_id": None, "first_seen": v["first_seen"], "scam_type": v["scam_type"],
                    "channel": v["channel"], "proven": True})
    out.sort(key=lambda r: r["first_seen"] or "", reverse=True)
    return {"intel": out[:max(1, min(limit, 2000))]}


@router.get("/api/cases/{case_id}")
async def get_case(case_id: str) -> dict:
    return await case_detail(case_id)
