"""Boundary scan behavior: what breaches, what is sanctioned, what escapes.

The scan (:mod:`lup.codescan.boundaries`) guards two directions. Inward, it is
the regression guard that keeps per-engine adapter imports from creeping
outside ``lup.adapters``, and the live tree is pinned at zero breaches.
Outward, the placement rule judges whether a library data table reaches its
adopters as an overridable default; the live tree still carries known
violations, so those tests work from fixtures rather than pinning a count.
"""

from pathlib import Path

from lup.codescan.boundaries import (
    audit_boundaries,
    audit_kernel_imports,
    audit_library_defaults,
    audit_path_boundaries,
    default_position_names,
    find_boundary_breaches,
    find_library_default_breaches,
    find_native_spelling_breaches,
    library_placement_path_is_audited,
    native_spelling_path_is_sanctioned,
    path_is_sanctioned,
)

from lup_template.devtools.dev.boundaries import scan_boundaries

BREACHING = "from lup.adapters.claude.runtime import ClaudeSessionFactory\n"


def test_per_engine_imports_breach() -> None:
    text = (
        "import lup.adapters.codex.runtime\n"
        "from lup.adapters.codex.native import CodexEventDecoder\n"
        "from lup.adapters.claude.profile_store import ClaudeProfileStore\n"
        "from lup.adapters.claude.harness import ClaudeSkillRenderer\n"
    )
    breaches = find_boundary_breaches(text)
    assert [breach.line for breach in breaches] == [1, 2, 3, 4]
    assert breaches[0].module == "lup.adapters.codex.runtime"


def test_seam_surface_does_not_breach() -> None:
    text = (
        "from lup.runtime.contracts import SessionFactory\n"
        "from lup.runtime.query import query\n"
        "from lup.harness.contracts import ArtifactRenderer\n"
        "from lup.policy.contracts import NativeEventDecoder\n"
        "from lup.adapters.harness import compile_codex\n"
    )
    assert not find_boundary_breaches(text)


def test_inline_ignore_excepts_the_line() -> None:
    ignored = BREACHING.rstrip() + "  # lup: ignore[seam-boundary]\n"
    assert not find_boundary_breaches(ignored)

    bare = BREACHING.rstrip() + "  # lup: ignore\n"
    assert not find_boundary_breaches(bare)

    other_rule = BREACHING.rstrip() + "  # lup: ignore[cast]\n"
    assert len(find_boundary_breaches(other_rule)) == 1


def test_file_level_ignore_excepts_the_file() -> None:
    typed = "# lup: ignore[seam-boundary]\n" + BREACHING
    assert not find_boundary_breaches(typed)

    bare = "# lup: ignore\n" + BREACHING
    assert not find_boundary_breaches(bare)

    other_rule = "# lup: ignore[cast]\n" + BREACHING
    assert len(find_boundary_breaches(other_rule)) == 1


def test_boundary_suppressions_are_typed_and_audited() -> None:
    bare = BREACHING.rstrip() + "  # lup: ignore\n"
    assert [(item.kind, item.rule_id) for item in audit_boundaries(bare)] == [
        ("untyped", "seam-boundary")
    ]

    spurious = "value = 1  # lup: ignore[seam-boundary]\n"
    assert [(item.kind, item.rule_id) for item in audit_boundaries(spurious)] == [
        ("spurious", "seam-boundary")
    ]


def test_native_wire_spellings_breach_but_semantic_names_do_not() -> None:
    text = (
        'method = "thread" + "/start"\n'
        'config_home = "CODEX_HOME"\n'
        'semantic = "Bash Edit Fetch Search"\n'
    )

    breaches = find_native_spelling_breaches(text)

    assert [(item.line, item.module) for item in breaches] == [
        (1, "thread/start"),
        (2, "CODEX_HOME"),
    ]


def test_native_spelling_suppression_is_audited() -> None:
    text = 'method = "turn/start"  # lup: ignore[native-spelling]\n'
    assert find_native_spelling_breaches(text) == []
    assert audit_boundaries(text) == []

    spurious = 'method = "portable"  # lup: ignore[native-spelling]\n'
    findings = audit_boundaries(spurious)
    assert [(item.kind, item.rule_id) for item in findings] == [
        ("spurious", "native-spelling")
    ]


