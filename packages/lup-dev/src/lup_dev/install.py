"""Installing the judge: the operator reviews its source before a copy of it runs.

The judge that runs is a copy installed from a checkout of lup (`uv tool install`),
never a worktree's own source, so an agent's edit can't change what judges it
(`docs/judging-writes.md`, *Where things live*). Refreshing the copy shows the
operator every file it carries that changed since the commit they last approved,
and until they approve, the copy installed before keeps judging (decision 26):
1. refuse inside an agent's session, and refuse a checkout whose judge source has
   changes not committed, since the copy would carry what the review didn't show;
2. list the files the judge carries that changed since the commit approved last,
   or all of them the first time; where none did, stop;
3. build the engine (`packages/lup-dev/checker/build.py`);
4. show each changed file whole on both sides to a `Reviewer`, and wait for its
   answer: the first lup's dashboard in the bridge (`lup_dev.legacy_dashboard`),
   or the terminal;
5. approved, check again that `HEAD` is the commit reviewed and that the judge's
   source is committed, install `packages/lup-dev` with `uv tool install`, its
   dependencies held to the versions `uv.lock` pins, and record the commit.
"""

import difflib
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

import sh
import typer
from pydantic import Field
from rich.console import Console
from rich.text import Text

from lup.types import Model
from lup_dev.catalog.gate import Gate, Step
from lup_dev.clock import Clock
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout, Layout
from lup_dev.policy.runtime import Runtime
from lup_dev.policy.store import Git, nul_separated, read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Iterator


class InstallError(LupDevError):
    """The judge can't be installed from this checkout, or by whoever asked."""


class Approval(Model):
    """The commit of lup the operator approved as the judge that runs."""

    commit: str
    time: datetime
    checkout: Path
    """The checkout it was installed from."""


class ChangedFile(Model):
    """One file the judge carries, changed since the commit approved last."""

    path: Path
    """Its path in the checkout."""
    before: str | None
    """Its text at the commit approved last; none where it wasn't there."""
    after: str | None
    """Its text at `HEAD`; none where it's deleted."""

    def kind(self) -> Literal["created", "deleted", "modified"]:
        """Say whether the change creates the file, deletes it or modifies it."""
        if self.before is None:
            return "created"
        if self.after is None:
            return "deleted"
        return "modified"


class Review(Model):
    """What the operator reads before approving: the judge's files that changed."""

    since: str | None
    """The commit approved last; none for the first install."""
    commit: str
    """The commit the copy would be installed from."""
    files: list[ChangedFile]
    shortstat: str
    """git's one-line count of the change (`git diff --shortstat`)."""

    def heading(self) -> str:
        """Say which commit is reviewed, since which, and how much changed."""
        since = (
            f"since {self.since}, the commit you approved last"
            if self.since
            else "whole, since no copy was approved yet"
        )
        return f"The judge at {self.commit}: its source {since}: {self.shortstat}."


class LineComment(Model):
    """One comment the operator anchored to lines of a file the review showed."""

    path: Path
    """The file's path in the checkout."""
    first: int
    last: int
    side: Literal["before", "after"]
    """Which text the lines number: `before`, the file at the commit approved last;
    `after`, the file at `HEAD`."""
    note: str

    def text(self, since: str | None) -> str:
        """Say where the comment points, then what it says, naming the commit before."""
        lines = (
            str(self.first) if self.first == self.last else f"{self.first}-{self.last}"
        )
        side = f"before, at {since}" if self.side == "before" and since else self.side
        body = "\n    ".join(self.note.splitlines())
        return f"{self.path}:{lines} ({side}): {body}"


class Answer(Model):
    """The operator's answer to the judge's review, with what they wrote on it."""

    approved: bool
    note: str = ""
    comments: list[LineComment] = []

    def said(self, since: str | None) -> list[str]:
        """Return the note and the line comments as the terminal prints them."""
        note = (
            ["Your note:", *(f"    {line}" for line in self.note.splitlines())]
            if self.note
            else []
        )
        comments = (
            [
                "Your line comments:",
                *(f"  {comment.text(since)}" for comment in self.comments),
            ]
            if self.comments
            else []
        )
        return [*note, *comments]


class Unchanged(Model):
    """Nothing the judge carries changed since the commit approved last.

    Nothing was built, asked, installed or recorded, so the commit approved last
    stays one the operator reviewed.
    """

    commit: str
    since: str | None

    def report(self) -> str:
        """Say what came of the install, in one line."""
        return (
            f"Nothing the judge carries changed between {self.since}, the commit you "
            f"approved last, and {self.commit}: nothing to review or install."
        )


