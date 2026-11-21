"""`Forge`: each project's part acting on GitHub for its agents, through `gh` and the operator's own login, within what its declaration allows.

It runs in a container of its own, from the commit the operator approved,
holding their GitHub login alone (`GitHubLogin`, read with `gh auth token` on
their machine as it starts). Each tool (`README.md` here):
- **writes to the project's own repository alone,** named by the remote it
  lands on (`Landing.remote`), as `remote` says where that is, an alias of the
  operator's ssh configuration resolved; and reads any repository the
  operator's login can, a name validated as `owner/name` before it reaches
  `gh`;
- **is held to the declaration's actions** (`GitHub.actions`) before `gh` runs;
- **tells what it would post at `Publishing` first,** and posts nothing where a
  part hearing it refuses;
- **gives `gh` every value as `--flag=value`, a body on its input,** never
  through a shell.

Merging and approving aren't among them: either would show the operator's name
on a decision they didn't make.
"""

from datetime import timedelta
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import Field, PositiveInt, TypeAdapter, model_validator

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Codebase, Operator
from lup.doors.parts import Declared, GitHubLogin, Part, Program, Runtime
from lup.github.answers import (
    BranchQuery,
    CommentAnswer,
    Found,
    Issue,
    PullRequest,
    RepositoryName,
    ReviewComment,
    State,
    repository_name,
    terms,
)
from lup.landing.module import Landing
from lup.publishing.events import Post, Publishing, Written
from lup.remote.remotes import Naming, Remotes
from lup.types import Model
lazy from lup.github.module import GitHub

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
"""GitHub's GraphQL query for one branch of a repository, by its full ref name,
null where there's no such branch: the name is a variable, so it never reaches
a URL's path."""

type Closing = Literal["completed", "not planned", "duplicate"]
"""Why an issue closes, as `gh issue close --reason` spells it."""


class Reading(Model):
    """A reading tool's arguments, which may name another repository on GitHub than this one."""

    repository: RepositoryName | None = Field(
        default=None,
        description=(
            "Another repository on GitHub to read, as `owner/name`: any the "
            "operator's login can read. Left out, this one."
        ),
    )


class Numbered(Reading):
    """An issue or pull request, by its number: of this repository, or of the one named."""

    number: PositiveInt = Field(description="Its number in its repository.")


class Query(Reading):
    """A search of one repository's issues and pull requests: this one's, or the one named."""

    query: str = Field(
        description=(
            "What to search for, in GitHub's search syntax: words, and qualifiers "
            "such as `label:bug`, `is:pr` or `author:octocat`, each apart; a phrase "
            "in double quotes. Empty for every one."
        )
    )
    state: Literal["open", "closed", "all"] = Field(
        default="open",
        description=(
            "Which to find: the open ones, the closed ones (a merged pull request "
            "among them), or all."
        ),
    )
    limit: int = Field(
        default=100,
        gt=0,
        le=1000,
        description=(
            "How many matches to list at most, in GitHub's order: up to 1,000, "
            "the most GitHub's search gives a query."
        ),
    )

    @model_validator(mode="after")
    def quoted(self) -> Self:
        """Refuse a query whose double quotes don't close."""
        terms(self.query)
        return self


class NewIssue(Model):
    """An issue to file in this repository."""

    title: str = Field(min_length=1, description="Its title, one line.")
    body: str = Field(description="What it's about, in GitHub's Markdown.")
    labels: list[str] = Field(
        default=[],
        description="Labels the repository defines, by their names, such as `bug`.",
    )


class Edit(Model):
    """An edit of an issue or pull request of this repository: its title, its body, its labels, each changed only where given."""

    number: PositiveInt = Field(description="Its number in this repository.")
    title: str | None = Field(
        default=None, min_length=1, description="Its new title, one line."
    )
    body: str | None = Field(
        default=None,
        description="Its new body whole, in GitHub's Markdown, replacing the old.",
    )
    add_labels: list[str] = Field(
        default=[], description="Labels the repository defines, to add, by name."
    )
    remove_labels: list[str] = Field(
        default=[], description="Labels to take off, by name."
    )

    @model_validator(mode="after")
    def changing(self) -> Self:
        """Refuse an edit that changes nothing."""
        if not (
            self.title or self.body is not None or self.add_labels or self.remove_labels
        ):
            message = "an edit changes the title, the body or the labels"
            raise ValueError(message)
        return self


