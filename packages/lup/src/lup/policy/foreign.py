"""Refusals lup does not make, cannot lift, and can only recognise.

A command reaching a session passes more than one gate, and only one of them
is this project's. The runtime has gates of its own, and where a runtime
refuses something lup allowed, the agent is told by that runtime in that
runtime's words -- which name neither lup's declaration nor anything a
declaration could change.

What this module holds is the difference between predicting such a gate and
recognising it. Predicting is not available: the gate is somebody else's code,
it changes on their release schedule rather than ours, and a ``hooks classify``
that answered "the verdict a live session would reach" would be claiming to
know a verdict it cannot see. Recognising is available and is worth most of
the same: the token set is small and specific, so a command carrying one can
be pointed at before it is run, as a *warning* beside the verdict rather than
as the verdict.

The distinction is the whole design. A warning that never changes an effect
cannot be wrong in the expensive direction -- the worst it does is mention a
refusal that would not have happened, where a prediction folded into the
effect would refuse work the runtime would have allowed, in lup's name, for a
gate lup does not own.
"""

import posixpath

from pydantic import BaseModel, Field

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.lex import parse_shell_words


class ForeignGate(BaseModel, frozen=True):
    """One gate belonging to a runtime, and the argv shape it refuses.

    Declared as data rather than written as a check because the value is in
    being able to say *which* gate and *whose*: an agent that reads "this
    command carries a token Claude Code's worktree isolation refuses" knows to
    stop reshaping it for lup's policy, which is the wasted work this exists
    to prevent. A bare "this may fail" would send them back to the same
    vocabulary that is not the problem.
    """

    runtime: str = Field(description="Whose gate this is, as prose addresses it")
    gate: str = Field(description="What that runtime calls the thing that refuses")
    refuses: list[str] = Field(
        default=[],
        description=(
            "Tokens refused wherever they appear in the argv, matched against "
            "each element's basename, lowercased. Position-independence is the "
            "property that makes the gate worth warning about at all: a token "
            "that only mattered as the program would be visible in the verdict "
            "already, where one that matters as a search pattern or a "
            "subcommand name is not"
        ),
    )
    leading_only: list[str] = Field(
        default=[],
        description=(
            "Tokens refused only as the first element. Kept apart from "
            "`refuses` rather than folded in, because the difference is the "
            "whole of what makes the rest over-match — the gate's author "
            "index-gated these deliberately, having found they appear in "
            "argument position constantly, which is the argument for gating "
            "the others the same way"
        ),
    )
    consequence: str = Field(
        default="",
        description="What the runtime does, in terms of what the agent loses",
    )

    def caught(self, words: list[str]) -> list[str]:
        """Which declared tokens this argv carries, in the order they appear.

        Empty where the argv carries nothing, and also where it carries a
        token and *only* that token: the gate fires on a token with at least
        one other element beside it, so a bare one passes. Modelled rather
        than rounded off, because rounding it off would warn about every
        command whose whole text is one of these words -- which is the shape
        somebody types when they are checking what the word does.
        """
        if len(words) < 2:
            return []
        return [
            token
            for index, word in enumerate(words)
            for token in [posixpath.basename(word).lower()]
            if token in self.refuses or (token in self.leading_only and index == 0)
        ]

    def warning(self, command: str) -> str:
        """What to say about this command, or nothing when there is nothing.

        Segments are flattened rather than judged one at a time, because the
        gate is not segment-aware: it reads the argv of the whole call. A
        command the lexer cannot read yields nothing, which is correct -- the
        policy has already refused it in its own words, and a second sentence
        about somebody else's gate would be noise on top of a verdict.
        """
        segments = parse_shell_words(command)
        if isinstance(segments, KernelDecision):
            return ""
        found = sorted({token for words in segments for token in self.caught(words)})
        if not found:
            return ""
        return (
            f"{self.runtime}'s {self.gate} refuses a command carrying "
            f"{self.carried(found)}, whatever this verdict says. {self.consequence}"
        )

    def carried(self, found: list[str]) -> str:
        """The tokens this command carries, each said where it actually counts.

        Two clauses rather than one, because the position matters to whoever
        is about to reshape the command: a token refused anywhere has to go,
        while one refused only at the front can stay if it moves. Saying "in
        any argv position" of a leading-only token would send a reader
        hunting for an occurrence that was never the problem.
        """
        anywhere = [token for token in found if token in self.refuses]
        leading = [token for token in found if token not in self.refuses]
        spelled = ", ".join(f"`{token}`" for token in anywhere)
        first = ", ".join(f"`{token}`" for token in leading)
        return " and ".join(
            clause
            for clause in (
                f"{spelled} in any argv position" if anywhere else "",
                f"{first} as its first word" if leading else "",
            )
            if clause
        )


WORKTREE_ISOLATION = ForeignGate(
    runtime="Claude Code",
    gate="worktree isolation",
    refuses=["eval", "alias", "source"],
    leading_only=["."],
    consequence=(
        "It is armed for the rest of a session that entered a worktree "
        "through the runtime's own tool, it is not gated on the command "
        "touching git, and lup's escalation marker does not reach it — "
        "verified byte-identical with the marker as the leading line. Run the "
        "command without the token, or open the session rooted in the "
        "worktree instead of entering one"
    ),
)
"""The gate this repository's guidance is shaped around, declared once.

Not gated on git, despite every diagnostic in the family being phrased about
git: a read-only command with no git anywhere in it is refused for carrying
the token, which is how a handful of ordinary shell words become unavailable
for the rest of a session that entered a worktree.

``.`` sits in ``leading_only`` because the gate's author put it there -- the
decompiled check reads ``s === "." ? i === 0 : A1p.has(s)`` -- and that
special-casing is the argument for the report: the three beside it appear in
argument position exactly as constantly.
"""

REACHABLE_GATES = [WORKTREE_ISOLATION]
"""The default roster, and what each runtime contributes to it.

Claude Code contributes the one entry above. **Codex contributes nothing, and
that is a measured answer rather than a gap left unwritten**: it has no
worktree-isolation rail to over-match, because it never enters a worktree
through a tool of its own, so there is no session-long armed state and no
token set to carry. A project that only ever opens Codex therefore meets
nothing here, and one that opens both meets exactly what Claude Code brings.

One roster rather than a member per runtime, because the warning is about a
command's *shape* and a reader classifying a command has not necessarily
decided which runtime will run it. A per-runtime split would also have made
Codex's contribution an empty list nothing reads, which says the same thing
where nobody looks -- this docstring is where a reader asking "what about the
other runtime" actually arrives.
"""


def foreign_warnings(command: str, gates: list[ForeignGate] | None = None) -> list[str]:
    """Every foreign gate's warning about this command, in declaration order.

    ``gates`` defaults to the gates a session of this project can actually
    meet, which is a judgement and so reaches the caller as an overridable
    default rather than as a constant they would have to fork.
    """
    return [
        said
        for gate in (REACHABLE_GATES if gates is None else gates)
        for said in [gate.warning(command)]
        if said
    ]
