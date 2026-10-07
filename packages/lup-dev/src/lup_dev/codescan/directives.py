"""The `# lup:` comments the engine reads out of a file, as models, and checking them.

A directive is written as a call (`# lup: ignore("tuple-shape", why="…")`); anything
that isn't a call is a note. The engine parses each comment with pyright's own
expression parser and reports it in one of these shapes, told apart by `kind`. The
grammar and what each directive means are in `docs/judging-writes.md`, *The `# lup:`
directives*.

Each kind answers for itself (`docs/conventions.md`, *Dispatch*): which finding it
keeps, what's wrong with it, and what identifies it across edits. What's wrong is
reported as a `Problem`, which the judge turns into a finding of its own rule:
- `unused-ignore`: an `ignore` whose rule doesn't fire on the line it covers;
- `malformed-directive`: a call the grammar refuses, unknown or incomplete;
- `defer-issue`: a deferral's `issue` that's neither a number nor `owner/repo#7`;
- `defer-condition`: a deferral's `when` naming no declared condition;
- `defer-closed`, at the gate: a deferral whose issue is closed;
- `defer-due`, at the gate: a deferral whose condition holds.
"""

import json
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self, override
from urllib.parse import urlparse

import sh
from pydantic import Field, model_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lup.types import Model
from lup_dev.codescan.conditions import Condition


class IssueRef(Model):
    """An issue a deferral points at: in this repository, or `owner/repo` elsewhere."""

    repository: str | None = None
    """`owner/repo`; none for the repository the code is in."""
    number: int

    @classmethod
    def read(cls, issue: int | str) -> IssueRef | None:
        """Read a deferral's `issue`, or return none where it's neither form.

        >>> IssueRef.read("joy-void-joy/lup#7")
        IssueRef(repository='joy-void-joy/lup', number=7)
        >>> IssueRef.read("lup 7") is None
        True
        """
        match issue:
            case int():
                return cls(number=issue)
            case str():
                parsed = urlparse(issue)
                whole = not parsed.scheme and not parsed.netloc and not parsed.query
                named = len(PurePosixPath(parsed.path).parts) == 2
                if whole and named and parsed.fragment.isdigit():
                    return cls(repository=parsed.path, number=int(parsed.fragment))
                return None

    def __str__(self) -> str:
        """Spell the issue as GitHub does: `#7`, or `owner/repo#7`."""
        return f"{self.repository or ''}#{self.number}"


class Issues(Model, ABC):
    """Where a deferral's issue is tracked, asked whether it's still open."""

    @abstractmethod
    def state(self, issue: IssueRef) -> Literal["open", "closed"]:
        """Say whether `issue` is open or closed."""


class GitHubIssues(Issues):
    """GitHub's issues, through the `gh` command."""

    root: Path
    """The checkout `gh` runs in, which names this repository."""

    @override
    @retry(
        retry=retry_if_exception_type(sh.ErrorReturnCode),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )
    def state(self, issue: IssueRef) -> Literal["open", "closed"]:
        class Viewed(Model):
            """`gh issue view --json state`'s answer."""

            state: Literal["OPEN", "CLOSED"]

        elsewhere = ["--repo", issue.repository] if issue.repository else []
        viewed = sh.Command("gh")(
            "issue",
            "view",
            str(issue.number),
            *elsewhere,
            "--json",
            "state",
            _cwd=str(self.root),
            _tty_out=False,
            _return_cmd=True,
        )
        match Viewed.model_validate_json(viewed.stdout).state:
            case "OPEN":
                return "open"
            case "CLOSED":
                return "closed"


class Gate(Model, arbitrary_types_allowed=True):
    """What the gate adds to a directive's checks: the issues, and the conditions."""

    issues: Issues
    conditions: dict[str, Condition]
    """The project's conditions, by the names its conditions module binds."""


class Fired(Model):
    """A finding as a directive sees it: which rule fired, on which line."""

    rule: str
    line: int


class Checking(Model):
    """What a directive is checked against."""

    fired: list[Fired] = []
    """Every finding in the file, of every owner, before any `ignore` applies."""
    conditions: list[str] | None = None
    """The names the project's conditions module binds; none if it declares none."""
    gate: Gate | None = None
    """At the gate, the issues' states and the conditions themselves."""


class Problem(Model):
    """What's wrong with one directive, as the judge reports it."""

    line: int
    rule: str
    message: str
    steer: str = ""


class Identity(Model):
    """What identifies a directive across edits, whatever line it moves to."""

    text: str
    """The directive as written, after `# lup:`."""
    asked: bool
    """Whether adding it asks the operator: true for an `ignore`."""


class Comment(Model, ABC):
    """What every `# lup:` comment answers for itself."""

    @abstractmethod
    def keeps(self, rule: str, line: int) -> bool:
        """Say whether this comment keeps the finding of `rule` on `line`."""

    @abstractmethod
    def problems(self, checking: Checking) -> list[Problem]:
        """List what's wrong with this comment, as written and against `checking`."""

    @abstractmethod
    def identity(self) -> Identity:
        """Return what identifies this comment across edits."""


