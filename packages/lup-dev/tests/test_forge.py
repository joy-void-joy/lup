"""lup's GitHub tools, the room's issue states and naming the repository, through a stand-in `gh`.

No test reaches GitHub. `gh` is a script on the `PATH` that records each call
(its arguments, its standard input, where it ran) and answers as the test
scripted it, with `gh` 2.102.0's own answers recorded in `payloads/gh-2.102.0/`
(their bodies shortened; the pull request's checks and comment taken from other
answers recorded the same day, since lup's pull requests have none). The host
service the gate asks runs on sockets under the test's directory.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from lup.github.module import GitHub
from lup.github.tools import GitHubTools
from lup.tools.serving import Answer
from lup_dev import Modules, Project
from lup_dev.codescan.directives import HostIssues, IssueRef
from lup_dev.declaration.resolve import resolve
from lup_dev.forge.github import GitHubError, named
from lup_dev.host.client import RoomClient, asked
from lup_dev.host.courier import Conversation, Courier, Heard, Telling
from lup_dev.host.protocol import (
    Action,
    Done,
    GitHubRepository,
    Limits,
    Register,
    Registered,
    Stop,
    actions,
)
from lup_dev.host.records import Record, Records
from lup_dev.host.service import Answerer, Asked, HostService, Judged
from lup_dev.host.workers import Calling
from lup_dev.layout import HostLayout, Layout
from lup_dev.worker import Serving

if TYPE_CHECKING:
    from collections.abc import Generator

    from conftest import InProcess
    from pydantic import JsonValue

    from lup_dev.host.workers import LaunchModules

RECORDED = Path(__file__).parent / "payloads" / "gh-2.102.0"
LUP = GitHubRepository(owner="joy-void-joy", name="lup")
CALLER = Conversation(id="c1", session="s1")


class Nothing(Records):
    """A runtime that keeps no records."""

    def kept(self, under: list[Path]) -> list[Record]:
        return []

    def conversation(self, session: str, agent: str | None) -> Path | None:
        return None


STAND_IN = """#!{python}
import json, os, sys
from pathlib import Path

here = Path(__file__).parent
with (here / "calls.jsonl").open("a") as log:
    log.write(json.dumps({{
        "arguments": sys.argv[1:],
        "input": sys.stdin.read(),
        "directory": os.getcwd(),
        "pinned": {{
            name: os.environ.get(name) for name in ["GIT_DIR", "GIT_COMMON_DIR"]
        }},
    }}) + "\\n")
words = " ".join(sys.argv[1:3])
answers = json.loads((here / "answers.json").read_text())
if words not in answers:
    sys.stderr.write(f"the stand-in has no answer for `{{words}}`\\n")
    sys.exit(1)
answer = answers[words]
sys.stdout.write(answer["output"])
sys.stderr.write(answer["error"])
sys.exit(answer["status"])
"""


class Call(BaseModel):
    """One call the stand-in `gh` heard."""

    arguments: list[str]
    input: str
    directory: str
    pinned: dict[str, str | None]
    """`GIT_DIR` and `GIT_COMMON_DIR` as `gh`, and the git it runs, had them."""


def pinned_to(directory: Path) -> dict[str, str | None]:
    """`GIT_DIR` and `GIT_COMMON_DIR` both naming `directory`."""
    return {"GIT_DIR": str(directory), "GIT_COMMON_DIR": str(directory)}


class Gh:
    """A stand-in `gh` on the `PATH`: each call recorded, each answered as scripted by its first two words."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True)
        program = directory / "gh"
        program.write_text(STAND_IN.format(python=sys.executable))
        program.chmod(0o755)
        self.answers: dict[str, dict[str, object]] = {}
        self.write()

    def write(self) -> None:
        (self.directory / "answers.json").write_text(json.dumps(self.answers))

    def answer(
        self, words: str, output: str = "", *, status: int = 0, error: str = ""
    ) -> None:
        self.answers[words] = {"output": output, "status": status, "error": error}
        self.write()

    def recorded(self, words: str, name: str) -> None:
        self.answer(words, (RECORDED / name).read_text())

    def calls(self) -> list[Call]:
        log = self.directory / "calls.jsonl"
        if not log.exists():
            return []
        return [Call.model_validate_json(line) for line in log.read_text().splitlines()]

    def arguments(self) -> list[list[str]]:
        return [call.arguments for call in self.calls()]


