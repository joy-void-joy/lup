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
from lup import (
    Agent,
    Blocks,
    Codebase,
    Diff,
    Fold,
    Line,
    Machine,
    Markdown,
    Model,
    Operator,
    Part,
)
from lup.testing import (
    Accepted,
    Acting,
    Answering,
    RealGit,
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
    .edit(Gate(steps=Steps.of(Step(name="checked", command=["checked"], tells=True))))
    .drop("private", why="the promises' gate runs its one step alone")
    .add(Hosting())
)
"""
"""The home repository's declaration, as lup's own declares it, lup's default
modules and the machine's parts, `Private` dropped so its own step doesn't run,
its gate one step, `checked`, which tells what it prints, as a step listing what's due does, and whose program the promises
stand in for passing, saying `TOLD`: the gate as an agent runs it, on the files
the promise committed."""
TOLD = "historical-voice: main.py:3"
"""What the gate's step tells where it passes."""


class Found(Model):
    """What a gate step finds without failing, as it writes it to the file the gate gives it."""

    about: str = "harness"
    title: str = "a check that held on its second run"
    text: str = "it failed once, then held"


class Checked(Model, Acting):
    """The gate's step `checked`, stood in for: it passes, saying `TOLD`, and writes one finding to the file the gate gives it."""

    def ran(
        self,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
        cwd: Path | None,
    ) -> Answering:
        """Write the finding, and pass."""
        del arguments, given, cwd
        for each in env.values():
            Path(each).write_text(Found().model_dump_json() + "\n")
        return Answering(output=TOLD)


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
    """What the gate is asked, as `lup check` takes it."""

    directory: Path


class LandingAsked(Model):
    """A branch an agent lands, as their project's code asks the machine."""

    agent: Agent
    branch: str
    message: str


class Naming(Model):
    """A landing, by its repository and its branch."""

    repository: str = PROJECT
    branch: str


class Reviewing(Model):
    """A landing the operator says yes to, at the tip whose review they read."""

    repository: str = PROJECT
    branch: str
    tip: str


def reviewing(at: Places, branch: str) -> Reviewing:
    """Return the operator's yes to `branch`'s review at its tip as it stands."""
    return Reviewing(branch=branch, tip=at.git("rev-parse", branch))


class Registering(Model):
    """A project registered with lup: its name and where git keeps it."""

    repository: str = PROJECT
    common: Path


class Approving(Model):
    """A project whose approval to read."""

    project: str = PROJECT


class Approval(Model):
    """A commit of the repository the operator approves to run."""

    repository: str = PROJECT
    commit: str


class TrialOf(Model):
    """A repository whose landings to show."""

    repository: str = PROJECT


class Nothing(Model):
    """Nothing to give."""


class Titled(Model):
    """A concern of the project's inbox, by its title."""

    title: str


class Standing(Model):
    """What waits on the operator in the project's inbox, by number, and its concerns, frictions among them."""

    waiting: list[int] = []
    concerns: list[Titled] = []


class Ending(Model):
    """An agent whose untold items to tell, in the project's inbox."""

    repository: str = PROJECT
    agent: Agent


class ToldItem(Model):
    """An item told to an agent: its words."""

    text: str


class Told(Model):
    """What's told to an agent at their next call."""

    items: list[ToldItem] = []


class Seen(Model):
    """A `# lup: defer` a landing says its branch changes: the file, and what the branch does to it."""

    path: str
    how: str


class LandedDeferrals(Model):
    """What a landing says of the work left undone it lands."""

    deferrals: list[Seen] = []


class LandedItem(Model):
    """The item a landing posted, by its number."""

    item: int | None = None


async def standing(started: Started) -> Standing:
    """Return what the project's inbox holds, as its code reads it."""
    read = await started.serve("standing", Nothing(), Codebase(repository=PROJECT))
    assert isinstance(read, Accepted)
    assert isinstance(read.output, Model)
    return Standing.model_validate(read.output.model_dump())


async def waiting(started: Started) -> list[int]:
    """Return the numbers of what waits on the operator in the project's inbox."""
    return (await standing(started)).waiting


async def told(started: Started, agent: Agent) -> list[str]:
    """Return the words of what's told `agent` at their next call."""
    read = await started.serve("told", Ending(agent=agent), Machine())
    assert isinstance(read, Accepted)
    assert isinstance(read.output, Model)
    return [each.text for each in Told.model_validate(read.output.model_dump()).items]


def item_of(answered: Accepted | Refused) -> int:
    """Return the number of the item a landing posted, which it must have."""
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Model)
    number = LandedItem.model_validate(answered.output.model_dump()).item
    assert number is not None
    return number