class Ignore(Comment):
    """`# lup: ignore("<rule>", why="<reason>")`: keep one finding, with the reason why.

    It covers the line it's on when it follows code there, or the next line when
    it stands alone.
    """

    kind: Literal["ignore"] = "ignore"
    line: int
    """The line the comment is on, counted from 1."""
    covers: int
    """The line whose finding it keeps."""
    rule: str
    why: str

    @override
    def keeps(self, rule: str, line: int) -> bool:
        return rule == self.rule and line == self.covers

    @override
    def problems(self, checking: Checking) -> list[Problem]:
        if any(self.keeps(fired.rule, fired.line) for fired in checking.fired):
            return []
        message = f"`{self.rule}` doesn't fire on line {self.covers}, which this covers"
        steer = "remove the ignore, or move it to the line the finding is on"
        return [
            Problem(line=self.line, rule="unused-ignore", message=message, steer=steer)
        ]

    @override
    def identity(self) -> Identity:
        text = f"ignore({json.dumps(self.rule)}, why={json.dumps(self.why)})"
        return Identity(text=text, asked=True)


class Defer(Comment):
    """`# lup: defer(issue=12, why="…")`: work knowingly left undone, on its code.

    It sits on that code, so the next reader sees the gap is known and tracked
    rather than fixing it blind or calling it pre-existing. It needs a way to come
    back: an issue that tracks it, a condition that wakes it when it holds, or
    both. A deferral with neither is reported as malformed, since nothing would
    ever close it; one whose issue is closed is reported by the gate.
    """

    kind: Literal["defer"] = "defer"
    line: int
    why: str
    """What's left undone here, in one line."""
    issue: int | str | None = None
    """An issue number in this repository, or `owner/repo#7` elsewhere."""
    when: str | None = None
    """The name of a `Condition` declared in Python.

    The gate checks it, and when it holds, the deferral is due.
    """

    @model_validator(mode="after")
    def tracked(self) -> Self:
        """Refuse a deferral that nothing could bring back."""
        if self.issue is None and self.when is None:
            message = "a defer needs an issue, a condition (`when=`), or both"
            raise ValueError(message)
        return self

    @override
    def keeps(self, rule: str, line: int) -> bool:
        return False

    @override
    def problems(self, checking: Checking) -> list[Problem]:
        def problem(rule: str, message: str, steer: str) -> Problem:
            return Problem(line=self.line, rule=rule, message=message, steer=steer)

        issue = None if self.issue is None else IssueRef.read(self.issue)
        if self.issue is not None and issue is None:
            message = f"`issue={self.issue!r}` names no issue"
            steer = "an issue number here, or `owner/repo#7` elsewhere"
            return [problem("defer-issue", message, steer)]
        if self.when is not None and self.when not in (checking.conditions or []):
            message = f"`when={self.when}` names no declared condition"
            steer = "declare it in the conditions module the project names"
            return [problem("defer-condition", message, steer)]
        gate = checking.gate
        if gate is None:
            return []
        closed = issue is not None and gate.issues.state(issue) == "closed"
        due = self.when is not None and gate.conditions[self.when].holds()
        finish = "finish the work here, or point at the issue tracking what's left"
        closing = [problem("defer-closed", f"issue {issue} is closed", finish)]
        message = f"`{self.when}` holds, so the work deferred here is due"
        steer = "do the work, then remove the deferral"
        waking = [problem("defer-due", message, steer)]
        return [*(closing if closed else []), *(waking if due else [])]

    @override
    def identity(self) -> Identity:
        fields = [
            *([f"issue={json.dumps(self.issue)}"] if self.issue is not None else []),
            *([f"when={self.when}"] if self.when is not None else []),
            f"why={json.dumps(self.why)}",
        ]
        return Identity(text=f"defer({', '.join(fields)})", asked=False)


class Note(Comment):
    """A `# lup:` comment that isn't a call: a note for whoever reads the code next."""

    kind: Literal["note"] = "note"
    line: int
    text: str

    @override
    def keeps(self, rule: str, line: int) -> bool:
        return False

    @override
    def problems(self, checking: Checking) -> list[Problem]:
        return []

    @override
    def identity(self) -> Identity:
        return Identity(text=self.text, asked=False)


class Malformed(Comment):
    """A `# lup:` call the grammar refuses: unknown, or missing what it needs."""

    kind: Literal["malformed"] = "malformed"
    line: int
    text: str
    """The comment as written, after `lup:`."""
    problem: str
    """What's wrong with it, in one line."""

    @override
    def keeps(self, rule: str, line: int) -> bool:
        return False

    @override
    def problems(self, checking: Checking) -> list[Problem]:
        steer = (
            "write it as `docs/judging-writes.md` says, under *The `# lup:` directives*"
        )
        return [
            Problem(
                line=self.line,
                rule="malformed-directive",
                message=self.problem,
                steer=steer,
            )
        ]

    @override
    def identity(self) -> Identity:
        return Identity(text=self.text, asked=False)


type Directive = Annotated[
    Ignore | Defer | Note | Malformed, Field(discriminator="kind")
]
"""Any `# lup:` comment, as the engine reports it."""


def missing(kept: list[Directive], since: list[Directive]) -> list[Directive]:
    """List the comments of `since` that `kept` no longer holds, each time removed.

    A comment moved to another line is the same comment: they're compared by what
    they say, not where.
    """
    counts = Counter(directive.identity() for directive in kept)

    def gone(index: int, directive: Directive) -> bool:
        identity = directive.identity()
        earlier = [other for other in since[:index] if other.identity() == identity]
        return len(earlier) >= counts[identity]

    return [
        directive for index, directive in enumerate(since) if gone(index, directive)
    ]


def added_suppressions(
    before: list[Directive], after: list[Directive]
) -> list[Directive]:
    """List the comments `after` adds to `before` that ask the operator: `ignore`s."""
    return [
        directive for directive in missing(before, after) if directive.identity().asked
    ]
