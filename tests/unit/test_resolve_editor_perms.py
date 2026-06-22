# lup: ignore
"""Resolve-editor autonomy in the edit permission hook.

The /lup:resolve editor (agent_type ``lup:resolve-editor``) writes unattended on
a disposable, reviewed worktree branch: in the edit hook every verdict that would
prompt collapses to an auto-allow, while two guardrails stay — ``Edit(tmp/…)`` and
any ``# lup:`` marker-count change still prompt, and anti-pattern violations
still deny. The main session is never affected. The bash hook grants the editor
no special access: it relies on the standard allowlist plus the allowlisted
``lup-devtools`` commands (branch setup goes through ``dev resolve-branch``).

Fixtures here deliberately embed anti-pattern tokens and ``# lup:`` markers as
test data; the file-level ignore above keeps the edit hook off this file's own
fixtures.
"""

import importlib.util
from pathlib import Path

SCRIPTS = (
    Path(__file__).parents[2] / ".claude" / "plugins" / "lup" / "hooks" / "scripts"
)

edits_spec = importlib.util.spec_from_file_location(
    "auto_allow_edits", SCRIPTS / "auto_allow_edits.py"
)
assert edits_spec is not None and edits_spec.loader is not None
edits_hook = importlib.util.module_from_spec(edits_spec)
edits_spec.loader.exec_module(edits_hook)

EDITOR = "lup:resolve-editor"


def edit_dec(
    file_path: str,
    old: str,
    new: str,
    agent_type: str = "",
    replace_all: bool = False,
) -> str | None:
    result = edits_hook.decide(
        edits_hook.EditInput(
            file_path=file_path,
            old_string=old,
            new_string=new,
            replace_all=replace_all,
        ),
        agent_type,
    )
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


def write_dec(file_path: str, content: str, agent_type: str = "") -> str | None:
    result = edits_hook.decide_write(
        edits_hook.WriteInput(file_path=file_path, content=content), agent_type
    )
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


# --- edits hook: the editor writes autonomously where the main session prompts ---


def test_editor_large_edit_allows_where_main_session_prompts() -> None:
    old = "a = 1\n"
    new = "a = 1\n" + "".join(f"value{i} = compute{i}()\n" for i in range(8))
    assert edit_dec("src/module.py", old, new) is None
    assert edit_dec("src/module.py", old, new, EDITOR) == "allow"


def test_editor_write_allows_where_main_session_prompts() -> None:
    assert write_dec("src/new_module.py", "x = 1\n") is None
    assert write_dec("src/new_module.py", "x = 1\n", EDITOR) == "allow"


def test_editor_protected_file_allows() -> None:
    assert edit_dec(".claude/settings.json", "a", "b") == "ask"
    assert edit_dec(".claude/settings.json", "a", "b", EDITOR) == "allow"


# --- edits hook: guardrails kept even for the editor ---


def test_editor_tmp_writes_still_prompt() -> None:
    assert edit_dec("tmp/scratch.py", "x = 1\n", "x = 2\n", EDITOR) == "ask"
    assert write_dec("tmp/scratch.py", "x = 1\n", EDITOR) == "ask"
    assert edit_dec("/home/u/proj/tmp/x.py", "", "y = 1\n", EDITOR) == "ask"


def test_editor_marker_count_change_still_prompts() -> None:
    new = "x = 1  # lup: ignore\n"
    assert edit_dec("src/module.py", "x = 1\n", new, EDITOR) == "ask"


def test_editor_anti_patterns_still_deny() -> None:
    assert edit_dec("src/module.py", "", "from typing import Any\n", EDITOR) == "deny"
    assert write_dec("src/module.py", "import dataclasses\n", EDITOR) == "deny"
