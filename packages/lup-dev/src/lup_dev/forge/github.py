"""GitHub through `gh`, on one repository named from its own remote, each answer read into a model.

`docs/credentials.md`, *GitHub through `gh`*. A room holds no `gh` and no GitHub
login (`docs/launch.md`, *The mounts*), so lup reaches GitHub from the host,
through the operator's `gh` and its login:
- **One repository, named once.** When a launch starts, `named` runs `gh repo
  view` in the repository's git directory, which reads the repository's own
  remotes there (an SSH alias resolved through ssh's own configuration), and the
  registration carries the answer (`Register.github`). Every command then names
  that repository with `--repo`. Never from a worktree: a worktree's `.git` file
  is the room's to write (#54), so reading the repository there would let a room
  choose which repository the operator's login acts on. Reading reaches another
  repository too, any the operator's login can read, where a call names it
  (`docs/launch.md`, *Related repositories*); writing stays on the launch's own.
- **Spawned, never forked.** `gh` runs through the host service's `executed`,
  awaited on its event loop as each judge is, in the repository's git directory.
- **Its git pinned there.** `gh` runs with `GIT_DIR` and `GIT_COMMON_DIR` both
  naming that directory (`lup_dev.git`, `pinning`), which the git it runs
  inherits: run in the directory alone, git follows a `commondir` the room
  plants at its top to a git directory of the room's, and reads that one's
  remotes and `config`.
- **Typed answers.** Each command asks for `--json` where `gh` gives it, read
  into a model here, which names the fields asked for. A command that answers
  with a link alone, as filing an issue does, is passed on as `gh` printed it.
- **Bodies on standard input** (`--body-file=-`, or a GraphQL request whole
  with `--input=-`), and every value the model writes given as `--flag=value`
  or after `--`, so none is read as a flag, and no shell reads any.
- **A comment edited is found on its own thread:** read from the launch's
  repository by its issue's number, so a comment of another repository the
  operator's login could edit is never reached.

`gh` missing, without a login (its status 4: "If a command requires
authentication, the exit code will be 4", `gh help exit-codes`), or failing
raises `GitHubError`, saying why in `gh`'s own words.
"""

import shlex
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PositiveInt, TypeAdapter
from pydantic.alias_generators import to_camel

from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.git import pinning
from lup_dev.host.protocol import GitHubRepository, Register
from lup_dev.host.service import Program, executed

PROGRAM = "gh"
"""The program lup reaches GitHub through, as the `PATH` finds it."""

COMMENT_EDIT = """
mutation($id: ID!, $body: String!) {
  updateIssueComment(input: {id: $id, body: $body}) { issueComment { url } }
}
"""
"""GitHub's GraphQL mutation replacing a comment's text, by the comment's node
id, answering with its link."""

BRANCH_QUERY = """
query($owner: String!, $name: String!, $qualified: String!) {
  repository(owner: $owner, name: $name) { ref(qualifiedName: $qualified) { name } }
}
"""
"""GitHub's GraphQL query for one branch of a repository, by its full ref name:
the ref is null where there's no such branch. The name is a variable, so no
branch name reaches a URL's path."""


class GitHubError(LupDevError):
    """`gh` couldn't do what was asked on the host: missing, without a login, or failing; why, in its message."""


async def ran(arguments: list[str], directory: Path, given: str = "") -> str:
    """Run `gh` with `arguments` in the git directory `directory`, the git it runs pinned there, `given` on its input, and return what it printed.

    Raise `GitHubError` where it fails, saying why: `gh` that couldn't run (not
    installed, or `directory` gone), without a GitHub login, or ending with a
    failure, in its own words.
    """
    command = [PROGRAM, *arguments]
    program = Program(
        command=[*pinning(directory), *command], payload=given, directory=directory
    )
    answer = await executed(program)
    error = answer.said()
    match answer.status:
        case 0:
            return answer.output.decode(errors="replace")
        case 4:
            message = (
                f"`gh` on the host has no GitHub login; `gh auth login` there signs "
                f"in. It said: {error}"
            )
        case 127:
            message = f"`gh` couldn't run on the host: {error}"
        case status:
            message = f"`{shlex.join(command)}` ended with status {status}: {error}"
    raise GitHubError(message)


class Answered(Model, alias_generator=to_camel, validate_by_name=True):
    """An answer of `gh --json`, its fields spelled as GitHub's API spells them."""

    @classmethod
    def fields(cls) -> str:
        """Return the fields `--json` asks for: this model's, as GitHub spells them.

        >>> Viewed.fields()
        'owner,name'
        """
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


