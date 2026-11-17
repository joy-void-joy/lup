"""Answering a view: through its door, as a party reads it, its blocks checked against what a project's modules declare (`README.md` in `lup/shell/`, *Kinds*)."""

from typing import TYPE_CHECKING

from lup.doors.door import Accepted
from lup.shell.blocks import Blocks
from lup.shell.view import ViewDoor

if TYPE_CHECKING:
    from pydantic import JsonValue

    from lup.doors.door import Refused
    from lup.doors.parties import Party
    from lup.environment.doors import Running
    from lup.shell.looks import Looks


async def viewed(
    doors: Running,
    looks: Looks,
    module: str,
    view: str,
    given: JsonValue,
    by: Party,
) -> Accepted | Refused:
    """Answer the view `view` of the module named `module` for `given`, read by `by`, and say what came of it: its blocks each with a version, the core working one out where the module gives none (`Blocks.versioned`).

    Raise `BlockError` where what it answers names a kind neither the core nor
    its module declares: the view's fault, not the caller's.
    """
    answered = await doors.reached(ViewDoor, module, view, given, by)
    match answered:
        case Accepted(output=Blocks() as blocks):
            looks.checked(blocks, module)
            return answered.model_copy(update={"output": blocks.versioned()})
        case _:
            return answered
