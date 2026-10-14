"""What the operator approved for a repository: the host zone at a commit, and the `lup-dev` it runs.

Trust on launch records it (`lup_dev.launch.trust`; `docs/launch.md`, *Trust on
launch*), and the judge reads the declaration at its commit (`lup_dev.policy`;
`docs/judging-writes.md`, *The declaration, from the approved commit*), so what
runs on the host is what the operator approved. It's here, below both, since the
judge can't import the launch. Kept per repository in lup's state
(`Layout.approved`).
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from lup.types import Model
from lup_dev.declaration.runner import Uv
from lup_dev.layout import PackageLayout
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from lup_dev.layout import Layout


class WorkspaceTool(Model):
    """`lup-dev` from the repository's own workspace, as lup's lock resolves it.

    The host runs a copy built from the approved commit's source.
    """

    kind: Literal["workspace"] = "workspace"
    name: str
    """The package, as the lock names it."""
    package: Path
    """Its directory in the repository, which `uv tool install` installs."""
    members: list[Path]
    """The directory of each workspace package it needs, its own first: the copy
    carries their modules."""

    def paths(self) -> list[Path]:
        """List what the copy is built from, from the repository's root.

        uv's files, which hold the copy's dependencies to the lock and say where
        the workspace's packages are; each package's project file and modules; and
        the engine's source, which the build bundles into the package.
        """
        packages = [PackageLayout(root=member) for member in self.members]
        return [
            *(Path(each) for each in Uv().environment()),
            *(place for each in packages for place in [each.pyproject, each.source]),
            PackageLayout(root=self.package).engine,
        ]

    def lups_own(self) -> bool:
        """Say whether the copy is lup's own command too: it is, from lup's own repository.

        Only lup's own repository holds `lup-dev`'s source, so its copy is also
        installed as the `lup-dev` a person runs and the host service runs from.
        """
        return True

    def said(self, before: Tool | None) -> list[str]:
        """Say how the `lup-dev` the host runs changed beyond its source's diff."""
        match before:
            case ReleaseTool():
                said = (
                    f"`{self.name}` was the release {before.version} from "
                    f"{before.registry}; it becomes this repository's own source, "
                    f"at {self.package}."
                )
                return [said]
            case _:
                return []


class ReleaseTool(Model):
    """A `lup-dev` release the repository's lock pins, from an index."""

    kind: Literal["release"] = "release"
    name: str
    version: str
    registry: str
    """The index the lock resolves it from."""
    pins: dict[str, str]
    """Every other package it needs, by name, at the version the lock pins: the
    copy's dependencies are held to them."""

    def paths(self) -> list[Path]:
        """List none: a release is its version and pins, not the repository's files."""
        return []

    def lups_own(self) -> bool:
        """Say whether the copy is lup's own command too: a project's release isn't.

        The `lup-dev` a person runs, and the host service runs from, stays the one
        they installed; the release judges the project's own launches alone.
        """
        return False

    def requirement(self) -> str:
        """Return the release as a requirement: its name at its version."""
        return f"{self.name}=={self.version}"

    def constraints(self) -> str:
        """Return the pins as a requirements file, which uv takes as constraints."""
        return "".join(f"{name}=={version}\n" for name, version in self.pins.items())

    def said(self, before: Tool | None) -> list[str]:
        """Say how the release, and the versions it's held to, changed."""
        here = f"{self.version} from {self.registry}"
        match before:
            case ReleaseTool():
                there = f"{before.version} from {before.registry}"
                kept = there == here
                heading = (
                    f"`{self.name}` {here}, as before:"
                    if kept
                    else f"`{self.name}` {there} becomes {here}:"
                )
                earlier = before.pins
            case _:
                kept = False
                heading = f"`{self.name}` {here}, needing:"
                earlier = {}

        def moved(name: str) -> str:
            was = earlier.get(name)
            pinned = self.pins.get(name)
            if was is None:
                return f"  {name} {pinned}, added" if earlier else f"  {name} {pinned}"
            if pinned is None:
                return f"  {name} {was}, dropped"
            return f"  {name} {was} becomes {pinned}"

        names = list(dict.fromkeys([*earlier, *self.pins]))
        changed = [name for name in names if earlier.get(name) != self.pins.get(name)]
        if kept and not changed:
            return [f"`{self.name}` {here}, as before, needing what it did."]
        return [heading, *(moved(name) for name in changed)]


type Tool = Annotated[WorkspaceTool | ReleaseTool, Field(discriminator="kind")]
"""The `lup-dev` the host runs for a repository: its workspace's own, or a release."""


class Approval(Model):
    """The host zone the operator approved last for a repository, and when."""

    commit: str
    """The commit approved: the host runs the `lup-dev` it pins or holds, and the
    judge reads the declaration it holds."""
    fingerprint: str
    paths: list[Path]
    """The zone's paths at `commit`: a later change shows what changed in them
    since, and any path the zone holds beside them whole."""
    tool: Tool
    time: datetime


def approved(layout: Layout, repository: Path) -> Approval | None:
    """Return what the operator approved last for the repository at `repository`; none before the first approval."""
    return read_model(layout.approved(repository), Approval)
