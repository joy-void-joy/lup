"""Cross-native semantic decoding and conservative policy parity tests."""

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest
import sh
from pydantic import AnyHttpUrl, BaseModel, ConfigDict

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
from lup.policy.bundle import (
    bundled_antipattern_rows,
    policy_kernel_source,
    render_policy_data,
    runtime_path_rules,
    runtime_url_scope,
)
from lup.policy.kernel import KernelDecision
from lup.policy.models import (
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    ShellCommand,
    UnknownTool,
)
from lup.policy.rules import EditPolicy, FetchPolicy, PathRule, ShellPolicy, UrlScope


class DecisionCase(BaseModel):
    """One primitive input and its expected policy effect."""

    model_config = ConfigDict(frozen=True)

    input: str
    effect: Literal["allow", "ask", "deny"]


class EditDecisionCase(BaseModel):
    """One edit fixture shared by canonical and assembled policy forms."""

    model_config = ConfigDict(frozen=True)

    path: str
    before: str | None
    after: str | None
    effect: Literal["allow", "ask", "deny"]
    autonomous: bool = False
    path_exists: bool = True


SHELL_POLICY_CASES = [
    DecisionCase(input="env MODE=test python script.py", effect="deny"),
    DecisionCase(input="uv run --with requests python -c 'x'", effect="deny"),
    DecisionCase(input="uv run pytest | uv run python tmp/oneoff.py", effect="allow"),
    DecisionCase(input="find . -name '*.py' | xargs grep TODO", effect="allow"),
    DecisionCase(input="echo x | xargs rm -rf", effect="ask"),
    DecisionCase(input="cd /tmp/worktree && uv run pytest", effect="allow"),
    DecisionCase(input="git status\ncurl https://example.com", effect="ask"),
    DecisionCase(input="find . -name '*.tmp' -delete", effect="ask"),
    DecisionCase(input="cat x |& rm -rf ~", effect="ask"),
    DecisionCase(input="cat x ;& rm -rf ~", effect="ask"),
    DecisionCase(input="echo payload > pyproject.toml", effect="ask"),
    DecisionCase(input="echo payload >> src/generated.py", effect="ask"),
    DecisionCase(input="gh pr view 123", effect="allow"),
    DecisionCase(input="uv run tool --help", effect="allow"),
]

FETCH_POLICY_CASES = [
    DecisionCase(input="https://docs.example.com:8443/reference/api", effect="allow"),
    DecisionCase(
        input="https://docs.example.com:8443/reference/private/key", effect="deny"
    ),
    DecisionCase(input="http://docs.example.com:8443/reference/api", effect="ask"),
    DecisionCase(input="https://docs.example.com/reference/api", effect="ask"),
    DecisionCase(input="https://docs.example.com:8443/private", effect="ask"),
]

EDIT_POLICY_CASES = [
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value: Any = 1",
        effect="deny",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1  # type: ignore",
        effect="deny",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value: dict[str, object] = {}",
        effect="deny",
    ),
    EditDecisionCase(
        path="src/module.py", before="value = 1", after="value = 2", effect="allow"
    ),
    EditDecisionCase(
        path=".claude/settings.json", before="{}", after='{"ok": true}', effect="ask"
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1  # lup: revisit",
        effect="ask",
    ),
    EditDecisionCase(
        path=".claude/settings.json",
        before="{}",
        after='{"ok": true}',
        effect="allow",
        autonomous=True,
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="from typing import Any",
        effect="deny",
        autonomous=True,
    ),
    EditDecisionCase(
        path="tmp/scratch.py",
        before="value = 1",
        after="value = 2",
        effect="ask",
        autonomous=True,
    ),
    EditDecisionCase(
        path="README.md",
        before="# Lup\n",
        after="# Lup\n\nAn agent-added paragraph.\n",
        effect="ask",
    ),
    EditDecisionCase(
        path="README.md",
        before="# Lup\n",
        after="# Lup, renamed\n",
        effect="ask",
        autonomous=True,
    ),
    EditDecisionCase(
        path="src/new.py",
        before=None,
        after="value = 1",
        effect="ask",
        path_exists=False,
    ),
    EditDecisionCase(
        path="src/module.py", before="value = 1", after=None, effect="allow"
    ),
]


