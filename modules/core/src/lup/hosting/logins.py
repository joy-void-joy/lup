"""`Logins`: the machine's part reading the operator's logins on their machine, which it lends a part holding one as its container starts.

The operator's own credentials act for agents, as their terminal has them: a
part holding their GitHub login (`GitHubLogin`) is handed the token `gh auth
token` prints, read here as the part starts, so a login they renew with `gh auth
login` is the one the next start uses. `gh` is optional: without it, or without
a login, a part holding one waits, saying why, and the machine's other parts
run (`README.md` here, *Logins*).
"""

from pydantic import Field

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine
from lup.doors.parts import Part, Program
from lup.types import Model


class Borrowing(Model):
    """Asking to borrow one of the operator's logins, giving nothing."""


class Login(Model):
    """A login of the operator's, as the program holding it prints it."""

    token: str = Field(repr=False)


class Logins(Part, machine=True, shared=True):
    """The machine's part reading the operator's logins on their machine, for a part holding one."""

    gh: Program = Program(
        name="gh",
        optional=True,
        why=(
            "reads your GitHub login (`gh auth token`) for the parts acting on "
            "GitHub for agents"
        ),
        install="https://cli.github.com",
    )

    @lup.service
    async def github(self, borrowing: Borrowing, by: Machine) -> Login:
        """Return the operator's GitHub login, as `gh auth token` prints it on their machine.

        Raise `RefusedError` where `gh` has none, saying how to sign in.
        """
        del borrowing, by
        printed = await self.gh.ran("auth", "token")
        token = printed.text().strip()
        if printed.status != 0 or not token:
            message = (
                "`gh` on your machine has no GitHub login to lend: sign in with "
                f"`gh auth login` there, then open the project again. It said: {printed.said()}"
            )
            raise RefusedError(message)
        return Login(token=token)
