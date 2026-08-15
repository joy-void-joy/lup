"""The verdict vocabulary every kernel module returns."""

from typing import Literal


type DecisionEffect = Literal["allow", "ask", "deny", "defer"]

type SandboxPlacement = Literal["inside", "ambient", "outside"]
"""Where a call runs, which is a different question from who decides it.

The four effects answer *who decides*; this answers *where it runs*. They are
two fields rather than one widened vocabulary because folding them together
forces an ask-plus-escape member next, and then a deny-plus-escape. Composed,
the pairs that carry meaning read:

* ``ask`` + ``outside`` — ask, warning the call will run out of the sandbox
* ``deny`` — deny, whatever the placement says
* ``allow`` + ``inside`` — run confined, whatever the session's own mode is
* ``allow`` + ``ambient`` — run, deferring to the session's sandbox status
* ``allow`` + ``outside`` — run out of the sandbox, unprompted

``ambient`` is the default because saying nothing about placement is what
almost every verdict means, and a runtime that cannot place a single call
renders the plain effect instead — see :meth:`KernelDecision.placed`.
"""

SANDBOX_ESCAPE_NOTICE = " — this will run outside the sandbox"
"""What an approval question adds when the call it approves also escapes."""

SANDBOX_TRAPPED_REASON = (
    "this has to run outside the sandbox, and this runtime puts no single call"
    " outside its own — run from inside one it would reach the shell and die on"
    " a bare read-only-filesystem error, which reads like a broken repository"
    " rather than like a boundary; re-run it from a session that is not"
    " sandboxed"
)
"""Why a call that has to escape is refused where nothing can carry it out.

An intent no runtime will honour is worse than a refusal: the call runs,
fails on whatever it happened to write first, and the agent cannot tell that
from a repository in a bad state, so it retries, works around it, or reports
success from a session that never ran a command.
"""


KERNEL_IMPORT_ALLOWLIST = (  # lup: ignore[library-default] — the stdlib the kernel actually imports; the hermetic guarantee it exists to hold
    "ast",
    "collections.abc",
    "io",
    "posixpath",
    "re",
    "tokenize",
    "typing",
    "urllib.parse",
)
ESCALATE_HINT = (
    " — reshape the command into the allowed vocabulary, or resubmit with a"
    " leading '# lup: escalate: <why>' line to request approval"
)
RESHAPE_HINT = " — reshape the command into the allowed vocabulary"
SUBSTITUTION_REASON = (
    "command substitution is denied — run the inner command in its own call"
    " and splice its literal output, or read it through <(...) or a pipe"
)
BACKTICK_REASON = (
    "backtick substitution is denied — use $(...) so the inner command"
    " can be classified"
)
SUBSTITUTION_SENTINEL = "$~sub~"
"""Spliced into a word where a real ``$(...)`` stood.

The spelling sits outside identifier space, so no variable binding can
instantiate it, and a quoted literal that happens to match only makes the
word read as opaque — the conservative direction.
"""


class KernelDecision:
    """Dependency-free allow, ask, deny, or defer result, and where it runs."""

    effect: DecisionEffect
    reason: str
    sandbox: SandboxPlacement

    def __init__(
        self,
        effect: DecisionEffect,
        reason: str = "",
        sandbox: SandboxPlacement = "ambient",
    ) -> None:
        if effect not in ("allow", "ask", "deny", "defer"):
            raise ValueError(f"invalid kernel decision effect {effect!r}")
        if sandbox not in ("inside", "ambient", "outside"):
            raise ValueError(f"invalid kernel decision placement {sandbox!r}")
        self.effect = effect
        self.reason = reason
        # Only a verdict this policy actually reached is placed: a refusal is
        # not softened by where the call would have run, and a deferral hands
        # the whole question over, the session's sandbox status included.
        self.sandbox = sandbox if effect in ("allow", "ask") else "ambient"

    def placed(self, escapable: bool) -> "KernelDecision":
        """This verdict as the runtime about to render it will carry it out.

        ``escapable`` is whether that runtime can put a single call outside
        its sandbox at all. One that cannot renders the plain effect: an
        intent it will not honour must not be spelled, or the verdict reads
        as escaped while the call runs confined.

        Where it can, the only pair the effect does not already say by itself
        is an approval question over a call that also escapes — the human is
        being asked two things, so the reason says both.
        """
        if not escapable:
            return KernelDecision(self.effect, self.reason)
        if self.effect == "ask" and self.sandbox == "outside":
            return KernelDecision("ask", self.reason + SANDBOX_ESCAPE_NOTICE, "outside")
        return self


def unjudged(reason: str) -> KernelDecision:
    """One machinery bail-out: the kernel cannot judge, so it defers.

    The shell boundary decides what no-judgment means: a sandboxed
    execution runs confined by the OS, an unsandboxed one converts to a
    deny naming the escalation recipe.
    """
    return KernelDecision("defer", reason)
