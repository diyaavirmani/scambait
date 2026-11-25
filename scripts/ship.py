"""Ship only when Kane signs off: unit tests, then every Kane test in a real browser, then deploy.

    .venv/bin/python scripts/ship.py                 # test, write the Kane badge, commit it, push, deploy
    .venv/bin/python scripts/ship.py --dry-run       # run the checks, change nothing

Steps, stopping at the first failure:
1. The working tree must be clean (what ships is what was tested).
2. `pytest -q` must pass.
3. `scripts/kane_gate.py --all` must pass: every Kane test against the dashboard. Kane being unable to run
   (not logged in, no credits) also refuses the deploy here; a deploy without Kane's sign-off is not allowed.
4. kane/badge.json is rewritten from that run (a shields.io endpoint badge: "Kane CLI | 6/6 passed") and committed.
5. git push, then POST RENDER_DEPLOY_HOOK if it is set (turn off auto-deploy on Render so this is the only way in).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
BADGE = ROOT / "kane" / "badge.json"
IST = timezone(timedelta(hours=5, minutes=30))


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def clean_tree() -> bool:
    return sh("git", "status", "--porcelain").stdout.strip() == ""


def unit_tests() -> bool:
    return subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT).returncode == 0


def kane_all() -> tuple[bool, list[dict]]:
    """Run every Kane test; return (all passed, results of the run)."""
    code = subprocess.run([sys.executable, str(ROOT / "scripts" / "kane_gate.py"), "--all"], cwd=ROOT).returncode
    runs = sorted((ROOT / ".kane" / "runs").glob("*.json"))
    results = json.loads(runs[-1].read_text())["results"] if runs else []
    ok = code == 0 and bool(results) and all(r["status"] == "passed" for r in results)
    return ok, results


def badge(results: list[dict]) -> dict:
    passed = sum(r["status"] == "passed" for r in results)
    return {"schemaVersion": 1, "label": "Kane CLI", "message": f"{passed}/{len(results)} passed",
            "color": "brightgreen" if passed == len(results) else "red",
            "checked_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "tests": {r["id"]: f"{r['passed']}/{r['runs']}" for r in results}}


def deploy_hook() -> str:
    url = os.getenv("RENDER_DEPLOY_HOOK", "")
    if not url:
        return "no RENDER_DEPLOY_HOOK set; pushed only"
    with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=30) as r:
        return f"Render deploy hook answered HTTP {r.status}"


def main(argv=None, *, checks: dict[str, Callable] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    c = {"clean": clean_tree, "unit": unit_tests, "kane": kane_all, "deploy": deploy_hook, **(checks or {})}

    if not c["clean"]():
        print("Refusing to ship: commit or stash your changes first, so what ships is what Kane tested.")
        return 1
    if not c["unit"]():
        print("Refusing to ship: unit tests failed.")
        return 1
    ok, results = c["kane"]()
    if not ok:
        failing = ", ".join(f"{r['id']} ({r['status']})" for r in results if r["status"] != "passed") or "no Kane run"
        print(f"Refusing to ship: Kane did not sign off. {failing}")
        return 1
    b = badge(results)
    print(f"Kane signed off: {b['message']}")
    if a.dry_run:
        print("Dry run: nothing written, pushed or deployed.")
        return 0
    BADGE.write_text(json.dumps(b, indent=2) + "\n")
    sh("git", "add", str(BADGE))
    sh("git", "commit", "-q", "-m", f"chore(kane): Kane signed off this build ({b['message']})")
    push = sh("git", "push", "-q")
    if push.returncode != 0:
        print("Push failed:", push.stderr.strip())
        return 1
    print(c["deploy"]())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
