"""The drafts of a worktree: changes waiting beside their files to be submitted.

A write the operator must review goes into a draft instead of its file
(`docs/review-flow.md`, *Drafts*): one draft per file, per worktree, shared by a
session and its subagents. It's written at `.lup/drafts/<path>`, which git
ignores, so no snapshot, commit or test sees it while the agent keeps editing it.
Each segment of `<path>` that starts with a dot has the dot written `%2E`, since a
runtime may refuse a hook-approved write into a directory it protects, `.git/`
among them, at any depth; one that starts with `%` has it written `%25`, so each
draft's path reads back to one file.

What lup knows of each draft is kept in the worktree's store
(`StoreLayout.drafts`): its file, its base (the file's accepted content when the
draft began, kept as an object in the store), the conversation that began it, a
rename's old path, and the review it was last submitted in. A draft stands while
its file does: the agent drops one by deleting its file, and from then on its
record reads as gone until something forgets it.

Every method reads or writes the record, so its caller holds the store's lock, as
a checkpoint does. Merging a shell write into a draft, and rebasing a draft on a
file that moved under it, come with the checkpoint's part of the flow.
"""

import shutil
from pathlib import Path

from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout
from lup_dev.policy.store import Store, read_model, write_model

# lup: defer(issue=43, why="drop the escaping once lup generates the runtimes' own directories, when no draft of a file in one is written")
ESCAPED = {".": "%2E", "%": "%25"}
"""How a path segment's first character is written in a draft's path, where it's
one of these."""


class DraftError(LupDevError):
    """A draft can't be begun or found as asked."""


def escaped(segment: str) -> str:
    """Write one segment of a file's path as its draft's path holds it.

    >>> [escaped(each) for each in [".git", "%2Ex", "core.py"]]
    ['%2Egit', '%252Ex', 'core.py']
    """
    return next(
        (
            written + segment.removeprefix(first)
            for first, written in ESCAPED.items()
            if segment.startswith(first)
        ),
        segment,
    )


def unescaped(segment: str) -> str:
    """Read one segment of a draft's path back as its file's path holds it.

    >>> [unescaped(each) for each in ["%2Egit", "%252Ex", "core.py"]]
    ['.git', '%2Ex', 'core.py']
    """
    return next(
        (
            first + segment.removeprefix(written)
            for first, written in ESCAPED.items()
            if segment.startswith(written)
        ),
        segment,
    )


def drafted(worktree: Path, path: Path) -> Path:
    """Return the file `path` names, from the worktree's root: it, or the file it drafts.

    `path` is absolute, or from the root of the worktree at `worktree`; a draft's
    path names the file it's a draft of.

    >>> drafted(Path("/w"), Path("/w/.lup/drafts/%2Egit/info/exclude"))
    PosixPath('.git/info/exclude')
    >>> drafted(Path("/w"), Path("src/core.py"))
    PosixPath('src/core.py')
    """
    if path.is_absolute() and not path.is_relative_to(worktree):
        message = f"{path} isn't in the worktree at {worktree}"
        raise DraftError(message)
    relative = path.relative_to(worktree) if path.is_absolute() else path
    if ".." in relative.parts:
        message = f"{path} climbs out of the directory it names, which no file does"
        raise DraftError(message)
    drafts = CheckoutLayout(root=Path()).drafts
    if not relative.is_relative_to(drafts):
        return relative
    file = Path(*(unescaped(part) for part in relative.relative_to(drafts).parts))
    if not file.parts:
        message = f"{path} is where drafts are written, not a draft"
        raise DraftError(message)
    return file


def draft_path(worktree: Path, file: Path) -> Path:
    """Say where `file`'s draft is written, in the worktree at `worktree`.

    `file` is absolute, from the worktree's root, or the draft's own path.

    >>> draft_path(Path("/w"), Path(".git/info/exclude"))
    PosixPath('/w/.lup/drafts/%2Egit/info/exclude')
    """
    named = drafted(worktree, file)
    return CheckoutLayout(root=worktree).drafts.joinpath(
        *(escaped(part) for part in named.parts)
    )


class Conversation(Model):
    """One conversation of a session: its own, or one of its subagents'."""

    session: str
    agent: str = ""
    """The subagent, blank for the session's own conversation."""