@pytest.fixture
def gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Gh:
    stand_in = Gh(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{stand_in.directory}{os.pathsep}{os.environ['PATH']}")
    return stand_in


def launch(
    tmp_path: Path,
    allowed: list[Action] | None = None,
    github: GitHubRepository | None = LUP,
) -> Register:
    """A launch of lup's own repository, its git directory a directory under `tmp_path`."""
    repository = tmp_path / "lup.git"
    repository.mkdir(exist_ok=True)
    (tmp_path / "judge").touch()
    return Register(
        launch="one",
        runtime="claude",
        worktree=tmp_path,
        repository=repository,
        judge=tmp_path / "judge",
        container="lup-one",
        limits=Limits(
            actions=actions() if allowed is None else allowed,
            protected=["refs/heads/main"],
        ),
        github=github,
    )


def called(
    name: str, arguments: JsonValue, registered: Register, limit: int = 100
) -> Answer:
    """Call one of the GitHub module's tools as a launch's own process calls it."""
    declared = Project(modules=Modules.default().edit(GitHub(limit=limit)))
    serving = Serving(
        launch=registered,
        resolved=resolve(declared),
        records=Nothing(),
        layout=Layout(state=registered.worktree, data=registered.worktree),
    )
    calling = Calling(name=name, arguments=arguments, caller=CALLER)
    return asyncio.run(serving.call(calling))


def test_each_tool_is_summarized_in_fifty_characters_at_most() -> None:
    specs = GitHubTools.specs()
    assert {spec.name: spec.summary for spec in specs} == {
        "read_issue": "Read an issue or pull request, with its comments.",
        "find_issues": "Search a repository's issues and pull requests.",
        "file_issue": "File an issue in this repository.",
        "comment": "Comment on an issue or pull request.",
        "draft_pull_request": "Open a draft pull request from a pushed branch.",
    }
    assert all(len(spec.summary) <= 50 for spec in specs)


def test_a_call_with_an_argument_no_tool_takes_is_refused(
    gh: Gh, tmp_path: Path
) -> None:
    answer = called("find_issues", {"query": "x", "limit": 5}, launch(tmp_path))
    assert answer.error
    assert answer.text.startswith("`find_issues` refused the call:")
    assert "limit" in answer.text
    assert gh.calls() == []


def test_read_issue_reads_a_pull_request_with_its_comments_and_checks(
    gh: Gh, tmp_path: Path
) -> None:
    gh.recorded("pr view", "pr-view.json")
    registered = launch(tmp_path)
    answer = called("read_issue", {"number": 59}, registered)
    assert not answer.error
    assert answer.text == (
        "Pull request #59, merged: Design: launch, a terminal session in a room "
        "compiled from the declaration (#56, piece 1)\n"
        "https://github.com/joy-void-joy/lup/pull/59\n"
        "Opened by joy-void-joy, 2026-10-12 11:39 UTC, from `docs-launch` into `dev`.\n"
        "Checks:\n"
        "- lint (Lint): success "
        "https://github.com/cli/cli/actions/runs/38480825430/job/115582695282\n"
        "- node-test-commit: failure https://ci.nodejs.org/job/node-test-commit/93240/"
        "\n\n"
        "The design note for #56's first piece, `docs/launch.md`, with the facts it "
        "rests on in `docs/field-notes.md` and the `DESIGN.md` changes agreed while "
        "scoping #56. No code.\n\n"
        "Comments (1):\n\n"
        "joy-void-joy, 2026-10-12 09:48 UTC:\n"
        "Settled in docs/library.md with the library's first slice (merged on dev)."
    )
    [call] = gh.calls()
    assert call.arguments == [
        "pr",
        "view",
        "59",
        "--repo=joy-void-joy/lup",
        (
            "--json=number,title,state,isDraft,author,createdAt,url,headRefName,"
            "baseRefName,reviewDecision,labels,body,comments,statusCheckRollup"
        ),
    ]
    assert call.directory == str(registered.repository)


def test_read_issue_reads_an_issue_where_the_number_is_no_pull_request(
    gh: Gh, tmp_path: Path
) -> None:
    gh.answer(
        "pr view",
        status=1,
        error=(
            "GraphQL: Could not resolve to a PullRequest with the number of 50. "
            "(repository.pullRequest)\n"
        ),
    )
    gh.recorded("issue view", "issue-view.json")
    answer = called("read_issue", {"number": 50}, launch(tmp_path))
    assert not answer.error
    assert answer.text.startswith(
        "Issue #50, closed: docs/library.md names the output tool lup_submit; the "
        "code names it submit\nhttps://github.com/joy-void-joy/lup/issues/50\n"
        "Opened by joy-void-joy, 2026-10-12 08:33 UTC.\n\n"
    )
    assert answer.text.endswith(
        "Comments (1):\n\njoy-void-joy, 2026-10-12 09:48 UTC:\nSettled in "
        "docs/library.md with the library's first slice (merged on dev): the output "
        "tool is `submit`."
    )
    assert [arguments[:4] for arguments in gh.arguments()] == [
        ["pr", "view", "50", "--repo=joy-void-joy/lup"],
        ["issue", "view", "50", "--repo=joy-void-joy/lup"],
    ]


def test_read_issue_says_gh_s_own_words_where_there_is_no_such_number(
    gh: Gh, tmp_path: Path
) -> None:
    missing = (
        "GraphQL: Could not resolve to an issue or pull request with the number of "
        "999999. (repository.issue)\n"
    )
    gh.answer("pr view", status=1, error="not a pull request\n")
    gh.answer("issue view", status=1, error=missing)
    answer = called("read_issue", {"number": 999999}, launch(tmp_path))
    assert answer.error
    assert answer.text.startswith("`read_issue` didn't run: `gh issue view 999999")
    assert answer.text.endswith(f"ended with status 1: {missing.strip()}")


def test_find_issues_searches_this_repository_alone(gh: Gh, tmp_path: Path) -> None:
    gh.recorded("search issues", "search-issues.json")
    answer = called(
        "find_issues",
        {"query": 'launch "held call" -label:wontfix', "state": "open"},
        launch(tmp_path),
    )
    assert not answer.error
    assert answer.text == (
        '2 open in joy-void-joy/lup for `launch "held call" -label:wontfix`:\n'
        "#56  issue, open, updated 2026-10-12: launch: the harness, a lup launch "
        "claude that doesn't get in the agent's way\n"
        "#65  issue, open, updated 2026-10-13: Keep lup's own copy of each launched "
        "session's transcript\n"
        "1 matches in other repositories were left out: a search reads one "
        "repository, which `repository` names."
    )
    assert gh.arguments() == [
        [
            "search",
            "issues",
            "--repo=joy-void-joy/lup",
            "--include-prs",
            "--limit=100",
            "--json=number,title,state,isPullRequest,updatedAt,url,repository",
            "--state=open",
            "--",
            "launch",
            "held call",
            "-label:wontfix",
        ]
    ]


def test_find_issues_searches_another_repository_named_and_it_alone(
    gh: Gh, tmp_path: Path
) -> None:
    gh.recorded("search issues", "search-issues.json")
    registered = launch(tmp_path)
    answer = called(
        "find_issues", {"query": "token", "repository": "cli/cli"}, registered
    )
    assert not answer.error
    assert answer.text == (
        "1 open in cli/cli for `token`:\n"
        "#14673  pull request, open, updated 2026-10-13: Refreshable tokens: "
        "capture `auth_invocation` telemetry on `login` and `refresh`\n"
        "2 matches in other repositories were left out: a search reads one "
        "repository, which `repository` names."
    )
    [call] = gh.calls()
    assert call.arguments[:3] == ["search", "issues", "--repo=cli/cli"]
    assert call.directory == str(registered.repository)


def test_read_issue_reads_another_repository_named(gh: Gh, tmp_path: Path) -> None:
    gh.recorded("pr view", "pr-view.json")
    registered = launch(tmp_path)
    answer = called(
        "read_issue",
        {"number": 59, "repository": "someone/atlas"},
        registered,
    )
    assert not answer.error
    [call] = gh.calls()
    assert call.arguments[:4] == [
        "pr",
        "view",
        "59",
        "--repo=someone/atlas",
    ]
    assert call.directory == str(registered.repository)


def test_reading_another_repository_needs_none_named_for_the_launch(
    gh: Gh, tmp_path: Path
) -> None:
    gh.recorded("search issues", "search-issues.json")
    answer = called(
        "find_issues",
        {"query": "", "repository": "joy-void-joy/lup"},
        launch(tmp_path, github=None),
    )
    assert not answer.error
    assert answer.text.startswith("2 open in joy-void-joy/lup for ``:")
    [arguments] = gh.arguments()
    assert "--repo=joy-void-joy/lup" in arguments


@pytest.mark.parametrize(
    "written", ["atlas", "/atlas", "joy-void-joy/lup/x", "../lup", "a//b"]
)
def test_a_repository_that_isnt_owner_and_name_is_refused_before_gh_runs(
    gh: Gh, tmp_path: Path, written: str
) -> None:
    answer = called(
        "read_issue", {"number": 1, "repository": written}, launch(tmp_path)
    )
    assert answer.error
    assert answer.text.startswith("`read_issue` refused the call:")
    assert "a repository on GitHub is `owner/name`" in answer.text
    assert gh.calls() == []


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("file_issue", {"title": "t", "body": "b", "repository": "cli/cli"}),
        ("comment", {"number": 1, "body": "b", "repository": "cli/cli"}),
        (
            "draft_pull_request",
            {"branch": "b", "title": "t", "body": "b", "repository": "cli/cli"},
        ),
    ],
)
def test_the_tools_that_write_take_no_other_repository(
    gh: Gh, tmp_path: Path, name: str, arguments: JsonValue
) -> None:
    answer = called(name, arguments, launch(tmp_path))
    assert answer.error
    assert answer.text.startswith(f"`{name}` refused the call:")
    assert "repository" in answer.text
    assert gh.calls() == []


