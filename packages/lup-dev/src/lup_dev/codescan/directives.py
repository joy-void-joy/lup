"""The `# lup:` comments the engine reads out of a file, as models, and checking them.

A directive is written as a call (`# lup: ignore("tuple-shape", why="…")`); anything
that isn't a call is a note. The engine parses each comment with pyright's own
expression parser and reports it in one of these shapes, told apart by `kind`. The
grammar and what each directive means are in `docs/judging-writes.md`, *The `# lup:`
directives*.

Each kind answers for itself (`docs/conventions.md`, *Dispatch*): which finding it
keeps, what's wrong with it, and what identifies it across edits. What's wrong is
reported as a `Problem`, which the judge turns into a finding of its own rule:
- `unused-ignore`: an `ignore` whose rule doesn't fire on the line it covers,
  fixable: never told to an agent, removed by `lup-dev rules fix`, which
  `lup-dev check --fix` runs, and reported by the gate until it's removed;
- `malformed-directive`: a call the grammar refuses, unknown or incomplete;
- `defer-issue`: a deferral's `issue` that's neither a number nor `owner/repo#7`;
- `defer-condition`: a deferral's `when` naming no declared condition;
- `defer-closed`, at the gate: a deferral whose issue is closed;
- `defer-due`, at the gate: a deferral whose condition holds.
"""

import io
import json
import tokenize
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
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
from lup_dev.forge.protocol import IssueState, Stated
from lup_dev.host.client import RoomClient
from lup_dev.host.protocol import HostError


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
    def state(self, issue: IssueRef) -> Literal["open", "closed", "unchecked"]:
        """Say whether `issue` is open or closed, or that it went unchecked, having said why."""

    @abstractmethod
    def unreachable(self) -> str | None:
        """Say why the tracker can't be asked about any issue here, or none where it can."""


class GitHubIssues(Issues):
    """GitHub's issues, through the `gh` command."""

    root: Path
    """The checkout `gh` runs in, which names this repository."""

    @override
    def unreachable(self) -> str | None:
        """Say why `gh` can't be asked here: missing, or `gh auth status` failing; none where it can.

        A machine may have no `gh` or no GitHub login, or be offline: there, the
        gate leaves a deferral's issue unchecked and says why, rather than failing
        on what it couldn't ask (`docs/launch.md`). A room, which holds neither,
        asks the host instead (`HostIssues`).
        """
        try:
            status = sh.Command("gh")(
                "auth",
                "status",
                _cwd=str(self.root),
                _ok_code=list(range(256)),
                _tty_out=False,
                _return_cmd=True,
            )
        except sh.CommandNotFound:
            return "`gh` isn't installed here"
        if status.exit_code != 0:
            return (
                f"`gh auth status` ended with status {status.exit_code}: no GitHub "
                "login here, or GitHub is out of reach"
            )
        return None

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


class HostIssues(Issues, arbitrary_types_allowed=True):
    """GitHub's issues as the host service reads them for a room, asked on its launch's request socket.

    A room holds no `gh` and no GitHub login, so the gate there asks the host,
    which reads an issue's state with the operator's `gh` (`docs/host-tools.md`,
    *The gate in a room*). Where the host doesn't say (no service answering, an
    older one that doesn't know the request, `gh` out of reach there, or reading
    issues beyond the project's limits), the issue goes unchecked, said with the
    host's reason, and the gate goes on.
    """

    client: RoomClient
    say: Callable[[str], None]
    """Where the gate tells what it left unchecked."""

    @override
    def unreachable(self) -> str | None:
        """Say why the host can't be asked here: its request socket isn't there; none where it is."""
        if self.client.socket.exists():
            return None
        return f"the launch's request socket, {self.client.socket}, isn't there"

    @override
    def state(self, issue: IssueRef) -> Literal["open", "closed", "unchecked"]:
        asked = IssueState(repository=issue.repository, number=issue.number)
        try:
            return self.client.ask(asked, Stated).state
        except HostError as refused:
            self.say(f"Issue {issue} went unchecked: the host service said {refused}.")
            return "unchecked"


class Trackers(Model, arbitrary_types_allowed=True):
    """What a deferral is tracked by, which the gate asks: issues and conditions."""

    issues: Issues | None
    """None where the tracker can't be reached here, so a deferral's issue isn't
    checked; the gate says why."""
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
    gate: Trackers | None = None
    """At the gate, the issues' states and the conditions themselves."""


class Problem(Model):
    """What's wrong with one directive, as the judge reports it."""

    line: int
    rule: str
    message: str
    steer: str = ""
    fixable: bool = False
    """Whether `lup-dev rules fix` removes it, so no agent is told of it."""


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
            Problem(
                line=self.line,
                rule="unused-ignore",
                message=message,
                steer=steer,
                fixable=True,
            )
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
        closed = (
            issue is not None
            and gate.issues is not None
            and gate.issues.state(issue) == "closed"
        )
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
    """List the comments of `since` missing from `kept`, each time removed.

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


def without(text: str, lines: list[int]) -> str:
    r"""Return `text` without the comment on each of `lines`, a line left holding nothing removed whole.

    Where each comment starts is read with Python's tokenizer, so a `#` inside a
    string is never taken for one. A `# lup:` comment runs to the end of its line,
    so what's left of a line is what comes before it, its trailing spaces dropped.

    >>> without('x = 1  # lup: ignore("E1", why="w")\n# lup: ignore("E2", why="w")\ny = 2\n', [1, 2])
    'x = 1\ny = 2\n'
    """
    starts = {
        row: column
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        for row, column in [token.start]
        if token.type == tokenize.COMMENT and row in lines
    }

    def kept(number: int, line: str) -> list[str]:
        column = starts.get(number)
        if column is None:
            return [line]
        # lup: ignore("string-slice", why="the column is Python's tokenizer's, where the line's comment starts")
        before = line[:column].rstrip()
        return [f"{before}\n"] if before else []

    return "".join(
        each
        for number, line in enumerate(io.StringIO(text).readlines(), start=1)
        for each in kept(number, line)
    )
