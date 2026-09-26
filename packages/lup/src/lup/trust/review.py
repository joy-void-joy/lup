"""The question a changed host zone becomes, and the evidence an operator answers it on.

A launch whose host zone is not one the operator approved asks before
anything runs, and the question is an ordinary parked question in a relay --
so the review inbox lup already has reads it, with its file navigator and its
diffs, instead of a second surface being built for one kind of question. What
is particular to it is where the relay lives (the launcher's own state, never
the checkout) and where its files come from: not an operation's arguments, but
two trees in the launcher's store, named in the question's payload and
compared on demand. The record stays small however large the zone is, and the
diff shown is computed from the objects the approval will bind to.

**The base.** A change is measured against the tree this worktree was last
launched from, else the repository's most recent approval. Where there is no
base -- the first launch -- or the base's objects are missing or corrupt, the
evidence is the complete zone, every file as a creation, and the question says
which of the two it is.

**Binary content** is shown as a labelled summary of its size and object id.
A lossy decoding would put a document in front of the operator that is not the
one they are approving.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from lup.policy.operations import Operation
from lup.policy.relay import PersistentQuestion, QuestionRelay
from lup.policy.review import FilePreview, ReviewedFile
from lup.trust.objects import ObjectStore, ObjectUnreadable
from lup.trust.zone import FreeZones, HostZone, ZoneEntry, snapshot

# lup: ignore[constant-declaration] — the operation name every trust question
# carries, which the preview reader recognizes it by
TRUST_TOOL = "LaunchTrust"
"""What a launch question's operation is called, in the inbox and in the relay."""

# lup: ignore[constant-declaration] — the requester every launch question names,
# which is what keeps the operator eligible and the launcher not
LAUNCHER = "lup-launch"
"""Who asks a launch question: the installed launcher, never a session."""

# lup: ignore[constant-declaration] — the one principal a launch question may be
# answered by, and the one the terminal and the browser both answer as
OPERATOR = "operator"
"""Who answers: the person at the terminal or the inbox the launcher opened."""


class TrustEvidence(BaseModel, frozen=True):
    """What one launch question is about: two trees, and the zones they were read under."""

    worktree: str
    runtime: str
    """What answering runs: the runtime a launch opens, or a command ``lup-launch run`` hands over.

    Named for the first because every question an operator's relay already
    holds carries it under that name, and the inbox reads them all.
    """

    base: str | None
    current: str
    free: list[str]
    declared: list[str]


type ChangeKind = Literal["added", "changed", "removed"]
"""How one path of the zone differs from its base."""


class ChangedPath(BaseModel, frozen=True):
    """One path of the zone that differs from its base, and how."""

    path: PurePosixPath
    kind: ChangeKind

    def top(self) -> str:
        """Where the terminal groups it: its top directory, or itself at the root."""
        if len(self.path.parts) > 1:
            return f"{self.path.parts[0]}/"
        return self.path.as_posix()


class ZoneChange(BaseModel, frozen=True):
    """How one reading of the zone differs from its base, counted for a sentence."""

    added: int = 0
    changed: int = 0
    removed: int = 0

    @classmethod
    def of(cls, paths: list[ChangedPath]) -> "ZoneChange":
        """These paths, counted by how each differs."""
        kinds = [path.kind for path in paths]
        return cls(
            added=kinds.count("added"),
            changed=kinds.count("changed"),
            removed=kinds.count("removed"),
        )

    def total(self) -> int:
        return self.added + self.changed + self.removed

    def said(self) -> str:
        """The counts that are not zero, as the terminal says them: ``3 changed, 1 added``."""
        counts = [
            (self.changed, "changed"),
            (self.added, "added"),
            (self.removed, "removed"),
        ]
        return ", ".join(f"{count} {kind}" for count, kind in counts if count)


def files(count: int) -> str:
    """A number of files, spelled for a sentence."""
    return f"{count} file" if count == 1 else f"{count} files"


