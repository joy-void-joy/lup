"""A push that did not land, said in the two places a reader looks.

`dev pr push --json` reported `"pushed": false` with git's own message
nowhere in the structure, and the `pr create` chained after it blamed "No
commits between dev and <branch>" -- a sentence describing a branch with
nothing to merge, said about a branch the remote never received. These pin
the field and the sentence that separates the two readings.
"""

import json

import pytest
import sh
import typer

from lup.devtools.dev import pr
from lup.devtools import utils


class StubGit:
    """A git whose push refuses and whose ls-remote answers what it is told."""

    def __init__(self, refuse_push: bool = False, listed: str = "") -> None:
        self.refuse_push = refuse_push
        self.listed = listed

    def __call__(self, *arguments: str) -> str:
        if self.refuse_push:
            raise sh.ErrorReturnCode_128(
                "git push -u origin feat-thing",
                b"",
                b"Please make sure you have the correct access rights"
                b" and the repository exists.\n",
            )
        return ""

    def out(self, *arguments: str) -> str:
        return self.listed


class EmptyGh:
    """A `gh` that finds no open request over the branch."""

    def __call__(self, *arguments: str) -> str:
        return "[]"

    def out(self, *arguments: str) -> str:
        return "[]"


class UnreachableGit:
    """A git whose ls-remote never reaches the host."""

    def out(self, *arguments: str) -> str:
        raise sh.ErrorReturnCode_128("git ls-remote", b"", b"Bad Gateway\n")


@pytest.fixture
def no_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    """A forge with no open request over the branch, so only the push shows."""
    monkeypatch.setattr(utils, "repository_slug", lambda: "owner/name")
    monkeypatch.setattr(pr, "current_branch", lambda: "feat-thing")
    monkeypatch.setattr(pr, "gh", EmptyGh())


def test_a_refused_push_carries_its_reason_into_the_json(
    no_pr: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`pushed: false` beside the sentence that says whether to retry."""
    monkeypatch.setattr(pr, "git", StubGit(refuse_push=True))

    with pytest.raises(typer.Exit):
        pr.push(force=False, as_json=True)

    reported = json.loads(capsys.readouterr().out)
    assert reported["pushed"] is False
    assert "correct access rights" in reported["push_complaint"]


def test_a_push_that_landed_complains_about_nothing(
    no_pr: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pr, "git", StubGit())

    pr.push(force=False, as_json=True)

    reported = json.loads(capsys.readouterr().out)
    assert reported["pushed"] is True
    assert reported["push_complaint"] == ""


def test_a_branch_the_remote_never_received_is_named_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reading gh's sentence points away from, said in its own words."""
    monkeypatch.setattr(pr, "git", StubGit(listed=""))

    diagnosis = pr.creation_diagnosis(
        "feat-thing", "dev", "GraphQL: No commits between dev and feat-thing"
    )

    assert "no feat-thing" in diagnosis
    assert "did not land" in diagnosis


def test_a_branch_the_remote_holds_is_read_as_holding_nothing_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pr, "git", StubGit(listed="abc123\trefs/heads/feat-thing"))

    diagnosis = pr.creation_diagnosis(
        "feat-thing", "dev", "GraphQL: No commits between dev and feat-thing"
    )

    assert "holds nothing dev lacks" in diagnosis


def test_any_other_refusal_is_left_to_say_what_it_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pr, "git", StubGit(listed=""))

    assert pr.creation_diagnosis("feat-thing", "dev", "GraphQL: Not Found") == ""


def test_a_remote_that_could_not_be_asked_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two readings and no way to choose is its own answer, not either one."""
    monkeypatch.setattr(pr, "git", UnreachableGit())

    assert pr.head_on_remote("feat-thing") is pr.HeadOnRemote.unknown
