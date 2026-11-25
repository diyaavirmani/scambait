"""FastAPI entry point. Run one process: uvicorn app.main:app --workers 1 (per-case locks live in memory)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.runtime import Runtime, get_runtime, set_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("scambait")


async def start(settings: Settings) -> Runtime:
    from app.brain import CerebrasBrain, ScriptedBrain
    from app.bus import Bus
    from app.store import Store
    missing = settings.missing()
    if missing:
        raise RuntimeError(f"Missing settings: {', '.join(missing)} (see .env.example, or set OFFLINE_MODE=1)")
    store = Store(settings.db_path)
    await store.init()
    brain = ScriptedBrain() if settings.offline_mode else CerebrasBrain(settings)
    openai = None
    if settings.openai_api_key and not settings.offline_mode:
        from app.openai_client import OpenAIClient
        openai = OpenAIClient(settings)
    rt = Runtime(settings=settings, store=store, bus=Bus(store), brain=brain, openai=openai)
    set_runtime(rt)
    try:
        rt.health = await brain.self_test()
    except Exception as exc:
        rt.health = {"ok": False, "mode": brain.mode, "error": str(exc)}
        log.error("model self-test failed: %s", exc)
    if settings.offline_mode:
        log.warning("OFFLINE_MODE=1: rules-only detection and scripted Meena; Kane CLI still runs for real")
    from app import telegram
    await telegram.register_webhook(settings)
    return rt


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rt = await start(settings)
        yield
        from app import engine, telegram
        from app.investigate import drain
        await engine.settle()
        from app.voice import webhooks
        if webhooks._running:
            import asyncio
            await asyncio.gather(*list(webhooks._running), return_exceptions=True)
        await drain()
        await telegram.close()
        await rt.brain.close()
        if rt.openai is not None:
            await rt.openai.close()
        await rt.store.close()

    app = FastAPI(title="SCAM-BAIT", lifespan=lifespan)
    from app import bus, cases, check, console, evidence_pack, honeypot, networks, telegram, web
    from app.investigate import api as investigations
    from app.lab import router as lab
    from app.voice import router as voice
    for router in (bus.router, cases.router, check.router, console.router, evidence_pack.router, honeypot.router,
                   networks.router, telegram.router, voice, investigations.router, lab, web.router):
        app.include_router(router)

    @app.get("/health")
    async def health():
        rt = get_runtime()
        db = await rt.store.ping()
        brain = getattr(rt, "health", {"ok": False})
        ok = db and brain.get("ok", False)
        openai = rt.openai.status() if rt.openai is not None else {
            "configured": False, "decisions_available": False,
            "reason": "offline mode" if rt.settings.offline_mode else "OPENAI_API_KEY is not set"}
        return JSONResponse({"status": "ok" if ok else "degraded", "database": db, "brain": brain, "openai": openai},
                            status_code=200 if ok else 503)

    return app


app = create_app()
