"""The deploy gate refuses to ship unless the tree is clean, unit tests pass and every Kane test passes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ship  # noqa: E402

GREEN = [{"id": "K01", "status": "passed", "passed": 1, "runs": 1}, {"id": "K06", "status": "passed", "passed": 3, "runs": 3}]


def run(**over):
    calls = []
    checks = {"clean": lambda: True, "unit": lambda: True, "kane": lambda: (True, GREEN),
              "deploy": lambda: calls.append("deploy") or "deployed"}
    checks.update(over)
    return ship.main(["--dry-run"], checks=checks), calls


def test_refuses_dirty_tree_failed_units_and_failed_or_missing_kane(capsys):
    assert run(clean=lambda: False)[0] == 1
    assert run(unit=lambda: False)[0] == 1
    red = [{"id": "K05", "status": "failed", "passed": 0, "runs": 1}]
    code, calls = run(kane=lambda: (False, red))
    assert code == 1 and "K05 (failed)" in capsys.readouterr().out and calls == []
    assert run(kane=lambda: (False, []))[0] == 1


def test_green_run_signs_off_and_dry_run_changes_nothing(capsys):
    code, calls = run()
    out = capsys.readouterr().out
    assert code == 0 and "Kane signed off: 2/2 passed" in out and "Dry run" in out and calls == []


def test_badge_is_a_shields_endpoint():
    b = ship.badge(GREEN)
    assert b["schemaVersion"] == 1 and b["label"] == "Kane CLI" and b["message"] == "2/2 passed"
    assert b["color"] == "brightgreen" and b["tests"]["K06"] == "3/3"
    assert ship.badge(GREEN + [{"id": "K09", "status": "failed", "passed": 0, "runs": 1}])["color"] == "red"
