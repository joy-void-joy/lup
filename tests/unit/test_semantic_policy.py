"""Cross-native semantic decoding and conservative policy parity tests."""

import importlib.util
from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

from lup.adapters.claude.native import (
    ClaudeBeforeToolEvent,
    ClaudeEditBatchOperation,
    ClaudeEventDecoder,
    ClaudeUnknownOperation,
    ClaudeDecisionRenderer,
)
from lup.adapters.codex.native import (
    CodexBeforeToolEvent,
    CodexEventDecoder,
    CodexFileChange,
    CodexFileChangeOperation,
    CodexUnknownOperation,
    CodexDecisionRenderer,
)
from lup.policy.chain import UnknownToolPolicy
from lup.policy.bundle import BUNDLED_POLICY_SOURCE
from lup.policy.models import (
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    ShellCommand,
    UnknownTool,
)
from lup.policy.rules import EditPolicy, FetchPolicy, PathRule, ShellPolicy, UrlScope


def test_equivalent_multi_file_native_edits_decode_identically() -> None:
    changes = [
        EditChange(path=Path("a.py"), before="old", after="new"),
        EditChange(path=Path("b.py"), before="left", after="right"),
    ]
    claude = ClaudeEventDecoder().decode(
        ClaudeBeforeToolEvent(operation=ClaudeEditBatchOperation(changes=changes))
    )
    codex = CodexEventDecoder().decode(
        CodexBeforeToolEvent(
            operation=CodexFileChangeOperation(
                changes=[
                    CodexFileChange(
                        path=change.path,
                        before=change.before,
                        after=change.after,
                    )
                    for change in changes
                ]
            )
        )
    )

    assert claude.tool == codex.tool == EditBatch(changes=changes)


def test_unknown_tools_remain_auditable_and_ask() -> None:
    claude = ClaudeEventDecoder().decode(
        ClaudeBeforeToolEvent(operation=ClaudeUnknownOperation(name="Novel", input={}))
    )
    codex = CodexEventDecoder().decode(
        CodexBeforeToolEvent(operation=CodexUnknownOperation(name="Novel", input={}))
    )

    assert isinstance(claude.tool, UnknownTool)
    assert isinstance(codex.tool, UnknownTool)
    assert UnknownToolPolicy().decide(claude.tool).effect == "ask"
    assert UnknownToolPolicy().decide(codex.tool).effect == "ask"


def test_malformed_native_fetch_urls_become_conservative_unknown_tools() -> None:
    from lup.adapters.claude.native import ClaudeFetchOperation
    from lup.adapters.codex.native import CodexFetchOperation

    claude = ClaudeEventDecoder().decode(
        ClaudeBeforeToolEvent(operation=ClaudeFetchOperation(url="not a url"))
    )
    codex = CodexEventDecoder().decode(
        CodexBeforeToolEvent(operation=CodexFetchOperation(url="not a url"))
    )

    assert isinstance(claude.tool, UnknownTool)
    assert isinstance(codex.tool, UnknownTool)


def test_native_decision_renderers_preserve_or_fail_closed_on_ask() -> None:
    decision = Decision(effect="ask", reason="approval required")

    claude = ClaudeDecisionRenderer().render(decision)
    codex = CodexDecisionRenderer(supports_ask=False).render(decision)

    assert claude.permission_decision == "ask"
    assert codex.exit_code == 2
    assert codex.approximation == "ask rendered as fail-closed denial"
    with pytest.raises(ValueError, match="not been evidenced"):
        CodexDecisionRenderer(supports_ask=True)


def test_fetch_policy_normalizes_origin_and_rejects_lookalikes() -> None:
    policy = FetchPolicy(
        allowed=[
            UrlScope.model_validate(
                {"origin": "https://docs.example.com", "path_prefix": "/reference/"}
            )
        ],
        denied=[],
    )

    assert (
        policy.decide(
            FetchUrl(url=AnyHttpUrl("https://docs.example.com/reference/api?q=1"))
        ).effect
        == "allow"
    )
    assert (
        policy.decide(
            FetchUrl(url=AnyHttpUrl("https://docs.example.com.evil.test/reference/api"))
        ).effect
        == "ask"
    )


