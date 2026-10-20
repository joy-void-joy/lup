# Running the project's tools

**The runner.** The project's tools run in its environment through its runner, so spell a command as the project runs it: `{{ run("pytest") }}`, `{{ run("python tmp/probe.py") }}`. Adding a dependency changes the manifest and the lockfile, which are protected, so it waits for the operator.

**The gate** is `{{ run("lup-dev check") }}`. Its steps are `rules` (lup's code rules, ruff and pyright together, each finding kept only through a `# lup: ignore`), `format`, `pytest` and `lint-imports` (the import contracts), then whatever the project's modules add. Work is finished when it passes, judged by its exit code. It runs every step even after one fails, and reports each failure in full. Before its steps, it checks the tools the project's modules need from outside its environment, and names any missing with how to install it.
- ruff's and pyright's findings never hold a write, but the gate fails on them, so clean them as you go.
- A finding ruff fixes safely isn't reported to you: `{{ run("lup-dev check --fix") }}` applies those fixes and the formatter, then runs the gate.
- A pass is recorded for the files it passed on, so running the gate again on them, or pushing them, runs nothing; `--again` runs it anyway.

**Tests stub every agent and network call:** tests that reached real ones were slow (20 minutes a test in one project) and flaky. They don't depend on the real clock or on timing: a test that fails and then passes is a failure to fix.
