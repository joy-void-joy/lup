"""`Private`: what never leaves under the operator's name, refused where it would, among lup's default modules."""

from typing import ClassVar, get_args

from lup.declaration.grammar import Named
from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.gate.steps import Step, Steps
from lup.private.found import Kind
from lup.private.guard import Checker, Guard
from lup.private.promises import PrivatePromises
from lup.private.withholding import Withholding


class Values(Named[str]):
    """The operator's own values, never published under their name, each a string found literally, ignoring case, never inside a longer word: `Private(values=Values().add("Kestrel Labs", "RTX 4090"))`, in the machine's layer, `~/.config/lup/lup_project.local.py`, which no room mounts."""


class Details(Named[str]):
    """What lup finds on the machine and withholds, by kind: `Private(details=Details().drop("hostname", why="my machine's name is `desktop`"))`."""


class Private(Module):
    """What never leaves under your name.

    The operator's home path, user name, machine name and ssh aliases, the
    project's own path, their own values, and an inbox item's number in prose.
    The list is the machine's alone (`Withholding`). Each project's `Guard`
    refuses at `Publishing` a push or a post holding one, saying where, never
    what; the gate's `private` step fails on one in the worktree's files or in
    a commit the remotes lack.
    """

    name = "private"
    known: ClassVar[list[str]] = [
        each for each in get_args(Kind.__value__) if each != "value"
    ]
    """Every detail lup finds and withholds, which `Details.all()` starts from."""
    values: Values = Values.of()
    """The operator's own values: none unless their layer adds some."""
    details: Details = Details.all()
    """What lup finds and withholds: every kind it knows, but those a layer
    drops, each with why."""
    steps: Steps = Steps.of(
        Step(name="private", command=["lup", "private", "check"], together=True)
    )
    """The gate's step failing on what never leaves, in the worktree's files
    or a commit the remotes lack."""
    parts: Parts = Parts.of(Withholding, Guard, Checker, PrivatePromises)

    def withheld(self) -> list[str]:
        """Return each kind withheld: what lup finds that the declaration keeps, and the operator's own values."""
        found = [each.entry for each in self.details.resolve(self.known, self.known)]
        return [*found, "value"]
