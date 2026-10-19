"""`Project`: what a project declares in `lup_project.py`, its modules above all.

Every part lives in a module, so reading one module says what it does; `Project`
holds the modules, and what isn't a module's (`docs/declaration.md`, *A project is
its modules*).
"""

from typing import Literal, get_args

from pydantic import field_validator, model_validator

from lup.types import Model
from lup_dev.declaration.module import Modules

type Asking = Literal[
    "protected",
    "operator",
    "new-file",
    "whole-file",
    "public-api",
    "ignore",
    "private",
]
"""What a change asks the operator about, besides a rule's finding: a path's role
(`protected`, `operator`) or a kind of change, `private` a value never published
on a line it touches (`lup_dev.private`)."""


class Project(Model, extra="forbid"):
    """A project's declaration: its modules, and what isn't a module's.

    >>> Project() == Project(modules=Modules.default())
    True
    """

    modules: Modules = Modules.default()
    """The modules it's made of: lup's default ones, unless it says otherwise."""
    held: list[str] = ["protected", "operator", "ignore"]
    """What a change waits for the operator's answer on, by name: a path's role
    (`protected`, `operator`), a kind of change (`new-file`, `whole-file`,
    `public-api`, `ignore`, `private`), or one of lup's rules, a finding of on
    the lines the change touches. Which paths have a role is `Paths`'s to say;
    how each is answered is said here alone."""
    flagged: list[str] = ["new-file", "whole-file", "public-api", "private"]
    """What a change lands with, flagged for the operator's review of the branch,
    by the same names. A name in neither list is let through."""

    @field_validator("held", "flagged")
    @classmethod
    def named(cls, names: list[str]) -> list[str]:
        """Refuse a name that's neither a role, a kind of change, nor shaped as a rule's.

        >>> Project(held=["protected", "regex"]).held
        ['protected', 'regex']
        """
        unknown = [name for name in names if not answered_by_name(name)]
        if unknown:
            message = (
                f"{unknown} name nothing held or flagged: a path's role or a kind of "
                f"change ({', '.join(get_args(Asking.__value__))}), or a rule's "
                "name, as `lup-dev rules list` lists them"
            )
            raise ValueError(message)
        return names

    @model_validator(mode="after")
    def apart(self) -> Project:
        """Refuse a name both held and flagged."""
        both = [name for name in self.held if name in self.flagged]
        if both:
            message = f"{both} are both held and flagged: say each in one list"
            raise ValueError(message)
        return self


def answered_by_name(name: str) -> bool:
    """Say whether `name` names something held or flagged: a role, a kind of change, or a rule's name, its letters lower case, its words joined by `-`.

    >>> [answered_by_name(each) for each in ["protected", "tuple-shape", "Nope", ""]]
    [True, True, False, False]
    """
    if name in get_args(Asking.__value__):
        return True
    shaped = all(char.islower() or char.isdigit() or char == "-" for char in name)
    return shaped and name != "" and name[0].isalpha()
