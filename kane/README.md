# Kane tests

Plain-English end-to-end tests that Kane CLI runs against the dashboard in a real Chrome browser.

Each file has YAML frontmatter and an objective:

- `id`, `title`: shown in reports.
- `path`: where the test starts (appended to the app URL).
- `covers`: file globs. `scripts/kane_gate.py` runs only the tests whose globs match the files you changed.
- `timeout`: seconds Kane may spend.
- `repeat`: run this many times and report a pass rate (for checks on Meena, whose wording varies).

The app under test runs in offline mode (scripted detection and Meena, no model keys) with a recorded
investigator, so every UI test costs one Kane run and gives the same answer every time. How well the real
investigator reads real pages is measured separately against the practice lab:

    .venv/bin/python scripts/investigate.py --check-lab

Run the tests:

    .venv/bin/python scripts/kane_gate.py --all        # every test
    .venv/bin/python scripts/kane_gate.py              # only tests affected by uncommitted changes
    make verify                                        # unit tests, then the affected Kane tests
