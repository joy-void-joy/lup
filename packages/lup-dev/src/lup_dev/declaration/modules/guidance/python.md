# Running the project's tools

**The runner.** The project's tools run in its environment through its runner, so spell a command as the project runs it: `{{ run("pytest") }}`, `{{ run("python tmp/probe.py") }}`.

**The gate** is `{{ run("lup-dev check") }}`: lup's rules with ruff and pyright, the formatter, pytest and the import contracts, then whatever the project's modules add. Work is finished when it passes. It runs every step even after one fails, so one run shows every failure.
- ruff's and pyright's findings never hold a write, but the gate fails on them, so clean them as you go.
- ruff's safe fixes and the formatter aren't reported to you: `{{ run("lup-dev check --fix") }}` applies them, then runs the gate.
- A pass is remembered for the files it passed on, so running the gate again on them, or pushing them, runs nothing; `--again` runs it anyway.

**Tests stub every agent and network call:** tests that reached real ones were slow (20 minutes a test in one project) and flaky. They don't depend on the real clock or on timing either: a test that fails and then passes is a failure to fix.
