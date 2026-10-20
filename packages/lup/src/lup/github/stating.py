"""The answer to a room's question of whether an issue is open, through `gh` on the host within the launch's limits.

`docs/credentials.md`, *The gate in a room*. The gate checks each deferral's
issue is still open, and a room holds no `gh` and no login, so the gate there
asks the host on the launch's `request.sock` (`lup_dev.codescan.directives`,
`HostIssues`), which reads the state with the operator's `gh`. Reading an issue
is the launch's `read-issues` action, refused where the project's declaration
leaves it out. The request is the core's (`lup_dev.forge.protocol`), since the
gate asks it whatever modules a project selects.
"""

from typing import TYPE_CHECKING, override

from lup_dev.declaration.serving import ModuleHandler
from lup_dev.forge import github as gh
from lup_dev.forge.github import GitHubError
from lup_dev.forge.protocol import IssueState, Stated
from lup_dev.host.protocol import HostError, Reply

if TYPE_CHECKING:
    from lup.github.module import GitHub


class Stating(ModuleHandler):
    """Answers `IssueState` for a launch's room, through `gh` on the host, where the launch's limits allow reading issues."""

    module: GitHub
    request: IssueState

    @override
    async def answer(self) -> Reply:
        refusal = self.launch.limits.refusal("read-issues")
        if refusal is not None:
            message = f"lup didn't read the issue's state: {refusal}"
            raise HostError(message)
        try:
            github = gh.GitHub.launched(self.launch)
            state = await github.state(self.request.number, self.request.repository)
        except GitHubError as failed:
            raise HostError(str(failed)) from failed
        return Stated(state=state)
