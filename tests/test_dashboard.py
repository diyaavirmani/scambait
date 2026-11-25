"""The dashboard: it listens for every event the server sends, its pages and assets are served, nothing else is."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import EVENT_TYPES
from app.web import DIST

ROOT = Path(__file__).resolve().parent.parent
LIVE_TS = ROOT / "dashboard" / "src" / "lib" / "live.ts"


def test_dashboard_listens_for_every_event_type():
    block = re.search(r"EVENT_TYPES = \[(.*?)\];", LIVE_TS.read_text(), re.S).group(1)
    assert set(EVENT_TYPES) - set(re.findall(r"'([a-z_.]+)'", block)) == set()


@pytest.fixture
def client(settings):
    from app.main import create_app
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="dashboard not built")
def test_pages_and_assets(client):
    for page in ("/", "/check", "/console", "/chats", "/calls", "/cases", "/intel", "/networks", "/overview", "/system"):
        r = client.get(page)
        assert r.status_code == 200 and '<div id="root">' in r.text
    asset = re.search(r'/assets/([^"]+\.js)', client.get("/").text).group(1)
    assert client.get(f"/assets/{asset}").status_code == 200
    assert client.get("/assets/..%2F..%2Fmain.py").status_code == 404
    assert client.get("/nope").status_code == 404
