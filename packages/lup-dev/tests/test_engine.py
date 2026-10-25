"""The typed engine, run for real on small projects: its rules, reports and lifecycle.

These need the engine built (`uv run packages/lup-dev/checker/build.py`); without it
they fail, saying so. No test reaches the network or waits on a clock: an engine
stops when told, a test that needs another build gives it another bundle, and uv,
which gives each project its environment, runs offline (`offline_uv`).
"""

import importlib.util
import os
import re
import shutil
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.programs import run
from lup_dev import CodeRules, Module, Modules, Rules
from lup_dev import Project as Declaration
from lup_dev.codescan.contract import FileReport, Rule, Source
from lup_dev.codescan.directives import Defer, Ignore, Malformed, Note
from lup_dev.codescan.engine import (
    EngineChecker,
    EngineError,
    EngineParser,
    EngineStatus,
    printed,
)
from lup_dev.declaration.package_managers.uv import Uv as UvRunner
from lup_dev.declaration.resolve import Selected, resolve
from lup_dev.declaration.runner import Plain, RoomNeeds, RoomPlaces, Runner
from lup_dev.layout import Bundle, Layout

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conftest import Uv

    from lup_dev.declaration.requirements import Tools

EVERY = [Selected(module="code-rules", rules=Rules.all(), default=Rules())]
"""Every rule of lup's table, which the rules' own examples are checked against."""
REPOSITORY = Path(__file__).resolve().parents[3]
DOCSTRING = '"""An example."""\n\n'
PYPROJECT = """\
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.14"
include = ["example"]
reportUnusedVariable = "warning"
"""


class Bound:
    """The engine's client asked with one runner, as the judge asks it for a worktree
    by the runner of the declaration it reads."""

    def __init__(self, engine: EngineChecker, runner: Runner) -> None:
        self.engine = engine
        self.runner = runner

    def rules(self, selected: list[Selected] | None = None) -> list[Rule]:
        return self.engine.rules(selected)

    def check(
        self, root: Path, sources: list[Source], selected: list[Selected]
    ) -> list[FileReport]:
        return self.engine.check(root, sources, selected, self.runner)

    def importers(self, root: Path, changed: list[Path]) -> list[FileReport]:
        return self.engine.importers(root, changed, self.runner)

    def status(self, root: Path) -> EngineStatus:
        return self.engine.status(root, self.runner)

    def stop(self, root: Path) -> None:
        self.engine.stop(root, self.runner)


def engine_for(
    runtime: Path,
    state: Path,
    bundle: Bundle | None = None,
    runner: Runner | None = None,
) -> Bound:
    """An engine for tests, through uv unless given another runner."""
    engine = EngineChecker(
        layout=Layout(state=state, runtime=runtime),
        idle=timedelta(minutes=5),
        bundle=bundle or Bundle(),
    )
    return Bound(engine, UvRunner() if runner is None else runner)


class Project:
    """A small project on disk, with its own engine."""

    def __init__(self, root: Path, engine: Bound) -> None:
        self.root = root
        self.engine = engine

    def write(self, name: str, content: str) -> Path:
        path = Path("example") / name
        (self.root / path).write_text(content)
        return path

    def check(
        self, name: str, content: str | None = None, *, on_disk: str | None = None
    ) -> FileReport:
        path = Path("example") / name
        if on_disk is not None:
            (self.root / path).write_text(on_disk)
        [report] = self.engine.check(
            self.root, [Source(path=path, content=content)], EVERY
        )
        return report


