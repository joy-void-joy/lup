"""What a module's methods are typed as on the command line: each tool, command and view it serves, by its name as typer types it.

Resolving a declaration reads it to refuse a module named as one of the core's
methods is typed, since `lup` types those at its top level and every other
module's under its name; `lup new` reads it to refuse such a name before it
writes anything (`README.md` here, *Typing*).
"""

from typing import TYPE_CHECKING

from lup.doors.command import CommandDoor
from lup.doors.door import Method, served
from lup.doors.parts import Parts
from lup.doors.tool import ToolDoor
from lup.running.plan import typed
from lup.shell.view import ViewDoor

if TYPE_CHECKING:
    from lup.declaration.module import Module


def typed_methods(module: Module) -> dict[str, Method]:
    """Return each tool, command and view `module` serves, by its name as the command line types it (`lup.running.plan.typed`)."""
    return {
        typed(name): method
        for part in module.held(Parts)
        for name, method in served(part).items()
        if isinstance(method.door, ToolDoor | CommandDoor | ViewDoor)
    }