def test_only_the_tools_that_read_offer_another_repository() -> None:
    def offers(schema: dict[str, JsonValue]) -> bool:
        properties = schema["properties"]
        assert isinstance(properties, dict)
        return "repository" in properties

    specs = GitHubTools.specs()
    offered = {spec.name: offers(spec.input_schema) for spec in specs}
    assert offered == {
        "read_issue": True,
        "find_issues": True,
        "file_issue": False,
        "comment": False,
        "draft_pull_request": False,
    }


def test_find_issues_says_where_more_may_match_and_searches_every_state(
    gh: Gh, tmp_path: Path
) -> None:
    gh.recorded("search issues", "search-issues.json")
    answer = called(
        "find_issues", {"query": "", "state": "all"}, launch(tmp_path), limit=3
    )
    assert "GitHub gave the first 3 matches it found; more may match" in answer.text
    [arguments] = gh.arguments()
    assert "--limit=3" in arguments
    assert not [each for each in arguments if each.startswith("--state")]
    assert arguments[-1] == "--"


def test_find_issues_refuses_a_query_whose_quotes_dont_close(
    gh: Gh, tmp_path: Path
) -> None:
    answer = called("find_issues", {"query": 'the "held call'}, launch(tmp_path))
    assert answer.error
    assert answer.text.startswith("`find_issues` refused the call:")
    assert "No closing quotation" in answer.text
    assert gh.calls() == []


