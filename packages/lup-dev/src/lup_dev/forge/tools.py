"""lup's GitHub tools in a launched session: reading and finding issues, filing one, commenting, opening a draft pull request.

`docs/host-tools.md`, *lup's tools*. Each acts on the launch's own repository on
GitHub, named when the launch started (`Register.github`), through the
operator's `gh` on the host (`forge/github.py`), and only within the limits the
project's declaration sets (`Register.limits`): a tool's action (`read-issues`,
`file-issue`, `comment`, `draft-pull-request`) is checked before anything runs,
and one beyond the limits is refused, saying the declaration doesn't allow it and
that allowing it is the operator's call. There's no merge tool, and none closes
or edits an issue: closing one is the operator's judgement, which a comment can
ask for.

A tool's description is its method's docstring, whose first line is the summary
each session's guidance lists (`ToolSpec.summary`). Results are text.
"""

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, Self, override

from pydantic import Field, JsonValue, PositiveInt, ValidationError, model_validator

from lup.tools.serving import Answer
from lup.tools.tool import ToolSpec
from lup.types import Model
from lup_dev.forge.github import GitHub, GitHubError, terms
from lup_dev.host.protocol import Action, Register
from lup_dev.host.rooms import RoomTools

if TYPE_CHECKING:
    from lup_dev.host.courier import Conversation


class Numbered(Model, extra="forbid"):
    """An issue or pull request of this repository, by its number."""

    number: PositiveInt = Field(description="Its number in this repository.")


class Query(Model, extra="forbid"):
    """A search of this repository's issues and pull requests."""

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

    @model_validator(mode="after")
    def quoted(self) -> Self:
        """Refuse a query whose double quotes don't close."""
        terms(self.query)
        return self


class NewIssue(Model, extra="forbid"):
    """An issue to file."""

    title: str = Field(min_length=1, description="Its title, one line.")
    body: str = Field(description="What it's about, in GitHub's Markdown.")


class NewComment(Model, extra="forbid"):
    """A comment on an issue or pull request."""

    number: PositiveInt = Field(
        description="The issue's or pull request's number in this repository."
    )
    body: str = Field(min_length=1, description="The comment, in GitHub's Markdown.")


class NewDraft(Model, extra="forbid"):
    """A draft pull request to open."""

    branch: str = Field(
        min_length=1,
        description="The branch to merge, as GitHub names it: pushed there already.",
    )
    title: str = Field(min_length=1, description="Its title, one line.")
    body: str = Field(
        description="What it changes and why, in GitHub's Markdown, for the reviewer."
    )


class GitHubTool(Model, arbitrary_types_allowed=True):
    """One GitHub tool as a launch's session is served it: what the session is told, and its answer to a call."""

    spec: ToolSpec
    answer: Callable[[JsonValue, Register], Awaitable[Answer]]

    @classmethod
    def of[I: Model](
        cls,
        action: Action,
        model: type[I],
        act: Callable[[GitHub, I], Awaitable[str]],
    ) -> GitHubTool:
        """Serve `act` as a tool named after it and described by its docstring, its arguments read as `model`, doing `action` with the operator's credentials.

        A call is answered by `act` only where the launch's limits allow
        `action`, its arguments read as `model`, and the launch's repository on
        GitHub was named; otherwise, and where `gh` fails, the answer says why.
        """
        name = act.__name__
        spec = ToolSpec(
            name=name,
            description=inspect.getdoc(act) or "",
            input_schema=model.model_json_schema(),
        )

        async def answered(arguments: JsonValue, launch: Register) -> Answer:
            refusal = launch.limits.refusal(action)
            if refusal is not None:
                return Answer(text=f"lup didn't run `{name}`: {refusal}.", error=True)
            try:
                asked = model.model_validate(arguments)
            except ValidationError as invalid:
                return Answer(text=f"`{name}`'s arguments: {invalid}", error=True)
            try:
                return Answer(text=await act(GitHub.launched(launch), asked))
            except GitHubError as failed:
                return Answer(text=f"`{name}` didn't run: {failed}", error=True)

        return cls(spec=spec, answer=answered)


