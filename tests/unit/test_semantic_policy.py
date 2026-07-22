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
from lup.policy.rules import (
    EditPolicy,
    FetchPolicy,
    PathRule,
    ShellPolicy,
    UrlScope,
    human_owned_path_rule,
)


class DecisionCase(BaseModel):
    """One primitive input and its expected policy effect."""

    model_config = ConfigDict(frozen=True)

    input: str
    effect: Literal["allow", "ask", "deny", "defer"]


class EditDecisionCase(BaseModel):
    """One edit fixture shared by canonical and assembled policy forms."""

    model_config = ConfigDict(frozen=True)

    path: str
    before: str | None
    after: str | None
    effect: Literal["allow", "ask", "deny", "defer"]
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
    # Redirections: discards and fd duplication are stripped; file writes ask.
    DecisionCase(input="grep x f 2>&1", effect="allow"),
    DecisionCase(input="grep x f > /dev/null", effect="allow"),
    DecisionCase(input="cat f 2>/dev/null", effect="allow"),
    DecisionCase(input="ls >&2", effect="allow"),
    DecisionCase(input="echo x > out.txt", effect="ask"),
    DecisionCase(input="cat <<EOF", effect="ask"),
    # Quote-aware substitution: inert inside single quotes; live substitution
    # is denied with a rewrite hint toward a separate call, <(...), or a pipe.
    DecisionCase(input="git commit -m 'fixes $(bug)'", effect="allow"),
    DecisionCase(input="echo $(whoami)", effect="deny"),
    DecisionCase(input="echo `id`", effect="deny"),
    # Read-side process substitution classifies its inner command recursively;
    # the write side still asks and a substituting inner command is denied.
    DecisionCase(input="diff <(git status) <(git log)", effect="allow"),
    DecisionCase(input="diff <(sudo id) f", effect="ask"),
    DecisionCase(input="diff <(cat $(x)) f", effect="deny"),
    DecisionCase(input="cat >(tee f)", effect="ask"),
    # Loops classify their condition and body recursively; literal for-words
    # instantiate the body, and opaque word lists gate guarded arguments.
    DecisionCase(input="sleep 5", effect="allow"),
    DecisionCase(input='for f in a.py b.py; do wc -l "$f"; done', effect="allow"),
    DecisionCase(input='for f in *.py; do wc -l "$f"; done', effect="allow"),
    DecisionCase(input="until grep -q Ready dev.log; do sleep 1; done", effect="allow"),
    DecisionCase(input="while true; do date; done", effect="allow"),
    DecisionCase(
        input='for a in x y; do for b in z; do echo "$a$b"; done; done',
        effect="allow",
    ),
    DecisionCase(input="for x in -i; do sed \"$x\" 's/a/b/' f; done", effect="ask"),
    DecisionCase(input='for f in *.txt; do sort "$f"; done', effect="ask"),
    DecisionCase(input='for f in a; do python "$f"; done', effect="deny"),
    DecisionCase(input='for f in a; do wc "$f"', effect="ask"),
    DecisionCase(input="while do done", effect="ask"),
    DecisionCase(input='for f a; do wc "$f"; done', effect="ask"),
    # Expanded read-only vocabulary with writer-flag guards.
    DecisionCase(input="sort f", effect="allow"),
    DecisionCase(input="sort -o out f", effect="ask"),
    DecisionCase(input="sed -n '1,5p' f", effect="allow"),
    DecisionCase(input="sed -i 's/a/b/' f", effect="ask"),
    DecisionCase(input="sed 's/x/y/e' f", effect="ask"),
    DecisionCase(input="jq . f", effect="allow"),
    DecisionCase(input="cut -f1 f", effect="allow"),
    DecisionCase(input="diff a b", effect="allow"),
    DecisionCase(input="rg TODO", effect="allow"),
    # Git: read-only and reversible-local allow; destructive forms ask.
    DecisionCase(input="git rev-parse HEAD", effect="allow"),
    DecisionCase(input="git ls-files", effect="allow"),
    DecisionCase(input="git blame f", effect="allow"),
    DecisionCase(input="git stash push", effect="allow"),
    DecisionCase(input="git reset --soft HEAD~1", effect="allow"),
    DecisionCase(input="git branch -D topic", effect="ask"),
    DecisionCase(input="git worktree remove wt", effect="ask"),
    DecisionCase(input="git stash drop", effect="ask"),
    DecisionCase(input="git reset --hard", effect="ask"),
    DecisionCase(input="git clean -fd", effect="ask"),
    DecisionCase(input="git push --force", effect="ask"),
    DecisionCase(input="git checkout -- file", effect="ask"),
    DecisionCase(input="git config core.pager=x", effect="ask"),
    # Global value flags are consumed, never read as the subcommand; globals
    # that change execution behavior ask.
    DecisionCase(input="git -C /other status", effect="allow"),
    DecisionCase(input="git -C status push", effect="ask"),
    DecisionCase(input="git -c core.pager=touch log", effect="ask"),
    DecisionCase(input="git --exec-path=/tmp/x status", effect="ask"),
    # Exec-bearing and file-writing flags on allowed subcommands ask.
    DecisionCase(input="git rebase --exec 'touch x' HEAD~2", effect="ask"),
    DecisionCase(input="git fetch --upload-pack=/tmp/x origin", effect="ask"),
    DecisionCase(input="git grep -Ovim pattern", effect="ask"),
    DecisionCase(input="git log --output=/tmp/f", effect="ask"),
    DecisionCase(input="git reflog", effect="allow"),
    DecisionCase(input="git reflog expire --expire=now --all", effect="ask"),
    DecisionCase(input="sort --compress-program=/tmp/x f", effect="ask"),
    # gh: read-only operations allow; mutating forms ask.
    DecisionCase(input="gh run view 1", effect="allow"),
    DecisionCase(input="gh repo view", effect="allow"),
    DecisionCase(input="gh pr close 1", effect="ask"),
    DecisionCase(input="gh api -X POST /repos", effect="ask"),
    # Adversarial hardening: no auto-allowed code execution or injection.
    DecisionCase(input="sudo cat /etc/shadow", effect="ask"),
    DecisionCase(input="LD_PRELOAD=./x.so ls", effect="ask"),
    DecisionCase(input="GIT_SSH_COMMAND=./x git fetch origin", effect="ask"),
    DecisionCase(input="git fetch ext::sh -c id", effect="ask"),
    DecisionCase(input="uv run --with evil pytest", effect="ask"),
    DecisionCase(input="uv run ./pytest", effect="ask"),
    DecisionCase(input="uv run /tmp/tool --help", effect="ask"),
    DecisionCase(input="printf . | xargs find . -delete", effect="ask"),
    DecisionCase(input="find . -execdir sh -c id ;", effect="ask"),
    DecisionCase(input="sort f && python -c 'x'", effect="deny"),
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
        path="src/module.py",
        before="value = 1",
        after="value = compute()  # may return Any when unset",
        effect="allow",
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
    ),
    EditDecisionCase(
        path="sync.json",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app"}]}',
        effect="ask",
    ),
    EditDecisionCase(
        path="downstream.json",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app"}]}',
        effect="ask",
        path_exists=False,
    ),
    EditDecisionCase(
        path="sync.json",
        before='{"projects": []}',
        after='{"projects": [{"name": "fleet-app"}]}',
        effect="allow",
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
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\nalpha = 2\nbeta = 3\ngamma = 4\ndelta = 5",
        effect="defer",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="value = 1",
        after="value = 1\n\n# note one\n\n# note two\n\n# note three\n\n# four",
        effect="allow",
    ),
    EditDecisionCase(
        path="src/module.py",
        before="import x",
        after=(
            "import x\n\n\nclass Config(BaseModel):\n    name: str\n"
            "    size: int\n    tags: list[str]\n    active: bool"
        ),
        effect="allow",
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
    human_owned_files: list[str],
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
        path_rules=runtime_path_rules(protected_roots, human_owned_files),
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
            protected_roots=[
                ".claude",
                "tmp",
                "pyproject.toml",
                "sync.json",
                "downstream.json",
            ],
            human_owned_files=["README.md"],
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
        "    MAXIMUM_ADDED_LINES, PATH_RULES, SHELL_RULES,\n"
        ")\n"
        "fixtures = json.loads(\n"
        "    (Path(__file__).parent / 'fixtures.json').read_text(encoding='utf-8')\n"
        ")\n"
        "for case in fixtures['shell']:\n"
        "    result = decide_shell(case['input'], SHELL_RULES)\n"
        "    assert result.effect == case['effect'], case\n"
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
            UrlScope(
                origin=AnyHttpUrl("https://docs.example.com"),
                path_prefix="/reference/",
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
    scope = UrlScope(
        origin=AnyHttpUrl("https://docs.example.com:8443"),
        path_prefix="/reference/",
    )
    denied_scope = UrlScope(
        origin=AnyHttpUrl("https://docs.example.com:8443"),
        path_prefix="/reference/private/",
        reason="sensitive documentation path",
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
    assert policy.decide(ShellCommand(command="echo $(dangerous)")).effect == "deny"


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
        assert bundled.decide_shell(case.input, policy.rules).effect == case.effect


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

    denied = policy.decide(batch)
    assert denied.effect == "deny"
    assert "(rule any-type — see docs/rules.md)" in denied.reason
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
        human_owned_path_rule("README.md"),
        PathRule(
            kind="subtree",
            value="sync.json",
            reason="protected path requires approval",
            allow_autonomous=True,
        ),
        PathRule(
            kind="subtree",
            value="downstream.json",
            reason="protected path requires approval",
            allow_autonomous=True,
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
            human_owned_path_rule("README.md"),
            PathRule(
                kind="subtree",
                value="sync.json",
                reason="protected path requires approval",
                allow_autonomous=True,
            ),
            PathRule(
                kind="subtree",
                value="downstream.json",
                reason="protected path requires approval",
                allow_autonomous=True,
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
            [".claude", "tmp", "pyproject.toml", "sync.json", "downstream.json"],
            ["README.md"],
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
            [".claude", "tmp"],
            ["README.md"],
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
        assembled_edit_decision(bundled, "src/module.py", before, after, [], []).effect
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
        assembled_edit_decision(
            bundled, "src/scheduler.py", before, after, [], []
        ).effect
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