def test_policy_bundle_contains_assembly_but_no_decision_implementation() -> None:
    source = Path("packages/lup/src/lup/policy/bundle.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]

    assert "BUNDLED_POLICY_SOURCE" not in source
    assert all(not name.startswith("decide_") for name in functions)


def assembled_edit_decision(
    module: ModuleType,
    path: str,
    before: str | None,
    after: str | None,
    protected_roots: list[str],
    *,
    autonomous: bool = False,
) -> KernelDecision:
    """Invoke an isolated kernel with the same generated primitive rows."""
    suffix = Path(path).suffix.lower()
    rows_by_suffix = bundled_antipattern_rows()
    rows = rows_by_suffix[suffix] if suffix in rows_by_suffix else []
    return module.decide_edit(
        path,
        before,
        after,
        path_exists=Path(path).exists(),
        path_rules=runtime_path_rules(protected_roots),
        antipattern_rows=rows,
        autonomous=autonomous,
        python_source=suffix in (".py", ".pyi"),
    )


def test_assembled_kernel_runs_without_site_packages(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "kernel.py").write_text(policy_kernel_source(), encoding="utf-8")
    (runtime / "policy_data.py").write_text(
        render_policy_data(
            allowed_fetch_scopes=[
                runtime_url_scope("https://docs.example.com:8443", "/reference/")
            ],
            denied_fetch_scopes=[
                runtime_url_scope(
                    "https://docs.example.com:8443",
                    "/reference/private/",
                    "sensitive documentation path",
                )
            ],
            protected_roots=[".claude", "tmp", "pyproject.toml", "README.md"],
            autonomous_agent_identities=["resolve-editor"],
        ),
        encoding="utf-8",
    )
    fixtures = runtime / "fixtures.json"
    fixtures.write_text(
        json.dumps(
            {
                "shell": [item.model_dump() for item in SHELL_POLICY_CASES],
                "fetch": [item.model_dump() for item in FETCH_POLICY_CASES],
                "edit": [item.model_dump() for item in EDIT_POLICY_CASES],
            }
        ),
        encoding="utf-8",
    )
    probe = runtime / "probe.py"
    probe.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n"
        "from kernel import decide_edit, decide_fetch, decide_shell\n"
        "from policy_data import (\n"
        "    ALLOWED_FETCH_SCOPES, ANTI_PATTERN_ROWS, DENIED_FETCH_SCOPES,\n"
        "    MAXIMUM_ADDED_LINES, PATH_RULES,\n"
        ")\n"
        "fixtures = json.loads(\n"
        "    (Path(__file__).parent / 'fixtures.json').read_text(encoding='utf-8')\n"
        ")\n"
        "for case in fixtures['shell']:\n"
        "    assert decide_shell(case['input']).effect == case['effect'], case\n"
        "for case in fixtures['fetch']:\n"
        "    decision = decide_fetch(\n"
        "        case['input'], ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES\n"
        "    )\n"
        "    assert decision.effect == case['effect'], case\n"
        "for case in fixtures['edit']:\n"
        "    suffix = Path(case['path']).suffix.lower()\n"
        "    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else ()\n"
        "    decision = decide_edit(\n"
        "        case['path'], case['before'], case['after'],\n"
        "        path_exists=case['path_exists'], path_rules=PATH_RULES,\n"
        "        antipattern_rows=rows, maximum_added_lines=MAXIMUM_ADDED_LINES,\n"
        "        autonomous=case['autonomous'],\n"
        "        python_source=suffix in ('.py', '.pyi'),\n"
        "    )\n"
        "    assert decision.effect == case['effect'], case\n",
        encoding="utf-8",
    )

    sh.Command("python3")("-I", "-S", str(probe))


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
    path.write_text(policy_kernel_source(), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_fetch_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    scope = UrlScope.model_validate(
        {"origin": "https://docs.example.com:8443", "path_prefix": "/reference/"}
    )
    denied_scope = UrlScope.model_validate(
        {
            "origin": "https://docs.example.com:8443",
            "path_prefix": "/reference/private/",
            "reason": "sensitive documentation path",
        }
    )
    policy = FetchPolicy(allowed=[scope], denied=[denied_scope])
    wire_scope = [runtime_url_scope(str(scope.origin), scope.path_prefix)]
    denied_wire_scope = [
        runtime_url_scope(
            str(denied_scope.origin), denied_scope.path_prefix, denied_scope.reason
        )
    ]

    for case in FETCH_POLICY_CASES:
        canonical = policy.decide(FetchUrl(url=AnyHttpUrl(case.input)))
        generated = bundled.decide_fetch(case.input, wire_scope, denied_wire_scope)
        assert canonical.effect == generated.effect == case.effect


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
    path.write_text(policy_kernel_source(), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)
    policy = ShellPolicy()

    for case in SHELL_POLICY_CASES:
        assert policy.decide(ShellCommand(command=case.input)).effect == case.effect
        assert bundled.decide_shell(case.input).effect == case.effect


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
                after="value: Any",
            ),
        ]
    )

    assert policy.decide(batch).effect == "deny"
    protected = EditBatch(
        changes=[EditChange(path=Path("pyproject.toml"), after="version = '2'")]
    )
    assert policy.decide(protected).effect == "ask"


