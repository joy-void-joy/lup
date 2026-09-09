"""Claims, the evidence that backs them, and the corrections that retire them.

A corpus is a body of claims somebody is prepared to be held to, together with
what backs each one and what has since retired it. Every type here answers
``standing`` over its neighbourhood and stores none of it, which is the
invariant the whole design rests on: a claim cannot outrun its artifact and
cannot keep a label its evidence stopped supporting, because nothing ever
wrote the label down. Two things earned that rule its keep in the repository
it came from — a dead session's evidence all read as rejected the moment
anybody looked, and one landing invalidated ten keystone claims at once — and
both were the system noticing rather than a person.

**Evidence rots against files.** A piece of evidence carries the digests of
every file it was checked against, so it stops standing the moment one of
them changes. That is read from the working tree at the time somebody asks,
which is why the neighbourhood carries a root: on a machine with no tree the
honest answer is "unchecked", and the type says so rather than guessing.

**A claim refuses to hide contradiction.** Holding both a live counterexample
and live support, it says so instead of picking a side, because a reader who
was shown one of the two and not the other would be shown a lie by omission.

**Corrections supersede partially.** The register this shape came from wrote
each entry as what was wrong, what survives, and what changes — and the last
two are about the *relation* to the superseded node, so they live on the edge
rather than the correction. A boolean would have thrown the survivors away.
"""

from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field

from lup.ledger.models import LedgerEdge, LedgerNode, Standing, Surroundings


def digest_of(path: Path) -> str:
    """The content digest of one file, or nothing where there is no file."""
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


class Scoped(BaseModel, frozen=True):
    """One file a piece of evidence was checked against, as it was then."""

    path: str = Field(min_length=1)
    """Relative to the working tree, so the same record reads in every checkout."""

    digest: str


class Validation(BaseModel, frozen=True):
    """What one piece of evidence was checked as, over which files, by what.

    Three facts and each is load-bearing. The schema says which checker's
    word this is, so a certificate from a kernel and a hash from a script are
    not the same kind of thing. The subject digest pins what was checked. The
    scope pins what it was checked *against* — and that is the part that
    rots, because a proof over three files is a proof over those three files
    as they were.
    """

    schema_id: str = Field(min_length=1)
    subject_digest: str = Field(min_length=1)
    scope: list[Scoped] = []

    def drifted(self, root: Path) -> list[str]:
        """Every scoped path whose content is no longer what was checked."""
        return [
            scoped.path
            for scoped in self.scope
            if digest_of(root / scoped.path) != scoped.digest
        ]


class Evidence(LedgerNode, frozen=True):
    """Bytes that bear on a claim, with the validation that says what they are.

    The bytes ride as the node's attachments, under their own digest, so two
    pieces of evidence with the same bytes are one blob and nothing recorded
    later can change what an earlier one pointed at. What this adds is only
    the validation — and the answer to whether it still holds. The two kinds
    below share it and differ in one word, because a reader ranks a checker's
    output and a person's differently and should be able to.
    """

    validation: Validation

    def prepared(self, root: Path) -> Self:
        """The scope pinned to the tree as it is now, for any path recorded bare.

        A caller names the files evidence was checked against; the digests are
        this type's to take, at the one moment they are true. A scoped path
        that already carries a digest is left alone, so a record replayed from
        another machine keeps what it was checked against there.
        """
        pinned = [
            scoped
            if scoped.digest
            else Scoped(path=scoped.path, digest=digest_of(root / scoped.path))
            for scoped in self.validation.scope
        ]
        return self.model_copy(
            update={"validation": self.validation.model_copy(update={"scope": pinned})}
        )

    def standing(self, around: Surroundings) -> Standing:
        """Fresh while every scoped file is as it was; stale the moment one is not.

        Unchecked where there is no tree to read, which is true on a snapshot
        read elsewhere, and is reported as sound: a reader that cannot check
        has no grounds to say the evidence went away.
        """
        if around.root is None:
            return Standing(label="unchecked", reason="no working tree to read")
        gone = self.validation.drifted(around.root)
        if gone:
            return Standing(
                label="stale",
                reason=f"{', '.join(gone)} changed since it was checked",
                sound=False,
            )
        return Standing(label="fresh")


class Artifact(Evidence, frozen=True):
    """Evidence a person or a script produced: a log, a table, a measurement."""

    kind: Literal["corpus:artifact"] = "corpus:artifact"


class Certificate(Evidence, frozen=True):
    """Evidence a checker produced, whose schema names the checker.

    A certificate's word is that checker's word about the subject digest,
    which is a stronger thing than an artifact and is recorded as its own
    kind so nothing has to guess from the schema id.
    """

    kind: Literal["corpus:certificate"] = "corpus:certificate"


