"""Kane gate: run the Kane tests affected by your changes against the real dashboard, in a real browser.

    .venv/bin/python scripts/kane_gate.py            # tests whose `covers` globs match changed files
    .venv/bin/python scripts/kane_gate.py --all      # every test in kane/tests
    .venv/bin/python scripts/kane_gate.py --ids K05,K06
    .venv/bin/python scripts/kane_gate.py --hook     # Claude Code Stop hook (see .claude/settings.json)

Changed files = everything changed since the last all-green run (or since HEAD, the first time), plus
uncommitted and untracked files. If no app answers on --base, the gate starts one in offline mode (no model
keys) on a free port with the replay investigator (real Kane runs recorded from the practice lab), runs the
tests, and stops it.

Hook mode, for a coding agent: on a failure it prints what Kane saw (the test, Kane's reason, the failing step,
the evidence pack) to stderr and exits 2, which makes Claude Code keep working instead of stopping. It never
blocks more than MAX_BLOCKS times in a row, and it never blocks for problems the agent cannot fix (Kane not
logged in, out of credits): those pass through with a warning.

Every run is saved in .kane/runs/ (git-ignored).
"""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.investigate.kane import KaneResult, run_kane  # noqa: E402

TESTS_DIR = ROOT / "kane" / "tests"
STATE_DIR = ROOT / ".kane"
MAX_BLOCKS = 3
INFRA = ("not_started", "error")  # Kane could not run: not something the coding agent can fix
# Kane's own browser went away mid-run (seen on 25 Nov 2026 when the Mac slept during a run): also not the app's fault.
BROWSER_GONE = re.compile(r"TargetClosedError|browser has been closed|context or browser has been closed", re.I)


def is_infra(r: KaneResult) -> bool:
    return r.status in INFRA or bool(BROWSER_GONE.search(r.reason or ""))


@dataclass
class KaneTest:
    id: str
    title: str
    path: str
    objective: str
    covers: list[str] = field(default_factory=list)
    timeout: int = 240
    repeat: int = 1
    file: str = ""


def load_tests(folder: Path = TESTS_DIR) -> list[KaneTest]:
    tests = []
    for f in sorted(folder.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        _, front, body = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
        tests.append(KaneTest(id=str(meta["id"]), title=str(meta.get("title", "")), path=str(meta.get("path", "/")),
                              objective=" ".join(body.split()), covers=list(meta.get("covers") or []),
                              timeout=int(meta.get("timeout", 240)), repeat=int(meta.get("repeat", 1)), file=f.name))
    return tests


def select(tests: list[KaneTest], changed: list[str]) -> list[KaneTest]:
    """Tests whose covers globs match any changed file. Changing a Kane test file selects that test."""
    out = []
    for t in tests:
        own = f"kane/tests/{t.file}"
        if any(c == own or any(fnmatch.fnmatch(c, g) for g in t.covers) for c in changed):
            out.append(t)
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def changed_files(state: dict) -> list[str]:
    files = set(_git("diff", "--name-only", "HEAD").split())
    files |= set(_git("ls-files", "--others", "--exclude-standard").split())
    last = state.get("last_green")
    if last and _git("cat-file", "-t", last).strip() == "commit":
        files |= set(_git("diff", "--name-only", f"{last}..HEAD").split())
    return sorted(files)


def load_state() -> dict:
    try:
        return json.loads((STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))


# ---------- the app under test ----------
def healthy(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_app(inner: str) -> tuple[str, subprocess.Popen, str]:
    """Start the app in offline mode on a free port. inner: replay (recorded real Kane) | fixture | real."""
    port = free_port()
    work = tempfile.mkdtemp(prefix="kane-gate-")
    py = sys.executable
    cmd = {"replay": f"{py} {ROOT / 'scripts' / 'kane_replay.py'}",
           "fixture": f"{py} {ROOT / 'tests' / 'fixtures' / 'fake_kane.py'}",
           "real": "kane-cli"}[inner]
    env = {**os.environ, "OFFLINE_MODE": "1", "TELEGRAM_AUTO_WEBHOOK": "0", "DB_PATH": f"{work}/gate.db",
           "KANE_CMD": cmd, "KANE_WORKDIR": f"{work}/kane", "PYTHONPATH": str(ROOT), "API_KEY": "",
           "PUBLIC_BASE_URL": ""}
    log = open(f"{work}/server.log", "w")
    proc = subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
                             "--workers", "1"], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        if healthy(base):
            return base, proc, work
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"the app did not start; see {work}/server.log")


def reset_lab(base: str) -> None:
    try:
        urllib.request.urlopen(urllib.request.Request(base + "/lab/api/reset", method="POST"), timeout=5).close()
    except OSError:
        pass


# ---------- running ----------
Runner = Callable[[KaneTest, str], Awaitable[KaneResult]]


async def kane_runner(test: KaneTest, base: str) -> KaneResult:
    return await run_kane(test.objective, base + test.path, timeout_s=test.timeout, max_steps=60,
                          headless=os.getenv("KANE_HEADLESS", "1") == "1", workdir=str(STATE_DIR / "work"),
                          cmd=os.getenv("KANE_TEST_CMD", "kane-cli"), agent="scambait-kane-gate")