class Approved(Model):
    """The commit of a project approved to run last; none before."""

    commit: str | None = None


async def machine(by: Testing, at: Places) -> Started:
    """Start the machine's parts, git run for real, podman left out, with the project at `at` registered and the integration branch's tip approved, as the operator answers at its first run: its `remote`, which landing reaches the remote through, holding the project's git directory, ssh stood in for, never run."""
    started = await by.started(
        Repository(declaration=HOME),
        programs={
            "git": RealGit(),
            "ssh": Scripted(),
            "uv": Scripted(answers=[Answering(output="/srv/python\n")]),
            "checked": Checked(),
        },
        machine=True,
        git=at.project / ".git",
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
                    "landing", "yes", reviewing(at, branch), Operator()
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
                await started.run("landing", "yes", reviewing(at, branch), Operator())
            runs = await approved(started)
            assert runs is not None
            assert at.file_at(runs, "README.md") == "apple"

    @lup.promise
    async def what_waits_and_whats_on_trial_shows_with_what_it_changed(
        self, by: Testing
    ) -> None:
        """What's on trial shows each landing waiting on the operator or on trial, offering a yes on what waits and an accept on what's on trial, each opening on its review: what the gate told on its tip, then a file for each file its branch changed."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            for branch in ["waiting", "trying"]:
                at.branched(branch)
                at.committed(branch, f"{branch}.txt", f"{branch}\n")
                await gated(started, at)
                assert isinstance(await landed(started, branch, agent), Accepted)
            await started.run("landing", "yes", reviewing(at, "trying"), Operator())
            shown = await started.view("landing", "trial", TrialOf(), Operator())
            reviewed = await started.view(
                "landing", "review", Naming(branch="waiting"), Operator()
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
        assert "waiting.txt" in paths
        assert "trying.txt" not in paths
        told = [
            each.text for each in reviewed.output.blocks if isinstance(each, Markdown)
        ]
        assert any(TOLD in each for each in told)

    @lup.promise
    async def a_landing_waits_on_the_operator_until_they_answer_it(
        self, by: Testing
    ) -> None:
        """A landing waits on the operator in the agent's conversation until they answer it, their yes told to the agent; landing the branch again answers the one before, the tip it landed at since waiting in its place."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "feature.txt", "feature\n")
            await gated(started, at)
            first = item_of(await landed(started, "feature", agent))
            before = await waiting(started)
            at.committed("feature", "more.txt", "more\n")
            await gated(started, at)
            second = item_of(await landed(started, "feature", agent))
            again = await waiting(started)
            await told(started, agent)
            await started.run("landing", "yes", reviewing(at, "feature"), Operator())
            after = await waiting(started)
            heard = await told(started, agent)
        assert first in before
        assert first not in again
        assert second in again
        assert second not in after
        assert heard

    @lup.promise
    async def a_landing_says_the_work_left_undone_it_lands(self, by: Testing) -> None:
        """A landing says each `# lup: defer` its branch adds and removes in a Python file against the integration branch it holds, and none it only moves to another line."""
        agent = Agent.of("landing")
        with places() as at:
            at.committed("dev", "kept.py", '# lup: defer(issue=1, why="moved")\n')
            at.committed("dev", "gone.py", '# lup: defer(issue=2, why="done")\n')
            at.git("push", "--quiet", "origin", "dev")
            started = await machine(by, at)
            at.branched("feature")
            at.committed(
                "feature", "kept.py", 'x = 1\n# lup: defer(issue=1, why="moved")\n'
            )
            at.committed("feature", "gone.py", "y = 2\n")
            at.committed("feature", "new.py", '# lup: defer(issue=3, why="later")\n')
            await gated(started, at)
            answered = await landed(started, "feature", agent)
        assert isinstance(answered, Accepted)
        assert isinstance(answered.output, Model)
        seen = LandedDeferrals.model_validate(answered.output.model_dump()).deferrals
        assert Seen(path="new.py", how="adds") in seen
        assert Seen(path="gone.py", how="removes") in seen
        assert all(each.path != "kept.py" for each in seen)

    @lup.promise
    async def what_the_gate_found_is_filed_as_the_branch_lands(
        self, by: Testing
    ) -> None:
        """What the gate's steps found without failing on the landing's tip shows in its review, and is filed as a friction of the agent landing it, under its subject."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "feature.txt", "feature\n")
            await gated(started, at)
            answered = await landed(started, "feature", agent)
            reviewed = await started.view(
                "landing", "review", Naming(branch="feature"), Operator()
            )
            filed = (await standing(started)).concerns
        assert isinstance(answered, Accepted)
        assert isinstance(reviewed, Accepted)
        assert isinstance(reviewed.output, Blocks)
        assert any(
            Found().title in each.said()
            for each in reviewed.output.blocks
            if isinstance(each, Line)
        )
        assert Titled(title=Found().title) in filed

    @lup.promise
    async def a_yes_is_to_the_tip_whose_review_was_read(self, by: Testing) -> None:
        """A yes names the tip whose review the operator read: where the branch landed again since, at a tip they haven't read, it's refused and nothing of the tip it landed at since runs."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "seen.txt", "seen\n")
            await gated(started, at)
            assert isinstance(await landed(started, "feature", agent), Accepted)
            read = reviewing(at, "feature")
            at.committed("feature", "unseen.txt", "unseen\n")
            await gated(started, at)
            assert isinstance(await landed(started, "feature", agent), Accepted)
            stale = await started.run("landing", "yes", read, Operator())
            runs = await approved(started)
            assert runs is not None
            unseen = at.file_at(runs, "unseen.txt")
        assert isinstance(stale, Refused)
        assert unseen is None

    @lup.promise
    async def a_branch_named_like_the_integration_branch_stands_in_for_nothing(
        self, by: Testing
    ) -> None:
        """A branch on the remote whose name ends as the integration branch's does, `x/refs/heads/dev`, is never read as it: a branch built on it lands against the real one, so its review shows what the decoy holds beyond it."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("decoy")
            at.committed("decoy", "hidden.txt", "hidden\n")
            at.git("push", "--quiet", "origin", "decoy:refs/heads/a/refs/heads/dev")
            at.branched("feature", "decoy")
            at.committed("feature", "feature.txt", "feature\n")
            await gated(started, at)
            assert isinstance(await landed(started, "feature", agent), Accepted)
            reviewed = await started.view(
                "landing", "review", Naming(branch="feature"), Operator()
            )
        assert isinstance(reviewed, Accepted)
        assert isinstance(reviewed.output, Blocks)
        paths = [each.path for each in reviewed.output.blocks if isinstance(each, Diff)]
        assert "hidden.txt" in paths

    @lup.promise
    async def a_store_reading_anothers_objects_pushes_nothing(
        self, by: Testing
    ) -> None:
        """Accepting pushes nothing from a store that reads objects from outside it, through `alternates` or `http-alternates`, whose history a push would send: the integration branch on the remote stays as it was."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "feature.txt", "feature\n")
            await gated(started, at)
            assert isinstance(await landed(started, "feature", agent), Accepted)
            await started.run("landing", "yes", reviewing(at, "feature"), Operator())
            info = at.project / ".git" / "objects" / "info"
            info.mkdir(parents=True, exist_ok=True)

            async def refused_with(name: str) -> bool:
                (info / name).write_text(f"{at.remote / 'objects'}\n")
                accepted = await started.run(
                    "landing", "accept", Naming(branch="feature"), Operator()
                )
                (info / name).unlink()
                return isinstance(accepted, Refused)

            refused = [
                await refused_with(name) for name in ["alternates", "http-alternates"]
            ]
            after = at.remote_file("dev", "feature.txt")
        assert all(refused)
        assert after is None

    @lup.promise
    async def a_branch_the_integration_branch_holds_is_accepted_with_nothing_pushed(
        self, by: Testing
    ) -> None:
        """Accepting a branch the integration branch holds already, merged there another way, pushes nothing and ends its trial."""
        agent = Agent.of("landing")
        with places() as at:
            started = await machine(by, at)
            at.branched("feature")
            at.committed("feature", "feature.txt", "feature\n")
            await gated(started, at)
            assert isinstance(await landed(started, "feature", agent), Accepted)
            await started.run("landing", "yes", reviewing(at, "feature"), Operator())
            at.git("push", "--quiet", "origin", "feature:dev")
            before = at.git("ls-remote", "origin", "refs/heads/dev")
            accepted = await started.run(
                "landing", "accept", Naming(branch="feature"), Operator()
            )
            after = at.git("ls-remote", "origin", "refs/heads/dev")
            shown = await started.view("landing", "trial", TrialOf(), Operator())
        assert isinstance(accepted, Accepted)
        assert before == after
        assert isinstance(shown, Accepted)
        assert isinstance(shown.output, Blocks)
        assert offered(shown.output, "feature") == []

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
            await started.run("landing", "yes", reviewing(at, "feature"), Operator())
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