class Source(LedgerNode, frozen=True):
    """External bytes a claim rests on, kept under their own digest.

    A source is what a claim was read *from* — a paper, a dataset, a page —
    and the point of recording one is that it cannot move or change: the
    bytes are the node's attachment, the origin says where they were found,
    and a claim citing them cites those bytes and not whatever the origin
    serves next year.
    """

    kind: Literal["corpus:source"] = "corpus:source"
    origin: str = Field(min_length=1)


class Correction(LedgerNode, frozen=True):
    """Something recorded earlier was wrong, and here is what to know now.

    Append-only like everything else: the wrong node stays, readable, with
    this pointing at it. What survives of it and what changes are on the
    ``supersedes`` edge, because they are facts about the pair.
    """

    kind: Literal["corpus:correction"] = "corpus:correction"
    where: str = Field(min_length=1)
    """What the mistake was found in — a document, a figure, a node id."""

    wrong: str = Field(min_length=1)
    lesson: str = ""


class Claim(LedgerNode, frozen=True):
    """One statement somebody is prepared to be held to, graded in their words.

    The grade is uninterpreted here. What grades a project uses, and what
    each is worth, is the project's vocabulary; a library that fixed the words
    would be one every adopter argued with. What this type answers is not how
    good the claim is but whether what backs it is still there.
    """

    kind: Literal["corpus:claim"] = "corpus:claim"
    grade: str = ""

    def standing(self, around: Surroundings) -> Standing:
        """Where this claim stands, read from what points at it right now.

        Superseded first, because a correction outranks every piece of
        evidence the corrected claim ever had. Then the evidence, each piece
        asked whether it itself still stands — an artifact over a changed file
        counts for nothing — and the answer refuses to hide a contradiction.
        """
        superseding = [
            edge.source for edge in around.incoming if edge.kind == "corpus:supersedes"
        ]
        if superseding:
            return Standing(
                label="superseded",
                reason=f"corrected by {', '.join(superseding)}",
                sound=False,
            )

        def evidence(kind: str) -> list[LedgerNode]:
            return [
                node
                for edge in around.incoming
                if edge.kind == kind and (node := around.at(edge.source)) is not None
            ]

        def still_standing(nodes: list[LedgerNode]) -> list[LedgerNode]:
            return [
                node
                for node in nodes
                if node.standing(Surroundings(root=around.root)).sound
            ]

        support = evidence("corpus:supports")
        against = evidence("corpus:refutes")
        live_support = still_standing(support)
        live_against = still_standing(against)
        verified = any(edge.kind == "corpus:verifies" for edge in around.incoming)

        if live_against and live_support:
            return Standing(
                label="contradicted",
                reason=(
                    f"{len(live_against)} counterexample(s) and "
                    f"{len(live_support)} supporting artifact(s) both stand"
                ),
                sound=False,
            )
        if live_against:
            return Standing(
                label="refuted",
                reason=f"{len(live_against)} counterexample(s) stand",
                sound=False,
            )
        if support and not live_support:
            withered = [
                node.standing(Surroundings(root=around.root)).reason for node in support
            ]
            return Standing(
                label="stale",
                reason="; ".join(reason for reason in withered if reason),
                sound=False,
            )
        if live_support:
            return Standing(
                label="verified" if verified else "supported",
                reason=f"{len(live_support)} artifact(s) stand",
            )
        return Standing(label="unsupported", reason="no evidence attached")


class Supports(LedgerEdge, frozen=True):
    """This evidence is for that claim."""

    kind: Literal["corpus:supports"] = "corpus:supports"


class Refutes(LedgerEdge, frozen=True):
    """This evidence is a counterexample to that claim."""

    kind: Literal["corpus:refutes"] = "corpus:refutes"


class Verifies(LedgerEdge, frozen=True):
    """Somebody other than the author checked that claim and stands by it.

    The one rule this library keeps about who may say what, and it is a
    property of the relation: only the edge sees both ends, so only the edge
    can refuse an author verifying their own work.
    """

    kind: Literal["corpus:verifies"] = "corpus:verifies"

    def refusal(self, source: LedgerNode, target: LedgerNode) -> str:
        del source
        if target.author.id == self.author.id:
            return "a verification of your own work is not one"
        return ""


class Supersedes(LedgerEdge, frozen=True):
    """This correction retires that node — partially, and it says which parts.

    What changes may not be empty: a correction that changes nothing is a
    note, not a correction. What survives may be, and often is not, which is
    the whole reason this is not a boolean.
    """

    kind: Literal["corpus:supersedes"] = "corpus:supersedes"
    changes: list[str] = Field(min_length=1)
    survives: list[str] = []
