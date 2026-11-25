"""A Kane run that never ends is stopped on time, with everything it started.

Found in a real Kane test run on 24 Nov 2026: with --timeout 300, the run went on for 14 minutes, because killing
kane-cli left its runner and browser driver holding the output pipe and run_kane waited on that pipe."""
import os
import sys
import time
from pathlib import Path

from app.investigate.kane import run_kane

HANG = Path(__file__).parent / "fixtures" / "hang_kane.py"


async def test_a_hung_run_is_killed_with_its_children(tmp_path, monkeypatch):
    pidfile = tmp_path / "child.pid"
    monkeypatch.setenv("HANG_KANE_PIDFILE", str(pidfile))
    started = time.monotonic()
    res = await run_kane("x", "http://127.0.0.1/lab/kyc", cmd=f"{sys.executable} {HANG}", timeout_s=1, grace_s=1,
                         workdir=str(tmp_path / "w"))
    took = time.monotonic() - started
    assert res.status == "timeout"
    assert took < 15, took
    child = int(pidfile.read_text())
    time.sleep(0.3)
    try:
        os.kill(child, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "Kane's child process survived the timeout"
