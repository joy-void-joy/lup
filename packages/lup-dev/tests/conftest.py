"""Fakes for judging writes: the engine, ruff, the clock, the spawner, a runtime.

The fake engine reads a file the way the real one reports it, from markers:
- `# BAD <rule>` on a line is a lup finding of `<rule>` there;
- `# TYPE` on a line is one of pyright's type errors there;
- `# lup: …` comments are parsed into directives with Python's own parser;
- classes, functions and a package root's `__all__` make the public surface.
The fake linter reads `# RUFF <code>` as one of ruff's findings.
"""

import ast
import io
import tokenize
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import pytest
import sh

from lup_dev.clock import Clock
from lup_dev.codescan.contract import (
    Checker,
    FileReport,
    Finding,
    Parameter,
    Position,
    Rule,
    Signature,
    Source,
    Span,
    Surface,
)
from lup_dev.codescan.directives import Defer, Directive, Ignore, Malformed, Note
from lup_dev.codescan.ruff import Linter
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import Bench, Services
from lup_dev.policy.importers import Spawner
from lup_dev.policy.runtime import Runtime

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def marked(
    path: Path, content: str, marker: str, owner: Literal["lup", "pyright", "ruff"]
) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(content.splitlines(), start=1):
        if marker not in line:
            continue
        rest = line[line.index(marker) + len(marker) :].split()
        rule = rest[0] if rest else "reportGeneralTypeIssues"
        column = line.index(marker) + 1
        found.append(
            Finding(
                path=path,
                span=Span(
                    start=Position(line=number, column=column),
                    end=Position(line=number, column=column + len(marker)),
                ),
                owner=owner,
                rule=rule,
                message=f"{rule} fires here",
                steer="do it the other way" if owner == "lup" else "",
            )
        )
    return found


def directives(content: str) -> list[Directive]:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except tokenize.TokenError, SyntaxError:
        return []
    lines = content.splitlines()
    found: list[Directive] = []
    for token in tokens:
        if token.type != tokenize.COMMENT or "# lup:" not in token.string:
            continue
        line, column = token.start
        text = token.string[token.string.index("# lup:") + len("# lup:") :].strip()
        alone = lines[line - 1][:column].strip() == ""
        covers = line + 1 if alone else line
        try:
            parsed = ast.parse(text, mode="eval").body
        except SyntaxError:
            found.append(Note(line=line, text=text))
            continue
        if not isinstance(parsed, ast.Call) or not isinstance(parsed.func, ast.Name):
            found.append(Note(line=line, text=text))
            continue
        keywords: dict[str, str | int] = {
            kw.arg: kw.value.id
            if isinstance(kw.value, ast.Name)
            else ast.literal_eval(kw.value)
            for kw in parsed.keywords
            if kw.arg is not None
        }
        match parsed.func.id:
            case "ignore" if parsed.args and "why" in keywords:
                rule = ast.literal_eval(parsed.args[0])
                found.append(
                    Ignore(
                        line=line, covers=covers, rule=rule, why=str(keywords["why"])
                    )
                )
            case "defer" if "why" in keywords and (
                "issue" in keywords or "when" in keywords
            ):
                found.append(Defer.model_validate({"line": line, **keywords}))
            case name:
                found.append(
                    Malformed(
                        line=line,
                        text=text,
                        problem=f"`{name}` is missing what it needs, or unknown",
                    )
                )
    return found


def surface(path: Path, content: str) -> Surface:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return Surface()

    def signature(name: str, function: ast.FunctionDef) -> Signature:
        arguments = function.args
        defaults = len(arguments.defaults)
        positional = arguments.args
        parameters = [
            Parameter(
                name=argument.arg,
                kind="positional-or-keyword",
                annotation=ast.unparse(argument.annotation)
                if argument.annotation
                else "",
                has_default=index >= len(positional) - defaults,
            )
            for index, argument in enumerate(positional)
        ]
        returns = ast.unparse(function.returns) if function.returns else ""
        return Signature(name=name, parameters=parameters, returns=returns)

    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    functions = [
        signature(node.name, node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    ]
    methods = [
        signature(f"{node.name}.{item.name}", item)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, ast.FunctionDef)
    ]
    exported = []
    if path.name == "__init__.py":
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                exported = list(ast.literal_eval(node.value))
    return Surface(
        exported=exported, classes=classes, signatures=[*functions, *methods]
    )


class FakeEngine(Checker):
    """The typed engine, scripted from markers in the content it's given."""

    def __init__(self) -> None:
        self.checked: list[list[Source]] = []
        self.importers_asked: list[list[Path]] = []
        self.importer_reports: list[FileReport] = []

    def report(self, root: Path, source: Source) -> FileReport:
        content = source.content
        if content is None:
            content = (root / source.path).read_text()
        return FileReport(
            path=source.path,
            findings=[
                *marked(source.path, content, "# BAD ", "lup"),
                *marked(source.path, content, "# TYPE", "pyright"),
            ],
            directives=directives(content),
            surface=surface(source.path, content),
        )

    def rules(self) -> list[Rule]:
        return []

    def check(self, root: Path, sources: list[Source]) -> list[FileReport]:
        self.checked.append(sources)
        return [self.report(root, source) for source in sources]

    def importers(self, root: Path, changed: list[Path]) -> list[FileReport]:
        self.importers_asked.append(changed)
        return self.importer_reports


