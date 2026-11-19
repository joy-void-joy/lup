"""Setting a repository up, its environment side: `lup init` and `lup new` answered where they're typed, and the repository registered with the operator's lup.

`SettingUp` answers them in this process, over lup's default modules, as
`InProcess` does, and once one has set a repository up, tells lup's program on
the operator's machine of it, through `hosting register`, so the dashboard
lists it: over the socket `LUP_CALLING` names, else the machine's own, the
machine started first where nothing answers there. Without podman no machine
runs, and nothing is registered, which the answer says (`lup/setup/README.md`).
"""

import shutil
import sys
from pathlib import Path

from pydantic import ValidationError

from lup.declaration.layout import COMMON, RepositoryLayout
from lup.doors.door import RefusedError, served
from lup.environment.command_line import InProcess, machine
from lup.environment.running.calling import Calling
from lup.environment.running.loader import Loader, LoaderError, Places
from lup.environment.settings import LupSettings
from lup.hosting.projects import Opening
from lup.programs import ProgramError, run
from lup.running.plan import CORE
from lup.running.wire import Answered, Call, CommandCalled, Declined, Reply
from lup.setup.part import SetUp, Setup


class SettingUp(InProcess):
    """`lup init` and `lup new` answered in this process, over lup's default modules, and each repository they set up registered with the operator's lup."""

    async def answered(self, call: Call) -> Reply:
        """Answer `call` in this process; where it set a repository up, register it, and say whether it was."""
        reply = await super().answered(call)
        match call, reply:
            case CommandCalled(module=module, command=command), Answered(
                output=output
            ) if module == CORE and command in served(Setup):
                done = await registered(SetUp.model_validate(output))
                return Answered(output=done.model_dump(mode="json"))
            case _:
                return reply


async def registered(done: SetUp) -> SetUp:
    """Tell the operator's lup of the repository `done` set up, through `hosting register`, and return `done` saying whether it did, and why not where it didn't."""
    calling = LupSettings().lup_calling
    if calling is None and shutil.which("podman") is None:
        return done.model_copy(
            update={
                "unregistered": (
                    "podman isn't here, so no machine of lup's runs to list it: "
                    "once one does, `lup hosting register` lists it"
                )
            }
        )
    try:
        layout = RepositoryLayout.found(done.root)
        common = Path(run("git", *COMMON, cwd=done.root).text())
        opening = Opening(
            repository=layout.main.name,
            common=common,
            declaration=done.declaration.relative_to(done.root),
        )
        socket = (
            calling
            or await Loader(
                places=Places.found(),
                machine=machine(),
                interactive=sys.stdin.isatty(),
            ).ensured()
        )
        reply = await Calling(socket=socket).answered(
            CommandCalled(
                module="hosting",
                command="register",
                given=opening.model_dump(mode="json"),
            )
        )
    except (ProgramError, ValidationError, LoaderError, RefusedError) as failed:
        return done.model_copy(update={"unregistered": str(failed)})
    match reply:
        case Answered():
            return done.model_copy(update={"registered": True, "unregistered": ""})
        case Declined(rejection=rejection):
            return done.model_copy(update={"unregistered": rejection.reason})