async def run_suite(tests: list[KaneTest], base: str, runner: Runner = kane_runner, repeat: Optional[int] = None) -> list[dict]:
    results = []
    for t in tests:
        runs = []
        for _ in range(repeat or t.repeat):
            reset_lab(base)
            r = await runner(t, base)
            runs.append(r)
        passed = sum(r.passed for r in runs)
        failing = next((r for r in runs if not r.passed), None)
        results.append({
            "id": t.id, "title": t.title, "runs": len(runs), "passed": passed,
            "status": "passed" if passed == len(runs) else ("infra" if failing and is_infra(failing) else "failed"),
            "reason": failing.reason if failing else "", "summary": (failing or runs[-1]).summary,
            "failed_steps": [s for s in (failing.steps if failing else []) if s.get("status") == "failed"],
            "evidence": failing.evidence_path if failing else runs[-1].evidence_path,
            "credits": sum(r.credits or 0 for r in runs), "duration_s": round(sum(r.duration_s or 0 for r in runs), 1),
        })
    return results


def save_run(results: list[dict], selected_by: str) -> Path:
    runs = STATE_DIR / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = runs / f"{stamp}.json"
    path.write_text(json.dumps({"at": stamp, "head": _git("rev-parse", "--short", "HEAD").strip(),
                                "selected_by": selected_by, "results": results}, indent=2))
    return path


def report(results: list[dict]) -> str:
    lines = []
    for r in results:
        mark = {"passed": "PASS", "failed": "FAIL", "infra": "SKIP"}[r["status"]]
        rate = f" ({r['passed']}/{r['runs']})" if r["runs"] > 1 else ""
        lines.append(f"{mark} {r['id']} {r['title']}{rate}")
    return "\n".join(lines)


def failure_feedback(results: list[dict]) -> str:
    out = ["Kane CLI tested the dashboard in a real browser and these checks failed. Fix the code so they pass,",
           "then finish again. Do not weaken or delete the Kane tests to make them pass.", ""]
    for r in results:
        if r["status"] != "failed":
            continue
        out.append(f"{r['id']} {r['title']}: {r['passed']} of {r['runs']} runs passed")
        if r["reason"]:
            out.append(f"  Kane's reason: {r['reason']}")
        for s in r["failed_steps"][:3]:
            out.append(f"  failed step {s.get('step')}: {s.get('remark')}")
        if r["evidence"]:
            out.append(f"  evidence pack: {r['evidence']} (view with: kane-cli evidence serve <path>)")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None, runner: Runner = kane_runner, stdin=sys.stdin) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--hook", action="store_true", help="Claude Code Stop hook mode")
    ap.add_argument("--base", default=os.getenv("KANE_GATE_BASE", ""), help="use a running app instead of starting one")
    ap.add_argument("--inner", default=os.getenv("KANE_GATE_INNER", "replay"), choices=["replay", "fixture", "real"],
                    help="investigator inside the app under test")
    ap.add_argument("--repeat", type=int, default=None, help="override every test's repeat count")
    ap.add_argument("--list", action="store_true", help="print the selected tests and exit")
    a = ap.parse_args(argv)

    state = load_state()
    if a.hook:
        try:
            json.load(stdin)  # Claude Code sends the hook input; nothing in it changes what we test
        except (ValueError, OSError):
            pass
    tests = load_tests()
    if a.ids:
        wanted = {i.strip() for i in a.ids.split(",") if i.strip()}
        chosen, why = [t for t in tests if t.id in wanted], "ids"
    elif a.all:
        chosen, why = tests, "all"
    else:
        chosen, why = select(tests, changed_files(state)), "changed files"
    if a.list or not chosen:
        print("\n".join(f"would run {t.id} {t.title}" + (f" (x{t.repeat})" if t.repeat > 1 else "") for t in chosen)
              if chosen else "No Kane tests cover these changes.")
        return 0

    proc = None
    base = a.base.rstrip("/")
    try:
        if not base or not healthy(base):
            base, proc, _ = start_app(a.inner)
        results = asyncio.run(run_suite(chosen, base, runner, a.repeat))
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
    path = save_run(results, why)
    print(report(results))
    print(f"saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")

    failed = [r for r in results if r["status"] == "failed"]
    infra = [r for r in results if r["status"] == "infra"]
    if not failed:
        if not infra:
            state["last_green"] = _git("rev-parse", "HEAD").strip()
        state["blocks"] = 0
        save_state(state)
        if infra:
            print("Warning: Kane could not run some tests (" + "; ".join(r["reason"][:120] for r in infra) + ")",
                  file=sys.stderr)
        return 0
    if not a.hook:
        print(failure_feedback(results), file=sys.stderr)
        return 1
    state["blocks"] = state.get("blocks", 0) + 1
    if state["blocks"] > MAX_BLOCKS:
        state["blocks"] = 0
        save_state(state)
        print(f"Kane tests still fail after {MAX_BLOCKS} attempts; letting the agent stop so a person can look.\n"
              + failure_feedback(results))
        return 0
    save_state(state)
    print(failure_feedback(results), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
