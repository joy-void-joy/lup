"""The pytest plugin a project's gate checks its modules' promises through: each promise of the modules its declaration resolves to, one check each.

pytest finds it by lup's core's entry point (`pytest11`), so a project with the
core installed runs it. The declaration is `lup_project.py` at pytest's root, or
the file `[tool.lup]`'s `declaration` names in its `pyproject.toml`, as lup reads
a repository's, and it's collected where pytest's paths reach it. A project's gate checks the promises of the
modules whose code it holds, not those of lup's it installs, which lup's own
gate checks.

Every other check pytest collects names no promise, and fails, saying so,
unless it's a docstring's example or marked `unpromised(why=…)`; and a class of
promises no module lists fails, since nothing would check it
(`lup/testing/README.md`, *What the gate runs*).
"""

import inspect
import json
import sysconfig
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from pydantic import ValidationError

from lup.declaration.module import Module
from lup.doors.door import served
from lup.doors.parts import Part, Parts
from lup.environment.declaration import load, resolve
from lup.environment.layout import RepositoryLayout
from lup.environment.testing.checking import Check, Exploring
from lup.environment.testing.harness import promises, readers
from lup.errors import LupError
from lup.testing.harness import Broken, Kept
from lup.testing.promise import PromiseDoor
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest._code.code import ExceptionInfo, TerminalRepr

    from lup.declaration.project import Project
    from lup.environment.doors import Entry


