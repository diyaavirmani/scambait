"""Run Kane CLI on one objective and read its result.

Contract used (Kane CLI agent mode): `kane-cli run "<objective>" --url <url> --agent --headless` writes NDJSON to
stdout, one object per line. Step lines have `step`, `status` and `remark` and no `type`. The last line of a run
that started is `{"type": "run_end", ...}` with `status` (passed | failed), `summary`, `one_liner`, `reason`,
`duration`, `credits_consumed` and `final_state` (values saved with "store ... as" in the objective).
Exit codes: 0 passed, 1 ran but did not pass, 2 never started (no credits used), 3 cancelled or timed out.
The evidence pack path is printed on stderr as "kane-cli evidence serve <path>". Unknown lines and fields are
ignored, as the contract asks.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

EVIDENCE_RE = re.compile(r"kane-cli evidence serve\s+[`'\"]?([^\s`'\"]+)")
EXIT_MEANING = {0: "passed", 1: "failed", 2: "not_started", 3: "timeout"}


@dataclass
class KaneResult:
    status: str                      # passed | failed | not_started | timeout | error
    exit_code: Optional[int]
    summary: str = ""
    one_liner: str = ""
    reason: str = ""
    final_state: dict[str, Any] = field(default_factory=dict)
    credits: Optional[float] = None
    duration_s: Optional[float] = None
    session_dir: str = ""
    evidence_path: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    run_end: Optional[dict[str, Any]] = None
    raw_stdout: str = ""             # Kane's NDJSON as printed (kept for recordings and debugging)
    raw_stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def parse_stream(stdout: str, stderr: str = "", exit_code: Optional[int] = None) -> KaneResult:
    """Turn Kane's NDJSON stdout (and stderr, for the evidence path) into a KaneResult.

    Every finished step line is kept in order. Step numbers repeat across Kane's child agents (a bifurcated
    objective runs as several flows), so they cannot be used as keys: keying by number drops the parent flow's
    steps when a child reuses the number (docs/kane-log.md, catch 4)."""
    finished: list[dict] = []
    run_end: Optional[dict] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        if kind == "run_end":
            run_end = obj
        elif kind is None and "step" in obj and obj.get("status") in ("done", "failed"):
            finished.append({"step": obj.get("step"), "status": obj.get("status", ""), "remark": obj.get("remark", "")})

    m = EVIDENCE_RE.search(stderr or "")
    evidence = m.group(1) if m else ""

    if run_end is None:
        status = EXIT_MEANING.get(exit_code, "error") if exit_code not in (0, 1) else "error"
        return KaneResult(status=status, exit_code=exit_code, reason=_tail(stderr), steps=finished,
                          evidence_path=evidence)

    raw_status = str(run_end.get("status", "")).lower()
    status = "passed" if raw_status == "passed" else "failed"
    if exit_code == 3:
        status = "timeout"
    credits = run_end.get("credits_consumed", run_end.get("credits"))
    final_state = run_end.get("final_state") if isinstance(run_end.get("final_state"), dict) else {}
    return KaneResult(
        status=status, exit_code=exit_code,
        summary=str(run_end.get("summary") or ""), one_liner=str(run_end.get("one_liner") or ""),
        reason=str(run_end.get("reason") or ""), final_state=final_state,
        credits=_num(credits), duration_s=_num(run_end.get("duration")),
        session_dir=str(run_end.get("session_dir") or ""), evidence_path=evidence or _find_pack(run_end),
        steps=finished, run_end=run_end,
    )


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _tail(text: str, n: int = 400) -> str:
    text = (text or "").strip()
    return text[-n:]


def _find_pack(run_end: dict) -> str:
    """Fallback when stderr had no path: the newest *.evidence* file under session_dir/evidence."""
    session = run_end.get("session_dir")
    if not session:
        return ""
    folder = Path(str(session)) / "evidence"
    if not folder.is_dir():
        return ""
    packs = sorted(folder.glob("*evidence*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(packs[0]) if packs else ""


def build_command(objective: str, url: str, *, cmd: str = "kane-cli", timeout_s: int = 240, max_steps: int = 40,
                  headless: bool = True, username: str = "", access_key: str = "") -> list[str]:
    args = shlex.split(cmd) + ["run", objective, "--url", url, "--agent", "--timeout", str(timeout_s),
                               "--max-steps", str(max_steps)]
    if headless:
        args.append("--headless")
    if username and access_key:
        args += ["--username", username, "--access-key", access_key]
    return args


def kill_tree(pid: int) -> None:
    """Kill a process and everything it started, children first. Kane CLI starts a runner and a browser driver that
    keep its output pipe open, so killing only kane-cli left run_kane waiting on the pipe (a 5 minute timeout ran
    14 minutes in a real Kane test run)."""
    try:
        children = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        children = []
    for child in children:
        if child.isdigit():
            kill_tree(int(child))
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def run_kane(objective: str, url: str, *, cmd: str = "kane-cli", timeout_s: int = 240, max_steps: int = 40,
                   headless: bool = True, workdir: str = "out/kane", username: str = "",
                   access_key: str = "", agent: str = "scambait-investigator", grace_s: int = 60) -> KaneResult:
    """Run one Kane objective. Never raises for a failed run; returns status=error if Kane could not be started.
    agent tags the run (KANE_CLI_USER_AGENT), so investigator runs and test runs are told apart in TestMu.
    Kane gets timeout_s to stop itself; grace_s later the whole process tree is killed and the run is a timeout."""
    workdir = str(Path(workdir).resolve())
    Path(workdir).mkdir(parents=True, exist_ok=True)
    args = build_command(objective, url, cmd=cmd, timeout_s=timeout_s, max_steps=max_steps, headless=headless,
                         username=username, access_key=access_key)
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=workdir, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "KANE_CLI_USER_AGENT": agent})
    except (FileNotFoundError, PermissionError) as exc:
        return KaneResult(status="error", exit_code=None, reason=f"Kane CLI could not be started: {exc}")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s + grace_s)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        kill_tree(proc.pid)
        if isinstance(exc, asyncio.CancelledError):
            raise
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            out, err = b"", b""
        res = parse_stream(out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), 3)
        res.status = "timeout"
        res.raw_stdout, res.raw_stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        return res
    res = parse_stream(out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode)
    res.raw_stdout, res.raw_stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    if res.duration_s is None:
        res.duration_s = round(time.monotonic() - started, 1)
    if res.evidence_path and not os.path.isabs(res.evidence_path):
        res.evidence_path = str(Path(workdir) / res.evidence_path)
    return res