class Viewed(Answered):
    """`gh repo view --json owner,name`'s answer: the repository a git directory's remotes name."""

    owner: Login
    name: str


async def named(directory: Path) -> GitHubRepository:
    """Name the repository on GitHub whose git directory is `directory`, from its own remotes, as `gh repo view` reads them there.

    Raise `GitHubError` where `gh` can't: missing, without a login, or no remote
    of the repository on GitHub.
    """
    printed = await ran(["repo", "view", f"--json={Viewed.fields()}"], directory)
    viewed = Viewed.model_validate_json(printed)
    return GitHubRepository(owner=viewed.owner.login, name=viewed.name)


type Visibility = Literal["public", "private", "internal"]
"""Who GitHub lets read a repository: anyone, those it's shared with, or its
enterprise's members."""


class Seen(Answered):
    """`gh repo view --json visibility`'s answer, as GitHub spells it."""

    visibility: Literal["PUBLIC", "PRIVATE", "INTERNAL"]


async def visibility(directory: Path, repository: GitHubRepository) -> Visibility:
    """Say who GitHub lets read `repository`, asked with `gh` in the git directory `directory`.

    Raise `GitHubError` where `gh` can't say: missing, without a login, or no
    such repository the login can see.
    """
    printed = await ran(
        ["repo", "view", str(repository), f"--json={Seen.fields()}"], directory
    )
    match Seen.model_validate_json(printed).visibility:
        case "PUBLIC":
            return "public"
        case "PRIVATE":
            return "private"
        case "INTERNAL":
            return "internal"


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


class CheckRun(Answered):
    """A check run on a pull request's head, a GitHub Actions job among them."""

    typename: Literal["CheckRun"] = Field(alias="__typename")
    name: str
    workflow_name: str
    status: str
    """Where it is: `QUEUED`, `IN_PROGRESS`, `COMPLETED` and the like."""
    conclusion: str
    """How it ended once completed (`SUCCESS`, `FAILURE`, `SKIPPED` and the
    like); empty before."""
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
    """`SUCCESS`, `FAILURE`, `PENDING` or `ERROR`."""
    target_url: str

    def text(self) -> str:
        """Say the status in a line: its context, how it stands, where to look."""
        return f"{self.context}: {self.state.lower()} {self.target_url}"


type Check = Annotated[CheckRun | StatusContext, Field(discriminator="typename")]
"""One of a pull request's checks, told apart by GitHub's type for it."""


class Issue(Answered):
    """An issue, with its comments, as `gh issue view --json` gives it."""

    number: int
    title: str
    state: str
    """`OPEN` or `CLOSED`."""
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
        return thread(heading, self.body, self.comments)


class PullRequest(Answered):
    """A pull request, with its comments and its checks, as `gh pr view --json` gives it."""

    number: int
    title: str
    state: str
    """`OPEN`, `CLOSED` or `MERGED`."""
    is_draft: bool
    author: Login | None
    created_at: datetime
    url: str
    head_ref_name: str
    base_ref_name: str
    review_decision: str
    """`APPROVED`, `CHANGES_REQUESTED` or `REVIEW_REQUIRED`; empty where the
    repository asks for no review."""
    labels: list[Label]
    body: str
    comments: list[Comment]
    status_check_rollup: list[Check]

    def text(self) -> str:
        """Say the pull request whole: what it is, its checks, its body, then each comment."""
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
        return thread(heading, self.body, self.comments)


def thread(heading: list[str], body: str, comments: list[Comment]) -> str:
    """Say an issue's or pull request's thread: its heading, its body, then each comment whole."""
    said = [
        "\n".join(heading),
        body or "(No description.)",
        f"Comments ({len(comments)}):" if comments else "No comments.",
        *(comment.text() for comment in comments),
    ]
    return "\n\n".join(said)


class Named(Answered):
    """A repository as a search names it."""

    name_with_owner: str


class Found(Answered):
    """An issue or pull request a search found, as `gh search issues --json` gives it."""

    number: int
    title: str
    state: str
    """`open` or `closed`, as a search spells it; a merged pull request is closed."""
    is_pull_request: bool
    updated_at: datetime
    url: str
    repository: Named

    def text(self) -> str:
        """Say what was found in a line: its number, whether it's a pull request, its state, its title."""
        what = "pull request" if self.is_pull_request else "issue"
        return f"#{self.number}  {what}, {self.state}, updated {self.updated_at:%Y-%m-%d}: {self.title}"