def document(entry: ZoneEntry | None, store: ObjectStore) -> str | None:
    """What one zone entry reads as in a review, ``None`` where nothing stands.

    Text is shown as the text it is. Anything that is not text -- bytes that
    do not decode, or carry a NUL -- is described instead, as are the two
    kinds of entry that are not file content at all.
    """
    if entry is None:
        return None
    match entry.mode:
        case "160000":
            return f"submodule at commit {entry.oid}\n"
        case "120000":
            target = os.fsdecode(store.read(entry.oid, "blob"))
            return f"symbolic link to {target}\n"
        case _:
            data = store.read(entry.oid, "blob")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return binary_summary(entry, data)
            return binary_summary(entry, data) if "\0" in text else text


def binary_summary(entry: ZoneEntry, data: bytes) -> str:
    """The line a binary file is shown as: its size and the object it is."""
    return f"binary file: {len(data)} bytes, git blob {entry.oid}\n"


def mode_change(
    root: Path, before: ZoneEntry | None, after: ZoneEntry | None
) -> list[ReviewedFile]:
    """A pseudo-file stating an executable bit that appeared or changed.

    A mode change leaves the document identical, so the diff alone would show
    nothing for a file that just became runnable. It is shown as its own entry,
    named after the file, so the navigator lists it and nobody approves it
    without having seen it.
    """
    if after is None:
        return []
    was = before.mode if before is not None else None
    runnable = "100755" in (was, after.mode)
    if was == after.mode or not runnable:
        return []
    return [
        ReviewedFile(
            path=root / f"{after.path.as_posix()} (file mode)",
            before=f"{was}\n" if was is not None else None,
            after=f"{after.mode}\n",
        )
    ]


def reviewed(
    root: Path,
    before: ZoneEntry | None,
    after: ZoneEntry | None,
    store: ObjectStore,
) -> list[ReviewedFile]:
    """The review entries one path contributes: its documents, and any mode change."""
    present = after if after is not None else before
    if present is None:
        return []
    documents = [
        ReviewedFile(
            path=root / present.path,
            before=document(before, store),
            after=document(after, store),
        )
    ]
    return [*documents, *mode_change(root, before, after)]


def complete_listing(
    root: Path, current: HostZone, store: ObjectStore
) -> list[ReviewedFile]:
    """Every file of the zone as a creation: what "trust it as it stands" is shown as."""
    return [
        change
        for entry in current.entries
        for change in reviewed(root, None, entry, store)
    ]


def changes(
    root: Path, base: HostZone, current: HostZone, store: ObjectStore
) -> list[ReviewedFile]:
    """Every path whose entry differs between two readings of the zone."""
    before = {entry.path: entry for entry in base.entries}
    after = {entry.path: entry for entry in current.entries}
    return [
        change
        for path in sorted({*before, *after}, key=lambda item: item.parts)
        if (before[path] if path in before else None)
        != (after[path] if path in after else None)
        for change in reviewed(
            root,
            before[path] if path in before else None,
            after[path] if path in after else None,
            store,
        )
    ]


class Baseline(BaseModel, ABC, frozen=True):
    """What a launch question measures the current zone against.

    Three answers, each saying for itself what it shows and how it is put:
    an approved snapshot to diff against, no approval at all, or an approval
    whose objects can no longer be read.
    """

    @abstractmethod
    def changed(self, current: HostZone) -> list[ChangedPath]:
        """Every path that differs from this baseline, and how."""

    @abstractmethod
    def shown(self, root: Path, current: HostZone, store: ObjectStore) -> FilePreview:
        """Every file the question asks about, as the inbox and the terminal show it."""

    @abstractmethod
    def sentence(self, change: ZoneChange) -> str:
        """What the question says about the change, after saying what answering runs."""

    @abstractmethod
    def headline(self, project: str, change: ZoneChange) -> str:
        """Why the terminal is asking, in the first line it says before it does."""

    @abstractmethod
    def tally(self, change: ZoneChange) -> str:
        """What changed in one top directory, as the lines after the headline say it."""


