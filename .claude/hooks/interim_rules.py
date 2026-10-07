# /// script
# requires-python = ">=3.14"
# dependencies = ["pydantic>=2.12", "sh>=2"]
# ///
"""Judge a Python file the agent just wrote with the first lup's anti-pattern rules.

An interim check for the bridge, until lup's own rule engine lands
(`docs/after-call-diff.md`); then this file and its hook go. It runs after each
Write or Edit, in the background, and wakes the agent with the findings.

The first lup's checker judges a file outside its repository when told where
the file would sit in it (`--path` with `--as`). Production files are placed
under its application, tests under its test root, so only the rules about how
code is written apply, not the ones about the first lup's own layout.

It expects the first lup's checkout at `lup-legacy.git/tree/dev`, beside this
repository's `lup.git`, and says so when it isn't there.
"""

import sys
from pathlib import Path

import sh
from pydantic import BaseModel


class ToolInput(BaseModel):
    """The part of a Write or Edit call this hook reads."""

    file_path: Path | None = None


class HookPayload(BaseModel):
    """What Claude Code sends a PostToolUse hook on stdin."""

    cwd: Path
    tool_input: ToolInput


class Finding(BaseModel):
    """One finding from the first lup's checker."""

    line: int
    text: str
    message: str
    rule_id: str


class Report(BaseModel):
    """The first lup's checker output with `--json`."""

    findings: list[Finding]


class Settings(BaseModel):
    """What this check assumes about the machine and the first lup."""

    checker_checkout: Path = Path("lup-legacy.git/tree/dev")
    """The first lup's checkout, relative to the directory holding `lup.git`."""
    layout_rules: list[str] = [
        "assembly-boundary",
        "front-door",
        "kernel-imports",
        "native-spelling",
        "portable-content",
        "seam-boundary",
    ]
    """Rules about the first lup's own layout, which say nothing about this repository."""
    python_suffixes: list[str] = [".py", ".pyi"]


def git_dir(path: Path, question: str) -> Path:
    """Ask git where something is for the repository holding `path`."""
    return Path(str(sh.git("-C", path, "rev-parse", "--path-format=absolute", question)).strip())


def placed_path(relative: Path) -> Path:
    """Where the file sits in the first lup, so the rules judge it in the right role."""
    if "tests" in relative.parts:
        return Path("tests/interim") / relative
    return Path("src/lup_template/interim") / relative


def judge(file: Path, checker: Path, settings: Settings) -> list[Finding]:
    """Run the first lup's anti-pattern rules on one file."""
    worktree = git_dir(file.parent, "--show-toplevel")
    output = sh.uv(
        "run",
        "--offline",
        "--project",
        checker,
        "lup-devtools",
        "dev",
        "check",
        "--antipatterns",
        "--json",
        "--path",
        file,
        "--as",
        placed_path(file.relative_to(worktree)),
        _cwd=checker,
        _ok_code=[0, 1],
    )
    findings = Report.model_validate_json(str(output)).findings
    return [finding for finding in findings if finding.rule_id not in settings.layout_rules]


def main(settings: Settings) -> int:
    """Judge the written file and report findings to the agent through exit code 2."""
    payload = HookPayload.model_validate_json(sys.stdin.read())
    file = payload.tool_input.file_path
    if file is None or file.suffix not in settings.python_suffixes or not file.exists():
        return 0
    session_repository = git_dir(payload.cwd, "--git-common-dir")
    if git_dir(file.parent, "--git-common-dir") != session_repository:
        return 0
    checker = session_repository.parent / settings.checker_checkout
    if not checker.exists():
        print(f"interim rules not run: no first-lup checkout at {checker}", file=sys.stderr)
        return 2
    findings = judge(file, checker, settings)
    if not findings:
        return 0
    lines = [f"{file}:{finding.line} - {finding.rule_id}: {finding.message}" for finding in findings]
    print("The first lup's rules found this in your last write:", *lines, sep="\n", file=sys.stderr)
    return 2


sys.exit(main(Settings()))