class FakeLinter(Linter):
    """ruff, scripted from `# RUFF <code>` markers."""

    def findings(self, root: Path, sources: list[Source]) -> list[Finding]:
        def content(source: Source) -> str:
            return (
                source.content
                if source.content is not None
                else (root / source.path).read_text()
            )

        return [
            finding
            for source in sources
            for finding in marked(source.path, content(source), "# RUFF ", "ruff")
        ]


class FakeClock(Clock):
    """A clock that moves only when slept on, running what waits for that moment."""

    def __init__(self) -> None:
        self.time = datetime(2026, 10, 1, 12, tzinfo=UTC)
        self.on_sleep: list[Callable[[], None]] = []
        self.slept = 0.0

    def now(self) -> datetime:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.time += timedelta(seconds=seconds)
        self.slept += seconds
        waiting = self.on_sleep
        self.on_sleep = []
        for action in waiting:
            action()


class FakeSpawner(Spawner):
    def __init__(self) -> None:
        self.spawned: list[Path] = []

    def spawn(self, worktree: Path, log: Path) -> None:
        self.spawned.append(worktree)


class FakeRuntime(Runtime):
    def __init__(
        self, name: str = "asking", *, asks_before: bool = True, inside: bool = False
    ) -> None:
        self.called = name
        self.asks = asks_before
        self.within = inside

    def name(self) -> str:
        return self.called

    def asks_before(self) -> bool:
        return self.asks

    def inside(self) -> bool:
        return self.within


def git(root: Path, *arguments: str) -> str:
    return str(sh.git(*arguments, _cwd=str(root), _tty_out=False)).strip()


def commit(root: Path, message: str = "change") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


class Shell:
    """git in a test's repositories."""

    def git(self, root: Path, *arguments: str) -> str:
        return git(root, *arguments)

    def commit(self, root: Path, message: str = "change") -> None:
        commit(root, message)


@pytest.fixture
def shell() -> Shell:
    return Shell()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository with a small project, its first commit made."""
    root = tmp_path / "work"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "pyproject.toml").write_text(
        '[tool.pytest]\ntestpaths = ["tests", "src"]\n'
    )
    (root / ".gitignore").write_text(".venv/\n.lup/\n")
    (root / "src" / "pkg" / "__init__.py").write_text(
        '"""The package."""\n__all__ = ["Client"]\n'
    )
    (root / "src" / "pkg" / "core.py").write_text(
        '"""Core."""\n\n\n'
        "class Client:\n"
        "    def ask(self, prompt: str) -> str:\n"
        "        return prompt\n\n\n"
        "def helper(x: int) -> int:\n"
        "    return x\n"
    )
    (root / "tests" / "test_core.py").write_text("def test_it():\n    assert True\n")
    (root / "README.md").write_text("# Work\n")
    commit(root, "init")
    return root


@pytest.fixture
def linked(repo: Path, tmp_path: Path) -> Path:
    """A second worktree of `repo`, on its own branch `feat`."""
    root = tmp_path / "feat"
    git(repo, "worktree", "add", "-q", "-b", "feat", str(root))
    return root


@pytest.fixture
def bare(repo: Path, tmp_path: Path) -> Path:
    """A bare clone of `repo`, its worktrees under `tree/`, as lup's own layout is."""
    root = tmp_path / "proj.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(root))
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "tree").mkdir()
    git(root, "worktree", "add", "-q", "tree/main", "main")
    return root


class Kit:
    """A bench with its fakes, for one test."""

    def __init__(self, state: Path, runtime: FakeRuntime) -> None:
        self.engine = FakeEngine()
        self.linter = FakeLinter()
        self.clock = FakeClock()
        self.spawner = FakeSpawner()
        self.layout = Layout(state=state)
        self.runtime = runtime
        self.bench = Bench(
            runtime=runtime,
            services=Services(
                checker=self.engine,
                linter=self.linter,
                clock=self.clock,
                layout=self.layout,
                spawner=self.spawner,
            ),
        )


@pytest.fixture
def runtimes() -> list[FakeRuntime]:
    """Two runtimes, neither running this test inside one of its sessions."""
    return [FakeRuntime("first"), FakeRuntime("second")]


@pytest.fixture
def kit(tmp_path: Path) -> Kit:
    """A bench for a runtime that asks before a call."""
    return Kit(tmp_path / "state", FakeRuntime("asking", asks_before=True))


@pytest.fixture
def holding_kit(tmp_path: Path) -> Kit:
    """A bench for a runtime that can't ask before a call, so it holds."""
    return Kit(tmp_path / "state", FakeRuntime("holding", asks_before=False))