class Search(Model):
    """What a search found in the repository, and what it left out."""

    found: list[Found]
    """Each match in the repository, in GitHub's order."""
    elsewhere: int
    """How many matches were in another repository, which a query's own
    qualifiers can reach, and were left out."""
    limit: int
    """How many matches were asked for: where as many came, more may match."""

    def full(self) -> bool:
        """Say whether as many matches came as were asked for, here and elsewhere: more may match."""
        return len(self.found) + self.elsewhere >= self.limit


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


class State(Answered):
    """`gh issue view --json state`'s answer."""

    state: Literal["OPEN", "CLOSED"]


class Edited(Model):
    """What a comment's edit sets: the comment, by its node id, and its whole new text."""

    id: str
    body: str


class CommentEdit(Model):
    """The GraphQL request editing a comment, given whole on `gh api graphql`'s standard input."""

    query: str = COMMENT_EDIT
    variables: Edited


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


type Closing = Literal["completed", "not planned", "duplicate"]
"""Why an issue closes, as `gh issue close --reason` spells it: its work done,
not to be done, or another issue's repeat."""


def terms(query: str) -> list[str]:
    """Return a search query's terms as `gh search` takes them: each word and qualifier apart, a phrase in double quotes whole.

    `gh` searches an argument holding a space as a phrase, so a query given
    whole would be one phrase, its qualifiers words in it. An apostrophe is part
    of its word. Raise `ValueError` where a double quote doesn't close.

    >>> terms('''label:bug "held call" don't''')
    ['label:bug', 'held call', "don't"]
    """
    lexer = shlex.shlex(query, posix=True)
    lexer.whitespace_split = True
    lexer.quotes = '"'
    lexer.commenters = ""
    return list(lexer)


