"""What loading a worktree's declaration imports, weighed: the gate's `declaration` step, run as `python -m lup.environment.weighing` from a worktree's root.

A declaration is loaded at every hook, so whatever loading and resolving it
imports is paid at each: it imports nothing beyond the standard library, lup and
what lup depends on, and the project's own code. Anything else, a package the
project's code imports at the top of a file its declaration reaches, is heavy,
named with the chain of imports from the declaration to it, so it's imported
where it's used instead (`lazy from`). A module counts by where its file is,
never by its name: a heavy one is among the files of an installed distribution
lup's core doesn't need, its extras left out, and outside the worktree
(`lup/gate/README.md`, *Steps*).
"""

import inspect
import sys
from importlib.abc import MetaPathFinder
from importlib.metadata import PackageNotFoundError, distribution, distributions
from pathlib import Path
from typing import TYPE_CHECKING, override

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from lup.declaration.layout import MachineLayout, RepositoryLayout
from lup.environment.declaration import read, resolve
from lup.environment.settings import LupSettings
from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from collections.abc import Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType

CORE = "lup-core"
"""The distribution of lup's core, whose own requirements are what a declaration may import."""


class Heavy(Model):
    """A distribution loading the declaration imports beyond what it may: its name, and the chain of imports from the declaration to its first module imported."""

    distribution: str
    chain: list[str]


class Tracing(MutableModel, MetaPathFinder):
    """What imports each module loading a declaration imports for the first time: the module whose code ran the import, none where nothing's does."""

    importers: dict[str, str | None] = {}

    @override
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        """Note who imports `fullname`, the first time it's looked for, and find nothing, leaving it to the finders after this one."""
        del path, target
        if fullname not in self.importers:
            self.importers[fullname] = importer()
        return None

    def chain(self, module: str) -> list[str]:
        """Return the imports from the first module whose importer isn't known to `module`, each module by its name, in the order they ran."""
        named: list[str] = [module]
        while (found := self.importers.get(named[-1])) is not None and (
            found not in named
        ):
            named.append(found)
        return named[::-1]


def importer() -> str | None:
    """Return the name of the module whose code is importing, past the import system's own frames and this module's; none where there's none."""
    frame = inspect.currentframe()
    while frame is not None:
        # lup: ignore("dict-literal-key", why="a frame's globals are its module's namespace, which Python names under `__name__`")
        name = frame.f_globals.get("__name__")
        if (
            isinstance(name, str)
            and name != __name__
            and not name.startswith(("importlib", "_frozen_importlib"))
        ):
            return name
        frame = frame.f_back
    return None


def needed(
    name: str, by: str | None = None, known: dict[str, str | None] | None = None
) -> dict[str, str | None]:
    """Return the distribution called `name` and every distribution it needs, its extras and those of what it needs left out, each by its canonical name, with the distribution that needs it, none for `name`'s own; none where it isn't installed."""
    found = {} if known is None else known
    each = canonicalize_name(name)
    if each in found:
        return found
    try:
        installed = distribution(each)
    except PackageNotFoundError:
        return found
    found[each] = by
    for requirement in map(Requirement, installed.requires or []):
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            needed(requirement.name, each, found)
    return found


def owners() -> dict[Path, str]:
    """Return each installed distribution's files, resolved, by the canonical name of the distribution they're of."""
    return {
        Path(str(each.locate_file(file))).resolve(): canonicalize_name(each.name)
        for each in distributions()
        for file in each.files or []
    }


def weighed(root: Path, tracing: Tracing) -> list[Heavy]:
    """Return each installed distribution, beyond those lup's core needs, whose modules loading the declaration imported, as `tracing` noted them, with the chain to its first: a module of the standard library, which no distribution installs, or of the worktree at `root`, a member of its workspace among them, is never one."""
    light = needed(CORE)
    files = owners()

    def owner(name: str) -> str | None:
        where = getattr(sys.modules.get(name), "__file__", None)
        if not isinstance(where, str):
            return None
        path = Path(where).resolve()
        found = files.get(path)
        if found is None or found in light or path.is_relative_to(root):
            return None
        return found

    candidates = [
        Heavy(distribution=found, chain=tracing.chain(name))
        for name in tracing.importers
        if (found := owner(name)) is not None
    ]
    return [
        each
        for index, each in enumerate(candidates)
        if all(other.distribution != each.distribution for other in candidates[:index])
    ]


def main() -> None:
    """Load and resolve the declaration of the worktree this runs in, noting every module it imports, and end failed, naming each heavy distribution and the chain to it, where one is imported."""
    layout = RepositoryLayout.found(Path.cwd())
    machine = MachineLayout(configuration=LupSettings().xdg_config_home)
    tracing = Tracing()
    sys.meta_path.insert(0, tracing)
    try:
        resolve(read(layout, machine).project)
    finally:
        sys.meta_path.remove(tracing)
    heavy = weighed(layout.root.resolve(), tracing)
    for each in heavy:
        sys.stdout.write(f"{each.distribution}: {' → '.join(each.chain)}\n")
    if heavy:
        sys.stdout.write(
            "Loading the declaration imports these, beyond the standard library, "
            "lup and what it needs, and the project's own code: it's loaded at "
            "every hook, so import each where it's used (`lazy from`).\n"
        )
        raise SystemExit(1)
    sys.stdout.write(
        f"Loading the declaration imports {len(tracing.importers)} modules, none "
        "heavy.\n"
    )


if __name__ == "__main__":
    main()