def test_sanctioned_paths() -> None:
    assert path_is_sanctioned(Path("packages/lup/src/lup/adapters/claude/runtime.py"))
    assert path_is_sanctioned(Path("tests/unit/test_adapter_transforms.py"))
    assert path_is_sanctioned(Path("src/lup_template/agent/core.py"))
    assert not path_is_sanctioned(Path("packages/lup/src/lup/subagents.py"))


def test_portable_content_is_scanned_for_native_spellings() -> None:
    path = Path("src/lup_template/devtools/harness/content/skills/example.py")
    text = (
        "from lup.adapters.claude.runtime import ClaudeSessionFactory\n"
        'method = "turn/start"\n'
    )

    assert path_is_sanctioned(path)
    assert not native_spelling_path_is_sanctioned(path)
    findings = audit_path_boundaries(path, text)
    assert [(item.rule_id, item.line) for item in findings] == [("native-spelling", 2)]


def test_policy_kernel_imports_are_pinned_to_hermetic_stdlib() -> None:
    clean = "import ast\nimport urllib.parse\n"
    breach = "import ast\nfrom pydantic import BaseModel\n"

    assert audit_kernel_imports(clean) == []
    findings = audit_kernel_imports(breach)
    assert [(item.kind, item.module) for item in findings] == [("missing", "pydantic")]


def test_live_tree_has_zero_breaches() -> None:
    assert scan_boundaries() == []


TABLE = 'READ_ONLY_COMMANDS = ("ls", "cat", "grep")\n'
NOTHING_OVERRIDABLE = ()
"""A library where no caller can replace anything."""


def test_a_library_table_no_caller_can_replace_breaches() -> None:
    breaches = find_library_default_breaches(TABLE, NOTHING_OVERRIDABLE)

    assert [(item.line, item.module) for item in breaches] == [
        (1, "READ_ONLY_COMMANDS")
    ]


def test_only_declared_multi_entry_tables_are_judged() -> None:
    text = (
        'PREAMBLE = "one long prompt contract"\n'
        'SINGLETON = ("only",)\n'
        "DERIVED = [name.upper() for name in OTHER]\n"
        "lowercase = (1, 2)\n"
    )

    assert find_library_default_breaches(text, NOTHING_OVERRIDABLE) == []


def test_every_admitted_default_spelling_clears_a_table() -> None:
    reached = {
        "SIGNATURE": "def build(rules: list[str] = SIGNATURE) -> None: ...\n",
        "FIELD": "class Set(BaseModel):\n    rules: list[str] = Field(default=FIELD)\n",
        "FACTORY": (
            "class Set(BaseModel):\n"
            "    rules: list[str] = Field(default_factory=lambda: FACTORY)\n"
        ),
        "SENTINEL": "def build(rules=None):\n    return SENTINEL if rules is None else rules\n",
        "FALLBACK": "def build(rules=None):\n    return rules or FALLBACK\n",
    }

    for name, consumer in reached.items():
        declaration = f'{name} = ("a", "b")\n'
        overridable = default_position_names(consumer)

        assert name in overridable, name
        assert find_library_default_breaches(declaration, overridable) == [], name


def test_a_directive_heading_a_multi_line_table_suppresses_it() -> None:
    heading = "# lup: ignore[library-default] — canonical\n" + TABLE
    assert find_library_default_breaches(heading, NOTHING_OVERRIDABLE) == []

    spread = (
        "# lup: ignore[library-default] — canonical\n"
        "READ_ONLY_COMMANDS = (\n"
        '    "ls",\n'
        '    "cat",\n'
        ")\n"
    )
    assert find_library_default_breaches(spread, NOTHING_OVERRIDABLE) == []
    assert audit_library_defaults(spread, NOTHING_OVERRIDABLE) == []


def test_a_directive_two_lines_above_a_table_stays_spurious() -> None:
    detached = "# lup: ignore[library-default] — canonical\n\n" + TABLE
    findings = audit_library_defaults(detached, NOTHING_OVERRIDABLE)

    assert sorted(item.kind for item in findings) == ["missing", "spurious"]


def test_adapter_packages_are_exempt_from_the_placement_rule() -> None:
    assert library_placement_path_is_audited(
        Path("packages/lup/src/lup/policy/shell_rules.py")
    )
    assert not library_placement_path_is_audited(
        Path("packages/lup/src/lup/adapters/codex/harness.py")
    )
    assert not library_placement_path_is_audited(
        Path("src/lup_template/devtools/harness/catalog.py")
    )
