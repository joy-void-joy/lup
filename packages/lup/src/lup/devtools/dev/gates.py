# lup: ignore[import-re, re-call]
# The marker head this reads is `lup.codescan.markers` syntax, matched the way
# that module matches the rest of it; no format with a parser of its own is
# involved on either side.
"""The wake conditions a deferral states, in spellings the checker resolves.

A `# lup: defer[<condition>]:` note parks work behind something other than
this note can check. Every such condition was prose, rendered into the notes
listing and read by whoever happened to look — which is the half of a gate
that does not work. A deferral is dormant precisely because it is correct to
be dormant now, so nobody has any reason to read it until the moment it stops
being correct, and that is the one moment nothing announced.

So a condition written in one of the spellings below is *resolved* rather
than printed. Each names a fact about this checkout that has a definite
answer offline — a branch reaching integration, a path ceasing to exist — and
`dev check` asks it on every run. While the answer is no the note stays where
it was, listed among the other deferrals and gating nothing. When the answer
turns yes the check fails, once, at the moment the condition the author named
actually came true.

Prose keeps working and keeps meaning what it meant. A condition this module
does not recognise is not an error and not a typo to be corrected: "until the
v2 API ships" is a real gate that this checkout simply cannot see, and the
listing carrying it to a reader is the whole of what it ever did. What
changes is only that a condition which *can* be resolved no longer settles
for being read.

The spellings are a union rather than a table of branches, so naming another
kind of fact is adding a member that answers for itself. Each takes the
`<keyword>:<argument>` shape, which is what keeps prose and gate
distinguishable without either having to be quoted or escaped: a keyword is
one word, so prose that happens to contain a colon names no keyword this
union declares and falls through to being prose.
"""

import re
from pathlib import Path
from typing import ClassVar

import sh
from pydantic import BaseModel

from lup.devtools.dev.branches import get_integration_branch, is_ancestor
from lup.devtools.dev.comments import FoundComment
from lup.devtools.utils import git
from lup.workspace.paths import project_root

# A resolvable condition is `<keyword>:<argument>`, and the keyword is a
# single word — which is what separates it from prose that merely contains a
# colon. Matched rather than split because the shape is structured, and a
# pattern stating the whole of it at once cannot half-match the way a split
# followed by a length check can. The argument runs to the end, newlines
# included, because a continuation line joins into a note's text before this
# ever sees it.
GATE_RE = re.compile(r"^(?P<keyword>[\w-]+)\s*:\s*(?P<argument>.*)$", re.DOTALL)


class GateVerdict(BaseModel, frozen=True):
    """Whether a condition has come true, and what the tree said when asked.

    ``evidence`` is what the checkout answered rather than a restatement of
    the gate, because a woken deferral is read by somebody who did not write
    it and is deciding whether to act now. "has reached dev" tells them the
    thing they would otherwise go and check by hand; "the gate fired" sends
    them to do it.
    """

    fired: bool
    evidence: str


class Gate(BaseModel, frozen=True):
    """One deferral's condition, spelled so this checkout can resolve it.

    ``keyword`` is the word before the colon, and belongs to the class rather
    than to an instance: it is what the spelling *is*, so a member owns it the
    way it owns its own name. ``argument`` is everything after, unparsed,
    because what a keyword takes is that keyword's business.
    """

    keyword: ClassVar[str]
    argument: str

    def asked(self) -> GateVerdict:
        """Whether this checkout says the condition has come true."""
        raise NotImplementedError

    def spelling(self) -> str:
        """This gate written the way it appears inside the bracket."""
        return f"{self.keyword}:{self.argument}"


class BranchLanded(Gate, frozen=True):
    """`branch:<name>` — fires once that branch reaches the integration branch.

    A branch that no longer exists fires too, and says so. The likeliest
    reading is that it landed and was pruned, which is exactly the condition
    stated; the other reading is that it was abandoned, which is also a moment
    the note wants somebody at. Reporting "cannot tell" would leave the one
    case a deferral behind a branch exists to catch sitting silent, so it
    fires and the evidence says which question to go and settle.
    """

    keyword: ClassVar[str] = "branch"

    def asked(self) -> GateVerdict:
        if not self.argument:
            return GateVerdict(fired=True, evidence="names no branch")
        integration = get_integration_branch()
        try:
            git("rev-parse", "--verify", "--quiet", f"{self.argument}^{{commit}}")
        except sh.ErrorReturnCode:
            return GateVerdict(
                fired=True,
                evidence=(
                    f"{self.argument} no longer exists — landed and pruned, or "
                    "abandoned; either way it is not still on its way in"
                ),
            )
        if is_ancestor(self.argument, integration):
            return GateVerdict(
                fired=True, evidence=f"{self.argument} has reached {integration}"
            )
        return GateVerdict(
            fired=False, evidence=f"{self.argument} has not reached {integration}"
        )


