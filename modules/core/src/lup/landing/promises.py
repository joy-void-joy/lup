"""Landing's promises: what an agent landing a branch, and the operator putting it on trial and accepting it, can count on.

Merging is what only git can say, so these run it for real, in a temporary
directory: a remote's bare repository, and a clone of it, the project, where
the promise makes the commits an agent would and runs the gate on them as an
agent does, through a project's lup, its steps' programs stood in for. The
machine's parts are started on lup's defaults and `Hosting`, podman left out,
so opening a project at what's approved is refused, said in each answer, while
everything else runs (`README.md` here, *Promises*).
"""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import lup
from lup import Agent, Blocks, Codebase, Diff, Fold, Machine, Model, Operator, Part
from lup.testing import (
    Accepted,
    Acting,
    Answering,
    Refused,
    Repository,
    Scripted,
    Testing,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from lup.testing import Started

PROJECT = "harmon"
"""The project the promises land on, as it's registered with lup."""
HOME = """
from lup import Gate, Modules, Project, Step, Steps
from lup.hosting.module import Hosting

project = Project(
    modules=Modules.default()
    .edit(Gate(steps=Steps.of(Step(name="checked", command=["checked"]))))
    .add(Hosting())
)
"""
"""The home repository's declaration, as lup's own declares it, lup's default
modules and the machine's parts, its gate one step, `checked`, whose program
the promises stand in for passing: the gate as an agent runs it, on the files
the promise committed."""


class RealGit(Model, Acting):
    """git, run for real, with the variables and from the directory each run asks."""

    def ran(
        self,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
        cwd: Path | None,
    ) -> Answering:
        """Run git as asked, and answer how it ended."""
        pinned = [f"{name}={value}" for name, value in env.items()]
        done = lup.programs.run(
            "env", *pinned, "git", *arguments, cwd=cwd, stdin=given, checked=False
        )
        return Answering(status=done.status, output=done.output, error=done.error)


class Places(Model):
    """Where a promise's repositories are: the remote's, and the project's clone of it."""

    remote: Path
    project: Path
    who: list[str] = ["-c", "user.name=Agent", "-c", "user.email=agent@localhost"]
    """Who the promise's own commits are by, as git is told it."""

    def git(self, *arguments: str) -> str:
        """Run git in the project's clone, as an agent would in their worktree, and return what it printed."""
        return lup.programs.run("git", *self.who, *arguments, cwd=self.project).text()

    def committed(self, branch: str, path: str, text: str) -> str:
        """Commit `text` as the file at `path` on `branch`, made from where it's checked out, and return the commit."""
        self.git("checkout", "--quiet", branch)
        (self.project / path).write_text(text)
        self.git("add", path)
        self.git("commit", "--quiet", "-m", f"{path} on {branch}")
        return self.git("rev-parse", "HEAD")

    def branched(self, branch: str, start: str = "dev") -> None:
        """Make `branch` from `start`, as an agent's worktree starts."""
        self.git("branch", branch, start)

    def remote_file(self, ref: str, path: str) -> str | None:
        """Return the file at `path` on `ref` in the remote, as it holds it; none where it doesn't."""
        shown = lup.programs.run(
            "git", "show", f"{ref}:{path}", cwd=self.remote, checked=False
        )
        return shown.text() if shown.status == 0 else None

    def file_at(self, commit: str, path: str) -> str | None:
        """Return the file at `path` in `commit`, as the project's store holds it; none where it doesn't."""
        shown = lup.programs.run(
            "git", "show", f"{commit}:{path}", cwd=self.project, checked=False
        )
        return shown.text() if shown.status == 0 else None


@contextmanager
def places() -> Generator[Places]:
    """Make a remote holding `dev` with one file, and a clone of it, the project, in a temporary directory."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        remote, project = root / "remote.git", root / "project"
        lup.programs.run("git", "init", "--quiet", "--bare", str(remote))
        lup.programs.run("git", "init", "--quiet", "--initial-branch=dev", str(project))
        at = Places(remote=remote, project=project)
        at.git("remote", "add", "origin", str(remote))
        (project / "README.md").write_text("harmon\n")
        at.git("add", "README.md")
        at.git("commit", "--quiet", "-m", "harmon")
        at.git("push", "--quiet", "origin", "dev")
        yield at


class Gating(Model):
    """What the gate is asked, as `lup gate check` takes it."""

    directory: Path


class LandingAsked(Model):
    """A branch an agent lands, as their project's code asks the machine."""

    agent: Agent
    branch: str
    message: str


class Naming(Model):
    """A landing, by its project and its branch."""

    project: str = PROJECT
    branch: str


class Registering(Model):
    """A project registered with lup: its name and where git keeps it."""

    repository: str = PROJECT
    common: Path


class Approving(Model):
    """A project whose approval to read."""

    project: str = PROJECT


class Approval(Model):
    """A commit of the project the operator approves to run."""

    project: str = PROJECT
    commit: str


class TrialOf(Model):
    """A project whose landings to show."""

    project: str = PROJECT


class Approved(Model):
    """The commit of a project approved to run last; none before."""

    commit: str | None = None


async def machine(by: Testing, at: Places) -> Started:
    """Start the machine's parts, git run for real, podman left out, with the project at `at` registered and the integration branch's tip approved, as the operator answers at its first run."""
    started = await by.started(
        Repository(declaration=HOME),
        programs={
            "git": RealGit(),
            "uv": Scripted(answers=[Answering(output="/srv/python\n")]),
            "checked": Scripted(answers=[Answering()]),
        },
        machine=True,
    )
    registered = await started.run(
        "hosting", "register", Registering(common=at.project / ".git"), Operator()
    )
    first = await started.run(
        "hosting", "approve", Approval(commit=at.git("rev-parse", "dev")), Operator()
    )
    assert isinstance(registered, Accepted)
    assert isinstance(first, Accepted)
    return started


async def gated(started: Started, at: Places) -> None:
    """Run the gate on the project's checkout as it stands, as an agent does in their worktree, its step passing."""
    checked = await started.run(
        "gate", "check", Gating(directory=at.project), Operator()
    )
    assert isinstance(checked, Accepted)


async def landed(started: Started, branch: str, agent: Agent) -> Accepted | Refused:
    """Land `branch` as the project's code asks for `agent`."""
    return await started.serve(
        "lands",
        LandingAsked(agent=agent, branch=branch, message=f"Merge {branch}"),
        Codebase(repository=PROJECT),
    )


async def approved(started: Started) -> str | None:
    """Return the commit of the project approved to run last."""
    found = await started.serve("approval", Approving(), Machine())
    assert isinstance(found, Accepted)
    assert isinstance(found.output, Model)
    return Approved.model_validate(found.output.model_dump()).commit


def offered(shown: Blocks, branch: str) -> list[str]:
    """Return the commands what's on trial offers on `branch`'s landing, by name; none where it doesn't show it."""
    return [
        offer.command
        for each in shown.blocks
        if isinstance(each, Fold) and each.id == f"landing-{branch}"
        for offer in each.offers
    ]


class LandingPromises(Part):
    """What an agent landing a branch, and the operator putting it on trial and accepting it, can count on."""

    @lup.promise
    async def a_branch_lands_only_holding_the_integration_branch_and_gated(
        self, by: Testing
    ) -> None:
        """A branch lands only once it holds the integration branch's tip on the remote and the gate passed on its files: before, it's refused, saying what to do; merged and gated, it waits on the operator's review."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "feature.txt", "feature\n")
            ungated = await landed(started, "feature", agent)
            at.committed("dev", "other.txt", "other\n")
            at.git("push", "--quiet", "origin", "dev")
            at.git("checkout", "--quiet", "feature")
            await gated(started, at)
            behind = await landed(started, "feature", agent)
            at.git("merge", "--quiet", "--no-edit", "dev")
            await gated(started, at)
            waiting = await landed(started, "feature", agent)
        assert isinstance(ungated, Refused)
        assert isinstance(behind, Refused)
        assert isinstance(waiting, Accepted)

    @lup.promise
    async def a_yes_runs_the_branch_reviewed_and_approves_it(self, by: Testing) -> None:
        """The operator's yes puts a branch on trial: what the project runs, approved, is the integration branch with each branch on trial and picked merged in at the tip they reviewed; a branch taken out runs no more, and a commit added after the yes runs only once it lands again and is said yes to."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            for branch in ["first", "second"]:
                at.branched(branch)
                at.committed(branch, f"{branch}.txt", f"{branch}\n")
                await gated(started, at)
                assert isinstance(await landed(started, branch, agent), Accepted)
                said = await started.run(
                    "landing", "yes", Naming(branch=branch), Operator()
                )
                assert isinstance(said, Accepted)
            both = await approved(started)
            at.committed("second", "later.txt", "later\n")
            toggled = await started.run(
                "landing", "toggle", Naming(branch="first"), Operator()
            )
            assert isinstance(toggled, Accepted)
            alone = await approved(started)
            assert both is not None
            assert alone is not None
            assert at.file_at(both, "first.txt") == "first"
            assert at.file_at(both, "second.txt") == "second"
            assert at.file_at(alone, "first.txt") is None
            assert at.file_at(alone, "second.txt") == "second"
            assert at.file_at(alone, "later.txt") is None

    @lup.promise
    async def a_branch_that_doesnt_merge_is_left_out_of_what_runs(
        self, by: Testing
    ) -> None:
        """A branch on trial that conflicts with one before it is left out of what runs, and the other still runs."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            for branch in ["apple", "banana"]:
                at.branched(branch)
                at.committed(branch, "README.md", f"{branch}\n")
                await gated(started, at)
                assert isinstance(await landed(started, branch, agent), Accepted)
                await started.run("landing", "yes", Naming(branch=branch), Operator())
            runs = await approved(started)
            assert runs is not None
            assert at.file_at(runs, "README.md") == "apple"

    @lup.promise
    async def what_waits_and_whats_on_trial_shows_with_what_it_changed(
        self, by: Testing
    ) -> None:
        """What's on trial shows each landing waiting on the operator or on trial, offering a yes on what waits and an accept on what's on trial, each opening on its review: a file for each file its branch changed."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            for branch in ["waiting", "trying"]:
                at.branched(branch)
                at.committed(branch, f"{branch}.txt", f"{branch}\n")
                await gated(started, at)
                assert isinstance(await landed(started, branch, agent), Accepted)
            await started.run("landing", "yes", Naming(branch="trying"), Operator())
            shown = await started.view("landing", "trial", TrialOf(), Operator())
            reviewed = await started.view(
                "landing", "review", Naming(branch="waiting"), agent
            )
        assert isinstance(shown, Accepted)
        assert isinstance(shown.output, Blocks)
        assert isinstance(reviewed, Accepted)
        assert isinstance(reviewed.output, Blocks)
        waiting = offered(shown.output, "waiting")
        assert "yes" in waiting
        assert "accept" not in waiting
        assert "accept" in offered(shown.output, "trying")
        paths = [each.path for each in reviewed.output.blocks if isinstance(each, Diff)]
        assert paths == ["waiting.txt"]

    @lup.promise
    async def accepting_pushes_the_reviewed_tip_onto_the_integration_branch(
        self, by: Testing
    ) -> None:
        """Accepting a branch on trial pushes its reviewed tip, merged, onto the integration branch on the remote, which nothing else of landing moves; refused for a landing not said yes to."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "feature.txt", "feature\n")
            await gated(started, at)
            assert isinstance(await landed(started, "feature", agent), Accepted)
            unreviewed = await started.run(
                "landing", "accept", Naming(branch="feature"), Operator()
            )
            before = at.remote_file("dev", "feature.txt")
            await started.run("landing", "yes", Naming(branch="feature"), Operator())
            on_trial = at.remote_file("dev", "feature.txt")
            accepted = await started.run(
                "landing", "accept", Naming(branch="feature"), Operator()
            )
            after = at.remote_file("dev", "feature.txt")
        assert isinstance(unreviewed, Refused)
        assert isinstance(accepted, Accepted)
        assert before is None
        assert on_trial is None
        assert after == "feature"
