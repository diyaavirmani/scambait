"""Case API for the dashboard.

GET  /api/cases               newest first, with the scammer message count
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
    store = get_runtime().store
    case = await load_case(case_id)
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


@router.get("/api/cases/{case_id}")
async def get_case(case_id: str) -> dict:
    return await case_detail(case_id)