class PathGone(Gate, frozen=True):
    """`gone:<path>` — fires once that path no longer exists.

    Resolved against the project root rather than the working directory, so
    the gate says the same thing from wherever the check was run.
    """

    keyword: ClassVar[str] = "gone"

    def asked(self) -> GateVerdict:
        if not self.argument:
            return GateVerdict(fired=True, evidence="names no path")
        if (project_root() / Path(self.argument)).exists():
            return GateVerdict(fired=False, evidence=f"{self.argument} still exists")
        return GateVerdict(fired=True, evidence=f"{self.argument} is gone")


DECLARED_GATES: list[type[Gate]] = [BranchLanded, PathGone]
"""Every spelling a bracketed deferral can be resolved in.

A list of the members rather than a keyword-to-class mapping written out
beside them, because the keyword is already on the class and a second copy of
it here is the pair that drifts.
"""


def parse_gate(
    condition: str | None, declared: list[type[Gate]] = DECLARED_GATES
) -> Gate | None:
    """The gate a condition spelled, or ``None`` where it stated prose.

    ``None`` covers three things that are all the same thing to a caller: a
    deferral that stated no condition at all, one whose condition names no
    keyword this union declares, and one whose condition is prose that happens
    to contain a colon. Each is a note this checkout cannot resolve and must
    therefore carry to a reader, which is what the listing already does.
    """
    if condition is None:
        return None
    stated = GATE_RE.match(condition)
    if stated is None:
        return None
    for gate in declared:
        if gate.keyword == stated.group("keyword"):
            return gate(argument=stated.group("argument").strip())
    return None


class WokenDeferral(BaseModel, frozen=True):
    """A parked note whose stated condition this checkout says has come true."""

    file: str
    start_line: int
    end_line: int
    gate: str
    evidence: str
    text: str

    def reported(self) -> str:
        """This deferral as the failing check prints it.

        The note's own words come last and whole. What woke it is a line
        somebody skims; what it asked for is the thing they have to act on,
        and a deferral trimmed to fit a report is one whose instruction has to
        be gone and found in the file the report was supposed to save the trip
        to.
        """
        return (
            f"  {self.file}:{self.start_line}-{self.end_line}  "
            f"[{self.gate}] {self.evidence}\n    {self.text}"
        )


class GateSweep(BaseModel, frozen=True):
    """Every resolvable gate this tree carries, and which of them fired.

    ``asked`` counts the gates resolved rather than the notes scanned, because
    that is the number saying whether this check is doing anything: a tree
    whose deferrals are all prose asks nothing, and a line reporting "ok"
    over no gates at all would read as a guarantee it never made.
    """

    asked: int
    woken: list[WokenDeferral]

    def lines(self) -> list[str]:
        """The check's header and one entry per woken deferral."""
        if not self.woken:
            return [f"woken deferrals: ok, {self.asked} gate(s) asked"]
        header = (
            f"woken deferrals: FAIL ({len(self.woken)} of {self.asked} gate(s) fired)"
        )
        return [header, *(deferral.reported() for deferral in self.woken)]


def sweep_gates(
    found: list[FoundComment], declared: list[type[Gate]] = DECLARED_GATES
) -> GateSweep:
    """Resolve every bracketed deferral in *found* that names a declared gate.

    Notes that stated prose are not counted as asked. They were never a
    question this checkout could put, so folding them into the total would
    report coverage the sweep does not have.
    """
    asked = 0
    woken: list[WokenDeferral] = []  # lup: ignore[empty-collection] — scan fold
    for comment in found:
        gate = parse_gate(comment.condition, declared)
        if gate is None:
            continue
        asked += 1
        verdict = gate.asked()
        if not verdict.fired:
            continue
        woken.append(
            WokenDeferral(
                file=comment.file,
                start_line=comment.start_line,
                end_line=comment.end_line,
                gate=gate.spelling(),
                evidence=verdict.evidence,
                text=comment.text,
            )
        )
    return GateSweep(asked=asked, woken=woken)