class Declined(Model):
    """The operator declined the judge's review: the copy installed before stays."""

    commit: str
    since: str | None
    answer: Answer

    def report(self) -> str:
        """Say what came of the install, with what the operator wrote."""
        return "\n".join(
            [
                (
                    f"Declined: the judge at {self.commit} isn't installed, and the "
                    "copy installed before keeps judging."
                ),
                *self.answer.said(self.since),
            ]
        )


class Installed(Model):
    """The operator approved the judge's review, and its copy is installed."""

    approval: Approval
    since: str | None
    answer: Answer

    def report(self) -> str:
        """Say what came of the install, with what the operator wrote."""
        return "\n".join(
            [
                (
                    f"Installed the judge at {self.approval.commit}; it judges from "
                    "here on."
                ),
                *self.answer.said(self.since),
            ]
        )


type Outcome = Unchanged | Declined | Installed
"""What `Installer.install` came to: nothing to review, declined, or installed."""


class Toolchain(Model, ABC):
    """What builds the engine and installs the judge's copy."""

    @abstractmethod
    def build(self, checkout: Path) -> None:
        """Build the engine in the checkout of lup at `checkout`."""

    @abstractmethod
    def install(self, checkout: Path) -> None:
        """Install the judge from the checkout at `checkout`, replacing any copy."""


def engine() -> Step:
    """Return the gate's step that builds the engine, which the installer runs too."""
    return next(step for step in Gate().steps if step.builds is not None)


class Uv(Toolchain):
    """uv, building the engine as the gate does and installing as a uv tool."""

    executable: str = "uv"
    engine: Step = Field(default_factory=engine)
    """How the engine is built: the gate's own step, so the two never differ."""

    @override
    def build(self, checkout: Path) -> None:
        program, *arguments = self.engine.command
        sh.Command(program)(*arguments, _cwd=str(checkout), _fg=True)

    @override
    def install(self, checkout: Path) -> None:
        """Install a copy of `lup-dev`, its dependencies held to `uv.lock`.

        `uv tool install` resolves a tool's dependencies afresh, ignoring the
        workspace's lockfile, so the locked versions are exported as constraints.
        `lup`, a workspace source, is installed from the checkout as a copy.
        """
        uv = sh.Command(self.executable)
        tool = CheckoutLayout(root=checkout).tool
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            uv(
                "export",
                "--package",
                tool.name,
                "--no-dev",
                "--no-emit-workspace",
                "--no-hashes",
                "--frozen",
                "--format",
                "requirements-txt",
                "--quiet",
                "--output-file",
                str(constraints),
                _cwd=str(checkout),
            )
            uv(
                "tool",
                "install",
                "--force",
                "--constraints",
                str(constraints),
                str(tool),
                _cwd=str(checkout),
                _fg=True,
            )


class Reviewer(ABC):
    """Who answers the judge's review: the operator, in a dashboard or the terminal."""

    @abstractmethod
    def answer(self, review: Review) -> Answer:
        """Show `review` to the operator, and return their answer."""


class Terminal(Reviewer):
    """The terminal: each file coloured under its own header, then a question.

    The review goes through a pager, a header for each file naming whether it's
    created, deleted or modified and how many lines it adds and removes, then its
    hunks with three lines of context, removed lines red and added lines green.
    """

    @override
    def answer(self, review: Review) -> Answer:
        def shown(changed: ChangedFile) -> Iterator[Text]:
            before = (changed.before or "").splitlines()
            after = (changed.after or "").splitlines()
            matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
            changes = [
                opcode for opcode in matcher.get_opcodes() if opcode[0] != "equal"
            ]
            added = sum(end - start for _, _, _, start, end in changes)
            removed = sum(end - start for _, start, end, _, _ in changes)
            header = f"{changed.path}  {changed.kind()}  +{added} -{removed}"
            yield Text(header, style="bold")
            if not changes:
                yield Text("Its text is unchanged.", style="dim")
            for group in matcher.get_grouped_opcodes(3):
                _, first, _, start, _ = group[0]
                _, _, last, _, end = group[-1]
                yield Text(
                    f"@@ -{first + 1},{last - first} +{start + 1},{end - start} @@",
                    style="cyan",
                )
                for tag, low, high, begin, finish in group:
                    if tag == "equal":
                        yield from (Text(f" {line}") for line in before[low:high])
                        continue
                    yield from (
                        Text(f"-{line}", style="red") for line in before[low:high]
                    )
                    yield from (
                        Text(f"+{line}", style="green") for line in after[begin:finish]
                    )

        console = Console()
        with console.pager(styles=True):
            console.print(review.heading(), markup=False, highlight=False)
            for changed in review.files:
                lines = list(shown(changed))
                console.print()
                console.rule(lines[0], align="left")
                for line in lines[1:]:
                    console.print(line, markup=False, highlight=False)
        question = f"Install the judge at {review.commit} as the one that runs?"
        return Answer(approved=typer.confirm(question, default=False))


