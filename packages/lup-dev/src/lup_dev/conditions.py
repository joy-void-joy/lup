"""Conditions a deferral waits on, written in Python.

`# lup: defer(when=sdk_reports_ttl, why="…")` names a condition the project
declares in the module its declaration names for them (`Project.conditions`). The
comment holds only the name, so nothing in a comment is ever run, and the
condition is typed and tested like any code. lup ships two stock conditions; a
project subclasses `Condition` for its own.

At the edit, the judge checks the name is declared, reading the module without
running it. At the gate, the module is imported and each named condition asked
whether it holds; one that does makes its deferral due.
"""

import ast
import importlib
import importlib.util
from abc import ABC, abstractmethod
from pathlib import Path
from typing import override

import httpx
import sh
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, TypeAdapter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout
from lup_dev.project import Project, Pyproject, import_roots, importable


class ConditionError(LupDevError):
    """A project's conditions can't be read, or a condition can't be decided."""


class Condition(Model, ABC):
    """Something that becomes true later, which a deferral waits on."""

    @abstractmethod
    def holds(self) -> bool:
        """Say whether the condition holds now, so the deferral it wakes is due."""


class Pythons(Model, ABC):
    """Where the Python releases a project could use are listed."""

    @abstractmethod
    def versions(self) -> list[str]:
        """List every Python version available, as version strings."""


class UvPythons(Pythons):
    """The Python versions uv can install or has installed."""

    @override
    def versions(self) -> list[str]:
        class Listed(Model):
            """One interpreter as `uv python list --output-format json` lists it."""

            version: str

        listed = sh.Command("uv")(
            "python",
            "list",
            "--all-versions",
            "--output-format",
            "json",
            _tty_out=False,
            _return_cmd=True,
        )
        found = TypeAdapter(list[Listed]).validate_json(listed.stdout)
        return [python.version for python in found]


def final(version: str) -> Version | None:
    """Read a version string, or none where it's unreadable or a pre-release.

    >>> final("3.15.0rc3") is None
    True
    >>> final("3.15.0")
    <Version('3.15.0')>
    """
    try:
        parsed = Version(version)
    except InvalidVersion:
        return None
    return None if parsed.is_prerelease or parsed.is_devrelease else parsed


class PythonAvailable(Condition):
    """A final release of a Python version is out.

    `PythonAvailable(version="3.15")`.
    """

    version: str
    """The version as `major.minor`."""
    pythons: Pythons = Field(default_factory=UvPythons)

    @override
    def holds(self) -> bool:
        wanted = SpecifierSet(f"=={self.version}.*")
        released = [final(version) for version in self.pythons.versions()]
        return any(version in wanted for version in released if version is not None)


class PackageIndex(Model, ABC):
    """A package index that lists each package's releases."""

    @abstractmethod
    def releases(self, name: str) -> list[str]:
        """List the versions of `name` released and not yanked."""


class PyPI(PackageIndex, arbitrary_types_allowed=True):
    """The Python Package Index, through its JSON API."""

    url: str = "https://pypi.org/pypi"
    """The JSON API's root: a package's releases are at `<url>/<name>/json`."""
    timeout: float = 10.0
    """Seconds to wait for the index before a try counts as failed."""
    transport: httpx.BaseTransport | None = None
    """How requests reach the index; none for the network."""

    @override
    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )
    def releases(self, name: str) -> list[str]:
        class File(Model):
            """One file of a release, as the index lists it."""

            yanked: bool = False

        class Package(Model):
            """A package's page in the JSON API: its releases and their files."""

            releases: dict[str, list[File]] = {}

        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            response = client.get(f"{self.url}/{name}/json")
        response.raise_for_status()
        package = Package.model_validate_json(response.content)
        return [
            version
            for version, files in package.releases.items()
            if any(not file.yanked for file in files)
        ]


class PackageReleased(Condition):
    """A package released a version, or a later one.

    `PackageReleased(name="anthropic", version="1.0")`.
    """

    name: str
    version: str
    index: PackageIndex = Field(default_factory=PyPI)

    @override
    def holds(self) -> bool:
        wanted = Version(self.version)
        released = [final(version) for version in self.index.releases(self.name)]
        return any(version >= wanted for version in released if version is not None)


def module_file(root: Path, module: str) -> Path:
    """Find the file of the project's module `module`, from the worktree at `root`.

    Its parent packages are imported to find it, as Python's import system does.
    """
    roots = import_roots(root, Pyproject.read(CheckoutLayout(root=root).pyproject))
    with importable(roots):
        try:
            spec = importlib.util.find_spec(module)
        except ImportError as missing:
            message = f"the conditions module `{module}` can't be found: {missing}"
            raise ConditionError(message) from missing
    if spec is None or spec.origin is None:
        message = f"the conditions module `{module}` can't be found from {root}"
        raise ConditionError(message)
    return Path(spec.origin)


def declared(root: Path, project: Project) -> list[str] | None:
    """List the names the project's conditions module binds, without running it.

    None where the project declares no conditions module, so every `when` is
    unknown. Each name bound at the module's top level counts; the gate checks
    that it's a `Condition`.
    """
    if project.conditions is None:
        return None
    tree = ast.parse(module_file(root, project.conditions).read_text())

    def bound(statement: ast.stmt) -> list[str]:
        match statement:
            case ast.Assign(targets=targets):
                return [target.id for target in targets if isinstance(target, ast.Name)]
            case ast.AnnAssign(target=ast.Name(id=name)):
                return [name]
            case _:
                return []

    return [name for statement in tree.body for name in bound(statement)]


def loaded(root: Path, project: Project) -> dict[str, Condition]:
    """Import the project's conditions module, and return its conditions by name.

    Empty where the project declares no conditions module.
    """
    if project.conditions is None:
        return {}
    roots = import_roots(root, Pyproject.read(CheckoutLayout(root=root).pyproject))
    with importable(roots):
        module = importlib.import_module(project.conditions)
    return {
        name: value
        for name, value in vars(module).items()
        if isinstance(value, Condition)
    }
