"""The typed engine, run for real on small projects: its rules, reports and lifecycle.

These need the engine built (`uv run packages/lup-dev/checker/build.py`); without it
they fail, saying so. No test reaches the network or waits on a clock: an engine
stops when told, and a test that needs another build gives it another bundle.
"""

import os
import shutil
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sh

from lup_dev.codescan.contract import FileReport, Rule, Source
from lup_dev.codescan.directives import Defer, Ignore, Malformed, Note
from lup_dev.codescan.engine import EngineChecker, EngineError
from lup_dev.layout import Bundle, Layout

if TYPE_CHECKING:
    from collections.abc import Iterator

REPOSITORY = Path(__file__).resolve().parents[3]
DOCSTRING = '"""An example."""\n\n'
PYPROJECT = """\
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.14"
include = ["example"]
reportUnusedVariable = "warning"
"""


def engine_for(
    runtime: Path, state: Path, bundle: Bundle | None = None
) -> EngineChecker:
    return EngineChecker(
        layout=Layout(state=state, runtime=runtime),
        idle=timedelta(minutes=5),
        bundle=bundle or Bundle(),
    )


class Project:
    """A small project on disk, with its own engine."""

    def __init__(self, root: Path, engine: EngineChecker) -> None:
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
        [report] = self.engine.check(self.root, [Source(path=path, content=content)])
        return report


