"""Kane gate: the test files parse, changes select the right tests, and the Stop hook blocks the agent on a real
failure (exit 2, Kane's reason on stderr), never more than MAX_BLOCKS times in a row, and never for problems
the agent cannot fix. Kane is replaced by a stub runner; the app by a stubbed health check."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import kane_gate as gate  # noqa: E402

from app.investigate.kane import KaneResult  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_every_test_file_parses_and_says_what_it_verifies():
    tests = gate.load_tests()
    ids = [t.id for t in tests]
    assert len(ids) == len(set(ids)) >= 6
    for t in tests:
        assert t.covers, t.id
        assert "Verify" in t.objective, t.id
        assert t.path.startswith("/")


def test_changes_select_only_affected_tests():
    tests = gate.load_tests()
    persona = {t.id for t in gate.select(tests, ["app/meena.py"])}
    assert {"K05", "K06", "K07", "K08"} <= persona and "K01" not in persona
    assert {t.id for t in gate.select(tests, ["kane/tests/K09-evidence-board.md"])} == {"K09"}
    assert gate.select(tests, ["README.md"]) == []


def result(status, reason="", steps=None):
    return KaneResult(status=status, exit_code={"passed": 0, "failed": 1}.get(status, 2), reason=reason,
                      summary="s", steps=steps or [], credits=2, duration_s=10, evidence_path="/tmp/pack.zip")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "STATE_DIR", tmp_path / ".kane")
    monkeypatch.setattr(gate, "healthy", lambda base: True)
    monkeypatch.setattr(gate, "reset_lab", lambda base: None)
    return tmp_path


def run_hook(capsys, outcomes):
    calls = iter(outcomes)

    async def runner(test, base):
        return next(calls)
    code = gate.main(["--hook", "--ids", "K06", "--base", "http://x", "--repeat", "1"], runner=runner,
                     stdin=io.StringIO(json.dumps({"stop_hook_active": False})))
    return code, capsys.readouterr()


def test_hook_blocks_with_kanes_reason_then_gives_up_after_three(env, capsys):
    fail = result("failed", "Meena said she is an AI assistant.",
                  [{"step": 4, "status": "failed", "remark": "Reply admits being an AI"}])
    for attempt in range(1, gate.MAX_BLOCKS + 1):
        code, out = run_hook(capsys, [fail])
        assert code == 2, attempt
        assert "Meena said she is an AI assistant." in out.err
        assert "Reply admits being an AI" in out.err and "Do not weaken or delete the Kane tests" in out.err
    code, out = run_hook(capsys, [fail])
    assert code == 0 and "letting the agent stop" in out.out
    code, _ = run_hook(capsys, [fail])
    assert code == 2  # counter was reset


def test_hook_passes_and_resets_the_counter(env, capsys):
    run_hook(capsys, [result("failed", "x")])
    code, out = run_hook(capsys, [result("passed")])
    assert code == 0 and "PASS K06" in out.out
    assert json.loads((env / ".kane" / "state.json").read_text())["blocks"] == 0


def test_hook_never_blocks_when_kane_cannot_run(env, capsys):
    code, out = run_hook(capsys, [result("not_started", 'Not authenticated [prod]. Run "kane-cli login" first.')])
    assert code == 0 and "Not authenticated" in out.err and "SKIP K06" in out.out


async def test_repeat_reports_a_pass_rate(env):
    tests = [t for t in gate.load_tests() if t.id == "K06"]
    outcomes = iter([result("passed"), result("failed", "slipped"), result("passed")])

    async def runner(test, base):
        return next(outcomes)
    res = await gate.run_suite(tests, "http://x", runner, repeat=3)
    assert res[0]["passed"] == 2 and res[0]["runs"] == 3 and res[0]["status"] == "failed"
    assert "(2/3)" in gate.report(res)


def test_kanes_browser_closing_does_not_blame_the_agent(env, capsys):
    """Kane's exact reason from 25 Nov 2026, 08:30 IST, when the Mac slept during a K06 run."""
    gone = result("failed", "Screenshot failed: TargetClosedError: screenshot: Target page, context or browser "
                            "has been closed")
    code, out = run_hook(capsys, [gone])
    assert code == 0 and "SKIP K06" in out.out  # the coding agent is not told to fix code


async def test_a_closed_browser_still_refuses_the_deploy(env):
    import ship
    tests = [t for t in gate.load_tests() if t.id == "K06"]

    async def runner(test, base):
        return result("failed", "TargetClosedError: browser has been closed")
    res = await gate.run_suite(tests, "http://x", runner, repeat=1)
    assert res[0]["status"] == "infra"
    code = ship.main(["--dry-run"], checks={"clean": lambda: True, "unit": lambda: True,
                                            "kane": lambda: (False, res), "deploy": lambda: "x"})
    assert code == 1  # only a clean pass ships


def test_replay_prints_a_recording_or_refuses(tmp_path):
    script = ROOT / "scripts" / "kane_replay.py"
    missing = subprocess.run([sys.executable, str(script), "run", "x", "--url", "http://h/lab/kyc"],
                             capture_output=True, text=True, env={"KANE_RECORDINGS": str(tmp_path)})
    assert missing.returncode == 2 and "No recorded Kane run" in missing.stderr
    (tmp_path / "kyc.ndjson").write_text('{"type": "run_end", "status": "passed", "final_state": {}}\n')
    ok = subprocess.run([sys.executable, str(script), "run", "x", "--url", "http://h/lab/kyc/0"],
                        capture_output=True, text=True, env={"KANE_RECORDINGS": str(tmp_path)})
    assert ok.returncode == 0 and '"run_end"' in ok.stdout


def test_stop_hook_is_configured():
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text())
    cmd = cfg["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "kane_gate.py --hook" in cmd