def pytest_addoption(parser: pytest.Parser) -> None:
    """Offer an exploring run."""
    parser.addoption(
        "--lup-explore",
        type=int,
        metavar="RUNS",
        default=None,
        help=(
            "Check each promise over RUNS runs of random values, rather than the "
            "gate's repeatable ones, to find what it doesn't; the gate never runs "
            "this."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Name the mark a check that names no promise is kept with."""
    config.addinivalue_line(
        "markers",
        "unpromised(why): a check that can't be said as a law or a scenario, kept, "
        "saying why; send a friction saying what couldn't be said",
    )


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> Declared | None:
    """Collect the declaration's file as its modules' promises."""
    config = parent.config
    root = config.rootpath
    if file_path != RepositoryLayout(root=root, main=root).declaration:
        return None
    # lup: ignore("reportUnknownMemberType", why="pytest leaves untyped the keyword arguments a node's constructor is passed")
    return Declared.from_parent(parent, path=file_path)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Fail a test function, which names no promise, unless it's kept `unpromised(why=…)`, saying why."""
    marker = pyfuncitem.get_closest_marker("unpromised")
    if marker is not None:
        try:
            Unpromised.model_validate(marker.kwargs)
        except ValidationError:
            message = (
                f"`{pyfuncitem.name}` is kept `unpromised` without saying why: "
                "`@pytest.mark.unpromised(why=…)`"
            )
            pytest.fail(message, pytrace=False)
        return None
    message = (
        f"`{pyfuncitem.name}` names no promise: write it as one, a law or a "
        "scenario behind `@lup.promise` (`lup/testing/README.md`). Where it can't "
        "be said as one, keep it with `@pytest.mark.unpromised(why=…)` and send a "
        "friction saying what couldn't be said"
    )
    pytest.fail(message, pytrace=False)


class Unpromised(Model):
    """Why a check is kept though it names no promise: what `unpromised` is given."""

    why: str


def own(code: type, root: Path) -> bool:
    """Say whether the class `code`'s source is the repository's at `root`, rather than installed from elsewhere.

    A class declared in the declaration's own file is the repository's.
    """
    try:
        source = Path(inspect.getfile(code)).resolve()
    except TypeError:
        return True
    installed = [
        Path(sysconfig.get_path(each)).resolve() for each in ("purelib", "platlib")
    ]
    if any(source.is_relative_to(each) for each in installed):
        return False
    return source.is_relative_to(root.resolve())


def subclasses[C](base: type[C]) -> list[type[C]]:
    """Return every class deriving from `base` defined so far, however far below it."""
    return [
        found for each in base.__subclasses__() for found in [each, *subclasses(each)]
    ]


def unlisted(root: Path) -> list[type[Part]]:
    """Return each class of the repository's at `root` holding promises that no module lists in its `parts`, so the gate would never check them."""
    listed = [
        served for module in subclasses(Module) for served in module().held(Parts)
    ]
    return [
        each
        for each in subclasses(Part)
        if own(each, root)
        and each not in listed
        and any(
            isinstance(method.door, PromiseDoor) for method in served(each).values()
        )
    ]


class Declared(pytest.File):
    """A declaration's file, collected as the promises of its modules."""

    @override
    def collect(self) -> Iterator[pytest.Item | pytest.Collector]:
        """Collect each of the repository's own modules' promises, a law with no door to read its state through failing here."""
        project = load(self.path)
        resolved = resolve(project)
        readers(resolved.doors)
        root = self.config.rootpath
        for module in resolved.modules:
            if own(type(module), root):
                # lup: ignore("reportUnknownMemberType", why="pytest leaves untyped the keyword arguments a node's constructor is passed")
                yield Held.from_parent(
                    self, name=module.name, module=module, project=project
                )
        for each in unlisted(root):
            # lup: ignore("reportUnknownMemberType", why="pytest leaves untyped the keyword arguments a node's constructor is passed")
            yield Unlisted.from_parent(self, name=each.__qualname__, unlisted=each)


class Held(pytest.Collector):
    """A module's promises, collected."""

    def __init__(
        self, *, module: Module, project: Project, name: str, parent: pytest.Collector
    ) -> None:
        """Hold `module`, of `project`."""
        super().__init__(name=name, parent=parent)
        self.module = module
        self.project = project

    @override
    def collect(self) -> Iterator[pytest.Item | pytest.Collector]:
        """Collect each promise the module serves, in the order declared."""
        runs = self.config.getoption("lup_explore")
        exploring = (
            Exploring() if runs is None else Exploring(runs=int(runs), seeded=False)
        )
        for entry in promises(self.module):
            # lup: ignore("reportUnknownMemberType", why="pytest leaves untyped the keyword arguments a node's constructor is passed")
            yield Promised.from_parent(
                self,
                name=f"{entry.serves.part.__name__}.{entry.name}",
                entry=entry,
                project=self.project,
                exploring=exploring,
            )


class Unlisted(pytest.Item):
    """A class of promises no module lists, which fails: nothing would check them."""

    def __init__(
        self, *, unlisted: type[Part], name: str, parent: pytest.Collector
    ) -> None:
        """Hold the class no module lists."""
        # lup: ignore("reportUnknownMemberType", why="pytest leaves untyped the keyword arguments a node's constructor is passed")
        super().__init__(name=name, parent=parent)
        self.unlisted = unlisted

    @override
    def runtest(self) -> None:
        """Fail, naming the class and what to do."""
        message = (
            f"`{self.unlisted.__qualname__}` holds promises no module lists in its "
            "`parts`, so nothing checks them: list it in its module's"
        )
        pytest.fail(message, pytrace=False)

    @override
    # lup: ignore("tuple-shape", why="pytest takes where a check is as this tuple: its file, its line and its name")
    def reportinfo(self) -> tuple[Path, int | None, str]:
        """Point at the class."""
        lines, line = inspect.getsourcelines(self.unlisted)
        del lines
        return Path(inspect.getfile(self.unlisted)), line, self.name


class BrokenPromiseError(LupError):
    """A promise the gate checked was broken."""

    def __init__(self, broken: Broken) -> None:
        """Say which promise `broken` broke."""
        super().__init__(f"the promise `{broken.promise}` doesn't hold")
        self.broken = broken


class Promised(pytest.Item):
    """One promise, checked."""

    def __init__(
        self,
        *,
        entry: Entry,
        project: Project,
        exploring: Exploring,
        name: str,
        parent: pytest.Collector,
    ) -> None:
        """Hold the promise behind `entry`, of a module of `project`, to check as `exploring` says."""
        # lup: ignore("reportUnknownMemberType", why="pytest leaves untyped the keyword arguments a node's constructor is passed")
        super().__init__(name=name, parent=parent)
        self.check = Check(entry=entry, project=project)
        self.exploring = exploring

    @override
    def runtest(self) -> None:
        """Check the promise; raise `BrokenPromiseError` where a run broke it."""
        match self.check.checked(self.exploring):
            case Kept():
                return
            case Broken() as broken:
                raise BrokenPromiseError(broken) from broken.error

    @override
    def repr_failure(
        self,
        excinfo: ExceptionInfo[BaseException],
        style: str | None = None,
    ) -> str | TerminalRepr:
        """Say which promise broke, what it promises, the smallest run that broke it, and where."""
        broken = excinfo.value
        if not isinstance(broken, BrokenPromiseError):
            return super().repr_failure(excinfo)
        return said(broken.broken, self.check.entry.method.taken.description)

    @override
    # lup: ignore("tuple-shape", why="pytest takes where a check is as this tuple: its file, its line and its name")
    def reportinfo(self) -> tuple[Path, int | None, str]:
        """Point at the promise's method."""
        function = self.check.entry.method.function
        lines, line = inspect.getsourcelines(function)
        del lines
        return Path(inspect.getfile(function)), line, self.name


def said(broken: Broken, description: str) -> str:
    """Say what a broken promise promised, the smallest run that broke it, and where."""
    drawn = [f"  {json.dumps(each)}" for each in broken.drawn]
    calls = [f"  {each.model_dump_json()}" for each in broken.calls]
    slices = [f"  {broken.calls.index(each) + 1}" for each in broken.slices]
    where = pytest.ExceptionInfo[BaseException].from_exception(broken.error)
    return "\n".join(
        [
            f"The promise `{broken.promise}` doesn't hold: {description}",
            *(["Drawn, the smallest that breaks it:", *drawn] if drawn else []),
            *(["Called, the shortest run that breaks it:", *calls] if calls else []),
            *(
                ["Each slice, by the call it was of, in the order they ran:", *slices]
                if len(calls) > 1
                else []
            ),
            str(where.getrepr(style="short")),
        ]
    )
