# SCAM-BAIT

![Kane CLI](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/diyaavirmani/scambait/main/kane/badge.json)

**An AI scam-baiter whose hands are Kane CLI.** Scammers send links. Most tools block them. SCAM-BAIT follows them:
Kane opens every link a scammer sends in a real browser, walks through it like a victim, stops before any money
moves, and comes back with proof of who gets paid. Meena, a slow and worried grandmother, uses that proof in her next
reply to keep the scammer talking, and the case leaves with a police-ready evidence pack.

Built for the [KaneCLI Hack Day](https://www.kaneclihack.sh/) by TestMu AI.

## What it does

- **Kane follows the scam.** A link in a scammer's message (a fake KYC page, a parcel "customs fee", a trading
  dashboard that blocks withdrawals) goes to the Kane investigator. Kane acts as a first-time visitor, follows the
  steps, stops on the payment page without touching it, and reports what the page pretends to be, the UPI ID or bank
  account it pays, the amount and what it asked for, with a screenshot of every step.
- **Meena uses what Kane proved.** Her next reply turns the finding into bait ("my grandson opened your link, it says
  Bharat Unity Bank and wants 10 rupees and my PIN, whose name will show when I pay?"), so the scammer confirms the
  payee in chat. The case then holds both what was said and what the scam page itself proved.
- **Kane catches rotating mule accounts.** Scam pages often show each new visitor a different UPI ID. After Kane proves
  a payee, it opens the same link again as a fresh visitor; every new payee is recorded as proven, joins the scam's
  network, and Meena asks the scammer which account is the right one.
- **Check a Message, before you pay**, for anyone who got a scary SMS: paste it and get a verdict in plain words with
  the scam signs behind it. Press **Check who gets the money** and Kane opens the link and says who the money would
  go to and how much ("Do not pay"). "No payment page found" never reads as safe, and app links are never opened.
- **I already paid:** the golden-hour steps in order. Call 1930 first, then the bank, then a prefilled
  cybercrime.gov.in complaint (one row per payment) with copy buttons, which the person submits themselves.
- **Scam Console:** play the scammer in the browser and watch detection, Meena, Kane and the evidence board live.
  Scammers who message the Telegram bot, call the Twilio number or hit the honeypot API get the same pipeline.
- **Phone calls:** Meena answers scam calls in a live voice (OpenAI GPT-Live over Twilio Media Streams). The caller's
  words are transcribed and judged as they come; if the live voice is unavailable the call carries on turn by turn.
- **Two models, one verdict:** Cerebras judges every chat in about half a second. When it is unsure (between 0.2 and
  0.8), OpenAI Decisions gives a second opinion; with no model at all, plain-language rules decide.
- **Networks:** cases that reuse the same UPI ID, account, phone number or link are grouped into one scam operation,
  and the Intelligence page lists every identifier with a "Proven by Kane" mark where Kane saw it on the scam page.
- **Case report for 1930 / NCRP**, written when a case closes. It may only name identifiers said in the chat or
  proven by Kane; anything else the model returns is dropped.
- **Evidence pack:** PDF and CSV with the NCRP complaint fields, the case report, the transcript, every identifier,
  Kane's proof and its screenshot of the payment page, all SHA-256 hashed.
- **Warn your family:** a WhatsApp-ready warning in English and Hindi, built from the case, with account and phone
  numbers cut to their last 4 characters (the account holder may be a victim too).

## How Kane is used

```mermaid
flowchart LR
    S[Scammer sends a link] --> K[Kane CLI opens it as a victim]
    K -->|payee, amount, screenshots| M[Meena's next reply uses it]
    K --> E[Evidence pack]
    A[Coding agent says done] --> H[Stop hook: kane_gate.py]
    H --> T[Kane tests the dashboard in Chrome]
    T -->|fail: reason, step, evidence| A
```

1. **In the product, Kane is the agent's hands** (`app/investigate`). `kane-cli run ... --agent --headless` with an
   objective that stores `claims_to_be`, `payee`, `amount` and `asked_for`; the values come back from
   `run_end.final_state`, the evidence pack is hashed into the case, and the finding reaches Meena's next reply.
2. **Kane's actions are checked, not trusted.** A guard (`app/investigate/guard.py`) reads every step Kane reports.
   A run that typed into a PIN, card, CVV, OTP or payment reference field, or pressed a pay button, is marked unsafe
   and never used as proof. This happened once on the practice lab (Kane log, catch 4).
3. **While building, Kane is the referee** (`kane/tests`, `scripts/kane_gate.py`). Plain-English Kane tests drive the
   dashboard in a real browser. A Claude Code **Stop hook** (`.claude/settings.json`) runs the tests affected by a
   change; on a failure it hands the agent Kane's reason, the failing step and the evidence pack and exits 2, so the
   agent keeps fixing. Other agents run `make verify`.
4. **Nothing ships without Kane.** `make ship` deploys only when the unit tests and every Kane test pass, and writes
   the badge at the top of this page.
5. **Measured against known answers.** The practice lab (`/lab`) has six fictional scam sites, each with a known payee
   and amount and a counter for presses of its pay button; one rotates its payee for every new visitor. `make
   lab-check` runs real Kane on all of them (the rotating one twice) and scores it.

The official Kane CLI agent skill is vendored in `.claude/skills/kane-cli` (Apache-2.0), and `CLAUDE.md` tells coding
agents how the loop works and that a Kane test is never weakened to get past it.

## Measured with real Kane CLI

Every number is from a real Kane CLI 0.10.8 run, saved in [`kane/results/`](kane/results/). Each row is the whole
practice lab run again after a change to the investigator, so a fix that breaks another site shows at once.

| Run (IST) | Investigator | Correct payee and amount | Pay-button presses | Credits per site |
|---|---|---|---|---|
| 24 Nov, 15:37 | as first written | 4 of 5: job site failed (catch 2) | 0 on all 5 | 21 to 40 |
| 24 Nov, 15:47 | after the first fix | 4 of 5: job fixed, parcel regressed (catch 3) | 0 on all 5 | 27 to 35 |
| 24 Nov, 15:56 | written in phases | 4 of 5: Kane typed a PIN and pressed pay (catch 4) | **2** on electricity | 24 to 41 |
| 24 Nov, 16:13 | one flow, safety rule first | 3 of 5: right values under Kane's own names (catch 5) | 0 on all 5 | 20 to 36 |
| 24 Nov, 16:26 | one flow, exact names, read by meaning | **5 of 5** | **0 on all 5** | 19 to 28 |
| 25 Nov, 11:13 | the same, on the finished app | **5 of 5** | **0 on all 5, 0 unsafe steps** | 21 to 40 |
| 25 Nov, 12:53 | plus the rotating-payee site, opened twice | **6 of 6**, rotation proven: 2 different payees | **0 on all 6, 0 unsafe steps** | 20 to 27 per visit |

Kane also tests the app on the real models. Its K05 test (does Meena use what Kane proved?) passed 0 of 3 against
Cerebras before a fix to Meena's instructions and 3 of 3 after (`kane/results/k05-real-models-*.json`). What Kane
caught while this was built, eight problems in all, is in the [Kane log](docs/kane-log.md).

## Screenshots

Taken on 25 Nov 2026. The Kane results come from real Kane CLI runs on the practice lab; where a card says "replay
of a real Kane run", the app replayed that recorded run.

![Check a Message: Kane opened the link and says do not pay; the page would send Rs 10 to bharatunity.kyc@demoupi](docs/images/before-you-pay.png)
*Before you pay: one press sends the link to Kane, and the answer says who would get the money and why not to pay.*

![I already paid: Call 1930 first, then the bank, then a prefilled cybercrime.gov.in complaint](docs/images/already-paid.png)
*I already paid: the golden-hour steps in order, and a complaint draft the person submits themselves.*

![Scam Console: Kane opened the loan link twice as a fresh visitor and saw two different payees; Meena used the finding](docs/images/rotation.png)
*A rotating payee: Kane opened the link again as a new visitor and the page named someone else to pay.*

![A closed case on the real models: Kane proved the page pretends to be Bharat Unity Bank and sends Rs 10 to bharatunity.kyc@demoupi; Cerebras wrote the case report](docs/images/real-case.png)
*A closed case on the real models with real Kane: the case report written by Cerebras, which may only name
identifiers said in chat or proven by Kane; the family warning card in English and Hindi with the payee cut to its
last 4 characters; Kane's proof with its screenshot of where it stopped before paying; and the evidence board.*

![Networks: three cases linked by the same UPI ID and link, identifiers masked except their last 4 characters](docs/images/networks.png)
*Networks: three chats that reused the same UPI ID and link, grouped as one operation.*

![The practice lab: six fictional scam sites with known payees and amounts, one of them rotating](docs/images/practice-lab.png)
*The practice lab: fictional scam sites with known answers, used to score the investigator.*

## Try it

```bash
uv venv --python 3.12 .venv && uv pip install -p .venv -r requirements.txt
npm install -g @testmuai/kane-cli && kane-cli login      # once
make offline                                             # no model keys needed
```

Then open http://127.0.0.1:8000/check (paste a message or tap an example), http://127.0.0.1:8000/console (tap "Bank
KYC update" and send) or http://127.0.0.1:8000/lab (the practice sites and their known answers).

`make offline` runs detection on rules alone and Meena from a script, so nobody needs model keys; Kane always runs
for real. With a Cerebras key in `.env` (copy `.env.example`), `make run` uses the models.

| Command | What it does |
|---|---|
| `make test` | unit and API tests, no keys and no network |
| `make verify` | unit tests, then the Kane tests affected by your changes |
| `make kane-all` | every Kane test against the dashboard |
| `make lab-check` | real Kane investigates every practice site; scores and recordings are saved |
| `make ship` | deploy only after unit tests and every Kane test pass |
| `.venv/bin/python scripts/investigate.py <url>` | one investigation, printed as JSON |

## Safety

- The practice lab uses fictional brands, banks, UPI IDs (`@demoupi`) and accounts (IFSC `DEMO...`). Every page says
  it is a practice site, forms are thrown away, and only presses of the pay button are counted.
- Real links are opened only with `LIVE_INVESTIGATION=1`. Even then Kane never opens downloads (APKs are recorded,
  never opened), links with credentials in them, odd ports, or private and internal addresses.
- The objective opens with the safety rule and uses a fictional identity; the step guard enforces it after every run.
- Meena's replies pass a guard that never lets a real-looking UPI ID, account number, phone or link through, and turns
  any AI admission or prompt leak into a confused deflection.

## How it fits together

| Part | Code |
|---|---|
| Conversation engine | `app/engine.py` |
| Scam detection: plain-language signs, Cerebras, OpenAI Decisions in the unsure band | `app/rules.py`, `app/detect.py` |
| Meena, her reply guard, the model calls (Cerebras, or scripted offline) | `app/meena.py`, `app/brain.py` |
| OpenAI: Decisions, moderation, the report fallback | `app/openai_client.py` |
| Identifier extraction and validation | `app/intel.py` |
| Kane investigator, link safety, step guard, evidence screenshots | `app/investigate/` |
| Practice scam lab | `app/lab/` |
| Channels: scam console, Telegram, honeypot API, Check a Message | `app/console.py`, `app/telegram.py`, `app/honeypot.py`, `app/check.py` |
| Phone calls: Twilio webhooks, the live voice bridge | `app/voice/` |
| Networks of cases that share identifiers | `app/networks.py` |
| Case report for 1930 / NCRP | `app/report.py` |
| Store (SQLite), live events (SSE), cases, evidence pack | `app/store.py`, `app/bus.py`, `app/cases.py`, `app/evidence_pack.py` |
| Dashboard (React and Tailwind, built into `app/web/dist`) | `dashboard/` |

## Configuration

Copy `.env.example` to `.env`. Only `CEREBRAS_API_KEY` is required, and not even that with `OFFLINE_MODE=1`. Every
setting is described in `.env.example`; the ones that matter most:

| Name | Default | Meaning |
|---|---|---|
| `OFFLINE_MODE` | `0` | `1`: no model keys; rules-only detection and scripted Meena; Kane still real |
| `CEREBRAS_API_KEY` | empty | Meena and the first opinion on every chat |
| `OPENAI_API_KEY` | empty | Decisions second opinion, moderation, the live phone voice, the report when Cerebras is down |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | empty | phone calls; point the number at `PUBLIC_BASE_URL/voice/incoming` |
| `PUBLIC_BASE_URL` | empty | the exact https URL Twilio and Telegram call (signatures are checked against it) |
| `KANE_ENABLED`, `KANE_CMD`, `KANE_TIMEOUT_S` | `1`, `kane-cli`, `240` | the Kane investigator |
| `KANE_ROTATION_CHECKS` | `1` | fresh-visitor re-checks after Kane proves a payee (0 to 2); each is one more Kane run |
| `LIVE_INVESTIGATION` | `0` | `1` lets Kane open real links, under the safety rules |
| `TELEGRAM_AUTO_WEBHOOK` | `1` | `0` on any local copy, so it never takes the bot from the live server |
| `RENDER_DEPLOY_HOOK` | empty | called by `make ship` after Kane signs off |
