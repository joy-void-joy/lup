"""What ``dev survey`` says about a forge it may not have reached.

A survey is read by ``/lup:land`` before it proposes a verb for every branch
in the repository, so a field that is structurally empty and a field that is
empty because the remote answered that way have to be told apart. These pin
the two places where they could not be.
"""

import json

import pytest

from lup.devtools.dev import branches
from lup.devtools import utils


class Recorder:
    """A stand-in for the `gh` command that keeps the arguments it was given."""

    def __init__(self, output: str = "") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.output = output

    def __call__(self, *arguments: str) -> str:
        self.calls.append(arguments)
        return self.output

    def out(self, *arguments: str) -> str:
        return self(*arguments)


PR_ROW = {
    "number": 169,
    "title": "fix(policy): type-check only the files the checker can read",
    "state": "OPEN",
    "mergedAt": None,
    "headRefName": "diagnostics-python-only",
    "url": "https://github.com/owner/name/pull/169",
}


@pytest.fixture
def gh_rows(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    """A `gh` answering one PR row, with the repository slug readable."""
    monkeypatch.setattr(utils, "repository_slug", lambda: "owner/name")
    recorder = Recorder(output=json.dumps([PR_ROW]))
    monkeypatch.setattr(branches, "gh", recorder)
    return recorder


def test_the_survey_asks_for_the_field_it_declares(gh_rows: Recorder) -> None:
    """``PRStatus.url`` is declared, so the query that fills it has to ask."""
    statuses = branches.fetch_pr_status(["diagnostics-python-only"])

    arguments = gh_rows.calls[0]
    requested = arguments[arguments.index("--json") + 1]
    assert "url" in requested.split(",")  # lup: ignore[string-split] — gh field list
    assert statuses["diagnostics-python-only"].url == PR_ROW["url"]
