"""The seam from a policy verdict to a live session's refusal.

`lup.policy.enforcement` is where a :class:`Decision` becomes the answer a
session gives an attempted call. These pin the mapping no caller should
re-derive: deny refuses, ask reaches a human, defer answers nothing so the
ambient permission flow applies, and a tool family with no declared policy
asks rather than passes.
"""

from pathlib import Path

import pytest
from pydantic import AnyHttpUrl, ValidationError

from lup.adapters.claude.harness import CLAUDE_DISPATCHER
from lup.adapters.claude.hooks import CLAUDE_SEMANTICS
from lup.adapters.claude.runtime import ClaudeSandboxConfig
from lup.adapters.codex.native import CodexDecisionRenderer
from lup.devtools.harness.resolve import worker_policy_hooks
from lup.hooks import LupHookInput, LupHookOutput
from lup.policy.enforcement import (
    NativeSemantics,
    SandboxPosture,
    SemanticToolPolicy,
    create_policy_hooks,
    policy_hook_output,
)
from lup.policy.kernel.decision import SANDBOX_TRAPPED_REASON, DecisionEffect
from lup.policy.vocabulary import runner_target_rules
from lup.policy.models import (
    Decision,
    EditBatch,
    EditChange,
    FetchUrl,
    SearchWeb,
    ShellCommand,
    ToolIdentity,
    UnknownTool,
)
from lup.policy.grants import LeaseGrants
from lup.policy.refused_tools import RefusedTool
from lup.policy.rules import EditPolicy, FetchPolicy, ShellPolicy, UrlScope
from lup_template.devtools.harness.catalog import declared_hook_set
from lup_template.devtools.harness.content.shell_vocabulary import SHELL_RULES

DOCS_ORIGIN = AnyHttpUrl("https://docs.example.com")
DENIED_URL = AnyHttpUrl("https://docs.example.com/private/token")


def docs_fetch_policy() -> FetchPolicy:
    return FetchPolicy(
        allowed=[UrlScope(origin=DOCS_ORIGIN, path_prefix="/api")],
        denied=[UrlScope(origin=DOCS_ORIGIN, path_prefix="/private")],
    )


def test_every_effect_maps_to_one_portable_decision() -> None:
    assert policy_hook_output(Decision(effect="allow")) == LupHookOutput(
        decision="allow"
    )
    assert policy_hook_output(
        Decision(effect="ask", reason="approval required")
    ) == LupHookOutput(decision="ask", reason="approval required")
    assert policy_hook_output(
        Decision(effect="deny", reason="URL is denied")
    ) == LupHookOutput(decision="deny", reason="URL is denied")
    # Defer carries no decision at all: the kernel declined to judge, so the
    # session's ambient permission flow decides instead of this hook granting
    # what nothing approved.
    deferred = policy_hook_output(Decision(effect="defer", reason="unjudged"))
    assert deferred.decision is None
    assert deferred.reason == "unjudged"


def test_no_effect_reaches_codex_as_a_silent_allow() -> None:
    """The neutral vocabulary carries ask; Codex's hook surface has no channel
    for it, so the widening is only safe while every non-allow effect still
    refuses there — a fail-closed denial, recorded as an approximation."""
    renderer = CodexDecisionRenderer(supports_ask=False)
    exit_codes: dict[DecisionEffect, int] = {
        "allow": 0,
        "defer": 0,
        "ask": 2,
        "deny": 2,
    }
    for effect, exit_code in exit_codes.items():
        rendered = renderer.render(Decision(effect=effect, reason="reason"))
        assert rendered.exit_code == exit_code
    assert (
        renderer.render(Decision(effect="ask")).approximation
        == "ask rendered as fail-closed denial"
    )


def test_router_sends_each_tool_to_the_policy_that_judges_it() -> None:
    router = SemanticToolPolicy(
        fetch=docs_fetch_policy(),
        shell=ShellPolicy(SHELL_RULES),
        edit=None,
    )

    assert router.decide(FetchUrl(url=DENIED_URL)).effect == "deny"
    assert (
        router.decide(FetchUrl(url=AnyHttpUrl("https://docs.example.com/api/x"))).effect
        == "allow"
    )
    assert router.decide(ShellCommand(command="git status")).effect == "allow"
    assert router.decide(ShellCommand(command="mycommand --flag")).effect == "deny"


def test_router_asks_rather_than_allows_what_no_policy_covers() -> None:
    router = SemanticToolPolicy(fetch=docs_fetch_policy())

    undeclared = router.decide(ShellCommand(command="git status"))
    assert undeclared.effect == "ask"
    assert "no shell policy is declared" in undeclared.reason

    edit = router.decide(
        EditBatch(changes=[EditChange(path=Path("module.py"), after="value = 1")])
    )
    assert edit.effect == "ask"
    assert "no edit policy is declared" in edit.reason

    assert router.decide(SearchWeb(query="anything")).effect == "ask"
    assert (
        router.decide(
            UnknownTool(identity=ToolIdentity(original_name="mcp__notes__write"))
        ).effect
        == "ask"
    )