class ApprovedBase(Baseline, frozen=True):
    """The approved snapshot a change is measured against, read whole."""

    zone: HostZone

    def changed(self, current: HostZone) -> list[ChangedPath]:
        before = {entry.path: entry for entry in self.zone.entries}
        after = {entry.path: entry for entry in current.entries}
        return [
            ChangedPath(
                path=path,
                kind=(
                    "added"
                    if path not in before
                    else "removed"
                    if path not in after
                    else "changed"
                ),
            )
            for path in sorted({*before, *after}, key=lambda item: item.parts)
            if (before[path] if path in before else None)
            != (after[path] if path in after else None)
        ]

    def shown(self, root: Path, current: HostZone, store: ObjectStore) -> FilePreview:
        return FilePreview(files=changes(root, self.zone, current, store))

    def sentence(self, change: ZoneChange) -> str:
        return (
            f" Since the last approval, {change.added} host-zone files were added, "
            f"{change.changed} changed and {change.removed} removed."
        )

    def headline(self, project: str, change: ZoneChange) -> str:
        return (
            f"{project}'s host code changed since your last approval on this "
            f"machine ({files(change.total())}):"
        )

    def tally(self, change: ZoneChange) -> str:
        return change.said()


class FirstLaunch(Baseline, frozen=True):
    """Nothing from this repository has been approved on this machine."""

    def changed(self, current: HostZone) -> list[ChangedPath]:
        return [ChangedPath(path=entry.path, kind="added") for entry in current.entries]

    def shown(self, root: Path, current: HostZone, store: ObjectStore) -> FilePreview:
        return FilePreview(
            files=complete_listing(root, current, store),
            notice=(
                "Nothing from this repository has been approved on this machine, "
                "so this shows the complete host zone."
            ),
        )

    def sentence(self, change: ZoneChange) -> str:
        return (
            " Nothing from this repository has been approved here yet: approve its "
            f"host zone as it stands ({change.added} files)."
        )

    def headline(self, project: str, change: ZoneChange) -> str:
        return (
            f"{project}'s host code has not been approved on this machine yet "
            f"(first run, {files(change.total())}):"
        )

    def tally(self, change: ZoneChange) -> str:
        return files(change.total())


class UnreadableBase(Baseline, frozen=True):
    """An approval whose objects are missing or corrupt, and why."""

    tree: str
    reason: str

    def changed(self, current: HostZone) -> list[ChangedPath]:
        return [ChangedPath(path=entry.path, kind="added") for entry in current.entries]

    def shown(self, root: Path, current: HostZone, store: ObjectStore) -> FilePreview:
        return FilePreview(
            files=complete_listing(root, current, store),
            notice=(
                f"The approved snapshot {self.tree} could not be read "
                f"({self.reason}), so this shows the complete host zone rather "
                "than what changed since it."
            ),
        )

    def sentence(self, change: ZoneChange) -> str:
        return (
            f" The approved snapshot could not be read ({self.reason}): review "
            f"the complete host zone ({change.added} files)."
        )

    def headline(self, project: str, change: ZoneChange) -> str:
        return (
            f"{project}'s last approval on this machine could not be read "
            f"({self.reason}), so all of its host code is up for review "
            f"({files(change.total())}):"
        )

    def tally(self, change: ZoneChange) -> str:
        return files(change.total())


def baseline(store: ObjectStore, tree: str | None) -> Baseline:
    """What a change is measured against: the tree named, if its objects still read.

    Every blob is read too, not only the trees, because a snapshot whose tree
    parses and whose files are gone is no more readable than one whose tree is
    gone: the diff would stop halfway through.
    """
    if tree is None:
        return FirstLaunch()
    try:
        base = snapshot(store, tree)
        for entry in base.entries:
            if entry.mode != "160000":
                store.read(entry.oid, "blob")
    except ObjectUnreadable as error:
        return UnreadableBase(tree=tree, reason=str(error))
    return ApprovedBase(zone=base)


def evidence(root: Path, question: TrustEvidence, store: ObjectStore) -> FilePreview:
    """Every file one launch question asks about, from the trees its payload names."""
    return baseline(store, question.base).shown(
        root, snapshot(store, question.current), store
    )


