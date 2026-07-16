"""Seam-boundary scan behavior: what breaches, what is sanctioned, what escapes.

The scan (:mod:`lup.codescan.boundaries`) is the regression guard that keeps
per-engine adapter imports from creeping outside ``lup.adapters``; the final
test pins the live tree at zero breaches.
"""

from pathlib import Path

from lup.codescan.boundaries import (
    audit_boundaries,
    audit_kernel_imports,
    find_boundary_breaches,
    find_native_spelling_breaches,
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


def test_policy_kernel_imports_are_pinned_to_hermetic_stdlib() -> None:
    clean = "import ast\nimport urllib.parse\n"
    breach = "import ast\nfrom pydantic import BaseModel\n"

    assert audit_kernel_imports(clean) == []
    findings = audit_kernel_imports(breach)
    assert [(item.kind, item.module) for item in findings] == [("missing", "pydantic")]


def test_live_tree_has_zero_breaches() -> None:
    assert scan_boundaries() == []
