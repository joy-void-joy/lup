"""What `gh` answers, read into models: each asked for with `--json`, or GitHub's API through `gh api`, its fields spelled as GitHub spells them.

A tool's answer is text an agent reads, so each model says itself (`text`).
"""

import shlex
import string
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, Field
from pydantic.alias_generators import to_camel

from lup.types import Model


def repository_name(
    value: str, spelled_with: str = string.ascii_letters + string.digits + "-._"
) -> str:
    """Return `value` where it names a repository on GitHub, `owner/name`, as GitHub spells one: two names apart by a `/`, each of the characters in `spelled_with`, neither starting with `-` or `.`, so it reaches `gh --repo` as a repository and nothing else.

    >>> repository_name("joy-void-joy/lup")
    'joy-void-joy/lup'
    """
    parts = PurePosixPath(value).parts
    spelled = len(parts) == 2 and all(
        each
        and not each.startswith(("-", "."))
        and all(letter in spelled_with for letter in each)
        for each in parts
    )
    if not spelled or str(PurePosixPath(*parts)) != value:
        message = f"a repository on GitHub is `owner/name`, not {value!r}"
        raise ValueError(message)
    return value


type RepositoryName = Annotated[str, AfterValidator(repository_name)]
"""A repository on GitHub, `owner/name`."""


class Answered(Model, alias_generator=to_camel, validate_by_name=True):
    """An answer of `gh --json`, its fields spelled as GitHub's API spells them."""

    @classmethod
    def fields(cls) -> str:
        """Return the fields `--json` asks for: this model's, as GitHub spells them."""
        return ",".join(field.alias or name for name, field in cls.model_fields.items())


class Login(Answered):
    """Someone on GitHub, by their login."""

    login: str


def written_by(author: Login | None) -> str:
    """Name who wrote something: their login, or a deleted account, which GitHub gives none.

    >>> written_by(None)
    'a deleted account'
    """
    return author.login if author is not None else "a deleted account"


class Label(Answered):
    """A label on an issue or pull request."""

    name: str


class Comment(Answered):
    """A comment on an issue or pull request."""

    id: str
    """Its node id in GitHub's GraphQL API, which editing it names."""
    author: Login | None
    created_at: datetime
    url: str
    body: str

    def text(self) -> str:
        """Say the comment whole, under who wrote it, when, and its link."""
        return (
            f"{written_by(self.author)}, {self.created_at:%Y-%m-%d %H:%M %Z}, "
            f"{self.url}:\n{self.body}"
        )


class Review(Answered):
    """A review of a pull request: who, how they decided, and what they wrote."""

    author: Login | None
    state: str
    """`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED` or `DISMISSED`."""
    submitted_at: datetime | None = None
    body: str

    def text(self) -> str:
        """Say the review whole, under who wrote it, how they decided, and when."""
        when = (
            ""
            if self.submitted_at is None
            else f", {self.submitted_at:%Y-%m-%d %H:%M %Z}"
        )
        said = f":\n{self.body}" if self.body else "."
        return f"{written_by(self.author)} reviewed, {self.state.lower()}{when}{said}"


class User(Model):
    """Someone on GitHub, as its REST API names them."""

    login: str


class ReviewComment(Model):
    """A comment on a line of a pull request's diff, as GitHub's REST API gives it."""

    user: User | None
    path: str
    line: int | None = None
    """Its line in the file the pull request's head holds; none where the
    line is gone from it."""
    body: str
    html_url: str
    created_at: datetime

    def text(self) -> str:
        """Say the comment whole, under who wrote it, where, when, and its link."""
        author = self.user.login if self.user is not None else "a deleted account"
        place = self.path if self.line is None else f"{self.path}:{self.line}"
        return (
            f"{author} on {place}, {self.created_at:%Y-%m-%d %H:%M %Z}, "
            f"{self.html_url}:\n{self.body}"
        )


class CheckRun(Answered):
    """A check run on a pull request's head, a GitHub Actions job among them."""

    typename: Literal["CheckRun"] = Field(alias="__typename")
    name: str
    workflow_name: str
    status: str
    conclusion: str
    details_url: str

    def text(self) -> str:
        """Say the check in a line: its name, its workflow, how it stands, where to look."""
        workflow = f" ({self.workflow_name})" if self.workflow_name else ""
        stands = (self.conclusion or self.status).lower()
        return f"{self.name}{workflow}: {stands} {self.details_url}"


class StatusContext(Answered):
    """A commit status on a pull request's head, from a service outside GitHub Actions."""

    typename: Literal["StatusContext"] = Field(alias="__typename")
    context: str
    state: str
    target_url: str

    def text(self) -> str:
        """Say the status in a line: its context, how it stands, where to look."""
        return f"{self.context}: {self.state.lower()} {self.target_url}"


type Check = Annotated[CheckRun | StatusContext, Field(discriminator="typename")]
"""One of a pull request's checks, told apart by GitHub's type for it."""


class Said(Model):
    """Something said on a thread: when, and as it's told."""

    at: datetime
    text: str


