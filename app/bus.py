"""Event bus and the live stream to the dashboard.

emit() stores the event first (so it gets an id and can be replayed), then hands it to every open stream without
waiting. A stream that falls behind is dropped; the browser reconnects with Last-Event-ID and replays the gap from
the database. GET /api/events is the server-sent events stream; every event is sent with its type as the SSE event
name, so the dashboard has to listen for each type in app.models.EVENT_TYPES.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.models import Event

log = logging.getLogger("scambait.bus")
QUEUE_SIZE = 1000
KEEPALIVE_S = 15

router = APIRouter()


class Bus:
    def __init__(self, store) -> None:
        self.store = store
        self._queues: set[asyncio.Queue] = set()
        self.dropped: set[asyncio.Queue] = set()  # streams that fell behind; they close so the browser replays

    async def emit(self, event: Event) -> Event:
        if self.store is not None:
            try:
                event.id = await self.store.add_event(event)
            except Exception:
                log.exception("could not store event %s", event.type)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._queues.discard(q)
                self.dropped.add(q)
        return event

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)
        self.dropped.discard(q)


async def emit(type_: str, data: dict, case_id: Optional[str] = None, channel: str = "web") -> None:
    """Emit through the runtime bus; never raises into the caller."""
    try:
        from app.runtime import get_runtime
        await get_runtime().bus.emit(Event(type=type_, data=data, case_id=case_id, channel=channel))
    except Exception:
        log.exception("emit %s failed", type_)


def sse(event: Event) -> str:
    return f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"


async def stream(request: Request, last_id: int) -> AsyncIterator[str]:
    from app.runtime import get_runtime
    rt = get_runtime()
    q = rt.bus.subscribe()  # subscribe first, then replay, so nothing falls in between
    try:
        sent = last_id
        for ev in await rt.store.events_after(last_id, limit=1000):
            yield sse(ev)
            sent = ev.id
        while True:
            if await request.is_disconnected() or q in rt.bus.dropped:
                return
            try:
                ev = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_S)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if ev.id is not None and ev.id <= sent:
                continue
            yield sse(ev)
            sent = ev.id or sent
    finally:
        rt.bus.unsubscribe(q)


@router.get("/api/events")
async def events(request: Request, last_id: int = 0) -> StreamingResponse:
    header = request.headers.get("last-event-id", "")
    start = int(header) if header.isdigit() else max(0, last_id)
    return StreamingResponse(stream(request, start), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
