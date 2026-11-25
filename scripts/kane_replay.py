"""Replay a recorded real Kane run, for UI tests. Used as KANE_CMD by scripts/kane_gate.py.

Called like Kane (`kane_replay.py run "<objective>" --url <url> --agent ...`). It finds the practice-lab site in
the url and prints the NDJSON that the real Kane CLI printed when it investigated that site, saved by
`scripts/investigate.py --check-lab --record` in kane/recordings/<site>.ndjson. So a UI test of the dashboard
costs one Kane run (the tester), not two, and shows exactly what real Kane found.

KANE_REPLAY_VISIT=n (set by the investigator on a fresh-visitor payee re-check) replays the real run recorded on
visit n instead, kane/recordings/<site>.<n>.ndjson; visit 1 is <site>.ndjson.

No recording for the site or visit: exits 2 with a message, which the app shows as "Kane could not start".
"""
import os
import sys
from pathlib import Path

RECORDINGS = Path(os.getenv("KANE_RECORDINGS") or Path(__file__).resolve().parent.parent / "kane" / "recordings")


def main() -> int:
    args = sys.argv[1:]
    url = args[args.index("--url") + 1] if "--url" in args else ""
    key = url.split("/lab/", 1)[1].split("/")[0].split("?")[0] if "/lab/" in url else ""
    visit = os.getenv("KANE_REPLAY_VISIT", "1").strip()
    name = key if visit in ("", "1") else f"{key}.{visit}"
    out = RECORDINGS / f"{name}.ndjson"
    if not key or not out.is_file():
        print(f"No recorded Kane run for {url!r} (visit {visit or 1}). Record one with: "
              "scripts/investigate.py --check-lab --record", file=sys.stderr)
        return 2
    sys.stdout.write(out.read_text(encoding="utf-8"))
    err = RECORDINGS / f"{name}.stderr"
    if err.is_file():
        sys.stderr.write(err.read_text(encoding="utf-8"))
    return 0 if '"status": "passed"' in out.read_text(encoding="utf-8").replace('"status":"passed"', '"status": "passed"') else 1


if __name__ == "__main__":
    raise SystemExit(main())
