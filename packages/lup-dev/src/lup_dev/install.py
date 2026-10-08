"""Installing the judge: the operator reviews its source before a new copy runs.

The judge that runs is a copy installed from a checkout of lup (`uv tool install`),
never a worktree's own source, so an agent's edit can't change what judges it
(`docs/judging-writes.md`, *Where things live*). Refreshing the copy shows the
operator the diff of everything it carries since the commit they last approved,
and until they approve, the copy installed before keeps judging (decision 26):
1. refuse inside an agent's session, and refuse a checkout whose judge source has
   changes not committed, since the copy would carry what the review didn't show;
2. build the engine (`packages/lup-dev/checker/build.py`);
3. show the diff of the judge's source from the approved commit (from nothing, the
   first time) to `HEAD`, and ask;
4. install `packages/lup-dev` with `uv tool install`, its dependencies held to the
   versions `uv.lock` pins;
5. record the approved commit in lup's state.
"""

import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import override

import sh
import typer
from pydantic import Field
from rich.console import Console

from lup.types import Model
from lup_dev.catalog.gate import Gate, Step
from lup_dev.clock import Clock
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout, Layout
from lup_dev.policy.runtime import Runtime
from lup_dev.policy.store import Git, read_model, write_model


class InstallError(LupDevError):
    """The judge can't be installed from this checkout, or by whoever asked."""


class Approval(Model):
    """The commit of lup the operator approved as the judge that runs."""

    commit: str
    time: datetime
    checkout: Path
    """The checkout it was installed from."""


class Review(Model):
    """What the operator reads before approving: the judge's source, changed."""

    since: str | None
    """The commit approved last; none for the first install."""
    commit: str
    """The commit the copy would be installed from."""
    stat: str
    """`git diff --stat` of the judge's source between the two."""
    diff: str
    """The diff itself."""

    def text(self) -> str:
        """Say what the review shows, its summary first."""
        since = (
            f"since {self.since}, the commit you approved last"
            if self.since
            else "whole, since no copy was approved yet"
        )
        header = f"The judge at {self.commit}: its source {since}."
        if not self.stat:
            return f"{header}\n\nIts source hasn't changed.\n"
        return f"{header}\n\n{self.stat}\n\n{self.diff}\n"


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
    """Who approves a copy of the judge: the operator, in their terminal."""

    @abstractmethod
    def approves(self, review: Review) -> bool:
        """Show `review`, and say whether it's approved."""


class Terminal(Reviewer):
    """The operator's terminal: the review in a pager, then a question."""

    @override
    def approves(self, review: Review) -> bool:
        console = Console()
        with console.pager():
            console.print(review.text(), markup=False, highlight=False)
        question = f"Install the judge at {review.commit} as the one that runs?"
        return typer.confirm(question, default=False)


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
        """Show the judge's source as it changed from `since` to `commit`.

        From nothing when `since` is none, or no longer in the repository.
        """
        git = Git(cwd=self.checkout)
        empty = git.run("hash-object", "-t", "tree", "--stdin", stdin=b"").stdout
        known = since is not None and (
            git.run("cat-file", "-e", f"{since}^{{commit}}", ok=[0, 1, 128]).exit_code
            == 0
        )
        start = since if known and since is not None else empty.decode().strip()
        paths = [str(path) for path in CheckoutLayout(root=self.checkout).judge_source]
        stat = git.text("diff", "--stat", start, commit, "--", *paths)
        diff = git.text("diff", start, commit, "--", *paths)
        return Review(
            since=since if known else None, commit=commit, stat=stat, diff=diff
        )

    def install(self) -> Approval | None:
        """Build, show, ask, install and record; return none where it's declined.

        Declined, nothing changes: the copy installed before keeps judging.
        """
        inside = [runtime.name() for runtime in self.runtimes if runtime.inside()]
        if inside:
            message = (
                f"this runs inside a {inside[0]} session, and an agent doesn't "
                "approve the judge that judges it: install from your own terminal"
            )
            raise InstallError(message)
        git = Git(cwd=self.checkout)
        paths = [str(path) for path in CheckoutLayout(root=self.checkout).judge_source]
        changed = git.text("status", "--porcelain", "--", *paths)
        if changed:
            message = (
                "the judge's source has changes not committed, which the copy would "
                f"carry unreviewed; commit or set them aside first:\n{changed}"
            )
            raise InstallError(message)
        commit = git.text("rev-parse", "HEAD")
        self.toolchain.build(self.checkout)
        previous = self.approved()
        review = self.review(previous.commit if previous else None, commit)
        if not self.reviewer.approves(review):
            return None
        self.toolchain.install(self.checkout)
        approval = Approval(
            commit=commit, time=self.clock.now(), checkout=self.checkout
        )
        write_model(self.layout.approval, approval)
        return approval
