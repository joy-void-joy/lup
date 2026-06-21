"""Behavior tests for the auto_allow_edits permission hook.

Loads the hook script by path (it lives outside the package tree) and
exercises decide() / decide_write() — the pure decision cores —
table-driven.
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
    / "auto_allow_edits.py"
)

spec = importlib.util.spec_from_file_location("auto_allow_edits", HOOK_PATH)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def edit_decision(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str | None:
    """Return 'allow', 'ask', 'deny', or None (fall through to user prompt)."""
    result = hook.decide(
        hook.EditInput(
            file_path=file_path,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
    )
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


def test_small_edit_is_allowed() -> None:
    old = "a = 1\n"
    new = "a = 1\nb = compute()\n"
    assert edit_decision("src/module.py", old, new) == "allow"


def test_large_edit_falls_through() -> None:
    old = "a = 1\n"
    new = "a = 1\n" + "".join(f"value{i} = compute{i}()\n" for i in range(6))
    assert edit_decision("src/module.py", old, new) is None


def test_pure_deletion_is_allowed() -> None:
    assert edit_decision("src/module.py", "x = 1\ny = 2\n", "") == "allow"


def test_protected_files_ask() -> None:
    assert edit_decision(".claude/settings.json", "a", "b") == "ask"
    assert edit_decision("pyproject.toml", "a", "b") == "ask"
    assert edit_decision(".env.local", "a", "b") == "ask"


def test_anti_pattern_is_denied() -> None:
    assert edit_decision("src/module.py", "", "from typing import Any\n") == "deny"
    assert (
        edit_decision("src/module.py", "x = 1\n", "x = 1\ndata: Any = load()\n")
        == "deny"
    )


def test_inline_marker_downgrades_to_ask() -> None:
    new = "result: Any = f()  # claude: ignore\n"
    assert edit_decision("src/module.py", "", new) == "ask"


def test_mapping_str_object_is_denied_like_dict() -> None:
    new = "x = 1\ndef f() -> Mapping[str, object]:\n    return {}\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "deny"


def test_bare_dataclasses_import_is_denied() -> None:
    assert edit_decision("src/module.py", "", "import dataclasses\n") == "deny"


def test_tuple_return_shape_is_denied() -> None:
    new = "x = 1\ndef f() -> tuple[str, int]:\n    return ('a', 1)\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "deny"


def test_cast_call_is_denied() -> None:
    new = "x = 1\ny = cast(int, raw)\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "deny"


def test_cast_call_with_inline_marker_asks() -> None:
    new = "x = 1\ny = cast(int, raw)  # claude: ignore\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "ask"


def test_ts_anti_pattern_is_denied() -> None:
    assert edit_decision("src/app.ts", "", "const v = data as any\n") == "deny"


def test_file_level_marker_skips_anti_patterns_only(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("# claude: ignore\nx = 1\n", encoding="utf-8")

    with_pattern = "x = 1\ndata = raw.split(',')\n"
    assert edit_decision(str(target), "x = 1\n", with_pattern) == "allow"

    big_clean = "x = 1\n" + "".join(f"value{i} = compute{i}()\n" for i in range(6))
    assert edit_decision(str(target), "x = 1\n", big_clean) is None


def test_introducing_a_marker_asks() -> None:
    new = "x = 1  # claude: ignore\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "ask"


def test_editing_near_an_existing_marker_does_not_ask() -> None:
    old = "x = 1  # claude: ignore\ny = 2\n"
    new = "x = 1  # claude: ignore\ny = 3\n"
    assert edit_decision("src/module.py", old, new) == "allow"


def test_single_line_replace_all_is_allowed() -> None:
    assert (
        edit_decision("src/module.py", "old_name", "new_name", replace_all=True)
        == "allow"
    )


def test_multi_line_replace_all_uses_size_gate() -> None:
    old = "def f():\n    return 1\n"
    big = "def f():\n" + "".join(f"    step{i} = run{i}()\n" for i in range(6))
    assert edit_decision("src/module.py", old, big, replace_all=True) is None

    small = "def f():\n    return 2\n"
    assert edit_decision("src/module.py", old, small, replace_all=True) == "allow"


def test_open_paren_comment_does_not_hide_additions() -> None:
    new = "x = 1\n# helper (see notes\n" + "".join(
        f"step{i} = run{i}()\n" for i in range(6)
    )
    assert edit_decision("src/module.py", "x = 1\n", new) is None


def test_import_continuations_stay_trivial() -> None:
    old = "from foo import (\n    alpha,\n)\n"
    new = "from foo import (\n    alpha,\n    beta,\n    gamma,\n    delta,\n    epsilon,\n)\n"
    assert edit_decision("src/module.py", old, new) == "allow"


def test_unused_underscore_parameters_are_not_denied() -> None:
    new = (
        "async def gate(\n"
        "    input_data: PreToolUseHookInput,\n"
        "    _tool_use_id: str | None,\n"
        "    _context: HookContext,\n"
        ") -> SyncHookJSONOutput:\n"
        "    return decision\n"
    )
    assert edit_decision("src/module.py", "", new) == "allow"


def test_underscore_module_assignments_are_still_denied() -> None:
    assert edit_decision("src/module.py", "", "_cache = {}\n") == "deny"
    assert edit_decision("src/module.py", "", "_LIMIT: int = 5\n") == "deny"


def write_decision(file_path: str, content: str) -> str | None:
    """Return 'ask' or None (fall through to user prompt)."""
    result = hook.decide_write(hook.WriteInput(file_path=file_path, content=content))
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


def test_write_to_protected_file_asks() -> None:
    assert write_decision(".claude/settings.json", "{}") == "ask"
    assert write_decision("pyproject.toml", "") == "ask"
    assert write_decision(".env", "SECRET=1") == "ask"
    assert write_decision("sub/dir/.env.local", "SECRET=1") == "ask"


def test_ordinary_write_falls_through() -> None:
    assert write_decision("src/new_module.py", "x = 1\n") is None
    assert write_decision("notes/scratch.md", "hello") is None


def test_tmp_paths_always_ask() -> None:
    # A small edit that would normally auto-allow instead asks under tmp/.
    assert edit_decision("tmp/scratch.py", "x = 1\n", "x = 2\n") == "ask"
    # A large edit that would normally fall through also asks under tmp/.
    big = "x = 1\n" + "".join(f"value{i} = compute{i}()\n" for i in range(6))
    assert edit_decision("tmp/scratch.py", "x = 1\n", big) == "ask"
    # Write under tmp/ asks too.
    assert write_decision("tmp/scratch.py", "x = 1\n") == "ask"
    # Absolute paths with a tmp/ segment are gated as well.
    assert edit_decision("/home/u/proj/tmp/x.py", "", "y = 1\n") == "ask"


def test_system_tmp_is_not_gated() -> None:
    # The system temp dir (pytest fixtures) is not the repo's ./tmp/.
    assert edit_decision("/tmp/pytest-of-u/module.py", "a = 1\n", "a = 2\n") == "allow"
    assert write_decision("/tmp/pytest-of-u/module.py", "a = 1\n") is None
