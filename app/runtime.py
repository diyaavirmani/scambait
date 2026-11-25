"""Process-wide dependencies. One server process, one Runtime; tests install their own with set_runtime()."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import Settings


@dataclass
class Runtime:
    settings: Settings
    store: Any          # app.store.Store
    bus: Any            # app.bus.Bus
    brain: Any = None   # app.brain.CerebrasBrain or app.brain.ScriptedBrain
    openai: Any = None  # app.openai_client.OpenAIClient, or None when OPENAI_API_KEY is not set
    health: Optional[dict] = None   # the brain self-test result, shown on /health


_runtime: Optional[Runtime] = None


def set_runtime(rt: Runtime) -> None:
    global _runtime
    _runtime = rt


def get_runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("Runtime not set: start the app with create_app(), or call set_runtime() in a test")
    return _runtime
