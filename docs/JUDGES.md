# Judge guide

Everything below can be checked in about ten minutes. No model key is needed; Kane needs `kane-cli login`.

## 1. Run it (2 minutes)

```bash
git clone https://github.com/diyaavirmani/scambait && cd scambait
uv venv --python 3.12 .venv && uv pip install -p .venv -r requirements.txt
make offline          # http://127.0.0.1:8000, rules-only detection and scripted Meena, real Kane
```

## 2. Kane as the agent's hands (3 minutes)

1. Open http://127.0.0.1:8000/console, tap **Bank KYC update**, press **Send**.
2. The Kane card says "Kane is opening this link in a real browser". In about a minute and a half it turns green:
   pretends to be Bharat Unity Bank, money goes to `bharatunity.kyc@demoupi`, Rs 10, with Kane's screenshot of the page
   where it stopped.
3. Send any message ("Did you do it?"). Meena's reply now talks about what the page asked for, and it is marked "used
   what Kane found". The evidence board marks the UPI ID as proven by Kane.
4. Open **Cases** and download the PDF: its "Links opened by Kane CLI" section has the screenshot and the evidence pack
   SHA-256.

From the command line, with only the app running:

```bash
.venv/bin/python scripts/investigate.py http://127.0.0.1:8000/lab/kyc     # one investigation, as JSON
make lab-check                                                            # all five practice sites, scored
curl -s http://127.0.0.1:8000/lab/api/activity                           # payment_attempts stays 0
```

## 3. Kane closing the build loop (3 minutes)

- `.claude/settings.json` registers `scripts/kane_gate.py --hook` as a Claude Code **Stop** hook.
- Open Claude Code in this folder and ask for any change to `app/meena.py`: when it says it is done, the hook runs the
  affected Kane tests (`kane/tests/K05` to `K08`) in Chrome. A failure comes back to the agent as Kane's reason, the
  failing step and the evidence pack, and the agent keeps working.
- Without an agent: `make verify` (unit tests, then the affected Kane tests) or `make kane-all`.
- Every run is saved in `.kane/runs/`. `make ship` refuses to deploy unless every Kane test passes.

## 4. Evidence that it was really run

- `kane/results/`: every practice-lab check with real Kane: per site the expected and found payee and amount,
  pay-button presses, unsafe steps, credits, seconds and steps.
- `kane/recordings/`: the raw NDJSON real Kane printed on each site, replayed for dashboard tests and on hosts without
  a browser (every replayed result is labelled "replay of a real Kane run").
- [`docs/kane-log.md`](kane-log.md): what Kane caught while this was built, with Kane's own diagnosis and the fix.
- `kane/badge.json`: the last `make ship` run and each Kane test's pass count.
- `make test`: unit and API tests (no keys, no network).