class TrustPreview:
    """What the inbox calls to learn a question's files, launch questions included.

    Every other question keeps the preview its own arguments carry, so the one
    inbox the launcher serves reads a launch question from the store and would
    read anything else the ordinary way. Computed once per question and kept,
    because a snapshot is immutable and the inbox asks again every second.
    """

    def __init__(
        self,
        root: Path,
        store: ObjectStore,
        otherwise: Callable[[PersistentQuestion], FilePreview],
    ) -> None:
        self.root = root
        self.store = store
        self.otherwise = otherwise
        self.computed: dict[str, FilePreview] = {}

    def __call__(self, question: PersistentQuestion) -> FilePreview:
        if question.operation.tool != TRUST_TOOL:
            return self.otherwise(question)
        if question.fingerprint not in self.computed:
            asked = TrustEvidence.model_validate(question.operation.payload)
            self.computed[question.fingerprint] = evidence(self.root, asked, self.store)
        return self.computed[question.fingerprint]


def freed(declared: FreeZones, approved: list[PurePosixPath] | None) -> str:
    """The sentence saying how a checkout's free zones differ from the approved ones."""
    if approved is None:
        return (
            f"Free zones declared: {', '.join(declared.spelled())}."
            if declared.free
            else ""
        )
    before = FreeZones(free=approved)
    added = [zone for zone in declared.free if zone not in before.free]
    removed = [zone for zone in before.free if zone not in declared.free]
    if not added and not removed:
        return ""
    spelled = [
        *(f"+ {zone.as_posix()}/" for zone in added),
        *(f"- {zone.as_posix()}/" for zone in removed),
    ]
    return f"Free zones would change: {', '.join(spelled)}."


def launch_question(
    root: Path,
    asked: TrustEvidence,
    reason: str,
) -> PersistentQuestion:
    """The parked question one unapproved launch asks its operator."""
    operation = Operation(
        id=f"launch-{asked.current}",
        session=LAUNCHER,
        requester=LAUNCHER,
        tool=TRUST_TOOL,
        payload=asked.model_dump(mode="json"),
        cwd=root,
        worktree=root,
        kind="process_execution",
        placement="outside",
    )
    return PersistentQuestion(
        id=f"launch-{uuid4().hex}",
        operation=operation,
        fingerprint=PersistentQuestion.review_fingerprint(operation, None),
        reason=reason,
        rule="trust-on-launch",
        purpose="untrusted_dependency",
        requirement="human_only",
        eligible=[OPERATOR],
    )


def asked_once(
    relay: QuestionRelay, question: PersistentQuestion
) -> PersistentQuestion:
    """The pending question for this evidence, recorded if nobody asked it yet.

    A launch interrupted while it waited leaves its question pending; the next
    launch over the same trees asks the same question rather than a second
    copy of it, so an answer given to either settles both.
    """
    with relay.transaction():
        waiting = next(
            (
                entry
                for entry in relay.pending()
                if entry.fingerprint == question.fingerprint
            ),
            None,
        )
        return waiting if waiting is not None else relay.record(question)


def question_reason(
    named: str,
    root: Path,
    base: Baseline,
    current: HostZone,
    free_sentence: str,
) -> str:
    """What the operator reads first: what answering lets run, and what changed."""
    opening = (
        f"Launching {named} from {root} runs this checkout's code on this machine."
    )
    return (
        opening
        + base.sentence(ZoneChange.of(base.changed(current)))
        + (f" {free_sentence}" if free_sentence else "")
    )


def explanation(
    project: str,
    named: str,
    base: Baseline,
    current: HostZone,
    free_sentence: str,
) -> list[str]:
    """What the terminal says once, before the inbox opens: why it asks, and what then.

    Why, in one line; what changed, one line per top directory, so a first
    run of a large project is a screenful rather than a listing of every
    file; how the free zones move, where they do; and what approving runs.
    Every file and its diff are the inbox's, and the terminal's on ``d``.
    """
    paths = base.changed(current)
    tops = sorted({path.top() for path in paths})
    width = max((len(top) for top in tops), default=0)
    return [
        base.headline(project, ZoneChange.of(paths)),
        *(
            f"  {top:<{width}}  "
            + base.tally(ZoneChange.of([path for path in paths if path.top() == top]))
            for top in tops
        ),
        *([free_sentence] if free_sentence else []),
        f"{named} runs after you approve.",
    ]
