"""`Project`: what a project declares in `lup_project.py`, its modules above all.

Every part lives in a module, so reading one module says what it does; `Project`
holds the modules, and what isn't a module's (`docs/declaration.md`, *An
example*).
"""

from typing import Literal, get_args

from pydantic import ValidationInfo, field_validator, model_validator

from lup.types import Model
from lup_dev.declaration.module import Modules

type Asking = Literal[
    "new-file",
    "whole-file",
    "public-api",
    "ignore",
    "private",
]
"""What a change asks the operator about, besides a rule's finding: a kind of
change, `private` a value never published on a line it touches
(`lup_dev.private`). A path's role asks by its level (`Levels`), never by name
here."""

type RoleName = Literal[
    "protected", "operator", "excluded", "test", "scratch", "docs", "data", "production"
]
"""A path's role, as `Levels` keys it: named in `held` or `flagged`, it's refused,
its level going in `Levels`."""


class Project(Model, extra="forbid"):
    """A project's declaration: its modules, and what isn't a module's.

    >>> Project() == Project(modules=Modules.default())
    True
    """

    modules: Modules = Modules.default()
    """The modules it's made of: lup's default ones, unless it says otherwise."""
    held: list[str] = ["ignore"]
    """What a change waits for the operator's answer on, by name: a kind of
    change (`new-file`, `whole-file`, `public-api`, `ignore`, `private`), or one
    of lup's rules, a finding of on the lines the change touches. A path's role
    is never named here: how far each role is reviewed, held among it, is its
    level (`Core.levels`, `Levels`)."""
    flagged: list[str] = ["new-file", "whole-file", "public-api", "private"]
    """What a change lands with, flagged for the operator's review of the branch,
    by the same names. A name in neither list is let through."""
    profile: str | None = None
    """The profile the repository's launches run on where `--profile` names
    none, by its name among the person's profiles (`docs/declaration.md`,
    *Profiles*); none for `default`. A profile is a person's own, so only their
    layer, `lup_project.local.py`, chooses one: a committed declaration setting
    it fails the load."""

    @field_validator("held", "flagged")
    @classmethod
    def named(cls, names: list[str], info: ValidationInfo) -> list[str]:
        """Refuse a path's role, which goes in `Levels`, and a name that's neither a kind of change nor shaped as a rule's.

        >>> Project(held=["ignore", "regex"]).held
        ['ignore', 'regex']
        >>> from pydantic import ValidationError
        >>> try:
        ...     Project(held=["protected"])
        ... except ValidationError as refused:
        ...     print(refused.errors()[0]["msg"])
        Value error, `protected` is a path's role, whose level goes in `Levels`, not in `held`: `Core(levels=Levels(protected="held"))`
        """
        level = "held" if info.field_name == "held" else "flagged"
        roles = [name for name in names if name in get_args(RoleName.__value__)]
        if roles:
            said = ", ".join(f"`{role}`" for role in roles)
            given = ", ".join(f'{role}="{level}"' for role in roles)
            what = "a path's role" if len(roles) == 1 else "paths' roles"
            message = (
                f"{said} {'is' if len(roles) == 1 else 'are'} {what}, whose level "
                f"goes in `Levels`, not in `{info.field_name}`: "
                f"`Core(levels=Levels({given}))`"
            )
            raise ValueError(message)
        unknown = [name for name in names if not answered_by_name(name)]
        if unknown:
            message = (
                f"{unknown} name nothing held or flagged: a kind of change "
                f"({', '.join(get_args(Asking.__value__))}), or a rule's name, as "
                "`lup-dev rules list` lists them"
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
    """Say whether `name` names something held or flagged: a kind of change, or a rule's name, its letters lower case, its words joined by `-`.

    >>> [answered_by_name(each) for each in ["ignore", "tuple-shape", "Nope", ""]]
    [True, True, False, False]
    """
    if name in get_args(Asking.__value__):
        return True
    shaped = all(char.islower() or char.isdigit() or char == "-" for char in name)
    return shaped and name != "" and name[0].isalpha()
