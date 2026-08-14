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

from pydantic import BaseModel, ConfigDict, Field

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
from lup.policy.contracts import DeclaredPolicies, DecisionPolicy
from lup.policy.refused_tools import RefusedTool, routed_for
from lup.policy.models import (
    Decision,
    EditBatch,
    FetchUrl,
    SemanticTool,
    ShellCommand,
)


def policy_hook_output(decision: Decision, escapable: bool = False) -> LupHookOutput:
    """Render one policy verdict as the portable hook decision.

    ``defer`` carries no decision at all: the kernel declined to judge, so
    the session's ambient permission flow applies rather than this hook
    granting what nothing approved.

    ``escapable`` is whether the runtime this reaches can put a single call
    outside its sandbox. The composition happens here rather than at each
    adapter, so what a converter receives is already the placement its own
    runtime will honour — and a runtime that has no such channel is handed
    the plain effect instead of an intent it would silently drop.
    """
    decision = decision.placed(escapable)
    match decision.effect:
        case "allow":
            return allow_hook(decision.sandbox)
        case "ask":
            return ask_hook(decision.reason, decision.sandbox)
        case "deny":
            return deny_hook(decision.reason)
        case "defer":
            return LupHookOutput(reason=decision.reason)


class SemanticToolPolicy(DecisionPolicy[SemanticTool]):
    """Hold the declared policies and let each tool find its own.

    The tool answers rather than this class deciding, so a new kind of tool
    is a class beside the others rather than an arm here that a reader has
    to remember to add. What that costs a composition is stated where the
    tools implement it: an undeclared family asks rather than allows, and
    search and unclassified tools have no rule surface at all.
    """

    def __init__(
        self,
        *,
        fetch: DecisionPolicy[FetchUrl] | None = None,
        shell: DecisionPolicy[ShellCommand] | None = None,
        edit: DecisionPolicy[EditBatch] | None = None,
        refused_tools: list[RefusedTool] | None = None,
    ) -> None:
        self.policies = DeclaredPolicies(
            unknown=UnknownToolPolicy(refused_tools),
            fetch=fetch,
            shell=shell,
            edit=edit,
        )

    def decide(self, event: SemanticTool) -> Decision:
        return event.decide_under(self.policies)


type SemanticDecoder = Callable[[LupHookInput], SemanticTool]
"""Decode one native tool call into the semantic tool a policy judges.

Native tool names and payload fields are adapter knowledge, so the
composition root supplies this — ``lup.adapters.claude.hooks`` has the
decoder for Claude sessions."""


class NativeSemantics(BaseModel):
    """One runtime's call decoder together with the tools it has rules for.

    The two are one fact, and a caller asked for them separately can supply
    a decoder with no routed set. That mismatch is silent and inverts the
    enforcement: registered against nothing, the hook judges every call, and
    a tool this vocabulary cannot classify reaches the conservative ``ask``
    that then outranks an ``allow`` a directory ACL beside it granted. An
    adapter exports the pair it means, and an empty routed set — the shape
    that disables enforcement while looking like configuration — is refused
    at construction.
    """

    model_config = ConfigDict(frozen=True)

    decode: SemanticDecoder
    routed_tools: list[str] = Field(min_length=1)
    escapable: bool = False
    """Whether this runtime can put one call outside its own sandbox.

    An adapter fact rather than a policy one, so it arrives with the decoder
    and the routed set. Left false, a placement never reaches the wire — the
    conservative direction, and the right one for a runtime whose sandbox is
    a session-level flag rather than a per-call argument."""

    def also_refusing(self, refused: list[RefusedTool]) -> "NativeSemantics":
        """The same decoder, registered for the refused tools as well.

        A refusal reaches nothing it was not routed for, and the plugin widens
        its matcher from the same declaration — so an in-process session that
        took the adapter's pairing unchanged would enforce strictly less than
        the generated tree beside it.
        """
        return NativeSemantics(
            decode=self.decode, routed_tools=routed_for(self.routed_tools, refused)
        )


def create_policy_hooks(
    policy: DecisionPolicy[SemanticTool],
    semantics: NativeSemantics,
    *,
    tag: str = "semantic_policy",
) -> LupHooksConfig:
    """Create a PreToolUse hook that enforces *policy* on the tools it judges.

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

    **Why scoped:** the routed set carried by *semantics* is what keeps this
    the same enforcement the plugin performs rather than a stricter one.
    Unregistered elsewhere, this hook sees every call, and a tool with no
    rule surface reaches :class:`UnknownToolPolicy`, whose conservative
    ``ask`` then outranks an ``allow`` a directory ACL beside it already
    granted — so composing this with an ACL denies the reads that ACL exists
    to permit.

    Args:
        policy: The judge for one decoded tool, typically a
            :class:`SemanticToolPolicy` over the fetch, shell, and edit rules.
        semantics: The adapter's decoder and the native tool names this
            policy has rules for, as the adapter exports them.
        tag: Matcher tag for adapter dispatch.

    Returns:
        SDK-agnostic hooks configuration; combine via ``merge_hooks``.
    """

    async def policy_hook(event: LupHookInput) -> LupHookOutput:
        # LupHookEvent adopts Claude's event names as the neutral seam's own
        # vocabulary, so this reads a lup spelling rather than a provider's.
        if event.event != "PreToolUse":  # lup: ignore[native-spelling]
            return LupHookOutput()
        return policy_hook_output(
            policy.decide(semantics.decode(event).as_documents()),
            semantics.escapable,
        )

    return LupHooksConfig(
        pre_tool_use=[
            LupHookMatcher(
                hook=policy_hook,
                matcher="|".join(semantics.routed_tools),
                tag=tag,
            )
        ]
    )
