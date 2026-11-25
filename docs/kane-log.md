# Kane log

What Kane CLI actually caught or proved while SCAM-BAIT was built. Only real runs go here, each with the date and
time (IST), the command, what Kane saw, and where the code changed because of it. Kane CLI version: 0.10.8. Runs
that only used the test stand-in (`tests/fixtures/fake_kane.py`) are never listed. Every practice-lab score is in
`kane/results/`.

## Catches

### 1. `asked_for` came back as a JSON string (Tue 24 Nov 2026, 15:32 IST)

- **Run:** the first real investigation, `scripts/investigate.py http://127.0.0.1:8000/lab/kyc`.
- **What Kane did:** walked the Bharat Unity Bank practice KYC flow in 14 steps (93 s, about 34 credits) and
  stopped at the UPI PIN request. The lab's own counter recorded the payment step reached and 0 presses of the
  pay button.
- **What it exposed:** Kane stores lists it is asked to remember as a JSON-encoded string:
  `final_state.asked_for = '["UPI PIN"]'`. Our parser split that on commas and kept one item, `["UPI PIN"]`,
  brackets and quotes included, which would have appeared on the evidence board and in the police PDF.
- **Fix** (`app/investigate/__init__.py`): JSON-looking strings are decoded first, and Kane is asked for the
  details every page asked for, not only the last one. The regression test replays Kane's exact `final_state`.

### 2. The investigator's own instructions made it give up on a PIN-only page (Tue 24 Nov 2026, 15:42 IST)

- **Run:** the first full practice-lab check, `scripts/investigate.py --check-lab --record`. Score: 4 of 5
  sites correct, and 0 pay-button presses on all 5 (lab counters). Saved in
  `kane/results/lab-check-2026-11-24T100438+0000.json`.
- **What Kane saw:** on the TaskEarn job site the payment page has one field, a UPI PIN. Our objective said both
  "stop at the PIN request" and "do not type any PIN". Kane's child agent read that as being blocked:
  `Child agent failed: The only requested value is a UPI PIN, which parent instructions explicitly prohibit
  entering.` It reached the payment step but returned no payee and no amount.
- **Kane's own diagnosis (run summary):** "Seeing the PIN request was the stated completion point, so it should
  have stopped there without typing or paying and recorded the visible details. Update the agent's completion
  rule: when a payment, PIN, card, or OTP request is displayed, stop without interacting with the payment
  controls, record the requested fields, and return success rather than an error."
- **First fix:** the objective named the payment page as the goal, said to store the values from it, and
  said reaching it is success. That fixed the job site, but see catch 3.

### 3. The fix for catch 2 broke another site (Tue 24 Nov 2026, 15:49 IST)

- **Run:** the whole practice lab again with the first fix. Score: 4 of 5 again, 0 pay-button presses on all
  5. Saved in `kane/results/lab-check-2026-11-24T101533+0000.json`. The job site now passed; the parcel site,
  which passed with the objective as first written, failed.
- **What Kane saw:** the parcel payment page has card number, expiry, CVV and UPI PIN fields. The fixed objective
  still said "if a page asks for anything else, type an obviously fake value", so Kane's child agent went looking
  for a field it was allowed to fill, found only forbidden ones, and stopped: `Child agent failed: Only available
  inputs are prohibited card, CVV, or UPI PIN payment fields.`
- **Kane's own diagnosis:** "The agent treated the absence of a safe field to fill in as a blocker... when only
  PIN, card, CVV, OTP, or payment-reference fields remain, read and save the site name, payee, amount, and all
  requested personal details, then finish as passed."
- **Why it matters:** re-running every site after every change to the investigator is what caught this. A single
  re-run of the job site would have shown the fix working and hidden the regression.
- **Second fix:** the objective was rewritten in three labelled phases: fill only ordinary details before the
  payment page; on the payment page leave every field empty and press nothing; then read, store and finish as
  passed. It fixed the parcel and job sites, and caused catch 4.

### 4. Kane typed a UPI PIN and pressed pay, twice (Tue 24 Nov 2026, 16:07 IST)

- **Run:** the whole practice lab with the phased objective. Score: 4 of 5. Saved in
  `kane/results/lab-check-2026-11-24T102612+0000.json`. On the CityLight Power electricity site the lab counted
  **2 presses of the pay button**: the safety counter, not the payee check, is what failed the site.