def test_canonical_edit_policy_preserves_shared_security_outcomes() -> None:
    protected = [
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
        PathRule(
            kind="exact",
            value="README.md",
            reason="README.md is human-authored; propose changes via "
            "AskUserQuestion instead of editing",
        ),
    ]

    for case in EDIT_POLICY_CASES:
        policy = EditPolicy(protected=protected, autonomous=case.autonomous)
        decision = policy.decide(
            EditBatch(
                changes=[
                    EditChange(
                        path=Path(case.path), before=case.before, after=case.after
                    )
                ]
            )
        )
        assert decision.effect == case.effect


def test_bundled_edit_policy_matches_canonical_security_outcomes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bundled_policy.py"
    path.write_text(policy_kernel_source(), encoding="utf-8")
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
            PathRule(
                kind="exact",
                value="README.md",
                reason="README.md is human-authored; propose changes via "
                "AskUserQuestion instead of editing",
            ),
        ]
    )
    cases = [
        item
        for item in EDIT_POLICY_CASES
        if not item.autonomous and item.before is not None and item.after is not None
    ]
    for case in cases:
        canonical = policy.decide(
            EditBatch(
                changes=[
                    EditChange(
                        path=Path(case.path), before=case.before, after=case.after
                    )
                ]
            )
        )
        generated = assembled_edit_decision(
            bundled,
            case.path,
            case.before,
            case.after,
            [".claude", "tmp", "pyproject.toml", "README.md"],
        )
        assert canonical.effect == generated.effect == case.effect


def test_bundled_resolve_editor_keeps_guardrails(tmp_path: Path) -> None:
    path = tmp_path / "bundled_editor_policy.py"
    path.write_text(policy_kernel_source(), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bundled_editor_policy", path)
    assert spec is not None and spec.loader is not None
    bundled = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundled)

    cases = [item for item in EDIT_POLICY_CASES if item.autonomous]
    for case in cases:
        decision = assembled_edit_decision(
            bundled,
            case.path,
            case.before,
            case.after,
            [".claude", "tmp", "README.md"],
            autonomous=True,
        )
        assert decision.effect == case.effect


def test_edit_policy_uses_full_python_context_for_added_docstrings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bundled_docstring_policy.py"
    path.write_text(policy_kernel_source(), encoding="utf-8")
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
    assert (
        assembled_edit_decision(bundled, "src/module.py", before, after, []).effect
        == "allow"
    )


def test_edit_policy_bundle_embeds_canonical_ast_refinement(tmp_path: Path) -> None:
    path = tmp_path / "bundled_ast_policy.py"
    path.write_text(policy_kernel_source(), encoding="utf-8")
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
    assert (
        assembled_edit_decision(bundled, "src/scheduler.py", before, after, []).effect
        == "allow"
    )


def test_content_prose_examples_do_not_trip_code_or_marker_gates() -> None:
    path = Path("src/lup_template/devtools/harness/content/skills/commit.py")
    before = path.read_text(encoding="utf-8")
    after = before + (
        '\nPROSE_GATE_EXAMPLE = """Any and # lup: examples remain prose."""\n'
    )

    decision = EditPolicy(protected=[]).decide(
        EditBatch(changes=[EditChange(path=path, before=before, after=after)])
    )

    assert decision.effect == "allow"
