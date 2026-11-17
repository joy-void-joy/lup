"""What runs the programs a part declares where it runs: on the operator's machine for the machine's parts, in its container for a project's.

A part runs a program through its field (`lup.Program`), never through
`lup.programs` itself, so a promise stands it in (`lup.testing.Scripted`); here
is what runs it for real, through `lup.programs`. Variables a run sets beside
those it runs with go through `env`, as `lup.programs` replaces a program's
environment whole where it's given one, which would drop `PATH` and `HOME`.
"""

import shutil
from datetime import timedelta
from typing import override

from lup.doors.parts import Finished, Program, Runs, UnrunError
from lup.programs import ProgramMissingError, ProgramOverdueError, awaited
from lup.types import Model


class Local(Model, Runs):
    """What runs a part's programs where the part runs, through `lup.programs`, each on the event loop, killed past `within`."""

    within: timedelta = timedelta(minutes=30)
    """The longest a program may run, past which it's killed and its call
    refused: well past an image built from nothing, and a limit still, since a
    program reading a FIFO a room made waits for good."""
    unfound: int = 127
    """The status `env` ends with where the program it's asked to run isn't
    there."""

    @override
    async def ran(
        self,
        program: Program,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
    ) -> Finished:
        """Run `program` with `arguments`, `given` on its input, `env` set beside the variables this process runs with, and say how it ended, whatever its status.

        Raise `UnrunError` where it isn't there, or runs past `within`.
        """
        pinned = [f"{name}={value}" for name, value in env.items()]
        words = [*(["env", *pinned] if env else []), program.name, *arguments]
        missing = (
            f"`{program.name}` isn't there"
            + (f": lup runs it as it {program.why}" if program.why else "")
            + (f"; install it from {program.install}" if program.install else "")
        )
        try:
            ran = await awaited(*words, stdin=given, checked=False, within=self.within)
        except ProgramMissingError as unfound:
            raise UnrunError(missing, about=[program.name]) from unfound
        except ProgramOverdueError as late:
            message = (
                f"`{program.name}` ran past {self.within}, and was stopped: "
                "something it reads may be a FIFO, or a file nothing finishes writing"
            )
            raise UnrunError(message, about=[program.name]) from late
        if env and ran.status == self.unfound and not await self.found(program):
            raise UnrunError(missing, about=[program.name])
        return Finished(status=ran.status, output=ran.output, error=ran.error)

    @override
    async def found(self, program: Program) -> bool:
        """Say whether `program` is there, on the `PATH` this process runs with."""
        return shutil.which(program.name) is not None