class Draft(Model):
    """What lup knows of one file's draft; the draft itself is a file.

    Its path is the file's, escaped under `.lup/drafts/` (`draft_path`).
    """

    file: Path
    """The file it drafts, from the worktree's root."""
    base: str | None
    """The object id, in the store, of the file's accepted content when the draft
    began, or that it was last applied as; none where the file didn't exist."""
    began: Conversation
    renamed_from: Path | None = None
    """The file's old path, where the draft moves it from there."""
    submission: int | None = None
    """The review it was last submitted in, by its number; none before."""


class Recorded(Model):
    """The record of a worktree's drafts, as its store keeps it."""

    drafts: list[Draft] = []


class Drafts(Model):
    """The drafts of one worktree, read from and kept in its store.

    Its caller holds the store's lock.
    """

    store: Store

    @property
    def root(self) -> Path:
        """The worktree's root."""
        return self.store.worktree

    def recorded(self) -> list[Draft]:
        """Return every draft recorded, standing or dropped, in the order they began."""
        return (read_model(self.store.layout.drafts, Recorded) or Recorded()).drafts

    def path(self, draft: Draft) -> Path:
        """Say where `draft` is written."""
        return draft_path(self.root, draft.file)

    def all(self) -> list[Draft]:
        """Return every draft standing, in the order they began."""
        return [draft for draft in self.recorded() if self.path(draft).is_file()]

    def of(self, path: Path) -> Draft | None:
        """Return the draft standing for `path`, a file or its draft's path; or none.

        `path` is absolute, or from the worktree's root. A draft written with no
        record has none until it's begun.
        """
        file = drafted(self.root, path)
        return next((draft for draft in self.all() if draft.file == file), None)

    def begin(self, path: Path, began: Conversation, *, copy: bool = False) -> Draft:
        """Begin the draft of `path`, a file or its draft's path, and return it.

        Its base is the file's accepted content. With `copy`, the file as it
        stands is copied to the draft's path, for an edit to go on from it, unless
        a draft is written there already: the draft written stands. Without, the
        draft is what's written there, by the call it's begun for or before. A file
        with a draft standing refuses, and so does a worktree with no accepted
        tree yet, where a draft would have no base.
        """
        file = drafted(self.root, path)
        standing = self.of(file)
        if standing is not None:
            message = (
                f"{self.root / file} has a draft already, at {self.path(standing)}"
            )
            raise DraftError(message)
        accepted = self.store.accepted()
        if accepted is None:
            message = (
                f"no content is accepted in {self.root} yet, so a draft there would "
                "have no base: a session begins there first"
            )
            raise DraftError(message)
        target = draft_path(self.root, file)
        source = self.root / file
        if copy and not target.exists():
            if not source.is_file():
                message = (
                    f"{source} isn't a file, so there's nothing to copy into its draft"
                )
                raise DraftError(message)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        draft = Draft(file=file, base=self.store.blob(accepted, file), began=began)
        dropped = [each for each in self.recorded() if each.file != file]
        write_model(self.store.layout.drafts, Recorded(drafts=[*dropped, draft]))
        return draft

    def keep(self, draft: Draft) -> Draft:
        """Record `draft` in place of what was recorded for its file; return it."""
        recorded = self.recorded()
        kept = (
            [draft if each.file == draft.file else each for each in recorded]
            if any(each.file == draft.file for each in recorded)
            else [*recorded, draft]
        )
        write_model(self.store.layout.drafts, Recorded(drafts=kept))
        return draft

    def forget(self, path: Path) -> None:
        """Forget the draft of `path`, a file or its draft's path: its file and record.

        The directories left empty under `.lup/drafts/` go with it.
        """
        file = drafted(self.root, path)
        target = draft_path(self.root, file)
        target.unlink(missing_ok=True)
        top = CheckoutLayout(root=self.root).drafts
        emptied = [
            parent
            for parent in target.parents
            if parent.is_relative_to(top) and parent != top
        ]
        for parent in emptied:
            if not parent.is_dir() or any(parent.iterdir()):
                break
            parent.rmdir()
        others = [each for each in self.recorded() if each.file != file]
        write_model(self.store.layout.drafts, Recorded(drafts=others))