@pytest.fixture(scope="module")
def short() -> Iterator[Path]:
    # A socket's path is limited in length, so engines listen in a short directory.
    directory = Path(tempfile.mkdtemp(prefix="lup", dir="/tmp"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


SHARED = [
    "annotated_doc",
    "annotated_types",
    "click",
    "dotenv",
    "lup",
    "packaging",
    "pydantic",
    "pydantic_core",
    "pydantic_settings",
    "rich",
    "shellingham",
    "typer",
    "typing_extensions",
    "typing_inspection",
]
"""What the rules' examples import from the packages the tests run with, and what
those import in turn for their types."""


def linked_or_copied(source: str, destination: str) -> None:
    """Link a file where it can be, as uv installs a package, else copy it."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def shared(site: Path) -> None:
    """Install the packages the examples import in the environment holding `site`.

    The engine reads nothing outside the worktree and its environment, so a
    `.pth` file naming the running environment's packages would be left out:
    each is put inside, as an installer puts it.
    """
    for name in SHARED:
        spec = importlib.util.find_spec(name)
        assert spec is not None, f"{name} isn't installed"
        assert spec.origin is not None, f"{name} has no file"
        origin = Path(spec.origin)
        if spec.submodule_search_locations:
            shutil.copytree(
                origin.parent,
                site / name,
                copy_function=linked_or_copied,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            linked_or_copied(str(origin), str(site / origin.name))


def make_project(
    base: Path, runtime: Path, uv: Uv, bundle: Bundle | None = None
) -> Project:
    root = base / "project"
    (root / "example").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "example" / "__init__.py").write_text('"""Examples."""\n')
    uv.lock(root)
    uv.sync(root)
    [site] = (root / ".venv" / "lib").glob("python*/site-packages")
    shared(site)
    return Project(root, engine_for(runtime, base / "state", bundle))


@pytest.fixture(scope="module")
def project(
    tmp_path_factory: pytest.TempPathFactory, short: Path, offline_uv: Uv
) -> Iterator[Project]:
    made = make_project(tmp_path_factory.mktemp("engine"), short / "run", offline_uv)
    yield made
    made.engine.stop(made.root)


def lup(report: FileReport) -> list[str]:
    return [finding.rule for finding in report.findings if finding.owner == "lup"]


def pyright(report: FileReport) -> list[str]:
    return [f"{f.rule}: {f.message}" for f in report.findings if f.owner == "pyright"]


# The rules' examples are their specification.


def listed() -> list[Rule]:
    return engine_for(Path("/nowhere"), Path("/nowhere")).rules()


RULES = listed()


def test_every_rule_has_an_example_it_flags_with_its_rewrite() -> None:
    assert RULES
    for rule in RULES:
        assert rule.examples.flags, rule.id
        assert all(
            each.code.strip() and each.rewritten.strip() for each in rule.examples.flags
        )


@pytest.mark.parametrize(
    ("rule", "index"),
    [(rule.id, index) for rule in RULES for index in range(len(rule.examples.flags))],
)
def test_a_flagged_example_gets_its_rule_and_no_other(
    project: Project, rule: str, index: int
) -> None:
    [chosen] = [each for each in RULES if each.id == rule]
    name = f"flags_{rule.replace('-', '_')}_{index}.py"
    report = project.check(name, on_disk=DOCSTRING + chosen.examples.flags[index].code)
    found = lup(report)
    assert rule in found
    assert set(found) == {rule}


@pytest.mark.parametrize(
    ("rule", "index"),
    [(rule.id, index) for rule in RULES for index in range(len(rule.examples.flags))],
)
def test_a_rewritten_example_passes_every_rule_ruff_and_pyright(
    project: Project, rule: str, index: int
) -> None:
    [chosen] = [each for each in RULES if each.id == rule]
    name = f"rewritten_{rule.replace('-', '_')}_{index}.py"
    report = project.check(
        name, on_disk=DOCSTRING + chosen.examples.flags[index].rewritten
    )
    assert lup(report) == []
    # A steer may name a library lup doesn't install, whose stubs pyright has.
    typed = [
        f for f in pyright(report) if not f.startswith("reportMissingModuleSource")
    ]
    assert typed == []
    run(
        Path(sys.executable).parent / "ruff",
        "check",
        "--ignore-noqa",
        "--config",
        str(REPOSITORY / "pyproject.toml"),
        str(project.root / "example" / name),
    )


@pytest.mark.parametrize(
    ("rule", "index"),
    [(rule.id, index) for rule in RULES for index in range(len(rule.examples.passes))],
)
def test_a_near_miss_gets_no_finding_from_its_rule(
    project: Project, rule: str, index: int
) -> None:
    [chosen] = [each for each in RULES if each.id == rule]
    name = f"passes_{rule.replace('-', '_')}_{index}.py"
    report = project.check(name, on_disk=DOCSTRING + chosen.examples.passes[index])
    assert rule not in lup(report)


# What a finding holds.


def test_a_finding_is_whole_its_message_saying_what_was_seen_and_the_mistake(
    project: Project,
) -> None:
    report = project.check(
        "whole.py",
        on_disk=DOCSTRING + "def pair() -> tuple[int, int]:\n    return 1, 2\n",
    )
    [finding] = [each for each in report.findings if each.owner == "lup"]
    [rule] = [each for each in RULES if each.id == "tuple-shape"]
    assert finding.rule == "tuple-shape"
    assert finding.message == f"`tuple[int, int]` is a tuple type. {rule.mistake}"
    assert finding.steer == rule.steer
    assert finding.path == Path("example/whole.py")
    assert (finding.span.start.line, finding.span.start.column) == (3, 15)
    assert (finding.span.end.line, finding.span.end.column) == (3, 30)


def test_a_span_counts_columns_in_characters(project: Project) -> None:
    body = (
        "def f(text: str) -> list[str]:\n"
        '    mark = "😀"; return (mark + text).split(",")\n'
    )
    report = project.check("columns.py", on_disk=DOCSTRING + body)
    [finding] = [each for each in report.findings if each.owner == "lup"]
    # `    mark = "😀"; return ` is 23 characters, though 24 units in UTF-16.
    assert (finding.span.start.line, finding.span.start.column) == (4, 24)


def test_a_span_leaves_out_the_parentheses_around_an_expression(
    project: Project,
) -> None:
    content = (
        DOCSTRING
        + "def f(text: str) -> list[str]:\n"
        + '    return (\n        text.split(",")\n    )\n'
    )
    report = project.check("parentheses.py", on_disk=content)
    [finding] = [each for each in report.findings if each.owner == "lup"]
    assert (finding.span.start.line, finding.span.start.column) == (5, 9)


def test_pyright_errors_and_warnings_come_as_findings(project: Project) -> None:
    content = DOCSTRING + "def f() -> int:\n    unused = 1\n    return 'text'\n"
    report = project.check("types.py", on_disk=content)
    rules = [f.rule for f in report.findings if f.owner == "pyright"]
    assert "reportUnusedVariable" in rules  # a warning in this project
    assert "reportReturnType" in rules  # an error
    assert all(f.steer == "" for f in report.findings if f.owner == "pyright")


# Which rules run: each module's selection as the declaration records it, which the
# engine resolves.

SELECTING = DOCSTRING + (
    "import re\n\n\n"
    "def pair() -> tuple[int, int]:\n    return 1, 2\n\n\n"
    'def runtime() -> str:\n    """Name a runtime."""\n    return "codex"\n'
)
"""A module `regex`, `tuple-shape` and `runtime-mention` each flag."""


class Tuples(Module):
    """A module whose own rules start from nothing beneath them."""

    name = "tuples"

    rules: Rules = Rules().add("tuple-shape")


class Runtimes(Module):
    """A module whose own rules are one of lup's."""

    name = "runtimes"

    rules: Rules = Rules.only("runtime-mention")


def ran(project: Project, selected: list[Selected]) -> set[str]:
    """Check `SELECTING` with `selected`, and return the rules that flagged it."""
    path = project.write("selecting.py", SELECTING)
    [report] = project.engine.check(project.root, [Source(path=path)], selected)
    return set(lup(report))


def editing(rules: Rules) -> list[Selected]:
    """Return the selection of a project editing `CodeRules` with `rules`."""
    project = Declaration(modules=Modules.default().edit(CodeRules(rules=rules)))
    return resolve(project).rules


FLAGGED = {"regex", "tuple-shape", "runtime-mention"}


def test_lups_default_runs_every_rule_but_those_it_leaves_out(
    project: Project,
) -> None:
    assert ran(project, resolve(Declaration()).rules) & FLAGGED == {
        "regex",
        "tuple-shape",
    }


def test_a_layer_drops_from_and_adds_to_the_modules_default(project: Project) -> None:
    assert ran(project, editing(Rules().drop("regex"))) & FLAGGED == {"tuple-shape"}
    assert ran(project, editing(Rules().add("runtime-mention"))) & FLAGGED == FLAGGED


def test_default_starts_from_the_modules_own_default(project: Project) -> None:
    dropped = editing(Rules.default().drop("tuple-shape"))
    assert ran(project, dropped) & FLAGGED == {"regex"}


def test_all_starts_from_every_rule_and_only_from_those_named(
    project: Project,
) -> None:
    assert ran(project, editing(Rules.all())) & FLAGGED == FLAGGED
    assert ran(project, editing(Rules.only("regex"))) == {"regex"}
    replaced = editing(Rules.only("regex").replace("regex", "tuple-shape"))
    assert ran(project, replaced) == {"tuple-shape"}


def test_below_starts_from_nothing_beneath_the_modules_own_default(
    project: Project,
) -> None:
    modules = Modules.default().add(Tuples())
    [*_, tuples] = resolve(Declaration(modules=modules)).rules
    assert tuples.rules.start.kind == "below"
    assert ran(project, [tuples]) == {"tuple-shape"}


def test_the_selected_modules_rules_run_together(project: Project) -> None:
    modules = (
        Modules.default()
        .edit(CodeRules(rules=Rules.only("regex")))
        .add(Tuples(), Runtimes())
    )
    selected = resolve(Declaration(modules=modules)).rules
    assert [each.module for each in selected] == ["code-rules", "tuples", "runtimes"]
    assert ran(project, selected) == FLAGGED


def test_no_module_holding_rules_runs_none(project: Project) -> None:
    assert ran(project, []) == set()


@pytest.mark.parametrize(
    ("rules", "refusal"),
    [
        (
            Rules().drop("no-such-rule"),
            (
                "`code-rules`'s rules: `Rules.drop` names `no-such-rule`, which isn't "
                "there; there are `regex`, "
            ),
        ),
        (
            Rules.only("no-such-rule"),
            (
                "`code-rules`'s rules: `Rules.only` names `no-such-rule`, which isn't "
                "one of lup's rules; they are `regex`, "
            ),
        ),
        (
            Rules().add("no-such-rule"),
            "`Rules.add` names `no-such-rule`, which isn't one of lup's rules",
        ),
        (Rules().add("regex"), "`Rules.add` names `regex`, already there"),
        (
            Rules().drop("regex").drop("regex"),
            "`Rules.drop` names `regex`, which isn't there",
        ),
        (
            Rules.only("regex", "regex"),
            "`Rules.only` starts from `regex` more than once",
        ),
        (
            Rules().replace("regex", "tuple-shape"),
            (
                "`Rules.replace` puts `tuple-shape` in place of `regex`, but "
                "`tuple-shape` is already there"
            ),
        ),
    ],
)
def test_a_selection_the_table_cant_resolve_is_refused_naming_what_there_is(
    project: Project, rules: Rules, refusal: str
) -> None:
    with pytest.raises(EngineError, match=re.escape(refusal)):
        ran(project, editing(rules))


def test_a_modules_own_default_cant_start_from_itself(project: Project) -> None:
    circular = Selected(module="mine", rules=Rules.default(), default=Rules.default())
    with pytest.raises(EngineError, match="which is that default itself"):
        ran(project, [circular])


# Listing the rules a selection runs, as the launch and `lup-dev rules list` ask.


def listing(selected: list[Selected]) -> list[str]:
    """Return the ids of the rules the engine lists for `selected`, with no project loaded."""
    engine = engine_for(Path("/nowhere"), Path("/nowhere"))
    return [rule.id for rule in engine.rules(selected)]


TABLE = [rule.id for rule in RULES]
"""Every rule's id, in the table's order."""


def test_the_rules_a_selection_runs_are_listed_in_the_tables_order() -> None:
    assert listing(resolve(Declaration()).rules) == [
        each for each in TABLE if each != "runtime-mention"
    ]
    assert listing(editing(Rules.all())) == TABLE
    assert listing(editing(Rules.only("tuple-shape", "regex"))) == [
        "regex",
        "tuple-shape",
    ]


def test_the_selected_modules_rules_are_listed_together() -> None:
    modules = (
        Modules.default()
        .edit(CodeRules(rules=Rules.only("regex")))
        .add(Tuples(), Runtimes())
    )
    listed = listing(resolve(Declaration(modules=modules)).rules)
    assert listed == [each for each in TABLE if each in FLAGGED]


def test_no_module_holding_rules_lists_none() -> None:
    assert listing([]) == []


def test_a_selection_the_table_cant_resolve_is_refused_when_listed_without_a_stack() -> (
    None
):
    refusal = "`Rules.drop` names `no-such-rule`, which isn't there"
    with pytest.raises(EngineError, match=re.escape(refusal)) as refused:
        listing(editing(Rules().drop("no-such-rule")))
    assert "\n    at " not in str(refused.value)


def test_rules_refuses_an_input_that_isnt_a_selection() -> None:
    with pytest.raises(EngineError, match=r"`rules` reads nothing, or a JSON list"):
        printed("node", Bundle(), "rules", stdin=b'[{"module": "mine"}]')


# Would-be content, and keeping in step with the disk.


def test_would_be_content_is_checked_without_touching_the_disk(
    project: Project,
) -> None:
    clean = DOCSTRING + "def f(text: str) -> list[str]:\n    return text.split()\n"
    flagged = DOCSTRING + 'def f(text: str) -> list[str]:\n    return text.split(",")\n'
    path = project.write("buffer.py", clean)
    assert lup(project.check("buffer.py", flagged)) == ["string-split"]
    assert (project.root / path).read_text() == clean
    # The next request reads the disk again.
    assert lup(project.check("buffer.py")) == []
    # An edit that lands is what the disk then holds.
    assert lup(project.check("buffer.py", on_disk=flagged)) == ["string-split"]


def test_a_file_changed_on_disk_is_read_anew(project: Project) -> None:
    project.write("helper.py", DOCSTRING + "def size() -> int:\n    return 1\n")
    user = (
        DOCSTRING
        + "from example.helper import size\n\n\n"
        + "def doubled() -> int:\n    return size() * 2\n"
    )
    assert pyright(project.check("user.py", on_disk=user)) == []
    project.write("helper.py", DOCSTRING + "def size() -> str:\n    return 'one'\n")
    assert any("reportReturnType" in each for each in pyright(project.check("user.py")))


def test_a_new_module_is_found_by_the_files_that_import_it(project: Project) -> None:
    importer = (
        DOCSTRING
        + "from example.later import value\n\n\ndef get() -> int:\n    return value\n"
    )
    assert any(
        "reportMissingImports" in each
        for each in pyright(project.check("importer.py", on_disk=importer))
    )
    project.write("later.py", DOCSTRING + "value = 1\n")
    assert pyright(project.check("importer.py")) == []


def test_an_edit_judged_then_landed_is_what_the_next_edit_reads(
    project: Project,
) -> None:
    sized = DOCSTRING + "def size() -> int:\n    return 1\n"
    counted = sized + "\n\ndef count() -> int:\n    return 2\n"
    path = project.write("judged.py", sized)
    sizing = DOCSTRING + "from example.judged import size\n\nTOTAL = size()\n"
    assert pyright(project.check("caller.py", on_disk=sizing)) == []
    # As the judge asks before an edit lands: the content after, before and at the
    # session's start, each as would-be content.
    for content in [counted, sized, sized]:
        project.check("judged.py", content)
    (project.root / path).write_text(counted)
    counting = DOCSTRING + "from example.judged import count\n\nTOTAL = count()\n"
    assert pyright(project.check("caller.py", counting)) == []


# The worktree's environment.

WORKSPACE = """\
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.14"
include = ["packages"]
"""
HOLDING = (
    DOCSTRING
    + "class Holding:\n"
    + '    """Held."""\n\n'
    + "    def reach(self) -> bool:\n"
    + '        """Reach."""\n'
    + "        return True\n"
)
RELEASING = (
    HOLDING
    + "\n    def release(self) -> bool:\n"
    + '        """Release."""\n'
    + "        return False\n"
)
CALLER = (
    DOCSTRING
    + "from pkg.held import Holding\n\n\n"
    + "def use(held: Holding) -> bool:\n"
    + '    """Use."""\n'
    + "    return held.release()\n"
)


def workspace(root: Path, held: str) -> Path:
    """A workspace laid out like lup's, its package under `packages/pkg/src`."""
    source = root / "packages" / "pkg" / "src"
    (source / "pkg").mkdir(parents=True)
    (root / "pyproject.toml").write_text(WORKSPACE)
    (source / "pkg" / "__init__.py").write_text('"""A package."""\n')
    (source / "pkg" / "py.typed").write_text("")
    (source / "pkg" / "held.py").write_text(held)
    return source


UV_WORKSPACE = WORKSPACE + '\n[tool.uv.workspace]\nmembers = ["packages/*"]\n'
# uv builds with its own backend when it's `uv_build`, so the member installs offline.
MEMBER = """\
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.14"

[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
"""
CALLING = Source(path=Path("packages/pkg/src/pkg/caller.py"), content=CALLER)


def environment(at: Path, source: Path) -> Path:
    """Make a virtual environment with `source` installed editable, as uv does."""
    run(sys.executable, "-m", "venv", "--without-pip", str(at))
    [site] = (at / "lib").glob("python*/site-packages")
    (site / "_pkg.pth").write_text(str(source))
    return at / "bin"


def in_session(other: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the session in another checkout's environment, which a hook inherits.

    There the package lacks the method the worktree adds.
    """
    session = environment(other / ".venv", workspace(other, HOLDING))
    monkeypatch.setenv("PATH", f"{session}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VIRTUAL_ENV", str(session.parent))


def member(package: Path) -> None:
    """Make `package` a member of its uv workspace."""
    (package / "pyproject.toml").write_text(MEMBER.format(name=package.name))


def uv_workspace(root: Path, held: str, uv: Uv) -> None:
    """`workspace`, as a uv workspace with its lock and no environment yet."""
    workspace(root, held)
    (root / "pyproject.toml").write_text(UV_WORKSPACE)
    member(root / "packages" / "pkg")
    uv.lock(root)


def test_the_engine_reads_the_environment_uv_makes_in_the_worktree_never_the_sessions(
    tmp_path: Path, short: Path, offline_uv: Uv, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_session(tmp_path / "dev", monkeypatch)
    root = tmp_path / "branch"
    uv_workspace(root, RELEASING, offline_uv)
    offline_uv.sync(root)
    engine = engine_for(short / "made", tmp_path / "state")
    try:
        [report] = engine.check(root, [CALLING], EVERY)
        assert pyright(report) == []
    finally:
        engine.stop(root)


def test_a_missing_environment_is_none_never_made_nor_borrowed(
    tmp_path: Path, short: Path, offline_uv: Uv, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_session(tmp_path / "dev", monkeypatch)
    root = tmp_path / "branch"
    uv_workspace(root, RELEASING, offline_uv)
    engine = engine_for(short / "missing", tmp_path / "state")
    try:
        [report] = engine.check(root, [CALLING], EVERY)
        # pyright finds the worktree's own `pkg` beside the file importing it, not
        # the session's, which lacks the method.
        assert pyright(report) == []
        assert not (root / ".venv").exists()
    finally:
        engine.stop(root)


EXTRA = Source(
    path=Path("packages/pkg/src/pkg/using.py"),
    content=DOCSTRING + "from extra import EXTRA\n\nVALUE = EXTRA\n",
)
"""A module importing a package its environment alone has."""


def test_a_package_installed_under_a_running_engine_is_read_at_the_next_check(
    tmp_path: Path, short: Path
) -> None:
    root = tmp_path / "branch"
    environment(root / ".venv", workspace(root, RELEASING))
    engine = engine_for(short / "installed", tmp_path / "state")
    try:
        engine.check(root, [CALLING], EVERY)
        # A package arrives installed editable, as uv installs one: a `.pth` file
        # naming its source.
        extra = root / "packages" / "extra" / "src"
        (extra / "extra").mkdir(parents=True)
        (extra / "extra" / "__init__.py").write_text(DOCSTRING + "EXTRA = 1\n")
        (extra / "extra" / "py.typed").write_text("")
        [site] = (root / ".venv" / "lib").glob("python*/site-packages")
        (site / "_extra.pth").write_text(str(extra))
        [report] = engine.check(root, [EXTRA], EVERY)
        assert pyright(report) == []
    finally:
        engine.stop(root)


def says_it_ran(program: Path, ran: Path) -> None:
    """Make `program` a script noting each run in `ran`."""
    program.unlink(missing_ok=True)
    program.write_text(f"#!/bin/sh\necho {program.name} >> {ran}\nexit 1\n")
    program.chmod(0o755)


def test_the_engine_runs_nothing_of_the_environments_whatever_it_finds_there(
    tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = tmp_path / "ran"
    root = tmp_path / "branch"
    environment(root / ".venv", workspace(root, RELEASING))
    # Its interpreter notes each run, and so does a `.pth` file's `import` line,
    # which Python runs at its start.
    for each in (root / ".venv" / "bin").glob("python*"):
        says_it_ran(each, ran)
    [site] = (root / ".venv" / "lib").glob("python*/site-packages")
    (site / "_run.pth").write_text(f"import os; os.system('echo pth >> {ran}')\n")
    # Another environment has no `site-packages`, where pyright otherwise asks the
    # Python on the `PATH` for its search path; that Python notes its runs too.
    bare = tmp_path / "bare"
    environment(bare / ".venv", workspace(bare, RELEASING))
    shutil.rmtree(bare / ".venv" / "lib")
    path = tmp_path / "path"
    path.mkdir()
    for name in ["python", "python3"]:
        says_it_ran(path / name, ran)
    monkeypatch.setenv("PATH", f"{path}{os.pathsep}{os.environ['PATH']}")
    engine = engine_for(short / "nothing", tmp_path / "state")
    try:
        [report] = engine.check(root, [CALLING], EVERY)
        assert pyright(report) == []
        [report] = engine.check(bare, [CALLING], EVERY)
        assert pyright(report) == []
    finally:
        engine.stop(root)
        engine.stop(bare)
    assert not ran.exists()


VERSIONED = """\
[tool.pyright]
typeCheckingMode = "strict"
include = ["packages"]
"""
OVERRIDING = Source(
    path=Path("packages/pkg/src/pkg/overriding.py"),
    content=DOCSTRING + "from typing import override\n\nUSED = override\n",
)


@pytest.mark.parametrize("key", ["version_info", "version"])
def test_the_python_is_the_environments_where_the_configuration_names_none(
    tmp_path: Path, short: Path, key: str
) -> None:
    root = tmp_path / "branch"
    environment(root / ".venv", workspace(root, RELEASING))
    (root / "pyproject.toml").write_text(VERSIONED)
    configuration = root / ".venv" / "pyvenv.cfg"
    recorded = configuration.read_text()
    # uv and virtualenv record `version_info`; `python -m venv`, `version`.
    configuration.write_text(f"home = /usr/bin\n{key} = 3.11.9\n")
    engine = engine_for(short / f"versioned-{key}", tmp_path / "state")
    try:
        # `typing.override` is Python 3.12's.
        [report] = engine.check(root, [OVERRIDING], EVERY)
        assert any(
            '"override" is unknown import symbol' in each for each in pyright(report)
        )
        # The environment made again on another Python is another program.
        configuration.write_text(recorded)
        [report] = engine.check(root, [OVERRIDING], EVERY)
        assert pyright(report) == []
    finally:
        engine.stop(root)


SECRET = DOCSTRING + 'TOKEN = "s3cret"\nHOST = 1\n'
LEAKING = Source(
    path=Path("packages/pkg/src/pkg/leaking.py"),
    content=(
        DOCSTRING
        + "from listed import TOKEN\n"
        + "from linked import TOKEN as LINKED\n"
        + "from linkedpkg import HOST\n"
        + "from through64 import TOKEN as THROUGH\n"
        + "from pkg.planted import TOKEN as PLANTED\n"
        + "from pkg.held import Holding\n\n"
        + "WRONG: int = TOKEN\n"
    ),
)


def test_the_engine_reads_nothing_the_worktree_or_its_environment_links_to_elsewhere(
    tmp_path: Path, short: Path
) -> None:
    host = tmp_path / "host"
    (host / "linkedpkg").mkdir(parents=True)
    for name in ["listed.py", "secret.py", "linkedpkg/__init__.py"]:
        (host / name).write_text(SECRET)
    (host / "lib" / "python3.14" / "site-packages").mkdir(parents=True)
    (host / "lib" / "python3.14" / "site-packages" / "through64.py").write_text(SECRET)
    root = tmp_path / "branch"
    source = workspace(root, RELEASING)
    environment(root / ".venv", source)
    [site] = (root / ".venv" / "lib").glob("python*/site-packages")
    # A `.pth` line naming a directory elsewhere, a module and a package linked
    # there, and `lib64` linked to another library.
    (site / "_host.pth").write_text(str(host))
    (site / "linked.py").symlink_to(host / "secret.py")
    (site / "linkedpkg").symlink_to(host / "linkedpkg", target_is_directory=True)
    (root / ".venv" / "lib64").unlink(missing_ok=True)
    (root / ".venv" / "lib64").symlink_to(host / "lib", target_is_directory=True)
    # And a module of the worktree's own linked there.
    (source / "pkg" / "planted.py").symlink_to(host / "secret.py")
    engine = engine_for(short / "linked", tmp_path / "state")
    try:
        [report] = engine.check(root, [LEAKING], EVERY)
        found = pyright(report)
        for module in ["listed", "linked", "linkedpkg", "through64", "pkg.planted"]:
            assert f'Import "{module}" could not be resolved' in " ".join(found)
        assert not any("s3cret" in each for each in found)
        with pytest.raises(EngineError, match="resolves outside the worktree"):
            engine.check(
                root, [Source(path=Path("packages/pkg/src/pkg/planted.py"))], EVERY
            )
    finally:
        engine.stop(root)


def test_the_engines_parse_leaves_out_a_file_linking_out_of_the_worktree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "branch"
    root.mkdir()
    noted = DOCSTRING + '# lup: note("s3cret")\nVALUE = 1\n'
    (tmp_path / "host.py").write_text(noted)
    (root / "own.py").write_text(noted)
    (root / "linked.py").symlink_to(tmp_path / "host.py")
    sources = [Source(path=Path("linked.py")), Source(path=Path("own.py"))]
    linked, own = EngineParser().parsed(root, sources)
    assert linked == FileReport(path=Path("linked.py"))
    assert [type(each) for each in own.directives] == [Note]


# Another runner.


def test_with_plain_the_engine_reads_no_environment_and_runs_no_python(
    tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = tmp_path / "ran"
    root = tmp_path / "plain"
    workspace(root, RELEASING)
    # The `PATH`'s Python, which notes its runs, has `extra` installed.
    extra = tmp_path / "extra" / "src"
    (extra / "extra").mkdir(parents=True)
    (extra / "extra" / "__init__.py").write_text(DOCSTRING + "EXTRA = 1\n")
    found = environment(tmp_path / "environment", extra)
    for each in found.glob("python*"):
        says_it_ran(each, ran)
    monkeypatch.setenv("PATH", f"{found}{os.pathsep}{os.environ['PATH']}")
    engine = engine_for(short / "plain", tmp_path / "state", runner=Plain())
    try:
        [report] = engine.check(root, [EXTRA], EVERY)
        assert 'reportMissingImports: Import "extra" could not be resolved' in pyright(
            report
        )
    finally:
        engine.stop(root)
    assert not ran.exists()


class Chosen(Runner):
    """The environment at `directory`, which the worktree's `choice` file decides."""

    directory: Path

    @override
    def command(self, tool: list[str]) -> list[str]:
        return tool

    @override
    def judging(self, tool: list[str]) -> list[str]:
        return tool

    @override
    def environment(self) -> list[str]:
        return ["choice"]

    @override
    def venv(self) -> Path | None:
        return self.directory

    @override
    def room(self, root: Path, tools: Tools, places: RoomPlaces) -> RoomNeeds:
        return RoomNeeds()


def test_the_engine_reads_the_environment_the_runner_names_and_reads_it_anew_when_its_files_change(
    tmp_path: Path, short: Path
) -> None:
    root = tmp_path / "chosen"
    releasing = workspace(root, RELEASING)
    holding = workspace(root / "old", HOLDING)
    # An environment outside the worktree, named by its absolute path.
    elsewhere = tmp_path / "environments" / "chosen"
    environment(elsewhere, releasing)
    (root / "choice").write_text("releasing")
    engine = engine_for(
        short / "chosen", tmp_path / "state", runner=Chosen(directory=elsewhere)
    )
    try:
        [report] = engine.check(root, [CALLING], EVERY)
        assert pyright(report) == []
        # Its editable install moved elsewhere, a change the import search path's
        # directories don't show; the runner's file changing does.
        [site] = (elsewhere / "lib").glob("python*/site-packages")
        (site / "_pkg.pth").write_text(str(holding))
        (root / "choice").write_text("holding")
        [report] = engine.check(root, [CALLING], EVERY)
        assert any("release" in each for each in pyright(report))
    finally:
        engine.stop(root)


# Importers.


def test_importers_are_rechecked_for_type_errors(project: Project) -> None:
    project.write("base.py", DOCSTRING + "def count() -> int:\n    return 1\n")
    project.write(
        "middle.py",
        DOCSTRING
        + "from example.base import count\n\n\n"
        + "def twice() -> int:\n    return count() * 2\n",
    )
    project.write(
        "top.py",
        DOCSTRING
        + "from example.middle import twice\n\n\n"
        + "def thrice() -> int:\n    return twice() + 1\n",
    )
    project.check("top.py")
    project.write("base.py", DOCSTRING + "def count() -> str:\n    return 'one'\n")
    reports = project.engine.importers(project.root, [Path("example/base.py")])
    by_path = {report.path: report for report in reports}
    assert Path("example/middle.py") in by_path
    assert Path("example/top.py") in by_path
    assert Path("example/base.py") not in by_path
    assert any(
        "reportOperatorIssue" in each or "reportReturnType" in each
        for each in pyright(by_path[Path("example/middle.py")])
    )
    assert all(f.owner == "pyright" for report in reports for f in report.findings)


# Directives.


def directives(project: Project, name: str, body: str) -> list[object]:
    return list(project.check(name, on_disk=DOCSTRING + body).directives)


def test_an_ignore_on_a_line_of_code_keeps_that_line(project: Project) -> None:
    body = (
        "def f(text: str) -> list[str]:\n"
        '    return text.split(",")  # lup: ignore("string-split", why="a format")\n'
    )
    [ignore] = directives(project, "trailing.py", body)
    assert ignore == Ignore(line=4, covers=4, rule="string-split", why="a format")


def test_stacked_ignores_alone_keep_the_next_line_of_code(project: Project) -> None:
    body = (
        "def f(text: str) -> tuple[str, str]:\n"
        '    # lup: ignore("string-split", why="a fixed format")\n'
        '    # lup: ignore("tuple-shape", why="the caller unpacks it")\n'
        '    head, _, tail = text.partition(":")\n'
        "    return head, tail\n"
    )
    found = directives(project, "stacked.py", body)
    assert [(each.line, each.covers) for each in found if isinstance(each, Ignore)] == [
        (4, 6),
        (5, 6),
    ]


def test_an_ignore_carries_the_issue_it_waits_on(project: Project) -> None:
    body = (
        "def f(text: str) -> list[str]:\n"
        '    return text.split(",")  # lup: ignore("string-split", why="a format", '
        "issue=12)\n"
        '    # lup: ignore("tuple-shape", issue="owner/repo#7", why="the caller")\n'
        "    return []\n"
    )
    assert directives(project, "waiting.py", body) == [
        Ignore(line=4, covers=4, rule="string-split", why="a format", issue=12),
        Ignore(
            line=5, covers=6, rule="tuple-shape", why="the caller", issue="owner/repo#7"
        ),
    ]


def test_a_defer_carries_its_issue_or_condition(project: Project) -> None:
    body = (
        'x = 1  # lup: defer(issue=12, why="retry on reset")\n'
        "y = 2  # lup: "
        'defer(issue="owner/repo#7", when=sdk_ready, why="read the ttl")\n'
    )
    assert directives(project, "defer.py", body) == [
        Defer(line=3, why="retry on reset", issue=12),
        Defer(line=4, why="read the ttl", issue="owner/repo#7", when="sdk_ready"),
    ]


def test_a_comment_that_isnt_a_call_is_a_note(project: Project) -> None:
    body = "x = 1  # lup: the retry count matches the provider's documented limit\n"
    assert directives(project, "note.py", body) == [
        Note(line=3, text="the retry count matches the provider's documented limit")
    ]


def test_a_note_call_says_what_free_text_says(project: Project) -> None:
    body = (
        'x = 1  # lup: note("this looks wrong")\n'
        "y = 2  # lup: this looks wrong\n"
        "z = 3  # lup: note('this ' \"looks wrong\")\n"
    )
    assert directives(project, "note_call.py", body) == [
        Note(line=3, text="this looks wrong"),
        Note(line=4, text="this looks wrong"),
        Note(line=5, text="this looks wrong"),
    ]


@pytest.mark.parametrize(
    "written",
    [
        "sorted(x) here, why not heapq?",
        "retry(3) is the provider's limit",
        'todo("tighten this")',
        'ignor("string-split", why="a typo leaves the finding reported")',
        "ignore this, the provider fixes it",
        "defer to the caller's timeout",
        "ignore",
        "note()",
        "note(42)",
        'note("a", "b")',
        "note(this is unquoted)",
    ],
)
def test_any_other_comment_or_call_is_a_note_as_written(
    project: Project, written: str
) -> None:
    [found] = directives(project, "other.py", f"x = 1  # lup: {written}\n")
    assert found == Note(line=3, text=written)


@pytest.mark.parametrize(
    "written",
    [
        'ignore("string-split")',
        "ignore(why='no rule')",
        'ignore("a", "b", why="two")',
        'ignore("a", why="x", extra=1)',
        'ignore("a", why="x", when=ready)',
        'ignore("a", why="x", why="y")',
        'ignore("a", why="x", issue=1.5)',
        'defer(why="nothing brings it back")',
        "defer(issue=1)",
        "defer()",
        'defer("12", why="positional")',
        'defer(issue=12, when="quoted", why="x")',
        'todo(issue=12, why="an unknown call passing an issue")',
        'defr(when=ready, why="a typo passing a condition")',
        'ignore("x", why="y"',
        'defer(issue=12, why="y") and more',
    ],
)
def test_a_directive_the_grammar_refuses_is_malformed(
    project: Project, written: str
) -> None:
    [found] = directives(project, "malformed.py", f"x = 1  # lup: {written}\n")
    assert isinstance(found, Malformed)
    assert found.text == written
    assert found.problem


def test_other_comments_are_no_directives(project: Project) -> None:
    body = "x = 1  # an ordinary comment\ny = 2  # lupine: not lup\n"
    assert directives(project, "plain.py", body) == []


# The public surface and the imports.


def test_a_modules_surface_holds_its_public_classes_functions_and_methods(
    project: Project,
) -> None:
    body = (
        "class Outer:\n"
        '    """A class."""\n\n'
        "    class Inner:\n"
        '        """A nested class."""\n\n'
        "    def __init__(self) -> None:\n"
        '        """A dunder counts."""\n\n'
        "    async def method(self, first: int, /, *rest: int) -> str | None:\n"
        '        """A method."""\n'
        "        return None\n\n"
        "    def _hidden(self) -> None:\n"
        '        """Private: not listed."""\n\n\n'
        "class _Private:\n"
        '    """Private: not listed, nor its members."""\n\n'
        "    def method(self) -> None:\n"
        '        """Not listed."""\n\n\n'
        "def function(value: list[int]) -> int:\n"
        '    """A function."""\n\n'
        "    def nested() -> int:\n"
        "        return len(value)\n\n"
        "    return nested()\n\n\n"
        "def _helper() -> None:\n"
        '    """Private: not listed."""\n'
    )
    surface = project.check("surface.py", on_disk=DOCSTRING + body).surface
    assert surface.exported == []
    assert surface.classes == ["Outer", "Outer.Inner"]
    assert surface.functions == ["Outer.__init__", "Outer.method", "function"]
    start = DOCSTRING.count("\n")
    assert [(each.kind, each.name, each.line - start) for each in surface.places] == [
        ("class", "Outer", 1),
        ("class", "Outer.Inner", 4),
        ("function", "Outer.__init__", 7),
        ("function", "Outer.method", 10),
        ("function", "function", 25),
    ]


def test_a_name_defined_in_each_branch_is_listed_once_where_it_is_first(
    project: Project,
) -> None:
    body = (
        "import sys\n\n"
        "if sys.platform == 'win32':\n"
        "    def chosen() -> int:\n"
        "        return 1\n"
        "else:\n"
        "    def chosen() -> int:\n"
        "        return 2\n"
    )
    surface = project.check("branches.py", on_disk=DOCSTRING + body).surface
    assert surface.functions == ["chosen"]
    assert surface.place("function", "chosen") == DOCSTRING.count("\n") + 4


def test_a_package_root_exports_its_names_or_its_all(project: Project) -> None:
    package = project.root / "example" / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        DOCSTRING + "from example.pkg.inner import thing as thing\n\nVERSION = 1\n"
    )
    (package / "inner.py").write_text(DOCSTRING + "thing = 1\n")
    [report] = project.engine.check(
        project.root, [Source(path=Path("example/pkg/__init__.py"))], EVERY
    )
    assert report.surface.exported == ["VERSION", "thing"]
    start = DOCSTRING.count("\n")
    assert [(each.name, each.line - start) for each in report.surface.places] == [
        ("VERSION", 3),
        ("thing", 1),
    ]
    declared = (
        DOCSTRING + "from example.pkg.inner import thing\n\n__all__ = ['thing']\n"
    )
    [report] = project.engine.check(
        project.root,
        [Source(path=Path("example/pkg/__init__.py"), content=declared)],
        EVERY,
    )
    assert report.surface.exported == ["thing"]
    assert report.surface.place("export", "thing") == declared.count("\n")


# Read from the parse alone.

SURFACED = (
    "from collections.abc import Sequence\n\n"
    "class Outer:\n"
    '    """A class."""\n\n'
    "    def method(self, first: int, /, *rest: Sequence[ str ], flag: bool) -> None:\n"
    '        """A method."""\n'
    '        return None  # lup: ignore("tuple-shape", why="a pair")\n\n\n'
    "def function(value: 'list[int]') -> int:  # lup: the count\n"
    '    """A function."""\n'
    "    return len(value)\n"
)


def test_a_file_read_from_its_parse_alone_has_what_a_check_finds_but_types(
    project: Project,
) -> None:
    content = DOCSTRING + SURFACED
    checked = project.check("parsed.py", content)
    [parsed] = EngineParser().parsed(
        project.root, [Source(path=Path("example/parsed.py"), content=content)]
    )
    assert parsed.path == Path("example/parsed.py")
    assert parsed.directives == checked.directives
    assert parsed.surface == checked.surface
    assert parsed.surface.classes == ["Outer"]
    assert parsed.surface.functions == ["Outer.method", "function"]
    assert (parsed.findings, parsed.imports) == ([], [])


def test_a_package_root_read_from_its_parse_alone_exports_what_it_binds_or_its_all(
    tmp_path: Path,
) -> None:
    bound = (
        "import json\nimport os.path\nfrom .inner import thing as alias\n"
        "from . import sibling\n\nVERSION = 1\n\nif VERSION:\n    LATER = 2\n"
        "for each in []:\n    pass\n"
    )
    declared = "from .inner import thing, other\n\n__all__ = ['thing']\n"
    root = Path("pkg/__init__.py")
    [binding, listing, module] = EngineParser().parsed(
        tmp_path,
        [
            Source(path=root, content=bound),
            Source(path=root, content=declared),
            Source(path=Path("pkg/module.py"), content=declared),
        ],
    )
    # A package root's relative import binds its submodule too, as pyright has it.
    assert binding.surface.exported == [
        "LATER",
        "VERSION",
        "alias",
        "each",
        "inner",
        "json",
        "os",
        "sibling",
    ]
    assert binding.surface.place("export", "alias") == 3
    assert listing.surface.exported == ["thing"]
    assert listing.surface.place("export", "thing") == 3
    assert module.surface.exported == []


def test_the_parse_command_refuses_what_isnt_a_list_of_files() -> None:
    with pytest.raises(EngineError, match="JSON list"):
        printed("node", Bundle(), "parse", stdin=b'{"path": "a.py"}')


def test_imports_are_named_in_full_relative_ones_included(project: Project) -> None:
    body = (
        "import json\nimport os.path\nfrom collections import abc\n"
        "from . import helper\nfrom .helper import size\n"
    )
    project.write("helper.py", DOCSTRING + "def size() -> int:\n    return 1\n")
    report = project.check("imports.py", on_disk=DOCSTRING + body)
    assert report.imports == ["collections.abc", "example.helper", "json", "os.path"]


# Starting, stopping and the build.


def test_the_engine_starts_when_asked_and_stops_when_told(project: Project) -> None:
    project.write("status.py", DOCSTRING)
    first = project.engine.status(project.root)
    assert first.idle_seconds == 300
    assert first.root == str(project.root)
    project.engine.stop(project.root)
    second = project.engine.status(project.root)
    assert second.pid != first.pid


def test_hooks_asking_at_once_start_one_engine(
    tmp_path: Path, short: Path, offline_uv: Uv
) -> None:
    fresh = make_project(tmp_path, short / "together", offline_uv)
    fresh.write("one.py", DOCSTRING)
    pids: list[int] = []

    def ask() -> None:
        pids.append(fresh.engine.status(fresh.root).pid)

    threads = [threading.Thread(target=ask) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert len(pids) == 4
        assert len(set(pids)) == 1
    finally:
        fresh.engine.stop(fresh.root)


def test_an_engine_from_another_build_is_replaced(
    tmp_path: Path, short: Path, offline_uv: Uv
) -> None:
    built = Bundle()
    copy = Bundle(directory=tmp_path / "bundle")
    copy.directory.mkdir()
    shutil.copy2(built.script, copy.script)
    copy.stubs.symlink_to(built.stubs, target_is_directory=True)
    fresh = make_project(tmp_path, short / "rebuilt", offline_uv, copy)
    fresh.write("one.py", DOCSTRING)
    try:
        before = fresh.engine.status(fresh.root)
        # Another build: the same script, written again.
        copy.script.write_bytes(copy.script.read_bytes() + b"\n")
        after = fresh.engine.status(fresh.root)
        assert after.pid != before.pid
    finally:
        fresh.engine.stop(fresh.root)


def test_an_engine_started_with_another_runner_is_replaced(
    tmp_path: Path, short: Path, offline_uv: Uv, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = make_project(tmp_path, short / "rerun", offline_uv)
    fresh.write("one.py", DOCSTRING)
    monkeypatch.setenv(
        "PATH", f"{fresh.root / '.venv' / 'bin'}{os.pathsep}{os.environ['PATH']}"
    )
    plain = Bound(fresh.engine.engine, Plain())
    try:
        before = fresh.engine.status(fresh.root)
        after = plain.status(fresh.root)
        assert after.pid != before.pid
        assert plain.status(fresh.root).pid == after.pid
    finally:
        plain.stop(fresh.root)


def test_without_a_built_engine_the_error_says_how_to_build_it(tmp_path: Path) -> None:
    missing = engine_for(tmp_path, tmp_path, Bundle(directory=tmp_path / "nothing"))
    with pytest.raises(EngineError, match=r"uv run packages/lup-dev/checker/build\.py"):
        missing.rules()