def test_file_issue_gives_its_body_on_standard_input(gh: Gh, tmp_path: Path) -> None:
    gh.answer("issue create", "https://github.com/joy-void-joy/lup/issues/68\n")
    body = "What's wrong.\n\n--title isn't a flag here; `$(nothing)` runs.\n"
    answer = called(
        "file_issue", {"title": "--not a flag", "body": body}, launch(tmp_path)
    )
    assert answer == Answer(text="Filed: https://github.com/joy-void-joy/lup/issues/68")
    [call] = gh.calls()
    assert call.arguments == [
        "issue",
        "create",
        "--repo=joy-void-joy/lup",
        "--title=--not a flag",
        "--body-file=-",
    ]
    assert call.input == body


def test_comment_gives_its_body_on_standard_input(gh: Gh, tmp_path: Path) -> None:
    link = "https://github.com/joy-void-joy/lup/issues/66#issuecomment-1"
    gh.answer("issue comment", f"{link}\n")
    answer = called(
        "comment", {"number": 66, "body": "Can this close?"}, launch(tmp_path)
    )
    assert answer == Answer(text=f"Commented: {link}")
    [call] = gh.calls()
    assert call.arguments == [
        "issue",
        "comment",
        "66",
        "--repo=joy-void-joy/lup",
        "--body-file=-",
    ]
    assert call.input == "Can this close?"