class Installer(Model, arbitrary_types_allowed=True):
    """Installs the judge from a checkout of lup, once the operator approves it."""

    checkout: Path
    layout: Layout
    toolchain: Toolchain
    reviewer: Reviewer
    clock: Clock
    runtimes: list[Runtime]

    def approved(self) -> Approval | None:
        """Return the copy the operator approved last, if any."""
        return read_model(self.layout.approval, Approval)

    def review(self, since: str | None, commit: str) -> Review:
        """List each file the judge carries that changed from `since` to `commit`.

        Each is read whole on both sides; a rename is a deletion and a creation.
        From nothing when `since` is none, or gone from the repository. A file that
        isn't UTF-8 text refuses the review, since no review here can show it.
        """
        git = Git(cwd=self.checkout)
        empty = git.run("hash-object", "-t", "tree", "--stdin", stdin=b"").stdout
        known = since is not None and (
            git.run("cat-file", "-e", f"{since}^{{commit}}", ok=[0, 1, 128]).exit_code
            == 0
        )
        start = since if known and since is not None else empty.decode().strip()
        carried = [
            str(path) for path in CheckoutLayout(root=self.checkout).judge_source
        ]
        listed = git.run(
            *["diff-tree", "-r", "-z", "--no-renames", "--name-only", start, commit],
            *["--", *carried],
        )
        paths = nul_separated(listed.stdout)

        def standing(revision: str) -> list[str]:
            if not paths:
                return []
            found = git.run(
                "ls-tree", "-r", "-z", "--name-only", revision, "--", *paths
            )
            return nul_separated(found.stdout)

        def text(revision: str, path: str, there: list[str]) -> str | None:
            if path not in there:
                return None
            content = git.run("cat-file", "blob", f"{revision}:{path}").stdout
            try:
                return content.decode()
            except UnicodeDecodeError as failure:
                message = (
                    f"{path} isn't UTF-8 text at {revision}, so no review here can "
                    f"show it: {failure}"
                )
                raise InstallError(message) from failure

        before = standing(start)
        after = standing(commit)
        return Review(
            since=since if known else None,
            commit=commit,
            files=[
                ChangedFile(
                    path=Path(path),
                    before=text(start, path, before),
                    after=text(commit, path, after),
                )
                for path in paths
            ],
            shortstat=git.text("diff", "--shortstat", start, commit, "--", *carried),
        )

    def install(self) -> Outcome:
        """List, build, ask, install and record, and say what came of it.

        Where nothing the judge carries changed, it stops before building. Declined,
        nothing changes: the copy installed before keeps judging. Approved while
        `HEAD` moved, it refuses, since what would install isn't what was reviewed.
        """
        inside = [runtime.name() for runtime in self.runtimes if runtime.inside()]
        if inside:
            message = (
                f"this runs inside a {inside[0]} session, and an agent doesn't "
                "approve the judge that judges it: install from your own terminal"
            )
            raise InstallError(message)
        git = Git(cwd=self.checkout)
        carried = [
            str(path) for path in CheckoutLayout(root=self.checkout).judge_source
        ]

        def refuse_uncommitted() -> None:
            changed = git.text("status", "--porcelain", "--", *carried)
            if changed:
                message = (
                    "the judge's source has changes not committed, which the copy "
                    "would carry unreviewed; commit or set them aside first:\n"
                    f"{changed}"
                )
                raise InstallError(message)

        refuse_uncommitted()
        commit = git.text("rev-parse", "HEAD")
        previous = self.approved()
        review = self.review(previous.commit if previous else None, commit)
        if not review.files:
            return Unchanged(commit=commit, since=review.since)
        self.toolchain.build(self.checkout)
        answer = self.reviewer.answer(review)
        if not answer.approved:
            return Declined(commit=commit, since=review.since, answer=answer)
        head = git.text("rev-parse", "HEAD")
        if head != commit:
            message = (
                f"`HEAD` moved from {commit} to {head} during the review, so what "
                "would install isn't what you approved; run `lup-dev install` again "
                f"to review {head}"
            )
            raise InstallError(message)
        refuse_uncommitted()
        self.toolchain.install(self.checkout)
        approval = Approval(
            commit=commit, time=self.clock.now(), checkout=self.checkout
        )
        write_model(self.layout.approval, approval)
        return Installed(approval=approval, since=review.since, answer=answer)
