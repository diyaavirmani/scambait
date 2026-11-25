"""Serves the dashboard (the React build in app/web/dist) on the same origin as the API.

The app's pages return index.html; /assets/<name> serves the hashed JS and CSS, and nothing outside dist/assets can
be read. Build with: cd dashboard && npm ci && npm run build.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

router = APIRouter()
DIST = Path(__file__).parent / "web" / "dist"
PAGES = ("/", "/check", "/console", "/cases", "/overview")
ASSET_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}\.(js|css|svg)$")
MEDIA = {"js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}


async def index() -> Response:
    page = DIST / "index.html"
    if not page.is_file():
        return PlainTextResponse("Dashboard not built. Run: cd dashboard && npm ci && npm run build", status_code=503)
    return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})


for _path in PAGES:
    router.add_api_route(_path, index, methods=["GET"], include_in_schema=False, name="page_" + (_path.strip("/") or "home"))


@router.get("/assets/{name}", include_in_schema=False)
async def asset(name: str) -> Response:
    path = DIST / "assets" / name
    if not ASSET_RE.match(name) or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=MEDIA[name.rsplit(".", 1)[1]],
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
