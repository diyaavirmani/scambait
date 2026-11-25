"""API key check for the few routes that start work on request (POST /api/investigations)."""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException

from app.runtime import get_runtime


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="x-api-key")) -> None:
    expected = get_runtime().settings.api_key
    if not expected:
        return  # no API_KEY set: the route is open (local runs and the judged demo)
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")
