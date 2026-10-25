"""What `GitHub` serves: lup's GitHub tools in a launched session, and whether an issue is open, which the gate asks from a room.

**The tools** (`docs/inbox.md`, *lup's tools*): reading and finding issues,
filing, editing, closing and reopening one, commenting and editing a comment,
opening a draft pull request. Each acts on the launch's own repository on
GitHub, named when the launch started (`Register.github`), but for the two that
read, which reach another the operator's login can read where a call names it
(`repository`, `docs/launch.md`, *Related repositories*); each through the
operator's `gh` on the host (`lup_dev.forge.github`), and only within the limits
the project's declaration sets (`Register.limits`): a tool's action
(`read-issues`, `file-issue`, `edit-issue`, `close-issue`, `comment`,
`edit-comment`, `draft-pull-request`) is checked before anything runs, and one
beyond the limits is refused, saying the declaration doesn't allow it and that
allowing it is the operator's call. What a tool that writes would post is put to
every module's hooks at `Publishing` first (`ModuleServing.publish`), and
refused there, it isn't posted. There's no merge tool: work lands on the
integration branch through git, and what reaches `main` is the operator's to
merge.

Closing an issue posts its comment first, then closes it, so a close that fails
leaves the comment said rather than an issue closed without its reason; the
answer says which happened.

A tool's description is its docstring, whose first line is the summary each
session's guidance lists (`ToolSpec.summary`). Results are text.

**An issue's state** (`docs/credentials.md`, *The gate in a room*). The gate
checks each deferral's issue is still open, and a room holds no `gh` and no
login, so the gate there asks the host on the launch's `request.sock`
(`lup_dev.codescan.directives`, `HostIssues`), which reads the state with the
operator's `gh`. Reading an issue is the launch's `read-issues` action, refused
where the project's declaration leaves it out. The request is the core's
(`lup_dev.forge.protocol`), since the gate asks it whatever modules a project
selects.
"""

from typing import TYPE_CHECKING, Literal, Self, override

from pydantic import Field, PositiveInt, model_validator

from lup import doors
from lup.publishing import Part, Post
from lup.types import Model
from lup_dev.declaration.serving import Agent, ModuleServing, Room
from lup_dev.forge import github as gh
from lup_dev.forge.github import Closing, GitHubError, Search, terms
from lup_dev.forge.protocol import IssueState, Stated
from lup_dev.host.protocol import Action, GitHubRepository, HostError, Register
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from lup.github.module import GitHub


class Arguments(Model, extra="forbid"):
    """A GitHub tool's arguments: on the launch's own repository, unless they name another."""

    def elsewhere(self) -> GitHubRepository | None:
        """Return the repository on GitHub the call names; none for the launch's own, which a tool that writes always acts on."""
        return None


class Reading(Arguments):
    """A reading tool's arguments, which may name another repository on GitHub than the launch's own."""

    repository: str | None = Field(
        default=None,
        description=(
            "Another repository on GitHub to read, as `owner/name`: any the "
            "operator's login can read, such as one of the other repositories "
            "your guidance lists. Left out, this one."
        ),
    )

    @model_validator(mode="after")
    def readable(self) -> Self:
        """Refuse a repository that isn't `owner/name`."""
        self.elsewhere()
        return self

    @override
    def elsewhere(self) -> GitHubRepository | None:
        if self.repository is None:
            return None
        return GitHubRepository.read(self.repository)


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
    limit: PositiveInt = Field(
        default=100,
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


class NewIssue(Arguments):
    """An issue to file."""

    title: str = Field(min_length=1, description="Its title, one line.")
    body: str = Field(description="What it's about, in GitHub's Markdown.")
    labels: list[str] = Field(
        default=[],
        description="Labels the repository defines, by their names, such as `bug`.",
    )


class IssueEdit(Arguments):
    """An edit of an issue: its title, its body, its labels, each changed only where given."""

    number: PositiveInt = Field(description="The issue's number in this repository.")
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
        default=[], description="Labels to take off the issue, by name."
    )

    @model_validator(mode="after")
    def changing(self) -> Self:
        """Refuse an edit that changes nothing."""
        if (
            self.title is None
            and self.body is None
            and not self.add_labels
            and not self.remove_labels
        ):
            message = "an edit changes the title, the body or the labels"
            raise ValueError(message)
        return self


