"""`remote`'s promises: what the operator can count on of a room's push and fetch made with their credentials.

Pushing and fetching are what only git can say, so these run it for real
(`lup.testing.RealGit`), in a temporary directory: a forge's bare repository,
the remote, and the project's clone of it, whose git directory the part holds,
its `config` naming the forge as `origin`. ssh is stood in for, never run: the
forge is reached by its path (`README.md` here, *Promises*).
"""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import JsonValue

import lup
from lup import Agent, Model, Part
from lup.testing import Accepted, RealGit, Refused, Repository, Scripted, Testing

if TYPE_CHECKING:
    from collections.abc import Generator

    from lup.testing import Started

GIT = RealGit()

ALLOWING = """
from lup import Modules, Project
from lup.remote.module import Actions, Remote

project = Project(
    modules=Modules.default().edit(
        Remote(actions=Actions().add("force-push", "delete-any")),
        why="the promise allows what lup's default withholds",
    )
)
"""
"""A declaration allowing a forced push and deleting any ref, which lup's
default withholds."""

GUARDED = """
import lup
from lup import Modules, Part, Parts, Project, RefusedError
from lup.publishing.events import Publishing


class Guard(Part):
    '''Refuses what publishes the word `hush`.'''

    @lup.on(Publishing)
    async def heard(self, publishing: Publishing) -> None:
        '''Refuse a commit adding a line holding `hush`.'''
        published = publishing.published
        commit = getattr(published, "commit", None)
        lines = [] if commit is None else [
            line.text for each in commit.changed for line in each.added
        ]
        if any("hush" in each for each in lines):
            message = "a line says `hush`"
            raise RefusedError(message)


class Guarding(lup.Module):
    '''Guarding what's published.'''

    name = "guarding"
    parts: Parts = Parts.of(Guard)


project = Project(modules=Modules.default().add(Guarding()))
"""
"""A declaration with a module hearing `Publishing`, refusing a commit adding a
line that says `hush`."""


class Forge(Model):
    """The promise's forge and the project's clone of it, its `dev` pushed there, each by its path."""

    forge: Path
    work: Path
    dev: str
    """The commit `dev` is at, there and in the clone."""

    def common(self) -> Path:
        """Return the clone's git directory, which the part holds."""
        return self.work / ".git"

    def at(self, ref: str) -> str | None:
        """Return the commit `ref` names on the forge; none where it isn't there."""
        listed = GIT.git("for-each-ref", "--format=%(objectname)", ref, cwd=self.forge)
        return listed or None


@contextmanager
def forged() -> Generator[Forge]:
    """Make a forge holding `dev` and the project's clone of it, its `config` naming the forge `origin`, gone once the promise ends."""
    with tempfile.TemporaryDirectory(prefix="lup-remote-") as directory:
        root = Path(directory)
        forge = GIT.made(root / "forge.git", bare=True)
        work = GIT.made(root / "work")
        GIT.git("config", "remote.origin.url", str(forge), cwd=work)
        dev = GIT.committed(work, {"README.md": "harmon\n"}, "start")
        GIT.git("push", "--quiet", "origin", "dev:refs/heads/dev", cwd=work)
        yield Forge(forge=forge, work=work, dev=dev)


async def started_on(
    by: Testing, forge: Forge, declaration: str | None = None
) -> Started:
    """Start lup on lup's defaults, or `declaration`, its remote part holding the clone's git directory, git run for real and ssh stood in for."""
    declared = (
        lup.Project(modules=lup.Modules.default())
        if declaration is None
        else Repository(declaration=declaration)
    )
    return await by.started(
        declared,
        programs={"git": GIT, "ssh": Scripted()},
        git=forge.common(),
    )


def pushing(*updates: JsonValue, remote: str = "origin") -> JsonValue:
    """Return a push of `updates`, as a room's helper asks one."""
    return {"remote": remote, "updates": list(updates)}


class Outcome(Model):
    """How one update of a push ended, as the room reads it: why it wasn't made, none where it was."""

    destination: str
    error: str | None = None


class Outcomes(Model):
    """How each update of a push ended, as the room reads it."""

    updates: list[Outcome]


def errors(answered: Accepted) -> list[str | None]:
    """Return how each update of a push ended: none where it was made, else why not."""
    return [
        each.error for each in Outcomes.model_validate_json(answered.answer()).updates
    ]


class Destination(Model):
    """Where a room pushes a commit: a branch of its own, the integration branch, the release branch, or a tag."""

    ref: Literal["refs/heads/feat", "refs/heads/dev", "refs/heads/main", "refs/tags/v1"]


