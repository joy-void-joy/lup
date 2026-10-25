"""`Private`, the module: what never leaves under the operator's name, read on the host and given by the person.

`docs/private.md`. It's one of lup's default modules, so a project that drops it
says so in its declaration, with its reason. A person's own values go in their
own layer, which git ignores (`docs/declaration.md`, *Where it lives*):

    project = Project(modules=Modules().edit(Private(values=Values().add("kestrel"))))
"""

from pathlib import Path
from typing import Self

from pydantic import model_validator

from lup_dev.catalog.gate import Step
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Named, listed
from lup_dev.declaration.kinds import Gate, Guidance, Section, Serving, mentioned
from lup_dev.declaration.module import Module
from lup_dev.private.serving import PrivateServing
from lup_dev.private.withheld import DETAILS, Detail


class Details(Named[str]):
    """The details lup reads on the host, never published, each by its name.

    `home`, `user`, `hostname`, `alias`, `repository-path` and
    `private-repository` (`lup_dev.private.withheld`). `Details.all()` is every
    one; a name that isn't one is refused where it's written, naming those that
    are.

    >>> Details().drop("hostnme")
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `Details` has no detail `hostnme`; its details are `home`, `user`, `hostname`, `alias`, `repository-path` and `private-repository`
    """

    @model_validator(mode="after")
    def known(self) -> Self:
        """Refuse a name that isn't a detail, naming those that are."""
        every: list[str] = [*DETAILS]
        unknown = [name for name in mentioned(self) if name not in every]
        if unknown:
            message = (
                f"`Details` has no detail {listed(unknown)}; "
                f"its details are {listed(every)}"
            )
            raise ProjectError(message)
        return self


class Values(Named[str]):
    """The person's own values never published, each a plain string, found as a whole word whatever its case.

    A value that's blank, or spans lines, is refused where it's written: it would
    find nothing, or everything.

    >>> Values().add("  ")
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `Values` holds a value that's blank or spans lines: each is one word or phrase on one line
    """

    @model_validator(mode="after")
    def written(self) -> Self:
        """Refuse a blank value, or one spanning lines."""
        if any(
            not name.strip() or len(name.splitlines()) > 1 for name in mentioned(self)
        ):
            message = (
                "`Values` holds a value that's blank or spans lines: each is one "
                "word or phrase on one line"
            )
            raise ProjectError(message)
        return self


class Private(Module):
    """What never leaves under the operator's name: the details lup reads on the host, and the person's own values."""

    name = "private"

    details: Details = Details.all()
    """The details read on the host: every one, unless the project or the person
    drops one, with why (a hostname that's an ordinary word)."""
    values: Values = Values()
    """The person's own values: none, unless their own layer,
    `lup_project.local.py`, adds them."""
    serving: Serving = Serving.of(PrivateServing)
    """At `Publishing`, refusing a push or a post that carries a value; and the
    gate's step in a room, which never sees the list, answered on the host."""
    gate: Gate = Gate.of(Step(name="private", command=["lup-dev", "private", "check"]))
    """`private`: every file, and `HEAD`'s commits the remotes lack, read for a
    value, failing on one."""
    guidance: Guidance = Guidance.of(
        Section(name="private", package="lup_dev.private", path=Path("guidance.md"))
    )
    """What's published, and how a path or a name is written so nothing of the
    operator's machine goes with it."""

    def chosen_details(self) -> list[Detail]:
        """Return the details read on the host, every layer applied, in lup's order."""
        named = [each.entry for each in self.details.resolve([*DETAILS], [*DETAILS])]
        return [detail for detail in DETAILS if detail in named]

    def chosen_values(self) -> list[str]:
        """Return the person's own values, every layer applied."""
        return [each.entry for each in self.values.resolve([], [])]
