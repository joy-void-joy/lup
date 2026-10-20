"""The room's request for an issue's state, and the host's answer.

`docs/credentials.md`, *The gate in a room*. The gate checks each deferral's
issue is still open, and a room holds no `gh` and no login, so the gate there
asks the host on the launch's `request.sock` (`codescan/directives.py`,
`HostIssues`). The request is the core's, since the gate asks it whatever modules
a project selects; the `GitHub` module answers it (`lup.github.stating`).
"""

from typing import Literal

from pydantic import Field

from lup_dev.host.protocol import Reply, Request


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
