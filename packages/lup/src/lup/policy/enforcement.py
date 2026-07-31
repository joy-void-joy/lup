"""The seam that turns a policy verdict into a live session's refusal.

The policies in :mod:`lup.policy.rules` answer with a
:class:`~lup.policy.models.Decision`; a session refuses through the portable
hooks of :mod:`lup.hooks`. The mapping between them is not a choice a caller
should make twice — ``ask`` must reach a human and ``defer`` must reach
nobody, and a composition that guesses either one wrong turns a gate into a
silent grant. So it is decided here, once, and pinned by tests.

Generated plugins enforce the same policies from a subprocess dispatcher
assembled by :mod:`lup.policy.bundle`. This is the in-process counterpart:
same policies, same verdicts, delivered through the hook seam a session
already carries.
"""

from collections.abc import Callable

from lup.hooks import (
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
    allow_hook,
    ask_hook,
    deny_hook,
)
from lup.policy.chain import UnknownToolPolicy
from lup.policy.contracts import DecisionPolicy
from lup.policy.models import (
    Decision,
    EditBatch,
    FetchUrl,
    SearchWeb,
    SemanticTool,
    ShellCommand,
    UnknownTool,
)


def policy_hook_output(decision: Decision) -> LupHookOutput:
    """Render one policy verdict as the portable hook decision.

    ``defer`` carries no decision at all: the kernel declined to judge, so
    the session's ambient permission flow applies rather than this hook
    granting what nothing approved.
    """
    match decision.effect:
        case "allow":
            return allow_hook()
        case "ask":
            return ask_hook(decision.reason)
        case "deny":
            return deny_hook(decision.reason)
        case "defer":
            return LupHookOutput(reason=decision.reason)


class SemanticToolPolicy(DecisionPolicy[SemanticTool]):
    """Route each semantic tool to the policy that judges its family.

    An undeclared family asks rather than allows: a composition that wires
    fetch scopes and forgets shell must stop at a human, not wave the
    command through. Search and unclassified tools have no rule surface at
    all, so they always ask.
    """

    def __init__(
        self,
        *,
        fetch: DecisionPolicy[FetchUrl] | None = None,
        shell: DecisionPolicy[ShellCommand] | None = None,
        edit: DecisionPolicy[EditBatch] | None = None,
    ) -> None:
        self.fetch = fetch
        self.shell = shell
        self.edit = edit
        self.unknown = UnknownToolPolicy()

    def decide(self, event: SemanticTool) -> Decision:
        def undeclared(family: str) -> Decision:
            return Decision(
                effect="ask",
                reason=f"no {family} policy is declared, so this call needs approval",
            )

        match event:
            case FetchUrl():
                if self.fetch is None:
                    return undeclared("fetch")
                return self.fetch.decide(event)
            case ShellCommand():
                if self.shell is None:
                    return undeclared("shell")
                return self.shell.decide(event)
            case EditBatch():
                if self.edit is None:
                    return undeclared("edit")
                return self.edit.decide(event)
            case SearchWeb(query=query):
                return Decision(
                    effect="ask",
                    reason=f"web search {query!r} is not covered by policy",
                )
            case UnknownTool():
                return self.unknown.decide(event)


type SemanticDecoder = Callable[[LupHookInput], SemanticTool]
"""Decode one native tool call into the semantic tool a policy judges.

Native tool names and payload fields are adapter knowledge, so the
composition root supplies this — ``lup.adapters.claude.hooks`` has the
decoder for Claude sessions."""


def create_policy_hooks(
    policy: DecisionPolicy[SemanticTool],
    decode: SemanticDecoder,
    *,
    tag: str = "semantic_policy",
) -> LupHooksConfig:
    """Create a PreToolUse hook that enforces *policy* on every tool call.

    **What:** Decodes each attempted call into its semantic tool, asks
    *policy* for a verdict, and answers with the portable decision that
    verdict maps to — so a denied call never runs and an ``ask`` reaches a
    human instead of the model.

    **When:** Use for a session composed in this process. Generated native
    plugins enforce the same policies from their own dispatcher; this is
    for the session an application builds and runs itself.

    **Why:** A verdict a caller only prints is documentation. Registered
    here it is the session's answer, produced by the same policy objects
    the generated dispatchers erase into rows.

    Args:
        policy: The judge for one decoded tool, typically a
            :class:`SemanticToolPolicy` over the fetch, shell, and edit rules.
        decode: The adapter's native-call decoder.
        tag: Matcher tag for adapter dispatch.

    Returns:
        SDK-agnostic hooks configuration; combine via ``merge_hooks``.
    """

    async def policy_hook(event: LupHookInput) -> LupHookOutput:
        # LupHookEvent adopts Claude's event names as the neutral seam's own
        # vocabulary, so this reads a lup spelling rather than a provider's.
        if event.event != "PreToolUse":  # lup: ignore[native-spelling]
            return LupHookOutput()
        return policy_hook_output(policy.decide(decode(event)))

    return LupHooksConfig(pre_tool_use=[LupHookMatcher(hook=policy_hook, tag=tag)])