async def test_hook_judges_an_edit_by_the_documents_it_would_produce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hook splices fragments before judging, as the dispatchers do.

    Repo-relative path on purpose: the scratchpad role skips the marker
    gate, and this test needs the gate reading the spliced document.
    """
    monkeypatch.chdir(tmp_path)
    Path("content.py").write_text(
        'TABLE = """\nA note spells itself as # lup: fix this here.\n"""\n',
        encoding="utf-8",
    )
    hooks = create_policy_hooks(
        SemanticToolPolicy(edit=EditPolicy(protected=[])),
        CLAUDE_SEMANTICS,
    )
    allowed = await hooks.pre_tool_use[0].hook(
        LupHookInput(
            event="PreToolUse",
            tool_name="Edit",
            tool_input={
                "file_path": "content.py",
                "old_string": "A note spells itself as # lup: fix this here.\n",
                "new_string": "",
            },
        )
    )
    assert allowed.decision == "allow"


async def test_hook_refuses_a_denied_call_and_leaves_other_events_alone() -> None:
    hooks = create_policy_hooks(
        SemanticToolPolicy(fetch=docs_fetch_policy()),
        CLAUDE_SEMANTICS,
    )
    matcher = hooks.pre_tool_use[0]
    assert matcher.tag == "semantic_policy"

    refused = await matcher.hook(
        LupHookInput(
            event="PreToolUse",
            tool_name="WebFetch",
            tool_input={"url": str(DENIED_URL)},
        )
    )
    assert refused == LupHookOutput(decision="deny", reason="URL is denied")

    after = await matcher.hook(
        LupHookInput(
            event="PostToolUse",
            tool_name="WebFetch",
            tool_input={"url": str(DENIED_URL)},
        )
    )
    assert after == LupHookOutput()


async def test_permitting_an_escape_widens_only_the_calls_that_declare_one() -> None:
    """Opening the escape must move exactly the calls that asked for it.

    Composed as a worker is: the placement taken from the session's own
    sandbox declaration, and nothing else taken from it. Three shapes through
    one session — the toolchain declares ``outside`` and reaches it, an
    ordinary allow runs where the session runs, and a command no rule
    classifies is refused rather than carried anywhere. The last is what
    makes the first safe: a session that may place one call outside must not
    thereby place the ones it never judged.
    """
    posture = ClaudeSandboxConfig(allow_unsandboxed_commands=True).posture()
    assert posture == SandboxPosture(active=True, escapable=True)

    hooks = create_policy_hooks(
        SemanticToolPolicy(
            shell=ShellPolicy(
                SHELL_RULES,
                escapable=CLAUDE_SEMANTICS.escapes_from(posture),
                interactive=False,
                runner_targets=runner_target_rules(),
            )
        ),
        CLAUDE_SEMANTICS,
        sandbox=posture,
    )

    async def placed(command: str) -> LupHookOutput:
        return await hooks.pre_tool_use[0].hook(
            LupHookInput(
                event="PreToolUse",
                tool_name="Bash",
                tool_input={"command": command},
            )
        )

    assert await placed("uv run lup-devtools harness resolve") == LupHookOutput(
        decision="allow", sandbox="outside"
    )
    assert await placed("uv run pytest tests/unit") == LupHookOutput(
        decision="allow", sandbox="ambient"
    )
    unjudged = await placed("frobnicate --wildly")
    assert unjudged.decision == "deny"
    assert unjudged.sandbox == "ambient"


async def test_a_worker_is_judged_by_the_composition_a_run_actually_builds() -> None:
    """The judge itself, not a restatement of it — this is where it went wrong.

    Every verdict the kernel reached was already correct; what shipped a
    widening was the composition handing it host facts the session did not
    have. So this builds the worker's judge rather than a policy shaped like
    it: the toolchain is placed outside and gets there, while a guarded verb
    stays a refusal, and so does an escalation marker, which in a session
    with no way to reach a human would otherwise be the way to avoid one.
    """
    hooks = worker_policy_hooks(
        declared_hook_set(),
        LeaseGrants(),
        CLAUDE_SEMANTICS,
        ClaudeSandboxConfig(allow_unsandboxed_commands=True).posture(),
    )

    async def judged(command: str) -> LupHookOutput:
        return await hooks.pre_tool_use[0].hook(
            LupHookInput(
                event="PreToolUse",
                tool_name="Bash",
                tool_input={"command": command},
            )
        )

    assert await judged("uv run lup-devtools harness resolve") == LupHookOutput(
        decision="allow", sandbox="outside"
    )
    for refused in (
        "find . -delete",
        "git push --delete origin feat",
        "# lup: escalate: I would rather not be asked\nsudo rm -rf /var/tmp/x",
    ):
        assert (await judged(refused)).decision == "deny", refused


