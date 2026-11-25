.PHONY: test verify kane-all lab-check check-openai run offline ship

ship:  ## deploy only if unit tests and every Kane test pass (writes the Kane badge, pushes, calls the deploy hook)
	.venv/bin/python scripts/ship.py

test:  ## unit and API tests (no keys, no network)
	.venv/bin/python -m pytest -q

verify: test  ## unit tests, then the Kane tests affected by your changes
	.venv/bin/python scripts/kane_gate.py

kane-all:  ## every Kane test against the dashboard
	.venv/bin/python scripts/kane_gate.py --all

check-openai:  ## Decisions, moderation, the report and a live voice session against the real OpenAI API
	.venv/bin/python scripts/check_openai.py

lab-check:  ## real Kane investigates every practice site; scores and recordings are saved
	.venv/bin/python scripts/investigate.py --check-lab --record

run:  ## the app with your .env keys
	./scripts/run.sh

offline:  ## the app with no model keys (scripted detection and Meena, real Kane)
	OFFLINE_MODE=1 TELEGRAM_AUTO_WEBHOOK=0 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
