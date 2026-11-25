"""Investigation API.

GET  /api/investigations                 recent investigations (newest first), or ?case_id= for one case
GET  /api/investigations/{id}            one investigation
GET  /api/investigations/{id}/screenshots            step numbers that have a screenshot in the evidence pack
GET  /api/investigations/{id}/screenshots/{step|last} one step screenshot from Kane's evidence pack
POST /api/investigations {"url", "case_id"?}   ask Kane to investigate a link; returns the queued row.
     Needs x-api-key when API_KEY is set. Real (non-lab) links run only with LIVE_INVESTIGATION=1.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.runtime import get_runtime

router = APIRouter()


class InvestigateRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    case_id: Optional[str] = Field(default=None, max_length=64)


def _public(row: dict) -> dict:
    """Never expose local filesystem paths; say whether evidence exists and give its hash."""
    out = {k: v for k, v in row.items() if k not in ("evidence_path",)}
    out["evidence"] = bool(row.get("evidence_path"))
    out["replayed"] = bool((row.get("final_state") or {}).get("_replayed"))
    out["unsafe_actions"] = (row.get("final_state") or {}).get("_unsafe_actions") or []
    return out


@router.get("/api/investigations")
async def list_investigations(case_id: Optional[str] = None, limit: int = 50) -> dict:
    rows = await get_runtime().store.list_investigations(case_id, limit=max(1, min(limit, 200)))
    return {"investigations": [_public(r) for r in rows]}


@router.get("/api/investigations/{inv_id}")
async def get_investigation(inv_id: int) -> dict:
    row = await get_runtime().store.get_investigation(inv_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such investigation.")
    return _public(row)


async def _pack(inv_id: int) -> str:
    row = await get_runtime().store.get_investigation(inv_id)
    if row is None or not row.get("evidence_path"):
        raise HTTPException(status_code=404, detail="No evidence pack for this investigation.")
    return row["evidence_path"]


@router.get("/api/investigations/{inv_id}/screenshots")
async def list_screenshots(inv_id: int) -> dict:
    from app.investigate.evidence import screenshot_steps
    return {"steps": [n for n, _ in screenshot_steps(await _pack(inv_id))]}


@router.get("/api/investigations/{inv_id}/screenshots/{step}")
async def get_screenshot(inv_id: int, step: str) -> Response:
    from app.investigate.evidence import read_screenshot
    if step != "last" and not step.isdigit():
        raise HTTPException(status_code=404, detail="No such step.")
    shot = read_screenshot(await _pack(inv_id), None if step == "last" else int(step))
    if shot is None:
        raise HTTPException(status_code=404, detail="No screenshot for this step.")
    data, media = shot
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/api/investigations", dependencies=[Depends(require_api_key)])
async def create_investigation(body: InvestigateRequest) -> dict:
    from app.investigate import start_investigation
    store = get_runtime().store
    if body.case_id and await store.get_case(body.case_id) is None:
        raise HTTPException(status_code=404, detail="No such case.")
    row = await start_investigation(body.url.strip(), body.case_id, "api")
    return _public(row)