def test_bundled_fetch_matches_canonical_scheme_port_and_path(tmp_path: Path) -> None:
    path = tmp_path / "bundled_fetch_policy.py"
    path.write_text(BUNDLED_POLICY_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_fetch_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    scope = UrlScope.model_validate(
        {"origin": "https://docs.example.com:8443", "path_prefix": "/reference/"}
    )
    policy = FetchPolicy(allowed=[scope], denied=[])
    wire_scope = [{"origin": str(scope.origin), "path_prefix": scope.path_prefix}]
    cases = {
        "https://docs.example.com:8443/reference/api": "allow",
        "http://docs.example.com:8443/reference/api": "ask",
        "https://docs.example.com/reference/api": "ask",
        "https://docs.example.com:8443/private": "ask",
    }

    for url, expected in cases.items():
        canonical = policy.decide(FetchUrl(url=AnyHttpUrl(url)))
        generated = bundled.decide_fetch(url, wire_scope, [])
        assert canonical.effect == generated.effect == expected


def test_shell_policy_checks_every_segment_and_deny_wins() -> None:
    policy = ShellPolicy()

    assert policy.decide(
        ShellCommand(command="git status && uv run pytest")
    ).effect == ("allow")
    assert (
        policy.decide(
            ShellCommand(command="uv add package && python -c 'print(1)'")
        ).effect
        == "deny"
    )
    assert policy.decide(ShellCommand(command="echo $(dangerous)")).effect == "ask"


def test_shell_policy_preserves_golden_compound_and_wrapper_outcomes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bundled_policy.py"
    path.write_text(BUNDLED_POLICY_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    policy = ShellPolicy()
    cases = {
        "env MODE=test python script.py": "deny",
        "uv run --with requests python -c 'x'": "deny",
        "uv run pytest | uv run python tmp/oneoff.py": "allow",
        "find . -name '*.py' | xargs grep TODO": "allow",
        "echo x | xargs rm -rf": "ask",
        "cd /tmp/worktree && uv run pytest": "allow",
        "git status\ncurl https://example.com": "ask",
        "find . -name '*.tmp' -delete": "ask",
        "cat x |& rm -rf ~": "ask",
        "cat x ;& rm -rf ~": "ask",
        "echo payload > pyproject.toml": "ask",
        "echo payload >> src/generated.py": "ask",
        "gh pr view 123": "allow",
        "uv run tool --help": "allow",
    }

    for command, expected in cases.items():
        assert policy.decide(ShellCommand(command=command)).effect == expected
        assert bundled.decide_shell(command).effect == expected


def test_edit_policy_checks_every_file_before_allowing_batch() -> None:
    policy = EditPolicy(
        protected=[
            PathRule(
                kind="exact",
                value="pyproject.toml",
                reason="project configuration is protected",
            )
        ]
    )
    batch = EditBatch(
        changes=[
            EditChange(path=Path("safe.py"), before="x = 1", after="x = 2"),
            EditChange(
                path=Path("unsafe.py"),
                before="value: str",
                after="value: Any",  # lup: ignore[any-type] — adversarial policy fixture
            ),
        ]
    )

    assert policy.decide(batch).effect == "deny"
    protected = EditBatch(
        changes=[EditChange(path=Path("pyproject.toml"), after="version = '2'")]
    )
    assert policy.decide(protected).effect == "ask"


def test_edit_policy_never_auto_allows_a_full_file_write() -> None:
    policy = EditPolicy(protected=[])

    decision = policy.decide(
        EditBatch(changes=[EditChange(path=Path("src/new.py"), after="value = 1")])
    )

    assert decision.effect == "ask"


def test_bundled_edit_policy_matches_canonical_security_outcomes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bundled_policy.py"
    path.write_text(BUNDLED_POLICY_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_edit_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    policy = EditPolicy(
        protected=[
            PathRule(
                kind="subtree",
                value=".claude",
                reason="protected path requires approval",
                allow_autonomous=True,
            ),
            PathRule(
                kind="subtree",
                value="tmp",
                reason="scratch path requires approval",
            ),
        ]
    )
    cases = [
        (
            "src/module.py",
            "value = 1",
            "value: Any = 1",  # lup: ignore[any-type]
            "deny",
        ),
        (
            "src/module.py",
            "value = 1",
            "value = 1  # type: ignore",  # lup: ignore[type-ignore]
            "deny",
        ),
        (
            "src/module.py",
            "value = 1",
            "value: dict[str, object] = {}",  # lup: ignore[dict-str-object, empty-collection]
            "deny",
        ),
        ("src/module.py", "value = 1", "value = 2", "allow"),
        (".claude/settings.json", "{}", '{"ok": true}', "ask"),
        ("src/module.py", "value = 1", "value = 1  # lup" + ": revisit", "ask"),
    ]

    for file_path, before, after, expected in cases:
        canonical = policy.decide(
            EditBatch(
                changes=[EditChange(path=Path(file_path), before=before, after=after)]
            )
        )
        generated = bundled.decide_edit(
            file_path,
            before,
            after,
            [".claude", "tmp", "pyproject.toml"],
        )
        assert canonical.effect == generated.effect == expected


def test_bundled_resolve_editor_keeps_guardrails(tmp_path: Path) -> None:
    path = tmp_path / "bundled_editor_policy.py"
    path.write_text(BUNDLED_POLICY_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_editor_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)

    assert bundled.decide_edit(
        ".claude/settings.json", "a", "b", [".claude", "tmp"], "lup:resolve-editor"
    ).effect == ("allow")
    assert bundled.decide_edit(
        "src/module.py",
        "x = 1",
        "from typing import Any",  # lup: ignore[any-type]
        [".claude", "tmp"],
        "lup:resolve-editor",
    ).effect == ("deny")
    assert bundled.decide_edit(
        "tmp/scratch.py", "x = 1", "x = 2", [".claude", "tmp"], "lup:resolve-editor"
    ).effect == ("ask")
    assert bundled.decide_edit(
        "src/module.py",
        "x = 1",
        "x = 1  # lup" + ": revisit",
        [".claude", "tmp"],
        "lup:resolve-editor",
    ).effect == ("ask")


def test_edit_policy_uses_full_python_context_for_added_docstrings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bundled_docstring_policy.py"
    path.write_text(BUNDLED_POLICY_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_docstring_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    before = '"""Documentation.\n"""\nvalue = 1'
    unrestricted_type_name = "A" + "ny"
    after = (
        f'"""Documentation can mention {unrestricted_type_name} safely.\n"""\nvalue = 1'
    )
    canonical = EditPolicy(protected=[]).decide(
        EditBatch(
            changes=[EditChange(path=Path("src/module.py"), before=before, after=after)]
        )
    )

    assert canonical.effect == "allow"
    assert bundled.decide_edit("src/module.py", before, after, []).effect == "allow"


def test_edit_policy_bundle_embeds_canonical_ast_refinement(tmp_path: Path) -> None:
    path = tmp_path / "bundled_ast_policy.py"
    path.write_text(BUNDLED_POLICY_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_ast_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    before = (
        "class Scheduler:\n    def __init__(self) -> None:\n        self.ready = True\n"
    )
    empty_list_literal = "[]"
    after = before + f"        self.pending: list[str] = {empty_list_literal}\n"
    canonical = EditPolicy(protected=[]).decide(
        EditBatch(
            changes=[
                EditChange(path=Path("src/scheduler.py"), before=before, after=after)
            ]
        )
    )

    assert canonical.effect == "allow"
    assert bundled.decide_edit("src/scheduler.py", before, after, []).effect == "allow"
