# lup: ignore
"""Behavior tests for the auto_allow_edits permission hook.

Fixture strings here are deliberately made of anti-patterns (that is
what the hook detects), so the file opts out of the scan wholesale.
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
    new = "result: Any = f()  # lup: ignore\n"
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
    new = "x = 1\ny = cast(int, raw)  # lup: ignore\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "ask"


def test_typed_inline_marker_covering_rule_asks() -> None:
    new = "result: Any = f()  # lup: ignore[any-type]\n"
    assert edit_decision("src/module.py", "", new) == "ask"


def test_typed_inline_marker_naming_another_rule_denies() -> None:
    # Names dict-get, but the line trips any-type — the directive does not
    # cover it, so it still denies.
    new = "result: Any = f()  # lup: ignore[dict-get]\n"
    assert edit_decision("src/module.py", "", new) == "deny"


def test_deny_reason_hints_the_typed_ignore_for_the_rule() -> None:
    result = hook.decide(
        hook.EditInput(
            file_path="src/module.py", old_string="", new_string="y = cast(int, raw)\n"
        )
    )
    assert result is not None
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert "# lup: ignore[cast]" in reason


def test_file_level_typed_ignore_disables_only_that_rule(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("# lup: ignore[string-split]\nx = 1\n", encoding="utf-8")
    split_line = "x = 1\ny = raw.split(',')\n"
    assert edit_decision(str(target), "x = 1\n", split_line) == "allow"
    any_line = "x = 1\nz: Any = f()\n"
    assert edit_decision(str(target), "x = 1\n", any_line) == "deny"


def test_every_dict_get_is_denied() -> None:
    new = "x = 1\nname = payload.get('name')\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "deny"


def test_dict_get_with_typed_ignore_asks() -> None:
    new = "x = 1\nname = registry.get(key)  # lup: ignore[dict-get]\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "ask"


def test_declared_frozenset_is_denied() -> None:
    new = "TOKENS: frozenset[str] = frozenset({'a'})\n"
    assert edit_decision("src/module.py", "", new) == "deny"


def test_os_file_op_and_environ_are_denied() -> None:
    assert edit_decision("src/module.py", "", "entries = os.listdir(p)\n") == "deny"
    assert edit_decision("src/module.py", "", "home = os.environ['HOME']\n") == "deny"
    assert edit_decision("src/module.py", "", "port = os.getenv('PORT')\n") == "deny"


def test_os_exec_is_denied_as_shell() -> None:
    assert edit_decision("src/module.py", "", "os.execv(path, argv)\n") == "deny"


def test_empty_collection_literal_is_denied() -> None:
    assert edit_decision("src/module.py", "", "cache = {}\n") == "deny"
    assert edit_decision("src/module.py", "", "items = []\n") == "deny"


def test_bare_set_annotation_is_denied() -> None:
    assert edit_decision("src/module.py", "", "seen: set[str]\n") == "deny"


def test_concrete_valued_dict_is_allowed() -> None:
    # The relaxed dict rule permits concrete class value types (a registry);
    # dropping the `= {}` keeps the case focused on the annotation, not the
    # empty-collection literal.
    new = "engines: dict[str, Engine]\n"
    assert edit_decision("src/module.py", "", new) == "allow"


def test_ts_anti_pattern_is_denied() -> None:
    assert edit_decision("src/app.ts", "", "const v = data as any\n") == "deny"


def test_file_level_marker_skips_anti_patterns_only(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("# lup: ignore\nx = 1\n", encoding="utf-8")

    with_pattern = "x = 1\ndata = raw.split(',')\n"
    assert edit_decision(str(target), "x = 1\n", with_pattern) == "allow"

    big_clean = "x = 1\n" + "".join(f"value{i} = compute{i}()\n" for i in range(6))
    assert edit_decision(str(target), "x = 1\n", big_clean) is None


def test_introducing_a_marker_asks() -> None:
    new = "x = 1  # lup: ignore\n"
    assert edit_decision("src/module.py", "x = 1\n", new) == "ask"


def test_editing_near_an_existing_marker_does_not_ask() -> None:
    old = "x = 1  # lup: ignore\ny = 2\n"
    new = "x = 1  # lup: ignore\ny = 3\n"
    assert edit_decision("src/module.py", old, new) == "allow"


def test_single_line_replace_all_is_allowed() -> None:
    assert (
        edit_decision("src/module.py", "old_name", "new_name", replace_all=True)
        == "allow"
    )


def test_dotted_attribute_replace_all_is_allowed() -> None:
    assert (
        edit_decision("src/module.py", "mod.Old", "mod.New", replace_all=True)
        == "allow"
    )


def test_is_identifier_rename_accepts_only_symbol_paths() -> None:
    assert hook.is_identifier_rename("old_name", "new_name")
    assert hook.is_identifier_rename("mod.Old", "mod.New")
    # An expression is not a symbol rename; it must not ride the fast path.
    assert not hook.is_identifier_rename("a = 1 + 2", "a = 3 + 4")
    # Multi-line replace_all rewrites logic; never a rename.
    assert not hook.is_identifier_rename("foo\nbar", "baz\nqux")
    assert not hook.is_identifier_rename("", "name")


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


def test_strip_call_is_denied() -> None:
    assert (
        edit_decision("src/module.py", "x = 1\n", "x = 1\ny = raw.strip()\n") == "deny"
    )


def test_string_keyed_dict_annotation_is_denied() -> None:
    assert edit_decision("src/module.py", "", "env: dict[str, str] = {}\n") == "deny"


def test_bare_object_annotation_is_denied() -> None:
    new = "def probe(value: object) -> None:\n    return None\n"
    assert edit_decision("src/module.py", "", new) == "deny"


def test_bare_basemodel_param_is_denied() -> None:
    new = "def show(result: BaseModel) -> None:\n    return None\n"
    assert edit_decision("src/module.py", "", new) == "deny"


def test_basemodel_generic_bound_is_allowed() -> None:
    new = "def read[T: BaseModel](model: type[T]) -> T | None:\n    return None\n"
    assert edit_decision("src/module.py", "", new) == "allow"


def test_typing_modernization_is_denied() -> None:
    assert edit_decision("src/module.py", "", "x: Optional[int] = None\n") == "deny"
    assert edit_decision("src/module.py", "", "items: List[str] = []\n") == "deny"


def test_os_path_and_eval_are_denied() -> None:
    assert edit_decision("src/module.py", "", "base = os.path.dirname(p)\n") == "deny"
    assert edit_decision("src/module.py", "", "value = eval(expr)\n") == "deny"


def test_literal_eval_is_allowed() -> None:
    new = "value = ast.literal_eval(expr)\n"
    assert edit_decision("src/module.py", "", new) == "allow"


def test_global_statement_is_denied() -> None:
    new = "def bump() -> None:\n    global counter\n"
    assert edit_decision("src/module.py", "", new) == "deny"


def test_utcnow_is_denied() -> None:
    assert edit_decision("src/module.py", "", "now = datetime.utcnow()\n") == "deny"


def test_new_ts_rules_are_denied() -> None:
    assert edit_decision("src/app.ts", "", "const n = user!.name;\n") == "deny"
    assert edit_decision("src/app.ts", "", "var total = 0;\n") == "deny"
    assert edit_decision("src/app.ts", "", "let cb: Function;\n") == "deny"
    assert edit_decision("src/app.ts", "", "console.log('x');\n") == "deny"


def test_strict_equality_ts_line_is_allowed() -> None:
    assert edit_decision("src/app.ts", "", "const ok = a !== b;\n") == "allow"


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
