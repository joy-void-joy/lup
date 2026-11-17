"""Running a program: lup's one runner of them, which every other module's code uses.

`run` waits for one and returns how it ended (`Ran`), `awaited` does so on an
event loop, `started` keeps one running beside it to talk to over its input and
output, `spawned` one with its output the caller's, and `detached` starts one
that outlives its caller. `lup` re-exports it as a namespace, `lup.programs`,
never its names alone. Its reasons are in `README.md` here.
"""

from lup.programs.beside import Apart, Child, Running, detached, spawned, started
from lup.programs.ended import (
    ProgramError,
    ProgramFailedError,
    ProgramMissingError,
    ProgramOverdueError,
    ProgramOverflowError,
    Ran,
)
from lup.programs.waited import awaited, run

__all__ = [
    "Apart",
    "Child",
    "ProgramError",
    "ProgramFailedError",
    "ProgramMissingError",
    "ProgramOverdueError",
    "ProgramOverflowError",
    "Ran",
    "Running",
    "awaited",
    "detached",
    "run",
    "spawned",
    "started",
]