class GitHub(Model):
    """GitHub through `gh --json`, on the one repository named when its launch started."""

    repository: GitHubRepository
    directory: Path
    """The repository's git directory on the host, where `gh` runs."""
    searched: PositiveInt = 1000
    """The most matches GitHub's search gives a query: its API answers none
    past them, and `gh search` refuses a `--limit` beyond ("`--limit` must be
    between 1 and 1000")."""

    @classmethod
    def launched(
        cls, launch: Register, elsewhere: GitHubRepository | None = None
    ) -> GitHub:
        """Return GitHub on `launch`'s own repository, or on `elsewhere` where it's given, run in the launch's git directory.

        Raise `GitHubError` where it's the launch's own and the launch has none:
        `gh` couldn't name it when the launch started, which the launch said.
        """
        if elsewhere is not None:
            return cls(repository=elsewhere, directory=launch.repository)
        if launch.github is None:
            message = (
                "this launch has no repository on GitHub: `gh` on the host couldn't "
                "name one from the repository's remotes when the launch started, "
                "and the launch said why in the operator's terminal. A launch "
                "started once `gh` names it reaches GitHub"
            )
            raise GitHubError(message)
        return cls(repository=launch.github, directory=launch.repository)

    def repo(self) -> str:
        """Return the argument naming the repository to `gh`."""
        return f"--repo={self.repository}"

    async def thread(self, number: PositiveInt) -> PullRequest | Issue:
        """Return the issue or pull request `number`, with its comments, and a pull request's checks.

        `gh pr view` first, which fails on an issue's number; where it fails,
        `gh issue view`, which reads either, its failure the one raised.
        """
        asked = [str(number), self.repo()]
        try:
            printed = await ran(
                ["pr", "view", *asked, f"--json={PullRequest.fields()}"],
                self.directory,
            )
        except GitHubError:
            printed = await ran(
                ["issue", "view", *asked, f"--json={Issue.fields()}"], self.directory
            )
            return Issue.model_validate_json(printed)
        return PullRequest.model_validate_json(printed)

    async def search(
        self, query: str, state: Literal["open", "closed", "all"], limit: int
    ) -> Search:
        """Search the repository's issues and pull requests for `query`, in GitHub's search syntax, at most `limit` matches.

        A match in another repository, which a query's own qualifiers can reach,
        is left out and counted. Raise `ValueError` where a double quote in the
        query doesn't close.
        """
        states = [] if state == "all" else [f"--state={state}"]
        printed = await ran(
            [
                "search",
                "issues",
                self.repo(),
                "--include-prs",
                f"--limit={limit}",
                f"--json={Found.fields()}",
                *states,
                "--",
                *terms(query),
            ],
            self.directory,
        )
        found = TypeAdapter(list[Found]).validate_json(printed)
        here = [
            each
            for each in found
            if each.repository.name_with_owner.casefold()
            == str(self.repository).casefold()
        ]
        return Search(found=here, elsewhere=len(found) - len(here), limit=limit)

    async def file(self, title: str, body: str, labels: list[str]) -> str:
        """File an issue with `labels`, and return what `gh` printed: its link."""
        printed = await ran(
            [
                "issue",
                "create",
                self.repo(),
                f"--title={title}",
                "--body-file=-",
                *(f"--label={label}" for label in labels),
            ],
            self.directory,
            body,
        )
        return printed.strip()

    async def edit(
        self,
        number: PositiveInt,
        *,
        title: str | None,
        body: str | None,
        added: list[str],
        removed: list[str],
    ) -> None:
        """Edit the issue `number`: its title and body where given, the labels `added`, and those `removed`."""
        await ran(
            [
                "issue",
                "edit",
                str(number),
                self.repo(),
                *([f"--title={title}"] if title is not None else []),
                *(["--body-file=-"] if body is not None else []),
                *(f"--add-label={label}" for label in added),
                *(f"--remove-label={label}" for label in removed),
            ],
            self.directory,
            body or "",
        )

    async def close(
        self, number: PositiveInt, reason: Closing, duplicate_of: PositiveInt | None
    ) -> None:
        """Close the issue `number` for `reason`, naming the issue it repeats where it's a duplicate."""
        await ran(
            [
                "issue",
                "close",
                str(number),
                self.repo(),
                f"--reason={reason}",
                *(
                    [f"--duplicate-of={duplicate_of}"]
                    if duplicate_of is not None
                    else []
                ),
            ],
            self.directory,
        )

    async def reopen(self, number: PositiveInt) -> None:
        """Reopen the issue `number`."""
        await ran(["issue", "reopen", str(number), self.repo()], self.directory)

    async def comment(self, number: PositiveInt, body: str) -> str:
        """Comment on the issue or pull request `number`, and return what `gh` printed: the comment's link."""
        printed = await ran(
            ["issue", "comment", str(number), self.repo(), "--body-file=-"],
            self.directory,
            body,
        )
        return printed.strip()

    async def edit_comment(self, number: PositiveInt, link: str, body: str) -> str:
        """Replace the text of the comment at `link` on the issue or pull request `number` with `body`, and return its link.

        The comment is found on its thread, read from this repository, so only
        a comment of this repository is edited. Raise `GitHubError` where the
        thread has no comment at `link`.
        """
        thread = await self.thread(number)
        found = [each for each in thread.comments if each.url == link]
        if not found:
            message = (
                f"#{number} has no comment at {link}: `read_issue` gives each "
                "comment's link"
            )
            raise GitHubError(message)
        [comment] = found
        request = CommentEdit(variables=Edited(id=comment.id, body=body))
        printed = await ran(
            ["api", "graphql", "--input=-"], self.directory, request.model_dump_json()
        )
        answer = CommentAnswer.model_validate_json(printed)
        return answer.data.update_issue_comment.issue_comment.url

    async def pushed(self, branch: str) -> bool:
        """Say whether the repository on GitHub has the branch `branch`."""
        printed = await ran(
            [
                "api",
                "graphql",
                f"--raw-field=query={BRANCH_QUERY}",
                f"--raw-field=owner={self.repository.owner}",
                f"--raw-field=name={self.repository.name}",
                f"--raw-field=qualified=refs/heads/{branch}",
            ],
            self.directory,
        )
        return BranchQuery.model_validate_json(printed).data.repository.ref is not None

    async def draft(self, branch: str, base: str, title: str, body: str) -> str:
        """Open a draft pull request from `branch` into `base`, and return what `gh` printed: its link."""
        printed = await ran(
            [
                "pr",
                "create",
                self.repo(),
                "--draft",
                f"--base={base}",
                f"--head={branch}",
                f"--title={title}",
                "--body-file=-",
            ],
            self.directory,
            body,
        )
        return printed.strip()

    async def state(
        self, number: PositiveInt, elsewhere: str | None
    ) -> Literal["open", "closed"]:
        """Say whether the issue `number` is open or closed: in this repository, or in `elsewhere`, an `owner/repo`."""
        repository = elsewhere if elsewhere is not None else str(self.repository)
        printed = await ran(
            ["issue", "view", str(number), f"--repo={repository}", "--json=state"],
            self.directory,
        )
        match State.model_validate_json(printed).state:
            case "OPEN":
                return "open"
            case "CLOSED":
                return "closed"
