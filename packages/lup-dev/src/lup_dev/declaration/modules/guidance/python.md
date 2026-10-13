# Running the project's tools

**The runner.** The project's tools run in its environment through its runner, so a command is spelled as the project runs it: `{{ run("pytest") }}`, `{{ run("python tmp/probe.py") }}`. Adding a dependency changes the manifest and the lockfile, which are protected, so it waits for the operator.

**The gate** is `{{ run("lup-dev check") }}`: lup's code rules, ruff, the formatter, pyright, the tests and the import contracts, and whatever the project's modules add. It's judged by its exit code, runs every step even after one fails, and reports each failure in full; work is finished when it passes. Before its steps, it checks the tools the project's modules need from outside its environment, and names any missing with how to install it.
- ruff's and pyright's findings don't refuse a write, but the gate fails on them, so they're cleaned as you go.
- A finding ruff fixes safely isn't reported to you as you write: `{{ run("lup-dev check --fix") }}` applies those fixes and the formatter, then runs the gate.

**Tests stub every agent and network call,** since tests that reached real ones were slow and flaky, and they don't depend on the real clock or on timing: a test that fails and then passes is a failure to fix. They're exempt from lup's code rules, though not from ruff and pyright.