@pytest.fixture(scope="module")
def short() -> Iterator[Path]:
    # A socket's path is limited in length, so engines listen in a short directory.
    directory = Path(tempfile.mkdtemp(prefix="lup", dir="/tmp"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def make_project(base: Path, runtime: Path, bundle: Bundle | None = None) -> Project:
    root = base / "project"
    (root / "example").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "example" / "__init__.py").write_text('"""Examples."""\n')
    return Project(root, engine_for(runtime, base / "state", bundle))


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory, short: Path) -> Iterator[Project]:
    made = make_project(tmp_path_factory.mktemp("engine"), short / "run")
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
    ruff = sh.Command(str(Path(sys.executable).parent / "ruff"))
    ruff(
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


def test_a_rule_the_engine_lacks_is_refused(project: Project) -> None:
    project.write("refused.py", DOCSTRING)
    picky = project.engine.model_copy(update={"selected": ["no-such-rule"]})
    with pytest.raises(EngineError, match="no rule named `no-such-rule`"):
        picky.check(project.root, [Source(path=Path("example/refused.py"))])


def test_a_selection_runs_only_its_rules(project: Project) -> None:
    content = (
        DOCSTRING + "import re\n\n\ndef pair() -> tuple[int, int]:\n    return 1, 2\n"
    )
    project.write("selected.py", content)
    chosen = project.engine.model_copy(update={"selected": ["regex"]})
    [report] = chosen.check(project.root, [Source(path=Path("example/selected.py"))])
    assert lup(report) == ["regex"]


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


def environment(at: Path, source: Path) -> Path:
    """Make a virtual environment with `source` installed editable, as uv does."""
    sh.Command(sys.executable)("-m", "venv", "--without-pip", str(at))
    [site] = (at / "lib").glob("python*/site-packages")
    (site / "_pkg.pth").write_text(str(source))
    return at / "bin"


def test_an_environment_made_after_the_engine_started_is_the_one_it_reads(
    tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The session runs in another checkout's environment, which a hook inherits, and
    # there the package lacks the method this worktree adds.
    other = tmp_path / "dev"
    session = environment(other / ".venv", workspace(other, HOLDING))
    monkeypatch.setenv("PATH", f"{session}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VIRTUAL_ENV", str(session.parent))
    root = tmp_path / "branch"
    source = workspace(root, HOLDING)
    engine = engine_for(short / "environment", tmp_path / "state")
    try:
        # The engine starts before the worktree has an environment of its own.
        engine.check(root, [Source(path=Path("packages/pkg/src/pkg/held.py"))])
        environment(root / ".venv", source)
        (source / "pkg" / "held.py").write_text(RELEASING)
        caller = Source(path=Path("packages/pkg/src/pkg/caller.py"), content=CALLER)
        [report] = engine.check(root, [caller])
        assert pyright(report) == []
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


@pytest.mark.parametrize(
    "written",
    [
        'ignore("string-split")',
        "ignore(why='no rule')",
        'ignore("a", "b", why="two")',
        'ignore("a", why="x", extra=1)',
        'defer(why="nothing brings it back")',
        "defer(issue=1)",
        'defer("12", why="positional")',
        'defer(issue=12, when="quoted", why="x")',
        'unknown("x", why="y")',
        'ignore("x", why="y"',
        "ignore",
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


def test_a_modules_surface_holds_its_classes_and_signatures(project: Project) -> None:
    body = (
        "class Outer:\n"
        '    """A class."""\n\n'
        "    class Inner:\n"
        '        """A nested class."""\n\n'
        "    def method(\n"
        "        self, first: int, /, second: str = 'x', *rest: int, flag: bool,\n"
        "        **extra: float,\n"
        "    ) -> str | None:\n"
        '        """A method."""\n'
        "        return None\n\n\n"
        "def function(value: list[int]) -> int:\n"
        '    """A function."""\n'
        "    return len(value)\n"
    )
    surface = project.check("surface.py", on_disk=DOCSTRING + body).surface
    assert surface.exported == []
    assert surface.classes == ["Outer", "Outer.Inner"]
    [method, function] = surface.signatures
    assert method.name == "Outer.method"
    assert [
        (p.name, p.kind, p.annotation, p.has_default) for p in method.parameters
    ] == [
        ("self", "positional-only", "", False),
        ("first", "positional-only", "int", False),
        ("second", "positional-or-keyword", "str", True),
        ("rest", "variadic", "int", False),
        ("flag", "keyword-only", "bool", False),
        ("extra", "variadic-keyword", "float", False),
    ]
    assert method.returns == "str | None"
    assert (function.name, function.returns) == ("function", "int")


def test_a_package_root_exports_its_names_or_its_all(project: Project) -> None:
    package = project.root / "example" / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        DOCSTRING + "from example.pkg.inner import thing as thing\n\nVERSION = 1\n"
    )
    (package / "inner.py").write_text(DOCSTRING + "thing = 1\n")
    [report] = project.engine.check(
        project.root, [Source(path=Path("example/pkg/__init__.py"))]
    )
    assert report.surface.exported == ["VERSION", "thing"]
    declared = (
        DOCSTRING + "from example.pkg.inner import thing\n\n__all__ = ['thing']\n"
    )
    [report] = project.engine.check(
        project.root, [Source(path=Path("example/pkg/__init__.py"), content=declared)]
    )
    assert report.surface.exported == ["thing"]


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


def test_hooks_asking_at_once_start_one_engine(tmp_path: Path, short: Path) -> None:
    fresh = make_project(tmp_path, short / "together")
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


def test_an_engine_from_another_build_is_replaced(tmp_path: Path, short: Path) -> None:
    built = Bundle()
    copy = Bundle(directory=tmp_path / "bundle")
    copy.directory.mkdir()
    shutil.copy2(built.script, copy.script)
    copy.stubs.symlink_to(built.stubs, target_is_directory=True)
    fresh = make_project(tmp_path, short / "rebuilt", copy)
    fresh.write("one.py", DOCSTRING)
    try:
        before = fresh.engine.status(fresh.root)
        # Another build: the same script, written again.
        copy.script.write_bytes(copy.script.read_bytes() + b"\n")
        after = fresh.engine.status(fresh.root)
        assert after.pid != before.pid
    finally:
        fresh.engine.stop(fresh.root)


def test_without_a_built_engine_the_error_says_how_to_build_it(tmp_path: Path) -> None:
    missing = engine_for(tmp_path, tmp_path, Bundle(directory=tmp_path / "nothing"))
    with pytest.raises(EngineError, match=r"uv run packages/lup-dev/checker/build\.py"):
        missing.rules()
