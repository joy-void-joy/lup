"""What a module needs from outside the project's Python environment, and checking it.

Each module declares its own requirements as a class attribute, and a runner
brings its own (`docs/declaration.md`, *Requirements*). They're checked all at
once, strictly, before anything runs: a missing required one stops it, naming
every one missing, the module needing it and how to install it; a missing optional
one turns its feature off. A version is read from what the requirement's probe
prints, a bare version, with `packaging`, so nothing reads a tool's banner.
"""

import shutil
from abc import ABC, abstractmethod
from typing import Literal, Self, override

import sh
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import model_validator

from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.errors import LupDevError


class RequirementError(LupDevError):
    """A tool a selected module requires is missing, or not at a version it takes."""


class Requirement(Model, extra="forbid"):
    """A tool a module needs, from outside the project's Python environment.

    >>> Requirement(tool="node", version=">=22.18", why="runs the rule engine")
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `node` takes a version, so it needs a `probe` printing it
    """

    tool: str | None = None
    """The program, as the `PATH` finds it."""
    any_of: list[str] = []
    """Programs any one of which will do, where `tool` isn't given."""
    version: str | None = None
    """The versions that will do, as a specifier (`>=22.18`); without one, the
    check is that the tool is on the `PATH`."""
    probe: list[str] = []
    """The command printing the tool's bare version, required with `version`."""
    optional: bool = False
    """Whether its feature turns off without it, rather than nothing running."""
    why: str | None = None
    """What it's needed for, shown when it's missing."""
    install: str | None = None
    """How to install it, shown when it's missing."""

    @model_validator(mode="after")
    def complete(self) -> Self:
        """Refuse a requirement that names no tool, or a version it can't check."""
        if (self.tool is None) == (not self.any_of):
            message = "a requirement names one `tool`, or the programs `any_of` will do"
            raise ProjectError(message)
        if self.version is None:
            return self
        if not self.probe:
            message = f"`{self.named()}` takes a version, so it needs a `probe` printing it"
            raise ProjectError(message)
        try:
            SpecifierSet(self.version)
        except InvalidSpecifier as failure:
            message = f"`{self.named()}`'s version {self.version!r} isn't a specifier"
            raise ProjectError(message) from failure
        return self

    def programs(self) -> list[str]:
        """List the programs any one of which will do."""
        return [self.tool] if self.tool is not None else self.any_of

    def named(self) -> str:
        """Name the requirement by its programs.

        >>> Requirement(any_of=["wl-copy", "xclip"]).named()
        'wl-copy or xclip'
        """
        return " or ".join(self.programs())


class Printed(Model):
    """How a probe ended: its exit code, and what it printed."""

    code: int
    output: str


class Tools(ABC):
    """Where requirements are looked for: the programs on the `PATH`, and probes."""

    @abstractmethod
    def found(self, program: str) -> bool:
        """Say whether `program` is on the `PATH`."""

    @abstractmethod
    def run(self, command: list[str]) -> Printed:
        """Run a probe, and say how it ended."""


class Machine(Tools):
    """The programs on this machine, run as processes."""

    @override
    def found(self, program: str) -> bool:
        return shutil.which(program) is not None

    @override
    def run(self, command: list[str]) -> Printed:
        program, *arguments = command
        try:
            ran = sh.Command(program)(
                *arguments,
                _ok_code=list(range(256)),
                _tty_out=False,
                _return_cmd=True,
            )
        except sh.CommandNotFound:
            return Printed(code=127, output="")
        return Printed(code=ran.exit_code, output=ran.stdout.decode(errors="replace"))


class Needed(Model):
    """A requirement, with the module that needs it."""

    module: str
    """The module's name."""
    requirement: Requirement


class Checked(Model):
    """One requirement, checked."""

    needed: Needed
    status: Literal["met", "missing", "wrong version", "unreadable"]
    found: str | None = None
    """The program found, the version its probe printed, or what the probe printed
    in place of a version."""

    def described(self) -> str:
        """Say what the requirement is for and how it stands, for a message."""
        requirement = self.needed.requirement
        match self.status:
            case "met":
                stands = f"found {self.found}"
            case "missing":
                stands = "not on the `PATH`"
            case "wrong version":
                stands = f"takes {requirement.version}, found {self.found}"
            case "unreadable":
                stands = f"`{' '.join(requirement.probe)}` printed no version: {self.found!r}"
        why = requirement.why or "no reason given"
        install = f" Install: {requirement.install}." if requirement.install else ""
        named = f"`{requirement.named()}`, for `{self.needed.module}` ({why})"
        return f"{named}: {stands}.{install}"


class Report(Model):
    """Every requirement of a declaration, checked at once."""

    checked: list[Checked]

    @property
    def unmet(self) -> list[Checked]:
        """The required ones not met, which stop anything from running."""
        return [
            each
            for each in self.checked
            if each.status != "met" and not each.needed.requirement.optional
        ]

    @property
    def off(self) -> list[Checked]:
        """The optional ones not met, whose features turn off."""
        return [
            each
            for each in self.checked
            if each.status != "met" and each.needed.requirement.optional
        ]

    def require(self) -> Self:
        """Raise `RequirementError` naming every required one not met."""
        if not self.unmet:
            return self
        lines = "\n".join(f"- {each.described()}" for each in self.unmet)
        message = f"Requirements not met, so nothing ran:\n{lines}"
        raise RequirementError(message)


def check(needed: list[Needed], tools: Tools) -> Report:
    """Check every requirement in `needed` at once, through `tools`."""

    def one(each: Needed) -> Checked:
        requirement = each.requirement
        found = next(
            (program for program in requirement.programs() if tools.found(program)),
            None,
        )
        if found is None:
            return Checked(needed=each, status="missing")
        if requirement.version is None:
            return Checked(needed=each, status="met", found=found)
        ran = tools.run(requirement.probe)
        printed = ran.output.strip()
        if ran.code != 0:
            return Checked(needed=each, status="unreadable", found=printed)
        try:
            version = Version(printed)
        except InvalidVersion:
            return Checked(needed=each, status="unreadable", found=printed)
        if SpecifierSet(requirement.version).contains(version, prereleases=True):
            return Checked(needed=each, status="met", found=str(version))
        return Checked(needed=each, status="wrong version", found=str(version))

    return Report(checked=[one(each) for each in needed])