class RemotePromises(Part):
    """What the operator can count on of a room's push and fetch made with their credentials."""

    @lup.promise
    async def a_room_pushes_its_own_branches_and_nothing_held(
        self, by: Testing
    ) -> None:
        """A room's push of a commit reaches the remote where it names a branch of its own; one to the integration branch, the release branch or a tag is refused, and the remote's ref doesn't move."""
        destination = by.any(Destination).ref
        with forged() as forge:
            commit = GIT.committed(forge.work, {"notes.md": "a note\n"}, "notes")
            started = await started_on(by, forge)
            pushed = await started.serve(
                "pushed",
                pushing({"source": commit, "destination": destination}),
                by.any(Agent),
            )
            assert isinstance(pushed, Accepted)
            [error] = errors(pushed)
            own = destination == "refs/heads/feat"
            assert (error is None) == own
            assert (forge.at(destination) == commit) == own
            assert forge.at("refs/heads/dev") == forge.dev

    @lup.promise
    async def a_forced_push_is_refused_unless_the_declaration_allows_it(
        self, by: Testing
    ) -> None:
        """A push that isn't a fast-forward, forced, is refused under lup's default, the remote's branch unmoved; where the declaration allows `force-push`, it's made."""
        allowing = by.any(bool)
        with forged() as forge:
            first = GIT.committed(forge.work, {"a.md": "a\n"}, "a")
            GIT.git(
                "push", "--quiet", "origin", f"{first}:refs/heads/feat", cwd=forge.work
            )
            GIT.git("reset", "--quiet", "--hard", forge.dev, cwd=forge.work)
            other = GIT.committed(forge.work, {"b.md": "b\n"}, "b")
            started = await started_on(by, forge, ALLOWING if allowing else None)
            pushed = await started.serve(
                "pushed",
                pushing(
                    {"source": other, "destination": "refs/heads/feat", "forced": True}
                ),
                by.any(Agent),
            )
            assert isinstance(pushed, Accepted)
            [error] = errors(pushed)
            assert (error is None) == allowing
            assert forge.at("refs/heads/feat") == (other if allowing else first)

    @lup.promise
    async def a_branch_is_deleted_only_once_it_has_landed(self, by: Testing) -> None:
        """A room deletes a branch on the remote only where its commits are all in the integration branch there already, so nothing goes with it."""
        landed = by.any(bool)
        with forged() as forge:
            tip = GIT.committed(forge.work, {"a.md": "a\n"}, "a")
            GIT.git(
                "push", "--quiet", "origin", f"{tip}:refs/heads/feat", cwd=forge.work
            )
            if landed:
                GIT.git(
                    "push", "--quiet", "origin", f"{tip}:refs/heads/dev", cwd=forge.work
                )
            started = await started_on(by, forge)
            pushed = await started.serve(
                "pushed",
                pushing({"source": None, "destination": "refs/heads/feat"}),
                by.any(Agent),
            )
            assert isinstance(pushed, Accepted)
            [error] = errors(pushed)
            assert (error is None) == landed
            assert (forge.at("refs/heads/feat") is None) == landed

    @lup.promise
    async def a_fetch_brings_the_objects_and_writes_no_ref(self, by: Testing) -> None:
        """A fetch brings the objects a remote's refs name into the repository's store and writes no ref, which the room's git writes itself."""
        with forged() as forge, tempfile.TemporaryDirectory() as elsewhere:
            other = Path(elsewhere) / "other"
            GIT.git(
                "clone", "--quiet", str(forge.forge), str(other), cwd=Path(elsewhere)
            )
            commit = GIT.committed(other, {"b.md": "b\n"}, "b")
            GIT.git(
                "push", "--quiet", "origin", f"{commit}:refs/heads/theirs", cwd=other
            )
            refs = GIT.git("for-each-ref", cwd=forge.work)
            started = await started_on(by, forge)
            fetched = await started.serve(
                "fetched",
                {
                    "remote": "origin",
                    "wanted": [{"object": commit, "name": "refs/heads/theirs"}],
                },
                by.any(Agent),
            )
            assert isinstance(fetched, Accepted)
            assert GIT.git("cat-file", "-t", commit, cwd=forge.work) == "commit"
            assert GIT.git("for-each-ref", cwd=forge.work) == refs

    @lup.promise
    async def a_remote_the_repository_doesnt_name_is_refused(self, by: Testing) -> None:
        """A push or a fetch naming a remote the repository's `config` doesn't name, or a URL, is refused: where it goes is the repository's word, never the room's."""
        named = by.any(bool)
        with forged() as forge:
            commit = GIT.committed(forge.work, {"a.md": "a\n"}, "a")
            started = await started_on(by, forge)
            remote = "elsewhere" if named else str(forge.forge)
            pushed = await started.serve(
                "pushed",
                pushing(
                    {"source": commit, "destination": "refs/heads/feat"}, remote=remote
                ),
                by.any(Agent),
            )
            assert isinstance(pushed, Refused)
            assert forge.at("refs/heads/feat") is None

    @lup.promise
    async def a_refusal_at_publishing_keeps_a_push_from_leaving(
        self, by: Testing
    ) -> None:
        """Each commit a push would publish is told at `Publishing` first, and where a part hearing it refuses, nothing of it leaves, the room told why."""
        hushed = by.any(bool)
        with forged() as forge:
            GIT.committed(forge.work, {"a.md": "fine\n"}, "a")
            commit = GIT.committed(
                forge.work, {"b.md": "hush\n" if hushed else "fine too\n"}, "b"
            )
            started = await started_on(by, forge, GUARDED)
            pushed = await started.serve(
                "pushed",
                pushing({"source": commit, "destination": "refs/heads/feat"}),
                by.any(Agent),
            )
            assert isinstance(pushed, Accepted)
            [error] = errors(pushed)
            assert (error is not None) == hushed
            assert (forge.at("refs/heads/feat") is None) == hushed
