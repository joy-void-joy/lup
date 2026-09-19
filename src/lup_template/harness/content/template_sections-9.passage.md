---

<!-- section: Tooling -->
# Tooling

## lup-devtools

All development tooling lives in `src/<project>/devtools/` and is exposed as the `lup-devtools` CLI entry point. **Always use `lup-devtools` instead of ad-hoc commands.** Never use `uv run python -c "..."` or bare `python`/`python3` -- these are denied by the Bash permission hook.

If you find yourself running the same command repeatedly, **add a command** to `src/<project>/devtools/`.

`tmp/` is scratch: gitignored, so nothing written there reaches a diff, a reviewer, or the human — which is why it does not execute. For one-off work, in order: run it in the sandbox where the work allows; add a `lup-devtools` command, which is reviewable because `devtools/` lands in the diff; or, as a last resort, `python3 <<<EOF` behind a `# lup: escalate[decision]: <why>` marker. The argument is reviewability, not power — an agent may already edit `devtools/` and run it.

**Write scripts in Python using [typer](https://typer.tiangolo.com/)** for CLI interfaces. Use **[sh](https://sh.readthedocs.io/)** for shell commands instead of `subprocess`.

Run `uv run lup-devtools --help` for the full command tree.

