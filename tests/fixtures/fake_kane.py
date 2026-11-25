"""Stand-in for `kane-cli run ... --agent` in tests. Prints the documented NDJSON contract.

The answer depends on the --url: a known practice-lab site gets a passed run with that site's payee in
final_state; a url containing "fail" gets a failed run; "nostart" exits 2 with no run_end. It writes a small
evidence file in the working directory and prints its path on stderr, as Kane does. FAKE_KANE_LOG, if set, gets
one line per call so tests can count runs.
"""
import json
import os
import sys
import time

args = sys.argv[1:]
url = args[args.index("--url") + 1] if "--url" in args else ""
if os.environ.get("FAKE_KANE_LOG"):
    with open(os.environ["FAKE_KANE_LOG"], "a") as f:
        f.write(url + "\n")


def out(obj):
    obj.setdefault("v", 1)
    obj.setdefault("ts", time.time())
    print(json.dumps(obj), flush=True)


ANSWERS = {
    "/lab/kyc": {"claims_to_be": "Bharat Unity Bank KYC update", "payee": "UPI ID: bharatunity.kyc@demoupi",
                 "amount": "Rs 10", "asked_for": "full name, mobile number, date of birth and UPI PIN"},
    "/lab/trading": {"claims_to_be": "GrowthPro Capital VIP trading desk", "payee": "000987654321",
                     "amount": "33,210", "asked_for": ["mobile number", "payment reference number"]},
}

if "nostart" in url:
    print("Not authenticated [prod]. Run \"kane-cli login\" first.", file=sys.stderr)
    sys.exit(2)

out({"type": "stream_start", "cli_version": "0.0.0-fake", "pid": os.getpid(), "surface": "run"})
print("not json, ignored")
out({"step": 1, "status": "running", "remark": "Open the page"})
out({"step": 1, "status": "done", "remark": "Opened the page"})
out({"step": 2, "status": "done", "remark": "Filled the form with the given details"})

state = next((v for k, v in ANSWERS.items() if k in url), {})
passed = bool(state) and "fail" not in url
pack = os.path.join(os.getcwd(), f"fake-{int(time.time() * 1000)}.evidence.zip")
with open(pack, "wb") as f:
    f.write(b"fake evidence pack for " + url.encode())
print(f"evidence: view locally with `kane-cli evidence serve {pack}`", file=sys.stderr)
out({"type": "run_end", "status": "passed" if passed else "failed",
     "summary": "Reached the payment request without paying." if passed else "Could not find a payment request.",
     "one_liner": "payment request found" if passed else "no payment request",
     "reason": "" if passed else "The page did not ask for money.",
     "duration": 12.5, "credits_consumed": 3, "final_state": state, "session_dir": os.getcwd()})
sys.exit(0 if passed else 1)