def test_draft_pull_request_opens_a_draft_into_the_integration_branch(
    gh: Gh, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LUP_INTEGRATION_BRANCH", "next")
    gh.answer("api graphql", '{"data":{"repository":{"ref":{"name":"feat-forge"}}}}')
    gh.answer("pr create", "https://github.com/joy-void-joy/lup/pull/70\n")
    answer = called(
        "draft_pull_request",
        {"branch": "feat-forge", "title": "GitHub's tools", "body": "Why."},
        launch(tmp_path),
    )
    assert answer == Answer(
        text=(
            "Opened a draft pull request from `feat-forge` into `next`: "
            "https://github.com/joy-void-joy/lup/pull/70"
        )
    )
    lookup, create = gh.calls()
    assert lookup.arguments[:2] == ["api", "graphql"]
    assert lookup.arguments[3:] == [
        "--raw-field=owner=joy-void-joy",
        "--raw-field=name=lup",
        "--raw-field=qualified=refs/heads/feat-forge",
    ]
    assert create.arguments == [
        "pr",
        "create",
        "--repo=joy-void-joy/lup",
        "--draft",
        "--base=next",
        "--head=feat-forge",
        "--title=GitHub's tools",
        "--body-file=-",
    ]
    assert create.input == "Why."


def test_draft_pull_request_says_a_branch_must_be_pushed_first(
    gh: Gh, tmp_path: Path
) -> None:
    gh.answer("api graphql", '{"data":{"repository":{"ref":null}}}')
    answer = called(
        "draft_pull_request",
        {"branch": "attacker:evil", "title": "t", "body": "b"},
        launch(tmp_path),
    )
    assert answer == Answer(
        text=(
            "`draft_pull_request` didn't run: `attacker:evil` isn't a branch of "
            "joy-void-joy/lup on GitHub: push it there first (`git push`), then "
            "open its pull request"
        ),
        error=True,
    )
    assert [arguments[:2] for arguments in gh.arguments()] == [["api", "graphql"]]


@pytest.mark.parametrize(
    ("name", "arguments", "action"),
    [
        ("read_issue", {"number": 1}, "read-issues"),
        ("find_issues", {"query": "x"}, "read-issues"),
        ("file_issue", {"title": "t", "body": "b"}, "file-issue"),
        ("comment", {"number": 1, "body": "b"}, "comment"),
        (
            "draft_pull_request",
            {"branch": "b", "title": "t", "body": "b"},
            "draft-pull-request",
        ),
    ],
)
def test_an_action_beyond_the_limits_is_refused_before_gh_runs(
    gh: Gh, tmp_path: Path, name: str, arguments: JsonValue, action: Action
) -> None:
    allowed: list[Action] = [each for each in actions() if each != action]
    answer = called(name, arguments, launch(tmp_path, allowed))
    assert answer == Answer(
        text=(
            f"`{name}` didn't run: the project's declaration doesn't allow "
            f"`{action}` with the operator's credentials (`Core.credentials`), and "
            "allowing it is the operator's call"
        ),
        error=True,
    )
    assert gh.calls() == []


def test_a_launch_whose_repository_wasnt_named_reaches_no_github(
    gh: Gh, tmp_path: Path
) -> None:
    answer = called("read_issue", {"number": 1}, launch(tmp_path, github=None))
    assert answer.error
    assert answer.text.startswith(
        "`read_issue` didn't run: this launch has no repository on GitHub"
    )
    assert gh.calls() == []


def test_each_tool_says_why_without_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `env` alone on the `PATH`, which pins the git directory before `gh` runs.
    only = tmp_path / "only-env"
    only.mkdir()
    env = shutil.which("env")
    assert env is not None
    (only / "env").symlink_to(env)
    monkeypatch.setenv("PATH", str(only))
    answer = called("comment", {"number": 1, "body": "b"}, launch(tmp_path))
    assert answer.error
    assert answer.text.startswith(
        "`comment` didn't run: `gh` couldn't run on the host: "
    )


def test_each_tool_says_why_without_a_login(gh: Gh, tmp_path: Path) -> None:
    gh.answer(
        "issue view",
        status=4,
        error="To get started with GitHub CLI, please run:  gh auth login\n",
    )
    gh.answer("pr view", status=4, error="To get started with GitHub CLI\n")
    answer = called("read_issue", {"number": 1}, launch(tmp_path))
    assert answer.error
    assert answer.text == (
        "`read_issue` didn't run: `gh` on the host has no GitHub login; `gh auth "
        "login` there signs in. It said: To get started with GitHub CLI, please "
        "run:  gh auth login"
    )


def test_every_call_names_the_registered_repository(gh: Gh, tmp_path: Path) -> None:
    gh.recorded("pr view", "pr-view.json")
    gh.recorded("search issues", "search-issues.json")
    gh.answer("issue create", "https://github.com/x/y/issues/1\n")
    gh.answer("issue comment", "https://github.com/x/y/issues/1#c\n")
    gh.answer("api graphql", '{"data":{"repository":{"ref":{"name":"b"}}}}')
    gh.answer("pr create", "https://github.com/x/y/pull/2\n")
    registered = launch(tmp_path)
    cases: list[tuple[str, JsonValue]] = [
        ("read_issue", {"number": 1}),
        ("find_issues", {"query": "repo:someone/private"}),
        ("file_issue", {"title": "t", "body": "--repo=someone/private"}),
        ("comment", {"number": 1, "body": "b"}),
        ("draft_pull_request", {"branch": "b", "title": "t", "body": "b"}),
    ]
    for name, arguments in cases:
        assert not called(name, arguments, registered).error
    calls = gh.calls()
    assert len(calls) == 6
    for call in calls:
        arguments = call.arguments
        named_repository = [each for each in arguments if each.startswith("--repo=")]
        graphql = [each for each in arguments if each.startswith("--raw-field=owner")]
        assert named_repository == ["--repo=joy-void-joy/lup"] or graphql == [
            "--raw-field=owner=joy-void-joy"
        ]
        assert call.directory == str(registered.repository)
        assert call.pinned == pinned_to(registered.repository)


def test_the_repository_is_named_from_its_git_directory_pinned_past_a_planted_commondir(
    gh: Gh, tmp_path: Path
) -> None:
    directory = tmp_path / "lup.git"
    planted = tmp_path / "planted.git"
    for each, probe in [(directory, "the repository's"), (planted, "the room's")]:
        subprocess.run(["git", "init", "-q", "--bare", str(each)], check=True)
        subprocess.run(
            ["git", "config", "--file", str(each / "config"), "lup.probe", probe],
            check=True,
        )
    (directory / "commondir").write_text(f"{planted}\n")
    gh.answer(
        "repo view",
        '{"name":"lup","owner":{"id":"MDQ6VXNlcjU2MjU3NDA1","login":"joy-void-joy"}}\n',
    )
    assert asyncio.run(named(directory)) == LUP
    [call] = gh.calls()
    assert call == Call(
        arguments=["repo", "view", "--json=owner,name"],
        input="",
        directory=str(directory),
        pinned=pinned_to(directory),
    )
    # The git `gh` runs, given what `gh` was, reads the repository's own `config`.
    given = {name: value for name, value in call.pinned.items() if value is not None}
    probed = subprocess.run(
        ["git", "config", "lup.probe"],
        cwd=call.directory,
        env={**os.environ, **given},
        capture_output=True,
        text=True,
        check=True,
    )
    assert probed.stdout.strip() == "the repository's"


def test_naming_says_gh_s_own_words_where_it_cant(gh: Gh, tmp_path: Path) -> None:
    gh.answer("repo view", status=1, error="none of the git remotes point to GitHub\n")
    with pytest.raises(GitHubError, match="none of the git remotes point to GitHub"):
        asyncio.run(named(tmp_path))


class Nobody(Answerer):
    def runtimes(self) -> list[str]:
        return ["claude"]

    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        return ""


class Deaf(Courier):
    """No hook reaches these tests' service: what a courier says is never read."""

    def heard(self, runtime: str, payload: str) -> Heard:
        return Heard(event="call-started", session="s1", judged=False, fits=10_000)

    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        return answer

    def woken(self, runtime: str, session: str, text: str) -> str | None:
        return None


async def unjudged(asked: Asked) -> Judged:
    message = f"no hook reaches a judge here: {asked}"
    raise AssertionError(message)


@contextmanager
def hosting(
    tmp_path_factory: pytest.TempPathFactory,
    registered: Register,
    modules: LaunchModules | None,
) -> Generator[RoomClient]:
    """Serve `registered` in a host service of its own thread, with lup's default modules, the GitHub module among them, or without any, as an older service; yield its room's client."""
    base = tmp_path_factory.mktemp("host")
    layout = HostLayout(sockets=base / "run", state=base / "state")
    service = HostService(
        layout=layout,
        answerer=Nobody(),
        courier=Deaf(),
        judge=unjudged,
        say=lambda line: None,
        modules=modules,
    )
    bound = threading.Event()
    failures: list[BaseException] = []

    def run() -> None:
        async def serve() -> None:
            async with service.serving() as serving:
                bound.set()
                await serving.stopped.wait()

        try:
            asyncio.run(serve())
        except BaseException as failure:
            failures.append(failure)
        finally:
            bound.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    bound.wait()
    assert not failures
    patience = timedelta(seconds=30)
    asked(layout.control, registered, Registered, patience)
    try:
        yield RoomClient(socket=layout.launch(registered.launch).request)
    finally:
        asked(layout.control, Stop(), Done, patience)
        thread.join(timeout=60)


def test_the_host_answers_the_gate_s_issue_states_in_a_room(
    gh: Gh,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    default_modules: InProcess,
) -> None:
    said: list[str] = []
    registered = launch(tmp_path)
    with hosting(tmp_path_factory, registered, default_modules) as room:
        issues = HostIssues(client=room, say=said.append)
        assert issues.unreachable() is None
        gh.answer("issue view", '{"state":"CLOSED"}\n')
        assert issues.state(IssueRef(number=50)) == "closed"
        gh.answer("issue view", '{"state":"OPEN"}\n')
        assert issues.state(IssueRef(repository="cli/cli", number=14673)) == "open"
    assert said == []
    assert [call.arguments for call in gh.calls()] == [
        ["issue", "view", "50", "--repo=joy-void-joy/lup", "--json=state"],
        ["issue", "view", "14673", "--repo=cli/cli", "--json=state"],
    ]


def test_an_issue_the_host_wont_read_goes_unchecked_and_says_why(
    gh: Gh,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    default_modules: InProcess,
) -> None:
    said: list[str] = []
    allowed: list[Action] = [each for each in actions() if each != "read-issues"]
    registered = launch(tmp_path, allowed)
    with hosting(tmp_path_factory, registered, default_modules) as room:
        state = HostIssues(client=room, say=said.append).state(IssueRef(number=50))
    assert state == "unchecked"
    assert said == [
        (
            "Issue #50 went unchecked: the host service said lup didn't read the "
            "issue's state: the project's declaration doesn't allow `read-issues` "
            "with the operator's credentials (`Core.credentials`), and allowing it "
            "is the operator's call."
        )
    ]
    assert gh.calls() == []


def test_an_older_service_refuses_the_kind_by_its_name_and_the_issue_goes_unchecked(
    gh: Gh, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    said: list[str] = []
    with hosting(tmp_path_factory, launch(tmp_path), None) as room:
        state = HostIssues(client=room, say=said.append).state(IssueRef(number=50))
    assert state == "unchecked"
    assert said == [
        (
            "Issue #50 went unchecked: the host service said no handler for "
            "`issue-state`; a room's request socket answers no kind."
        )
    ]


def test_a_room_without_its_request_socket_is_unreachable(tmp_path: Path) -> None:
    issues = HostIssues(
        client=RoomClient(socket=tmp_path / "request.sock"), say=lambda line: None
    )
    assert issues.unreachable() == (
        f"the launch's request socket, {tmp_path / 'request.sock'}, isn't there"
    )
