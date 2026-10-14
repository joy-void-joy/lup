"""The room's request for an issue's state, and the host's answer, through `gh` within the launch's limits.

`docs/host-tools.md`, *The gate in a room*. The gate checks each deferral's
issue is still open, and a room holds no `gh` and no login, so the gate there
asks the host on the launch's `request.sock` (`codescan/directives.py`,
`HostIssues`), which reads the state with the operator's `gh` (`Stating`).
Reading an issue is the launch's `read-issues` action, refused where the
project's declaration leaves it out.
"""

from typing import Literal, override

from pydantic import Field

from lup.types import Model
from lup_dev.forge.github import GitHub, GitHubError
from lup_dev.host.protocol import HostError, Register, Reply, Request
from lup_dev.host.rooms import RoomHandler


class IssueState(Request):
    """Ask whether an issue is open, as the gate does of a deferral's issue."""

    kind: Literal["issue-state"] = "issue-state"
    repository: str | None = None
    """`owner/repo`, as a deferral names an issue elsewhere; none for the launch's
    own repository."""
    number: int = Field(gt=0)


class Stated(Reply):
    """An issue's state, as GitHub has it."""

    kind: Literal["stated"] = "stated"
    state: Literal["open", "closed"]


class Stating(Model, RoomHandler[IssueState]):
    """Answers `IssueState` for a launch's room, through `gh` on the host, where the launch's limits allow reading issues."""

    @override
    def request(self) -> type[IssueState]:
        return IssueState

    @override
    async def answer(self, request: IssueState, launch: Register) -> Reply:
        refusal = launch.limits.refusal("read-issues")
        if refusal is not None:
            message = f"lup didn't read the issue's state: {refusal}"
            raise HostError(message)
        try:
            github = GitHub.launched(launch)
            return Stated(state=await github.state(request.number, request.repository))
        except GitHubError as failed:
            raise HostError(str(failed)) from failed