class IssueClosing(Arguments):
    """An issue to close, why, and the comment saying where what's left of it went."""

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


class IssueReopening(Arguments):
    """A closed issue to reopen, and why."""

    number: PositiveInt = Field(description="The issue's number in this repository.")
    comment: str = Field(
        min_length=1,
        description="Why it reopens, in GitHub's Markdown, posted first.",
    )


class NewComment(Arguments):
    """A comment on an issue or pull request."""

    number: PositiveInt = Field(
        description="The issue's or pull request's number in this repository."
    )
    body: str = Field(min_length=1, description="The comment, in GitHub's Markdown.")


class CommentEdit(Arguments):
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


class NewDraft(Arguments):
    """A draft pull request to open."""

    branch: str = Field(
        min_length=1,
        description="The branch to merge, as GitHub names it: pushed there already.",
    )
    title: str = Field(min_length=1, description="Its title, one line.")
    body: str = Field(
        description="What it changes and why, in GitHub's Markdown, for the reviewer."
    )


class GitHubServing(ModuleServing):
    """lup's GitHub tools, served to each launched session, which write to its repository alone and read any the operator's login can; and an issue's state, for the gate in a room."""

    module: GitHub

    def github(self, action: Action, asked: Arguments, launch: Register) -> gh.GitHub:
        """Return GitHub, through `gh`, for `action` of `launch`'s on the repository `asked` names, or the launch's own.

        Raise `GitHubError` where the launch's limits don't allow `action`.
        """
        refusal = launch.limits.refusal(action)
        if refusal is not None:
            raise GitHubError(refusal)
        return gh.GitHub.launched(launch, asked.elsewhere())

    @doors.tool(reads=True)
    async def read_issue(self, asked: Numbered, by: Agent) -> str:
        """Read an issue or pull request, with its comments.

        Any issue or pull request of this repository on GitHub, by its number,
        or of another the operator's login can read, named by `repository` as
        `owner/name`: its title, state, author, labels and description, then
        each comment whole, oldest first. For a pull request, its branches,
        whether it's a draft, its review decision, and each check on its head
        with how it stands and where to look.
        """
        github = self.github("read-issues", asked, by.launch)
        return (await github.thread(asked.number)).text()

    @doors.tool(reads=True)
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
        github = self.github("read-issues", asked, by.launch)
        if asked.limit > github.searched:
            message = (
                f"`limit` is {github.searched:,} at most, the most matches GitHub's "
                "search gives a query: narrow the query, by `created:` dates say, to "
                "reach the rest"
            )
            raise GitHubError(message)
        search = await github.search(asked.query, asked.state, asked.limit)
        found = [each.text() for each in search.found]
        heading = (
            f"{len(found)} {asked.state} in {github.repository} for `{asked.query}`:"
            if found
            else f"Nothing {asked.state} in {github.repository} matches `{asked.query}`."
        )
        more = beyond(search, github.searched)
        elsewhere = (
            [
                (
                    f"{search.elsewhere} matches in other repositories were left "
                    "out: a search reads one repository, which `repository` names."
                )
            ]
            if search.elsewhere
            else []
        )
        return "\n".join([heading, *found, *elsewhere, *more])

    @doors.tool
    async def file_issue(self, asked: NewIssue, by: Agent) -> str:
        """File an issue in this repository.

        It opens on GitHub at once, in the operator's name, so `find_issues`
        first, to find one already open. `labels` are the repository's own: a
        name it doesn't define is refused in `gh`'s words. Its link is the
        answer.
        """
        github = self.github("file-issue", asked, by.launch)
        await self.publish(
            Post(
                what="an issue",
                parts=[
                    Part(name="title", text=asked.title),
                    Part(name="body", text=asked.body),
                    *(Part(name="label", text=label) for label in asked.labels),
                ],
            ),
            "this issue",
            by,
        )
        return f"Filed: {await github.file(asked.title, asked.body, asked.labels)}"

    @doors.tool
    async def edit_issue(self, asked: IssueEdit, by: Agent) -> str:
        """Edit an issue's title, body or labels.

        Any issue of this repository on GitHub, by its number, in the
        operator's name: `title` and `body` replace its own where given, and
        labels are added and removed by name, from those the repository
        defines. GitHub keeps the earlier text in the issue's edit history,
        which only the operator can clear, on the web: where an edit takes out
        something that shouldn't be public, tell them.
        """
        github = self.github("edit-issue", asked, by.launch)
        await self.publish(
            Post(
                what=f"an edit of #{asked.number}",
                parts=[
                    *(
                        [Part(name="title", text=asked.title)]
                        if asked.title is not None
                        else []
                    ),
                    *(
                        [Part(name="body", text=asked.body)]
                        if asked.body is not None
                        else []
                    ),
                    *(Part(name="label", text=label) for label in asked.add_labels),
                ],
            ),
            "this edit",
            by,
        )
        await github.edit(
            asked.number,
            title=asked.title,
            body=asked.body,
            added=asked.add_labels,
            removed=asked.remove_labels,
        )
        return f"Edited #{asked.number}."

    @doors.tool
    async def close_issue(self, asked: IssueClosing, by: Agent) -> str:
        """Close an issue in this repository, saying why.

        `comment` is posted first, in the operator's name, then the issue
        closes for `reason`. Before closing one, check nothing is dropped:
        what's left of it filed as an issue of its own, a lesson in it carried
        where it'll be looked up (`docs/field-notes.md`, a doc, a docstring),
        and the comment saying where each went. A pull request isn't closed
        here. `reopen_issue` undoes it.
        """
        github = self.github("close-issue", asked, by.launch)
        await self.publish(
            Post(
                what=f"the closing comment on #{asked.number}",
                parts=[Part(name="body", text=asked.comment)],
            ),
            "this comment",
            by,
        )
        await self.issue_in(github, asked.number, "OPEN")
        link = await github.comment(asked.number, asked.comment)
        try:
            await github.close(asked.number, asked.reason, asked.duplicate_of)
        except GitHubError as failed:
            message = f"commented ({link}), but #{asked.number} didn't close: {failed}"
            raise GitHubError(message) from failed
        return f"Closed #{asked.number} as {asked.reason}, after the comment {link}"

    @doors.tool
    async def reopen_issue(self, asked: IssueReopening, by: Agent) -> str:
        """Reopen a closed issue in this repository.

        `comment`, saying why, is posted first, in the operator's name, then
        the issue reopens.
        """
        github = self.github("close-issue", asked, by.launch)
        await self.publish(
            Post(
                what=f"the reopening comment on #{asked.number}",
                parts=[Part(name="body", text=asked.comment)],
            ),
            "this comment",
            by,
        )
        await self.issue_in(github, asked.number, "CLOSED")
        link = await github.comment(asked.number, asked.comment)
        try:
            await github.reopen(asked.number)
        except GitHubError as failed:
            message = f"commented ({link}), but #{asked.number} didn't reopen: {failed}"
            raise GitHubError(message) from failed
        return f"Reopened #{asked.number}, after the comment {link}"

    async def issue_in(
        self, github: gh.GitHub, number: PositiveInt, state: Literal["OPEN", "CLOSED"]
    ) -> None:
        """Check that `number` is an issue, not a pull request, and that it's `state`.

        Raise `GitHubError` saying what it is instead, before anything is posted.
        """
        thread = await github.thread(number)
        if isinstance(thread, gh.PullRequest):
            message = (
                f"#{number} is a pull request: closing or reopening one is the "
                "operator's"
            )
            raise GitHubError(message)
        if thread.state != state:
            message = f"#{number} is already {thread.state.lower()}"
            raise GitHubError(message)

    @doors.tool
    async def comment(self, asked: NewComment, by: Agent) -> str:
        """Comment on an issue or pull request.

        On any issue or pull request of this repository on GitHub, by its
        number, in the operator's name. The comment's link is the answer.
        """
        github = self.github("comment", asked, by.launch)
        await self.publish(
            Post(
                what=f"a comment on #{asked.number}",
                parts=[Part(name="body", text=asked.body)],
            ),
            "this comment",
            by,
        )
        return f"Commented: {await github.comment(asked.number, asked.body)}"

    @doors.tool
    async def edit_comment(self, asked: CommentEdit, by: Agent) -> str:
        """Edit a comment on an issue or pull request.

        The comment at `link` on the issue or pull request `number` of this
        repository, as `read_issue` gives each comment's link: its text becomes
        `body` whole. GitHub keeps the earlier text in the comment's edit
        history, which only the operator can clear, on the web: where an edit
        takes out something that shouldn't be public, tell them. The comment's
        link is the answer.
        """
        github = self.github("edit-comment", asked, by.launch)
        await self.publish(
            Post(
                what=f"an edit of a comment on #{asked.number}",
                parts=[Part(name="body", text=asked.body)],
            ),
            "this edit",
            by,
        )
        edited = await github.edit_comment(asked.number, asked.link, asked.body)
        return f"Edited: {edited}"

    @doors.tool
    async def draft_pull_request(self, asked: NewDraft, by: Agent) -> str:
        """Open a draft pull request from a pushed branch.

        From `branch`, which must be on GitHub already (`git push` puts it
        there), into the project's integration branch, as a draft the operator
        reviews and merges: there's no merging here. Its link is the answer.
        """
        github = self.github("draft-pull-request", asked, by.launch)
        await self.publish(
            Post(
                what="a draft pull request",
                parts=[
                    Part(name="branch", text=asked.branch),
                    Part(name="title", text=asked.title),
                    Part(name="body", text=asked.body),
                ],
            ),
            "this pull request",
            by,
        )
        if not await github.pushed(asked.branch):
            message = (
                f"`{asked.branch}` isn't a branch of {github.repository} on GitHub: "
                "push it there first (`git push`), then open its pull request"
            )
            raise GitHubError(message)
        integration = LupDevSettings().lup_integration_branch
        link = await github.draft(asked.branch, integration, asked.title, asked.body)
        return (
            f"Opened a draft pull request from `{asked.branch}` into "
            f"`{integration}`: {link}"
        )

    @doors.request
    async def issue_state(self, asked: IssueState, by: Room) -> Stated:
        """Say whether an issue is open, as the gate in a room asks of a deferral's issue, where the launch's limits allow reading issues.

        A `HostError` refuses it, saying why.
        """
        refusal = by.launch.limits.refusal("read-issues")
        if refusal is not None:
            message = f"lup didn't read the issue's state: {refusal}"
            raise HostError(message)
        try:
            github = gh.GitHub.launched(by.launch)
            state = await github.state(asked.number, asked.repository)
        except GitHubError as failed:
            raise HostError(str(failed)) from failed
        return Stated(state=state)


def beyond(search: Search, searched: int) -> list[str]:
    """Say what may match past what `search` gave, and how to reach it: a larger `limit`, or past `searched`, the most GitHub's search gives a query, a narrower query; nothing where fewer came than were asked for."""
    if not search.full():
        return []
    if search.limit < searched:
        return [
            (
                f"GitHub gave the first {search.limit} matches it found; more may "
                f"match: a larger `limit`, up to {searched:,}, lists them."
            )
        ]
    return [
        (
            f"GitHub gave the first {search.limit:,} matches it found, the most its "
            "search gives a query; more may match: narrow the query, by `created:` "
            "or `updated:` dates say, to reach them."
        )
    ]
