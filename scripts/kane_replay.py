"""Replay a recorded real Kane run, for UI tests. Used as KANE_CMD by scripts/kane_gate.py.

Called like Kane (`kane_replay.py run "<objective>" --url <url> --agent ...`). It finds the practice-lab site in
the url and prints the NDJSON that the real Kane CLI printed when it investigated that site, saved by
`scripts/investigate.py --check-lab --record` in kane/recordings/<site>.ndjson. So a UI test of the dashboard
costs one Kane run (the tester), not two, and shows exactly what real Kane found.

No recording for the site: exits 2 with a message, which the app shows as "Kane could not start".
"""
import os
import sys
from pathlib import Path

RECORDINGS = Path(os.getenv("KANE_RECORDINGS") or Path(__file__).resolve().parent.parent / "kane" / "recordings")


def main() -> int:
    args = sys.argv[1:]
    url = args[args.index("--url") + 1] if "--url" in args else ""
    key = url.split("/lab/", 1)[1].split("/")[0].split("?")[0] if "/lab/" in url else ""
    out = RECORDINGS / f"{key}.ndjson"
    if not key or not out.is_file():
        print(f"No recorded Kane run for {url!r}. Record one with: scripts/investigate.py --check-lab --record",
              file=sys.stderr)
        return 2
    sys.stdout.write(out.read_text(encoding="utf-8"))
    err = RECORDINGS / f"{key}.stderr"
    if err.is_file():
        sys.stderr.write(err.read_text(encoding="utf-8"))
    return 0 if '"status": "passed"' in out.read_text(encoding="utf-8").replace('"status":"passed"', '"status": "passed"') else 1


if __name__ == "__main__":
    raise SystemExit(main())
