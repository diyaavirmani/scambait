"""Telegram channel: scammers who message the bot get Meena.

POST /telegram/webhook receives updates. The X-Telegram-Bot-Api-Secret-Token header must match
TELEGRAM_WEBHOOK_SECRET; each update_id is handled once; the webhook answers at once and the turn runs in the
background (typing indicator, then Meena's reply), so Telegram never retries a slow update. On startup the webhook is
pointed at PUBLIC_BASE_URL/telegram/webhook, unless TELEGRAM_AUTO_WEBHOOK=0 (set that on any local copy, or it takes
the bot away from the live server). The bot token is never logged.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from app import engine
from app.models import MAX_TEXT

log = logging.getLogger("scambait.telegram")
router = APIRouter()
_http: Optional[httpx.AsyncClient] = None
_tasks: set[asyncio.Task] = set()


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(base_url="https://api.telegram.org", timeout=20)
    return _http


async def close() -> None:
    global _http
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
    if _http is not None:
        await _http.aclose()
        _http = None


async def call(token: str, method: str, payload: dict) -> Optional[dict]:
    try:
        r = await _client().post(f"/bot{token}/{method}", json=payload)
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("telegram %s failed: %s", method, type(exc).__name__)
        return None


async def register_webhook(settings) -> None:
    if not (settings.telegram_auto_webhook and settings.telegram_bot_token and settings.telegram_webhook_secret
            and settings.public_base_url):
        return
    body = await call(settings.telegram_bot_token, "setWebhook",
                      {"url": settings.public_base_url + "/telegram/webhook", "allowed_updates": ["message"],
                       "secret_token": settings.telegram_webhook_secret, "drop_pending_updates": False})
    log.info("telegram webhook registered: %s", bool(body and body.get("ok")))


async def _turn(token: str, chat_id: int, text: str) -> None:
    from app.runtime import get_runtime
    store = get_runtime().store
    await call(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    case = await store.open_case("telegram", f"tg:{chat_id}")
    reply = await engine.handle_message(case["id"], "telegram", text)
    if reply.text:
        await call(token, "sendMessage", {"chat_id": chat_id, "text": reply.text})


@router.post("/telegram/webhook")
async def webhook(request: Request,
                  secret: Optional[str] = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token")) -> dict:
    from app.runtime import get_runtime
    rt = get_runtime()
    s = rt.settings
    if not s.telegram_bot_token or not s.telegram_webhook_secret:
        raise HTTPException(status_code=404, detail="Telegram is not set up.")
    if not secret or not hmac.compare_digest(secret.encode(), s.telegram_webhook_secret.encode()):
        raise HTTPException(status_code=403, detail="Bad secret token.")
    update = await request.json()
    msg = update.get("message") or {}
    text, chat = msg.get("text"), (msg.get("chat") or {}).get("id")
    if not isinstance(text, str) or not text.strip() or chat is None or (msg.get("from") or {}).get("is_bot"):
        return {"ok": True}
    if not await rt.store.mark_seen(f"tg-update:{update.get('update_id')}"):
        return {"ok": True}  # Telegram retried an update we already have
    task = asyncio.create_task(_turn(s.telegram_bot_token, int(chat), text.strip()[:MAX_TEXT]))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"ok": True}