async def test_a_session_that_forbids_the_escape_is_never_told_it_has_one() -> None:
    """The runtime's channel is not the session's permission to use it.

    Read from the runtime alone, a session whose settings forbid unsandboxed
    commands was still handed the placement — rendered onto the wire, dropped
    without a word, and the call left confined to die on whatever it wrote
    first. Composed from the session instead, the runtime still reports the
    channel and the pair still says no, so a host that also declares its
    confinement stops the call with the sandbox named rather than letting it
    reach a shell it cannot survive.
    """
    posture = ClaudeSandboxConfig().posture()
    assert posture == SandboxPosture(active=True, escapable=False)
    assert CLAUDE_SEMANTICS.escapable
    assert not CLAUDE_SEMANTICS.escapes_from(posture)

    hooks = create_policy_hooks(
        SemanticToolPolicy(
            shell=ShellPolicy(
                SHELL_RULES,
                sandbox_active=posture.active,
                escapable=CLAUDE_SEMANTICS.escapes_from(posture),
                interactive=False,
                runner_targets=runner_target_rules(),
            )
        ),
        CLAUDE_SEMANTICS,
        sandbox=posture,
    )
    stopped = await hooks.pre_tool_use[0].hook(
        LupHookInput(
            event="PreToolUse",
            tool_name="Bash",
            tool_input={"command": "uv run lup-devtools harness resolve"},
        )
    )

    assert stopped.decision == "deny"
    assert stopped.reason == SANDBOX_TRAPPED_REASON
    assert stopped.sandbox == "ambient"


def test_hook_is_scoped_to_the_tools_the_policy_has_rules_for() -> None:
    """A tool with no rule surface must never reach this hook.

    Composed beside a directory ACL, an unscoped hook answers ``ask`` for
    every read the ACL allows, and ``ask`` outranks ``allow`` — which is
    what denied resolver workers their own leases. The matcher is the same
    list the generated plugin registers, so both paths judge one set.
    """
    hooks = create_policy_hooks(
        SemanticToolPolicy(fetch=docs_fetch_policy()),
        CLAUDE_SEMANTICS,
    )
    matched = hooks.pre_tool_use[0].matcher or ""

    assert set(matched.split("|")) == set(CLAUDE_DISPATCHER.routed_tools)
    for unruled in ("Read", "Skill", "mcp__lup-output__submit_output"):
        assert unruled not in matched.split("|")


def test_a_refusal_is_what_widens_the_routed_set() -> None:
    """A refused tool is routed, and refusing none routes nothing extra.

    Both halves matter. Unrouted, a declared refusal judges nothing and the
    reflex it exists to stop goes through; routed by a runtime that merely
    anticipates the name, every adopter refusing nothing pays the
    unclassified ``ask`` for a tool they have no opinion about.
    """
    refusal = RefusedTool(tool="Artifact", reason="publishing leaves the repository")

    assert "Artifact" not in CLAUDE_SEMANTICS.routed_tools
    assert "Artifact" in CLAUDE_SEMANTICS.also_refusing([refusal]).routed_tools
    assert CLAUDE_SEMANTICS.also_refusing([]).routed_tools == (
        CLAUDE_SEMANTICS.routed_tools
    )


def test_a_refused_tool_is_routed_exactly_once() -> None:
    """A refusal narrowed by specifier still names one tool to register."""
    refusals = [
        RefusedTool(tool="Skill", specifier="artifact-design", reason="leaves it"),
        RefusedTool(tool="Skill", specifier="page-design", reason="leaves it too"),
    ]

    routed = CLAUDE_SEMANTICS.also_refusing(refusals).routed_tools

    assert routed.count("Skill") == 1


def test_refusing_a_tool_the_runtime_decodes_is_refused_outright() -> None:
    """An unreachable refusal is a declaration that lies about being in force.

    ``Bash`` is judged by the shell lattice before the table is ever consulted,
    so a row naming it would read as a ban while every command went through.
    """
    with pytest.raises(ValueError, match="answer first"):
        CLAUDE_SEMANTICS.also_refusing(
            [RefusedTool(tool="Bash", reason="shells leave the repository")]
        )


def test_a_decoder_cannot_be_enforced_over_no_tools_at_all() -> None:
    """The scope is carried with the decoder, and an empty one is refused.

    Handing the routed set in separately let a caller supply a decoder and
    no scope, which reads as configuration and silently inverts the
    enforcement: matched against nothing the hook judges every call, and the
    conservative ``ask`` an unclassified tool earns outranks the ``allow``
    beside it. There is no such pair to construct.
    """
    assert CLAUDE_SEMANTICS.routed_tools == CLAUDE_DISPATCHER.routed_tools

    with pytest.raises(ValidationError):
        NativeSemantics(decode=CLAUDE_SEMANTICS.decode, routed_tools=[])