class Closure(Model):
    """An issue of this repository to close, why, and the comment saying where what's left of it went."""

    number: PositiveInt = Field(description="The issue's number in this repository.")
    reason: Closing = Field(
        description=(
            "Why it closes: `completed` for work done, `not planned` for work that "
            "won't be, `duplicate` for one repeating another."
        )
    )
    duplicate_of: PositiveInt | None = Field(
        default=None,
        description="The issue it repeats, by its number: with `duplicate` alone.",
    )
    comment: str = Field(
        min_length=1,
        description=(
            "Posted before it closes, in GitHub's Markdown: what settled it, and "
            "where each thing left of it went."
        ),
    )

    @model_validator(mode="after")
    def repeating(self) -> Self:
        """Refuse a duplicate without the issue it repeats, or the issue named for another reason."""
        if (self.reason == "duplicate") != (self.duplicate_of is not None):
            message = "`duplicate_of` names the issue repeated, with `duplicate` alone"
            raise ValueError(message)
        return self


class Reopening(Model):
    """A closed issue of this repository to reopen, and why."""

    number: PositiveInt = Field(description="The issue's number in this repository.")
    comment: str = Field(
        min_length=1, description="Why it reopens, in GitHub's Markdown, posted first."
    )


class NewComment(Model):
    """A comment on an issue or pull request of this repository."""

    number: PositiveInt = Field(
        description="The issue's or pull request's number in this repository."
    )
    body: str = Field(min_length=1, description="The comment, in GitHub's Markdown.")


class CommentEdit(Model):
    """A comment's new text, the comment named by its link on its thread."""

    number: PositiveInt = Field(
        description=(
            "The number, in this repository, of the issue or pull request the "
            "comment is on."
        )
    )
    link: str = Field(
        min_length=1,
        description="The comment's link, as `read_issue` gives it beside the comment.",
    )
    body: str = Field(
        min_length=1,
        description="Its new text whole, in GitHub's Markdown, replacing the old.",
    )


class NewPullRequest(Model):
    """A pull request to open in this repository, into the branch work lands on."""

    branch: str = Field(
        min_length=1,
        description="The branch to merge, as GitHub names it: pushed there already.",
    )
    title: str = Field(min_length=1, description="Its title, one line.")
    body: str = Field(
        description="What it changes and why, in GitHub's Markdown, for the reviewer."
    )
    draft: bool = Field(
        default=True,
        description="Whether it opens as a draft, not yet asking for review.",
    )


class Readying(Model):
    """A draft pull request of this repository to mark ready for review."""

    number: PositiveInt = Field(description="Its number in this repository.")


class Stating(Model):
    """An issue whose state is asked, as the gate asks of what a `defer` or an `ignore` waits on: in this repository, or the one named."""

    number: PositiveInt
    repository: RepositoryName | None = None


class Stated(Model):
    """An issue's state, as GitHub has it."""

    state: Literal["open", "closed"]