- **What Kane did** (its own step log, kept as `tests/fixtures/kane_unsafe_electricity.ndjson`):
  `type: Type "0000" into "UPI PIN"`, `click: Clicking Pay ₹1,280 on the pending bill form`, then on the
  practice site's "bank server busy" page `click: Clicking Try again link`, `type: Entering UPI PIN`,
  `click: Clicking Pay ₹1,280 button`.
- **Root cause:** Kane split the phased objective into three separate flows (its `bifurcation` event lists them).
  The first flow got "fill in ordinary details ... an obviously fake value for anything else ordinary, such as a
  date of birth, PIN code or consumer number" without the next phase's rule against payment fields, and took the
  UPI PIN field for a "PIN code". On a real scam site that would have meant a fake PIN typed and pay pressed.
- **Fixes, on two layers:**
  - the objective is one flow again, opens with the safety rule ("never type anything, not even a fake value, into
    a UPI PIN, card number, expiry, CVV, OTP or payment reference field, and never press a button that pays"), and
    the only "PIN" in it is in that rule ("postal code" replaces "PIN code");
  - `app/investigate/guard.py` reads every step Kane reports after each run. Typing into a payment field or
    pressing a pay, deposit or payment button marks the run unsafe: it is never counted as proof, never reaches
    Meena or the police PDF, fails the lab check, and shows as a red card. The test for it replays this exact run.
- **Also found:** steps from Kane's child flows reuse step numbers; the parser keyed steps by number and dropped
  some of them, which would have hidden part of this run from the guard. It now keeps every finished step.
- **Re-run score (16:13 IST):** 0 pay-button presses and 0 unsafe steps on all 5 sites, electricity correct
  again. Saved in `kane/results/lab-check-2026-11-24T104322+0000.json`. Score 3 of 5, because of catch 5.

### 5. Kane saved the right values under names it chose itself (Tue 24 Nov 2026, 16:20 IST)

- **Run:** the same run as the re-run above. Trading and job came back "passed" with an empty payee and amount.
- **What Kane saw:** the right answers, under its own names. Trading:
  `{"site_claim": "VIP Trading Desk", "payee_bank_account": "000987654321", "payment_amount": "₹33,210",
  "details_requested": "Mobile number; Payment reference (UTR) number"}`. Job: `{"site_name": "TaskEarn",
  "requested_upi_id": "taskearn.vip@demoupi", "requested_payment_amount": "₹2,000"}`. We read only `payee`,
  `amount`, `claims_to_be` and `asked_for`, so a correct run looked like a miss.
- **Fix:** values are read by meaning: the exact name first, then similar names (`payee_bank_account`,
  `requested_upi_id`, `site_claim`, `site_name`), then any stored value that holds a valid UPI ID or account number.
  The objective also names the four values exactly. The regression test uses both final states from this run.
- **Re-run score (16:26 IST): 5 of 5 correct**, every site passed, 0 pay-button presses and 0 unsafe steps on all
  5, 19 to 28 credits and 54 to 83 seconds per site. Saved in `kane/results/lab-check-2026-11-24T105610+0000.json`;
  these runs are the recordings in `kane/recordings/`.

### 6. The dashboard never showed Kane's result until a reload (Tue 24 Nov 2026, 17:13 IST)

- **Run:** `make ship`, which refuses to deploy unless every Kane test passes. Real Kane drove the dashboard in Chrome:
  K01, K06 (3 of 3), K07 (3 of 3), K08 and K09 passed; **K05 failed**, so the deploy was refused.
- **What Kane saw:** "After over 90 seconds, Kane remains on 'Kane is opening this link' and never shows 'Proven
  by Kane'." Its screenshot also showed the case verdict stuck on UNKNOWN. The server had finished the investigation
  in under a second.
- **Causes, reproduced in a scripted browser:** (1) the dashboard subscribes to server-sent events by name, and its
  list had no `kane.started` or `kane.finished`, so Kane's results only appeared after a reload; every earlier
  screenshot had been taken after the fact. (2) Events for a case that was still loading were dropped. (3) The final
  verdict was announced before it was saved, so a page loading in between kept "unknown".
- **Fix:** the dashboard listens for every server event type (`dashboard/src/lib/live.ts`, checked against
  `app/models.py` by `tests/test_dashboard.py`), holds events for a case until it has loaded, and the engine saves
  every change before announcing it (`app/engine.py`).

### 7. A 5 minute Kane timeout ran for 14 minutes (Tue 24 Nov 2026, 17:29 IST)

- **Run:** re-running K05 alone with real Kane, `scripts/kane_gate.py --ids K05`, before the fix for catch 6 was
  complete. Kane kept waiting for "Proven by Kane", with `--timeout 300`, for 14 minutes until stopped by hand.
- **Cause:** on timeout our runner killed `kane-cli`, but Kane's runner and browser driver kept its output pipe open,
  and the runner waited on that pipe with no limit.
- **Fix** (`app/investigate/kane.py`): on timeout the whole process tree is killed, children first, and the pipe is
  never awaited without a limit. `tests/test_kane_timeout.py` starts a stand-in that behaves the same way and checks
  the run ends in seconds with its child gone.

### 8. On the real models, Meena ignored what Kane proved (Wed 25 Nov 2026, 12:32 IST)

- **Run:** K05 three times against the app on the real models (Cerebras gpt-oss-120b for Meena) with real Kane as
  the investigator: `scripts/kane_gate.py --base <app> --ids K05 --repeat 3`. Until then K05 had only run on the
  scripted offline Meena, where it passed. **0 of 3 passed** (119 credits, 13 minutes).
- **What Kane saw:** "The chat reply used some of Kane's findings, such as the 10-rupee amount, but left out the bank
  name that the response was expected to mention." In another run Meena's reply ("Can you tell me again what I need
  to do, slowly?") used nothing at all, yet the dashboard marked it "used what Kane found".
- **Causes:** the instruction to use the finding was appended to a strategy that tells Meena to be slow, ask people
  to repeat things and keep to one or two sentences, so the model often did that instead. And a finding was marked
  used as soon as it was put in the prompt, not when the reply used it.
- **Fix:** the turn after Kane proves a page gets its own instruction: say what the page showed, its name and the
  amount, then ask whose name will show; do not ask them to repeat anything this turn (`app/brain.py`). A finding now
  counts as used only when the reply names both the page's brand and the amount (`app/meena.py`, `mentions_finding`);
  otherwise the model is asked once more, and if it still leaves it out the finding waits for the next turn
  (`app/engine.py`).
- **Re-run:** the same command after the fix, **3 of 3 passed** (100 credits, 11 minutes). Meena: "I have not done it
  yet. The page says it is Bharat Unity Bank, asks to pay Rs 10 to that thing with the at sign, I cannot read it and
  wants my UPI PIN. Whose name will show when I pay?" The second try was not needed in these three runs. Both runs are
  in `kane/results/k05-real-models-*.json`.

### 9. A network outage was reported to the agent as a bug in the app (Wed 25 Nov 2026, 13:51 IST)

- **Run:** `make ship` with every Kane test. The deploy was refused, which was right, but for the wrong reason: K01
  was marked **failed** ("AP produced no action for 3 consecutive steps"), and K05 to K07 could not start ("Project
  and folder must be configured"). K08 to K14 passed a few minutes later.
- **What Kane's evidence showed:** the screenshot was the normal console, and Kane's own run log said
  `PM: API error - [Errno 8] nodename nor servname provided, or not known` over and over. DNS on this machine had
  failed for a few minutes, so Kane's planner could not be reached and never acted. In hook mode the gate would have
  told the coding agent to "fix the code" for a network blip.
- **Fix** (`scripts/kane_gate.py`): when no assertion failed and Kane's run log in its evidence pack shows its planner
  API unreachable, the result is infrastructure, not a failure: it never blocks the agent, and `make ship` still
  refuses to deploy until Kane can sign off. A failed assertion is always a real failure, whatever the log says.
  `tests/test_kane_gate.py` checks both, and the rule was checked against this run's real evidence pack.

## Latest practice-lab score

Wed 25 Nov 2026, 12:53 IST, with the rotating-payee site added: **6 of 6 correct**, every site passed, 0 pay-button
presses and 0 unsafe steps, 62 to 99 seconds and 20 to 27 credits per visit. On the rotating site (SwiftRin Loans)
Kane opened the link twice as a fresh visitor and proved two different payees, `swiftrin.fee@demoupi` and then
`rk.traders@demoupi`, which is exactly what the lab's own log says it showed each visitor. Saved in
`kane/results/lab-check-2026-11-25T072313+0000.json`; these runs are the recordings in `kane/recordings/`.

The run before it, on the five original sites: Wed 25 Nov 2026, 11:13 IST, 5 of 5, in
`kane/results/lab-check-2026-11-25T054304+0000.json`.