class GitHubTools(Model, RoomTools):
    """lup's GitHub tools, served to each launched session: they act on its repository alone."""

    integration: str
    """The branch a draft pull request goes into: `LUP_INTEGRATION_BRANCH`, as
    trust on launch reads it."""
    limit: int = 100
    """The most matches `find_issues` asks GitHub for."""

    def served(self) -> list[GitHubTool]:
        """List the tools, each with the action it takes and the arguments it reads."""
        return [
            GitHubTool.of("read-issues", Numbered, self.read_issue),
            GitHubTool.of("read-issues", Query, self.find_issues),
            GitHubTool.of("file-issue", NewIssue, self.file_issue),
            GitHubTool.of("comment", NewComment, self.comment),
            GitHubTool.of("draft-pull-request", NewDraft, self.draft_pull_request),
        ]

    @override
    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self.served()]

    @override
    async def call(
        self, name: str, arguments: JsonValue, launch: Register, caller: Conversation
    ) -> Answer:
        tools = [tool for tool in self.served() if tool.spec.name == name]
        if not tools:
            return Answer(
                text=f"lup's GitHub tools have none named `{name}`", error=True
            )
        [tool] = tools
        return await tool.answer(arguments, launch)

    async def read_issue(self, github: GitHub, asked: Numbered) -> str:
        """Read an issue or pull request, with its comments.

        Any issue or pull request of this repository on GitHub, by its number:
        its title, state, author, labels and description, then each comment
        whole, oldest first. For a pull request, its branches, whether it's a
        draft, its review decision, and each check on its head with how it
        stands and where to look.
        """
        return (await github.thread(asked.number)).text()

    async def find_issues(self, github: GitHub, asked: Query) -> str:
        """Search this repository's issues and pull requests.

        GitHub's search over this repository on GitHub: each match's number,
        whether it's an issue or a pull request, its state, when it was last
        updated, and its title, in GitHub's order of relevance. `read_issue`
        reads one whole. Searching before filing an issue finds one already
        open.
        """
        search = await github.search(asked.query, asked.state, self.limit)
        found = [each.text() for each in search.found]
        heading = (
            f"{len(found)} {asked.state} in {github.repository} for `{asked.query}`:"
            if found
            else f"Nothing {asked.state} in {github.repository} matches `{asked.query}`."
        )
        more = (
            [
                (
                    f"GitHub gave the first {search.limit} matches it found; more "
                    "may match: narrow the query to see them."
                )
            ]
            if len(search.found) + search.elsewhere >= search.limit
            else []
        )
        elsewhere = (
            [
                (
                    f"{search.elsewhere} matches in other repositories were left "
                    "out: lup's tools read this repository alone."
                )
            ]
            if search.elsewhere
            else []
        )
        return "\n".join([heading, *found, *more, *elsewhere])

    async def file_issue(self, github: GitHub, asked: NewIssue) -> str:
        """File an issue in this repository.

        It opens on GitHub at once, in the operator's name, so `find_issues`
        first, to find one already open. Its link is the answer.
        """
        return f"Filed: {await github.file(asked.title, asked.body)}"

    async def comment(self, github: GitHub, asked: NewComment) -> str:
        """Comment on an issue or pull request.

        On any issue or pull request of this repository on GitHub, by its
        number, in the operator's name. Asking for an issue to be closed is a
        comment: closing one is the operator's call. The comment's link is the
        answer.
        """
        return f"Commented: {await github.comment(asked.number, asked.body)}"

    async def draft_pull_request(self, github: GitHub, asked: NewDraft) -> str:
        """Open a draft pull request from a pushed branch.

        From `branch`, which must be on GitHub already (`git push` puts it
        there), into the project's integration branch, as a draft the operator
        reviews and merges: there's no merging here. Its link is the answer.
        """
        if not await github.pushed(asked.branch):
            message = (
                f"`{asked.branch}` isn't a branch of {github.repository} on GitHub: "
                "push it there first (`git push`), then open its pull request"
            )
            raise GitHubError(message)
        link = await github.draft(
            asked.branch, self.integration, asked.title, asked.body
        )
        return (
            f"Opened a draft pull request from `{asked.branch}` into "
            f"`{self.integration}`: {link}"
        )