class Forge(Part):
    """Each project's part acting on GitHub for its agents, with the operator's own login."""

    module: GitHub
    login: GitHubLogin
    declared: Declared
    configuration: Runtime
    """`gh`'s own configuration and cache, in memory, which its login never
    reaches: `GH_TOKEN` carries that."""
    gh: Program = Program(
        name="gh",
        optional=True,
        package="github-cli",
        why="acts on GitHub for agents, with your login",
        install="https://cli.github.com",
    )
    within: timedelta = timedelta(minutes=2)
    """The longest `gh` may take: GitHub answers in seconds, and a search of a
    thousand matches reads ten pages."""
    named: str | None = None
    """The project's repository on GitHub, `owner/name`, once its remote said
    where it is."""

    def require(self, action: str) -> None:
        """Refuse `action` where the declaration doesn't allow it, saying that allowing it is the operator's call."""
        if action not in self.module.allowed():
            message = (
                f"the project's declaration doesn't allow `{action}` on GitHub with "
                "the operator's login (`GitHub.actions`), and allowing it is the "
                "operator's call"
            )
            raise RefusedError(message)

    async def ran(self, *arguments: str, given: str | None = None) -> str:
        """Run `gh` with `arguments`, `given` on its input, with the operator's login, and return what it printed.

        Raise `RefusedError` where it fails, saying why in its own words.
        """
        variables = {
            "GH_TOKEN": self.login.token,
            "GH_CONFIG_DIR": str(self.configuration.path),
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "NO_COLOR": "1",
        }
        ran = await self.gh.ran(
            *arguments, given=given, env=variables, within=self.within
        )
        match ran.status:
            case 0:
                return ran.text()
            case 4:
                message = (
                    "`gh` has no GitHub login: the operator signs in with `gh auth "
                    f"login` on their machine, and the project opens again. It said: {ran.said()}"
                )
            case status:
                message = (
                    f"`gh {arguments[0]}` ended with status {status}: {ran.said()}"
                )
        raise RefusedError(message)

    async def own(self) -> str:
        """Return the project's repository on GitHub, `owner/name`, where its remote is, as `remote` says.

        Raise `RefusedError` where it isn't on GitHub, or `remote` can't say.
        """
        # lup: defer(issue=2, why="writing to the other repositories the operator relates to a project too, a harmon agent filing an issue on lup's, once a declaration names them")
        if self.named is not None:
            return self.named
        landing = next(
            (each for each in self.declared.modules if isinstance(each, Landing)), None
        )
        remote = "origin" if landing is None else landing.remote
        hosted = await Remotes.hosted(Naming(remote=remote))
        path = PurePosixPath(hosted.path)
        name = path.stem if path.suffix == ".git" else path.name
        if hosted.host != "github.com" or path.parent.parent != PurePosixPath("/"):
            message = (
                f"this project's remote `{remote}` isn't a repository on GitHub "
                f"({hosted.host}{hosted.path}), so nothing here writes there"
            )
            raise RefusedError(message)
        self.named = repository_name(f"{path.parent.name}/{name}")
        return self.named

    async def published(self, what: str, parts: list[Written]) -> None:
        """Tell what a post would publish at `Publishing`, and refuse it where a part hearing it does, in its words."""
        heeded = await lup.heeded(Publishing(published=Post(what=what, parts=parts)))
        if heeded.refused is not None:
            raise RefusedError(heeded.refused)

    async def thread(self, repository: str, number: int) -> PullRequest | Issue:
        """Return the issue or pull request `number` of `repository`, with its comments, and a pull request's reviews and checks: `gh pr view` first, which fails on an issue's number, then `gh issue view`."""
        asked = [str(number), f"--repo={repository}"]
        try:
            printed = await self.ran(
                "pr", "view", *asked, f"--json={PullRequest.fields()}"
            )
        except RefusedError:
            printed = await self.ran(
                "issue", "view", *asked, f"--json={Issue.fields()}"
            )
            return Issue.model_validate_json(printed)
        return PullRequest.model_validate_json(printed)

    @lup.tool(reads=True, idempotent=True)
    async def read_issue(self, asked: Numbered, by: Agent) -> str:
        """Read an issue or pull request, with its comments.

        Any issue or pull request of this repository on GitHub, by its number,
        or of another the operator's login can read, named by `repository` as
        `owner/name`: its title, state, author, labels and description, then
        each comment whole, oldest first. For a pull request, its branches,
        whether it's a draft, its review decision, each check on its head with
        how it stands and where to look, and its reviews and the comments on
        lines of its diff among the comments.
        """
        del by
        self.require("read")
        repository = asked.repository or await self.own()
        thread = await self.thread(repository, asked.number)
        if isinstance(thread, Issue):
            return thread.text()
        pages = await self.ran(
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/pulls/{asked.number}/comments",
        )
        inline = TypeAdapter(list[list[ReviewComment]]).validate_json(pages)
        return thread.text([each for page in inline for each in page])

    @lup.tool(reads=True, idempotent=True)
    async def find_issues(self, asked: Query, by: Agent) -> str:
        """Search a repository's issues and pull requests.

        GitHub's search over this repository on GitHub, or over another the
        operator's login can read, named by `repository` as `owner/name`: each
        match's number, whether it's an issue or a pull request, its state,
        when it was last updated, and its title, in GitHub's order of
        relevance, up to `limit`; where as many came, the answer says more may
        match. `read_issue` reads one whole. Searching before filing an issue
        finds one already open.
        """
        del by
        self.require("read")
        repository = asked.repository or await self.own()
        states = [] if asked.state == "all" else [f"--state={asked.state}"]
        printed = await self.ran(
            "search",
            "issues",
            f"--repo={repository}",
            "--include-prs",
            f"--limit={asked.limit}",
            f"--json={Found.fields()}",
            *states,
            "--",
            *terms(asked.query),
        )
        found = TypeAdapter(list[Found]).validate_json(printed)
        here = [
            each
            for each in found
            if each.repository.name_with_owner.casefold() == repository.casefold()
        ]
        heading = (
            f"{len(here)} {asked.state} in {repository} for `{asked.query}`:"
            if here
            else f"Nothing {asked.state} in {repository} matches `{asked.query}`."
        )
        elsewhere = (
            [
                (
                    f"{len(found) - len(here)} matches in other repositories were "
                    "left out: a search reads one repository, which `repository` names."
                )
            ]
            if len(found) > len(here)
            else []
        )
        more = (
            [
                (
                    "As many came as `limit` asked for, so more may match: a larger "
                    "`limit`, up to 1,000, or a narrower query reaches them."
                )
            ]
            if len(found) >= asked.limit
            else []
        )
        return "\n".join([heading, *(each.text() for each in here), *elsewhere, *more])

    @lup.tool
    async def file_issue(self, asked: NewIssue, by: Agent) -> str:
        """File an issue in this repository.

        It opens on GitHub at once, in the operator's name, so `find_issues`
        first, to find one already open. `labels` are the repository's own: a
        name it doesn't define is refused in `gh`'s words. Its link is the
        answer.
        """
        del by
        self.require("file-issue")
        repository = await self.own()
        await self.published(
            f"an issue on {repository}",
            [
                Written(name="title", text=asked.title),
                Written(name="body", text=asked.body),
                *(Written(name="label", text=label) for label in asked.labels),
            ],
        )
        printed = await self.ran(
            "issue",
            "create",
            f"--repo={repository}",
            f"--title={asked.title}",
            "--body-file=-",
            *(f"--label={label}" for label in asked.labels),
            given=asked.body,
        )
        return f"Filed: {printed.strip()}"

    @lup.tool
    async def edit_issue(self, asked: Edit, by: Agent) -> str:
        """Edit an issue's or pull request's text or labels.

        Any issue or pull request of this repository on GitHub, by its number,
        in the operator's name: `title` and `body` replace its own where given,
        and labels are added and removed by name, from those the repository
        defines. GitHub keeps the earlier text in its edit history, which only
        the operator can clear, on the web: where an edit takes out something
        that shouldn't be public, tell them.
        """
        del by
        self.require("edit")
        repository = await self.own()
        await self.published(
            f"an edit of {repository}#{asked.number}",
            [
                *([Written(name="title", text=asked.title)] if asked.title else []),
                *(
                    [Written(name="body", text=asked.body)]
                    if asked.body is not None
                    else []
                ),
                *(Written(name="label", text=label) for label in asked.add_labels),
            ],
        )
        thread = await self.thread(repository, asked.number)
        kind = "pr" if isinstance(thread, PullRequest) else "issue"
        await self.ran(
            kind,
            "edit",
            str(asked.number),
            f"--repo={repository}",
            *([f"--title={asked.title}"] if asked.title else []),
            *(["--body-file=-"] if asked.body is not None else []),
            *(f"--add-label={label}" for label in asked.add_labels),
            *(f"--remove-label={label}" for label in asked.remove_labels),
            given=asked.body,
        )
        return f"Edited #{asked.number}."

    async def issue_in(
        self, repository: str, number: int, state: Literal["OPEN", "CLOSED"]
    ) -> None:
        """Check that `number` is an issue, not a pull request, and that it's `state`, before anything is posted.

        Raise `RefusedError` saying what it is instead.
        """
        thread = await self.thread(repository, number)
        if isinstance(thread, PullRequest):
            message = (
                f"#{number} is a pull request: closing or reopening one is the "
                "operator's"
            )
            raise RefusedError(message)
        if thread.state != state:
            message = f"#{number} is already {thread.state.lower()}"
            raise RefusedError(message)

    @lup.tool
    async def close_issue(self, asked: Closure, by: Agent) -> str:
        """Close an issue in this repository, saying why.

        `comment` is posted first, in the operator's name, then the issue
        closes for `reason`, so a close that fails leaves the comment said.
        Before closing one, check nothing is dropped: what's left of it filed as
        an issue of its own, and the comment saying where each thing went. A
        pull request isn't closed here. `reopen_issue` undoes it.
        """
        del by
        self.require("close-issue")
        repository = await self.own()
        await self.published(
            f"the closing comment on {repository}#{asked.number}",
            [Written(name="body", text=asked.comment)],
        )
        await self.issue_in(repository, asked.number, "OPEN")
        link = await self.commented(repository, asked.number, asked.comment)
        duplicate = (
            []
            if asked.duplicate_of is None
            else [f"--duplicate-of={asked.duplicate_of}"]
        )
        try:
            await self.ran(
                "issue",
                "close",
                str(asked.number),
                f"--repo={repository}",
                f"--reason={asked.reason}",
                *duplicate,
            )
        except RefusedError as failed:
            message = f"commented ({link}), but #{asked.number} didn't close: {failed}"
            raise RefusedError(message) from failed
        return f"Closed #{asked.number} as {asked.reason}, after the comment {link}"

    @lup.tool
    async def reopen_issue(self, asked: Reopening, by: Agent) -> str:
        """Reopen a closed issue in this repository.

        `comment`, saying why, is posted first, in the operator's name, then
        the issue reopens.
        """
        del by
        self.require("close-issue")
        repository = await self.own()
        await self.published(
            f"the reopening comment on {repository}#{asked.number}",
            [Written(name="body", text=asked.comment)],
        )
        await self.issue_in(repository, asked.number, "CLOSED")
        link = await self.commented(repository, asked.number, asked.comment)
        try:
            await self.ran("issue", "reopen", str(asked.number), f"--repo={repository}")
        except RefusedError as failed:
            message = f"commented ({link}), but #{asked.number} didn't reopen: {failed}"
            raise RefusedError(message) from failed
        return f"Reopened #{asked.number}, after the comment {link}"

    async def commented(self, repository: str, number: int, body: str) -> str:
        """Comment on `number` of `repository`, and return the comment's link, as `gh` prints it."""
        printed = await self.ran(
            "issue",
            "comment",
            str(number),
            f"--repo={repository}",
            "--body-file=-",
            given=body,
        )
        return printed.strip()

    @lup.tool
    async def comment(self, asked: NewComment, by: Agent) -> str:
        """Comment on an issue or pull request.

        On any issue or pull request of this repository on GitHub, by its
        number, in the operator's name. The comment's link is the answer.
        """
        del by
        self.require("comment")
        repository = await self.own()
        await self.published(
            f"a comment on {repository}#{asked.number}",
            [Written(name="body", text=asked.body)],
        )
        return (
            f"Commented: {await self.commented(repository, asked.number, asked.body)}"
        )

    @lup.tool
    async def edit_comment(self, asked: CommentEdit, by: Agent) -> str:
        """Edit a comment on an issue or pull request.

        The comment at `link` on the issue or pull request `number` of this
        repository on GitHub: its text is replaced whole, in the operator's
        name. GitHub keeps the earlier text in the comment's edit history,
        which only the operator can clear, on the web: where an edit takes out
        something that shouldn't be public, tell them.
        """
        del by
        self.require("edit-comment")
        repository = await self.own()
        thread = await self.thread(repository, asked.number)
        found = [each for each in thread.comments if each.url == asked.link]
        if not found:
            message = (
                f"#{asked.number} has no comment at {asked.link}: `read_issue` gives "
                "each comment's link"
            )
            raise RefusedError(message)
        await self.published(
            f"an edit of a comment on {repository}#{asked.number}",
            [Written(name="body", text=asked.body)],
        )
        printed = await self.ran(
            "api",
            "graphql",
            f"--raw-field=query={COMMENT_EDIT}",
            f"--raw-field=id={found[0].id}",
            f"--raw-field=body={asked.body}",
        )
        answer = CommentAnswer.model_validate_json(printed)
        return f"Edited: {answer.data.update_issue_comment.issue_comment.url}"

    @lup.tool
    async def pull_request(self, asked: NewPullRequest, by: Agent) -> str:
        """Open a pull request in this repository.

        Into the branch work lands on, from `branch`, pushed to GitHub already, a draft unless `draft` is
        false, in the operator's name. Merging it is theirs: work lands through
        `land`. Its link is the answer.
        """
        del by
        self.require("pull-request")
        repository = await self.own()
        landing = next(
            (each for each in self.declared.modules if isinstance(each, Landing)), None
        )
        base = "dev" if landing is None else landing.integration
        owner, name = PurePosixPath(repository).parts
        printed = await self.ran(
            "api",
            "graphql",
            f"--raw-field=query={BRANCH_QUERY}",
            f"--raw-field=owner={owner}",
            f"--raw-field=name={name}",
            f"--raw-field=qualified=refs/heads/{asked.branch}",
        )
        if BranchQuery.model_validate_json(printed).data.repository.ref is None:
            message = (
                f"{repository} has no branch `{asked.branch}`: push it first "
                f"(`git push origin {asked.branch}`)"
            )
            raise RefusedError(message)
        await self.published(
            f"a pull request on {repository}",
            [
                Written(name="title", text=asked.title),
                Written(name="body", text=asked.body),
            ],
        )
        opened = await self.ran(
            "pr",
            "create",
            f"--repo={repository}",
            *(["--draft"] if asked.draft else []),
            f"--base={base}",
            f"--head={asked.branch}",
            f"--title={asked.title}",
            "--body-file=-",
            given=asked.body,
        )
        return f"Opened: {opened.strip()}"

    @lup.tool
    async def ready_pull_request(self, asked: Readying, by: Agent) -> str:
        """Mark a draft pull request ready for review.

        A pull request of this repository, in the operator's name: it then asks for their review. Merging it
        stays theirs.
        """
        del by
        self.require("pull-request")
        repository = await self.own()
        await self.ran("pr", "ready", str(asked.number), f"--repo={repository}")
        return f"#{asked.number} is ready for review."

    @lup.service
    async def issue_state(
        self, stating: Stating, by: Agent | Operator | Codebase
    ) -> Stated:
        """Say whether an issue is open or closed, as the gate asks of what a `defer` or an `ignore` waits on: of this repository, or of the one named."""
        del by
        self.require("read")
        repository = stating.repository or await self.own()
        printed = await self.ran(
            "issue", "view", str(stating.number), f"--repo={repository}", "--json=state"
        )
        match State.model_validate_json(printed).state:
            case "OPEN":
                return Stated(state="open")
            case "CLOSED":
                return Stated(state="closed")
