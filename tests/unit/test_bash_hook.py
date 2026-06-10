"""Behavior tests for the auto_allow_bash permission hook.

Loads the hook script by path (it lives outside the package tree) and
exercises decide() — the pure rule-evaluation core — table-driven.
"""

import importlib.util
from pathlib import Path

HOOK_PATH = (
    Path(__file__).parents[2]
    / ".claude"
    / "plugins"
    / "lup"
    / "hooks"
    / "scripts"
    / "auto_allow_bash.py"
)

spec = importlib.util.spec_from_file_location("auto_allow_bash", HOOK_PATH)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def decision(command: str) -> str | None:
    """Return 'allow', 'deny', or None (fall through to user prompt)."""
    result = hook.decide(command)
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


def test_python_invocations_are_denied() -> None:
    assert decision("python script.py") == "deny"
    assert decision("python3 -c 'print(1)'") == "deny"
    assert decision("/usr/bin/python script.py") == "deny"
    assert decision("uv run python -m lup_template.environment.cli run 'x'") == "deny"
    assert decision("uv run python -c 'import os'") == "deny"


def test_python_after_separator_is_denied() -> None:
    assert decision("ls; python evil.py") == "deny"
    assert decision("git status && python evil.py") == "deny"
    assert decision("echo hi | python -") == "deny"


def test_python_as_argument_text_is_not_denied() -> None:
    assert decision("git commit -m 'add python script'") == "allow"
    assert decision("grep python README.md") == "allow"
    assert decision("ls python_stuff/") == "allow"


def test_tmp_scripts_are_allowed() -> None:
    assert decision("uv run tmp/oneoff.py") == "allow"
    assert decision("uv run python tmp/oneoff.py --flag") == "allow"
    assert decision("uv run ./tmp/oneoff.py") == "allow"


def test_lup_devtools_allow_is_anchored() -> None:
    assert decision("uv run lup-devtools trace list") == "allow"
    assert decision("rm -rf / && uv run lup-devtools version") is None


def test_uv_run_lup_falls_through_to_prompt() -> None:
    assert decision("uv run lup run 'some task'") is None


def test_no_blanket_xargs_allow() -> None:
    assert decision("echo x | xargs rm -rf") is None


def test_find_allowed_only_without_execution() -> None:
    assert decision("find . -name '*.py'") == "allow"
    assert decision("find . -name '*.tmp' -delete") is None
    assert decision("find . -exec rm {} ;") is None


def test_unknown_commands_fall_through() -> None:
    assert decision("curl https://example.com") is None