def thread(heading: list[str], body: str, comments: list[str]) -> str:
    """Say an issue's or pull request's thread: its heading, its body, then each comment whole."""
    return "\n\n".join(
        [
            "\n".join(heading),
            body or "(No description.)",
            f"Comments ({len(comments)}):" if comments else "No comments.",
            *comments,
        ]
    )


class Issue(Answered):
    """An issue, with its comments, as `gh issue view --json` gives it."""

    number: int
    title: str
    state: Literal["OPEN", "CLOSED"]
    author: Login | None
    created_at: datetime
    url: str
    labels: list[Label]
    body: str
    comments: list[Comment]

    def text(self) -> str:
        """Say the issue whole: what it is, its body, then each comment."""
        labels = ", ".join(label.name for label in self.labels)
        heading = [
            f"Issue #{self.number}, {self.state.lower()}: {self.title}",
            self.url,
            f"Opened by {written_by(self.author)}, {self.created_at:%Y-%m-%d %H:%M %Z}.",
            *([f"Labels: {labels}."] if labels else []),
        ]
        return thread(heading, self.body, [each.text() for each in self.comments])


class PullRequest(Answered):
    """A pull request, with its comments, reviews and checks, as `gh pr view --json` gives it."""

    number: int
    title: str
    state: Literal["OPEN", "CLOSED", "MERGED"]
    is_draft: bool
    author: Login | None
    created_at: datetime
    url: str
    head_ref_name: str
    base_ref_name: str
    review_decision: str
    labels: list[Label]
    body: str
    comments: list[Comment]
    reviews: list[Review]
    status_check_rollup: list[Check]

    def text(self, inline: list[ReviewComment]) -> str:
        """Say the pull request whole, with `inline`, the comments on lines of its diff: what it is, its checks, its body, then each comment, review and comment on a line, in the order they were written."""
        draft = ", a draft" if self.is_draft else ""
        labels = ", ".join(label.name for label in self.labels)
        review = f" Review: {self.review_decision}." if self.review_decision else ""
        checks = [f"- {check.text()}" for check in self.status_check_rollup]
        heading = [
            f"Pull request #{self.number}, {self.state.lower()}{draft}: {self.title}",
            self.url,
            (
                f"Opened by {written_by(self.author)}, "
                f"{self.created_at:%Y-%m-%d %H:%M %Z}, from `{self.head_ref_name}` "
                f"into `{self.base_ref_name}`.{review}"
            ),
            *([f"Labels: {labels}."] if labels else []),
            *(["Checks:", *checks] if checks else ["Checks: none reported."]),
        ]
        said = sorted(
            [
                *(Said(at=each.created_at, text=each.text()) for each in self.comments),
                *(
                    Said(at=each.submitted_at, text=each.text())
                    for each in self.reviews
                    if each.submitted_at is not None
                ),
                *(Said(at=each.created_at, text=each.text()) for each in inline),
            ],
            key=lambda each: each.at,
        )
        return thread(heading, self.body, [each.text for each in said])


class Named(Answered):
    """A repository, as a search names it."""

    name_with_owner: str


class Found(Answered):
    """An issue or pull request a search found, as `gh search issues --json` gives it."""

    number: int
    title: str
    state: str
    is_pull_request: bool
    updated_at: datetime
    repository: Named

    def text(self) -> str:
        """Say what was found in a line: its number, whether it's a pull request, its state, its title."""
        what = "pull request" if self.is_pull_request else "issue"
        return f"#{self.number}  {what}, {self.state}, updated {self.updated_at:%Y-%m-%d}: {self.title}"


class State(Answered):
    """`gh issue view --json state`'s answer."""

    state: Literal["OPEN", "CLOSED"]


class Ref(Answered):
    """A branch, as GitHub's GraphQL answers for one."""

    name: str


class Refs(Answered):
    """A repository, as the branch query reads it: the branch, or none."""

    ref: Ref | None


class Branched(Answered):
    """The branch query's data."""

    repository: Refs


class BranchQuery(Answered):
    """The branch query's answer."""

    data: Branched


class EditedComment(Answered):
    """A comment, as the edit's answer names it."""

    url: str


class CommentUpdate(Answered):
    """The edit's payload."""

    issue_comment: EditedComment


class CommentUpdated(Answered):
    """The edit's data."""

    update_issue_comment: CommentUpdate


class CommentAnswer(Answered):
    """The edit's answer."""

    data: CommentUpdated


def terms(query: str) -> list[str]:
    """Return a search query's terms as `gh search` takes them: each word and qualifier apart, a phrase in double quotes whole.

    `gh` searches an argument holding a space as a phrase, so a query given
    whole would be one phrase. An apostrophe is part of its word. Raise
    `ValueError` where a double quote doesn't close.

    >>> terms('''label:bug "held call" don't''')
    ['label:bug', 'held call', "don't"]
    """
    lexer = shlex.shlex(query, posix=True)
    lexer.whitespace_split = True
    lexer.quotes = '"'
    lexer.commenters = ""
    return list(lexer)
