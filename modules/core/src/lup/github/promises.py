"""`github`'s promises: what the operator can count on of what agents do on GitHub under their name.

`gh` is stood in for, each promise scripting what GitHub answers and reading
what lup asked of it: the gate never reaches GitHub. The project's repository
on GitHub is named by its remote, as `remote` says where that is: a clone made
for the promise, git run for real, its `origin` at `git@github.com:…`, and ssh
stood in for, resolving the host as itself (`README.md` here, *Promises*).
"""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import lup
from lup import Agent, Codebase, Model, Part
from lup.testing import (
    Accepted,
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

GIT = RealGit()
OWN = "joy-void-joy/harmon"
"""The project's repository on GitHub, as its remote names it."""

SSH = Scripted(
    answers=[Answering(when=["-G"], output="user git\nhostname github.com\n")]
)
"""ssh resolving the remote's host as itself."""

GUARDED = """
import lup
from lup import Modules, Part, Parts, Project, RefusedError
from lup.publishing.events import Publishing


class Guard(Part):
    '''Refuses what publishes the word `hush`.'''

    @lup.on(Publishing)
    async def heard(self, publishing: Publishing) -> None:
        '''Refuse a post saying `hush`.'''
        parts = getattr(publishing.published, "parts", [])
        if any("hush" in each.text for each in parts):
            message = "a part says `hush`"
            raise RefusedError(message)


class Guarding(lup.Module):
    '''Guarding what's published.'''

    name = "guarding"
    parts: Parts = Parts.of(Guard)


project = Project(modules=Modules.default().add(Guarding()))
"""
"""A declaration with a module hearing `Publishing`, refusing a post saying
`hush`."""

WITHHOLDING = """
from lup import Modules, Project
from lup.github.module import Actions, GitHub

project = Project(
    modules=Modules.default().edit(
        GitHub(actions=Actions().drop("file-issue", why="the promise withholds it")),
        why="the promise withholds filing an issue",
    )
)
"""
"""A declaration withholding filing an issue."""


def issue(number: int, state: Literal["OPEN", "CLOSED"] = "OPEN") -> str:
    """Return an issue as `gh issue view --json` answers it."""
    return json.dumps(
        {
            "number": number,
            "title": "a title",
            "state": state,
            "author": {"login": "someone"},
            "createdAt": "2026-11-21T10:00:00Z",
            "url": f"https://github.com/{OWN}/issues/{number}",
            "labels": [],
            "body": "a body",
            "comments": [],
        }
    )


def pull_request(number: int) -> str:
    """Return a pull request as `gh pr view --json` answers it."""
    return json.dumps(
        {
            "number": number,
            "title": "a title",
            "state": "OPEN",
            "isDraft": True,
            "author": {"login": "someone"},
            "createdAt": "2026-11-21T10:00:00Z",
            "url": f"https://github.com/{OWN}/pull/{number}",
            "headRefName": "feat",
            "baseRefName": "dev",
            "reviewDecision": "",
            "labels": [],
            "body": "a body",
            "comments": [],
            "reviews": [],
            "statusCheckRollup": [],
        }
    )


class Gh(Model):
    """`gh` as a promise stands it in: an issue, or a pull request, at every number, and every write succeeding."""

    pulls: bool = False
    """Whether each number is a pull request's."""
    state: Literal["OPEN", "CLOSED"] = "OPEN"

    def script(self) -> Scripted:
        """Return the script standing `gh` in."""
        return Scripted(
            answers=[
                Answering(when=["pr", "view"], output=pull_request(1))
                if self.pulls
                else Answering(when=["pr", "view"], status=1, error="no pull request"),
                Answering(when=["issue", "view"], output=issue(1, self.state)),
                Answering(when=["api", "--paginate"], output="[[]]"),
                Answering(
                    when=["issue", "create"],
                    output=f"https://github.com/{OWN}/issues/2\n",
                ),
                Answering(
                    when=["issue", "comment"],
                    output=f"https://github.com/{OWN}/issues/1#issuecomment-1\n",
                ),
                Answering(when=["issue", "close"]),
                Answering(when=["issue", "reopen"]),
                Answering(when=["issue", "edit"]),
                Answering(when=["pr", "edit"]),
            ]
        )


@contextmanager
def cloned() -> Generator[Path]:
    """Make the project's clone, its `origin` on GitHub, and return its git directory, gone once the promise ends."""
    with tempfile.TemporaryDirectory(prefix="lup-github-") as directory:
        work = GIT.made(Path(directory) / "work")
        GIT.git("config", "remote.origin.url", f"git@github.com:{OWN}.git", cwd=work)
        yield work / ".git"


async def started_on(
    by: Testing, common: Path, gh: Gh, declaration: str | None = None
) -> Started:
    """Start lup on lup's defaults, or `declaration`, `gh` stood in for as `gh` scripts it."""
    declared = (
        lup.Project(modules=lup.Modules.default())
        if declaration is None
        else Repository(declaration=declaration)
    )
    return await by.started(
        declared,
        programs={"git": GIT, "ssh": SSH, "gh": gh.script()},
        git=common,
    )


def asked(started: Started, *verb: str) -> list[list[str]]:
    """Return the arguments of each run of `gh` lup asked for whose first are `verb`."""
    return [each for each in started.ran("gh") if each[: len(verb)] == list(verb)]


class Said(Model):
    """What an issue filed says, drawn: a word that's refused, or not."""

    word: Literal["hush", "fine"]


class GitHubPromises(Part):
    """What the operator can count on of what agents do on GitHub under their name."""

    @lup.promise
    async def a_post_goes_to_the_projects_own_repository(self, by: Testing) -> None:
        """An issue filed goes to the project's own repository on GitHub, as its remote names it, whatever repository the call might mean."""
        with cloned() as common:
            started = await started_on(by, common, Gh())
            filed = await started.call(
                "file_issue", {"title": "a bug", "body": "it breaks"}, by.any(Agent)
            )
            assert isinstance(filed, Accepted), filed
            [created] = asked(started, "issue", "create")
            assert f"--repo={OWN}" in created

    @lup.promise
    async def a_post_refused_at_publishing_isnt_posted(self, by: Testing) -> None:
        """What a post would publish is told at `Publishing` first, and where a part hearing it refuses, nothing is posted."""
        said = by.any(Said).word
        with cloned() as common:
            started = await started_on(by, common, Gh(), GUARDED)
            filed = await started.call(
                "file_issue",
                {"title": "a bug", "body": f"it says {said}"},
                by.any(Agent),
            )
            assert isinstance(filed, Refused) == (said == "hush")
            assert bool(asked(started, "issue", "create")) == (said == "fine")

    @lup.promise
    async def an_action_the_declaration_drops_is_refused(self, by: Testing) -> None:
        """An action the project's declaration drops is refused before `gh` runs."""
        with cloned() as common:
            started = await started_on(by, common, Gh(), WITHHOLDING)
            filed = await started.call(
                "file_issue", {"title": "a bug", "body": "it breaks"}, by.any(Agent)
            )
            assert isinstance(filed, Refused)
            assert not asked(started, "issue", "create")

    @lup.promise
    async def a_repository_named_otherwise_than_owner_name_is_refused(
        self, by: Testing
    ) -> None:
        """A repository a call names is read only where it's `owner/name`, as GitHub spells one: anything else never reaches `gh`."""
        named = by.any(Named).repository
        with cloned() as common:
            started = await started_on(by, common, Gh())
            read = await started.call(
                "read_issue", {"number": 1, "repository": named}, by.any(Agent)
            )
            assert isinstance(read, Refused)
            assert not asked(started, "issue", "view")

    @lup.promise
    async def closing_a_pull_request_is_refused_before_anything_is_posted(
        self, by: Testing
    ) -> None:
        """Closing or reopening is for an issue in the state it changes: a pull request, or an issue already so, is refused before its comment is posted."""
        pulls = by.any(bool)
        with cloned() as common:
            started = await started_on(by, common, Gh(pulls=pulls))
            closed = await started.call(
                "close_issue",
                {"number": 1, "reason": "completed", "comment": "done"},
                by.any(Agent),
            )
            assert isinstance(closed, Refused) == pulls
            assert bool(asked(started, "issue", "comment")) != pulls

    @lup.promise
    async def an_issues_state_is_said_as_github_has_it(self, by: Testing) -> None:
        """Whether an issue is open or closed, as the gate asks of what a `defer` waits on, is GitHub's word."""
        state = by.any(State).state
        with cloned() as common:
            started = await started_on(by, common, Gh(state=state))
            stated = await started.serve(
                "issue_state", {"number": 1}, Codebase(repository="harmon")
            )
            assert isinstance(stated, Accepted), stated
            assert json.loads(stated.answer())["state"] == state.lower()


class Named(Model):
    """A repository a call names, but not as `owner/name`."""

    repository: Literal["../harmon", "joy-void-joy", "a/b/c", "-r/x", "a b/c"]


class State(Model):
    """An issue's state on GitHub."""

    state: Literal["OPEN", "CLOSED"]
