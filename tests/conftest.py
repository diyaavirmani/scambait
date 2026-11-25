"""Shared fixtures: a real Store on a temp file, a Bus, a Runtime with a scripted brain."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import Settings  # noqa: E402
from app.runtime import Runtime, set_runtime  # noqa: E402

FAKE_KANE = ROOT / "tests" / "fixtures" / "fake_kane.py"


@pytest.fixture
async def store(tmp_path):
    from app.store import Store
    s = Store(str(tmp_path / "test.db"))
    await s.init()
    yield s
    await s.close()


@pytest.fixture
def settings(tmp_path):
    return Settings(offline_mode=True, db_path=str(tmp_path / "test.db"), data_dir=str(tmp_path / "out"),
                    kane_cmd=f"{sys.executable} {FAKE_KANE}", kane_workdir=str(tmp_path / "kane"),
                    telegram_auto_webhook=False, api_key="")


@pytest.fixture
async def runtime(store, settings):
    from app.brain import ScriptedBrain
    from app.bus import Bus
    rt = Runtime(settings=settings, store=store, bus=Bus(store), brain=ScriptedBrain())
    set_runtime(rt)
    yield rt
    from app.investigate import drain
    await drain()
