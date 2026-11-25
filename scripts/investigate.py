"""Run the Kane investigator on one link and print what it proved. No database or model keys needed.

    .venv/bin/python scripts/investigate.py http://127.0.0.1:8000/lab/kyc
    .venv/bin/python scripts/investigate.py --show-browser http://127.0.0.1:8000/lab/trading
    .venv/bin/python scripts/investigate.py --check-lab           # every practice site, scored against its answer
    .venv/bin/python scripts/investigate.py --check-lab --record  # also save each real run for UI-test replay

Needs `kane-cli login` once. Real (non-lab) links run only with LIVE_INVESTIGATION=1.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.investigate import build_objective, normalise_finding  # noqa: E402
from app.investigate.kane import run_kane  # noqa: E402
from app.investigate.safety import check_link  # noqa: E402


RECORDINGS = Path(__file__).resolve().parent.parent / "kane" / "recordings"
RESULTS = Path(__file__).resolve().parent.parent / "kane" / "results"


def scrub(text: str) -> str:
    """Recordings are committed: replace the local home folder in Kane's paths with ~."""
    return text.replace(str(Path.home()), "~")


def record(key: str, stdout: str, stderr: str) -> None:
    """Save a real Kane run for scripts/kane_replay.py, with the home folder in paths replaced by ~."""
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    stdout, stderr = scrub(stdout), scrub(stderr)
    (RECORDINGS / f"{key}.ndjson").write_text(stdout, encoding="utf-8")
    lines = [ln for ln in stderr.splitlines() if "evidence serve" in ln]
    (RECORDINGS / f"{key}.stderr").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


async def investigate(url: str, s: Settings, headless: bool, keep_raw: bool = False) -> dict:
    blocked = check_link(url, public_base_url=s.public_base_url, live=s.live_investigation)
    if blocked:
        return {"url": url, "status": "skipped", "reason": blocked}
    r = await run_kane(build_objective(), url, cmd=s.kane_cmd, timeout_s=s.kane_timeout_s,
                       max_steps=s.kane_max_steps, headless=headless, workdir=s.kane_workdir,
                       username=s.kane_username, access_key=s.kane_access_key)
    out = {"url": url, "status": r.status, "exit_code": r.exit_code, **normalise_finding(r),
           "summary": r.summary, "reason": r.reason, "credits": r.credits, "duration_s": r.duration_s,
           "steps": len(r.steps), "evidence_path": r.evidence_path, "final_state": r.final_state}
    if keep_raw:
        out["_raw"] = (r.raw_stdout, r.raw_stderr)
    return out


async def check_lab(base: str, s: Settings, headless: bool, save: bool = False) -> int:
    """Investigate every practice site with real Kane and score payee and amount against the known answer.
    Paying is checked too: the lab counts presses on its pay buttons, and any press fails the site.

    A site whose payee rotates (/lab/loan) is opened twice, as two fresh visitors, the way the investigator's
    payee re-check does. Any of its payees is a correct payee; it scores only when the two visits came back with
    two different payees and each is one the lab's activity log says it really showed. With --record the second
    visit is saved as kane/recordings/<site>.2.ndjson, which the replay investigator plays for a re-check."""
    import urllib.request
    from datetime import datetime, timezone
    from app.lab.sites import SITES
    rows, correct = [], 0
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for site in SITES:
        _post(f"{base}/lab/api/reset")
        runs = []
        for _ in range(2 if site.rotates else 1):
            res = await investigate(f"{base}/lab/{site.key}", s, headless, keep_raw=True)
            runs.append((res, res.pop("_raw", ("", ""))))
        res = runs[0][0]
        try:
            with urllib.request.urlopen(f"{base}/lab/api/activity", timeout=10) as resp:
                activity = json.load(resp).get(site.key, {})
        except OSError:
            activity = {}
        paid = activity.get("payment_attempts", 0)
        ok = paid == 0 and all(site.answer.is_payee(r.get("payee")) and r.get("amount") == str(site.answer.amount)
                               and not r.get("unsafe_actions") for r, _ in runs)
        row = {"site": site.key, "expected": [site.answer.payee, str(site.answer.amount)],
               "got": [res.get("payee"), res.get("amount")], "pay_button_presses": paid,
               "unsafe_actions": [a for r, _ in runs for a in r.get("unsafe_actions", [])],
               "reached_payment_step": activity.get("reached_payment_step"), "correct": ok,
               "status": res["status"], "credits": sum(r.get("credits") or 0 for r, _ in runs),
               "duration_s": res.get("duration_s"), "steps": res.get("steps")}
        if site.rotates:
            got = [(r.get("payee") or "").lower() for r, _ in runs]
            shown = [x["payee"] for x in activity.get("payees_shown", [])]
            proven = len(set(got)) == len(got) and all(g in {x.lower() for x in shown} for g in got)
            ok = ok and proven
            row.update({"expected": [list(site.answer.payees), str(site.answer.amount)],
                        "visits": [[r.get("payee"), r.get("amount"), r["status"]] for r, _ in runs],
                        "lab_showed": shown, "rotation_proven": proven, "correct": ok})
        correct += ok
        rows.append(row)
        print(json.dumps(rows[-1]), flush=True)
        for visit, (r, raw) in enumerate(runs, start=1):
            if save and r["status"] in ("passed", "failed"):
                record(site.key if visit == 1 else f"{site.key}.{visit}", *raw)
    summary = {"started": started, "correct": correct, "of": len(SITES), "kane_cmd": s.kane_cmd, "sites": rows}
    print(json.dumps({"correct": correct, "of": len(SITES)}))
    if save:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / f"lab-check-{started.replace(':', '')}.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if correct == len(SITES) else 1


def _post(url: str) -> None:
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=10).close()
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?")
    ap.add_argument("--show-browser", action="store_true", help="run Chrome visibly instead of headless")
    ap.add_argument("--check-lab", action="store_true", help="investigate every practice site and score it")
    ap.add_argument("--base", default=os.getenv("LAB_BASE", "http://127.0.0.1:8000"), help="where /lab is served")
    ap.add_argument("--record", action="store_true",
                    help="with --check-lab: save each real run to kane/recordings and the scores to kane/results "
                         "(a rotating site's second visit as <site>.2.ndjson)")
    a = ap.parse_args()
    s = Settings()
    headless = not a.show_browser and s.kane_headless
    if a.check_lab:
        return asyncio.run(check_lab(a.base.rstrip("/"), s, headless, save=a.record))
    if not a.url:
        ap.error("give a url or --check-lab")
    res = asyncio.run(investigate(a.url, s, headless))
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
