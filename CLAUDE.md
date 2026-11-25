# Working in this repo (for coding agents)

SCAM-BAIT is checked by Kane CLI in a real browser. Read `kane/README.md` and `docs/JUDGES.md` first.

## The loop you are in

- A **Stop hook** (`.claude/settings.json`) runs `scripts/kane_gate.py --hook` when you finish. It runs the Kane tests
  whose `covers` globs match what you changed. If one fails you get Kane's reason, the failing step and the evidence
  pack on stderr, and you keep working. Fix the code; never weaken, skip or delete a Kane test to make it pass. After
  three blocks in a row it lets you stop so a person can look.
- The official **Kane CLI skill** is in `.claude/skills/kane-cli/` for ad-hoc checks (`kane-cli run ... --agent`).
- Other agents: `make verify` (unit tests, then the affected Kane tests).

## Map

| Part | Code |
|---|---|
| Conversation engine | `app/engine.py` |
| Scam detection (rules, then the model) | `app/rules.py`, `app/detect.py` |
| Meena, her guard, the model calls | `app/meena.py`, `app/brain.py` |
| Identifier extraction | `app/intel.py` |
| Kane investigator, safety guard, evidence | `app/investigate/` |
| Practice scam lab | `app/lab/` |
| Channels: console, Telegram, Check a message | `app/console.py`, `app/telegram.py`, `app/check.py` |
| Store, live events, cases, evidence pack | `app/store.py`, `app/bus.py`, `app/cases.py`, `app/evidence_pack.py` |
| Dashboard (React), built into `app/web/dist` | `dashboard/` |

## Rules

- `make test` must pass. A new dashboard feature gets a Kane test in `kane/tests/` with `covers` globs for its files.
- Every new server event type goes into `EVENT_TYPES` in `app/models.py` and `dashboard/src/lib/live.ts`.
- Save a change before emitting the event that announces it.
- The investigator objective (`app/investigate/__init__.py`) is tuned on real Kane runs: after changing it, run
  `make lab-check` (all five practice sites) and record the score in `docs/kane-log.md`. A fix for one site must not
  break another.
- Practice-lab brands and payees stay fictional. Real links are opened only with `LIVE_INVESTIGATION=1`, and Kane never
  pays, types a PIN, card, CVV or OTP, or downloads anything.
- Only real Kane runs go in `docs/kane-log.md` and `kane/results/`; never the test stand-in.
- No em dashes or emojis in code, docs or commit messages (`tests/test_style.py`).
