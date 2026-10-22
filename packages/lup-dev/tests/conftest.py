"""Fakes for judging writes: the engine, ruff, the clock, the spawner, a runtime.

The fake engine reads a file the way the real one reports it, from markers:
- `# BAD <rule>` on a line is a lup finding of `<rule>` there;
- `# TYPE` on a line is one of pyright's type errors there;
- `# lup: …` comments are parsed into directives with Python's own parser;
- classes, functions and a package root's `__all__` make the public surface.
The fake linter reads `# RUFF <code>` as one of ruff's findings, and `# FIXABLE
<code>` as one ruff fixes safely. The real engine and ruff run through uv, which
`offline_uv` keeps off the network and out of the operator's uv state.
"""

import ast
import io
import os
import sys
import time
import tokenize
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest

from lup.programs import run
from lup.types import MutableModel
from lup_dev import Project, cli
from lup_dev.clock import Clock
from lup_dev.codescan.contract import (
    Checker,
    Examples,
    FileReport,
    Finding,
    Parameter,
    Parser,
    Placed,
    Position,
    Rule,
    Signature,
    Source,
    Span,
    Surface,
)
from lup_dev.codescan.directives import (
    Defer,
    Directive,
    GitHubIssues,
    Ignore,
    Malformed,
    Note,
)
from lup_dev.codescan.ruff import Linter
from lup_dev.declaration.resolve import Resolved, resolve
from lup_dev.forge.github import GitHubError
from lup_dev.host.client import RoomClient
from lup_dev.host.protocol import HostError
from lup_dev.host.records import Record, Records
from lup_dev.host.workers import (
    Called,
    Calling,
    Happening,
    LaunchModules,
    Listing,
    Offered,
    Relayed,
    Relaying,
    Sent,
)
from lup_dev.inbox.protocol import AskFlag, Gathering, ShowGathering
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import Bench, Services
from lup_dev.policy.flags import Flagging
from lup_dev.policy.holds import Announcing, Hold, Response, answer
from lup_dev.policy.importers import Spawner
from lup_dev.policy.runtime import Runtime
from lup_dev.private.withheld import Facts, Machine
from lup_dev.worker import Serving

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from lup_dev.declaration.resolve import Selected
    from lup_dev.declaration.runner import Runner
    from lup_dev.forge.github import Visibility
    from lup_dev.host.protocol import GitHubRepository, Register, Reply, Request
    from lup_dev.inbox.store import ChangedFile


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
        tracked = "issue" in keywords or "when" in keywords
        said = [
            each.value
            for each in parsed.args
            if isinstance(each, ast.Constant) and isinstance(each.value, str)
        ]
        match parsed.func.id:
            case "ignore" if parsed.args and "why" in keywords:
                rule = ast.literal_eval(parsed.args[0])
                found.append(
                    Ignore(
                        line=line, covers=covers, rule=rule, why=str(keywords["why"])
                    )
                )
            case "defer" if "why" in keywords and tracked:
                found.append(Defer.model_validate({"line": line, **keywords}))
            case "note" if len(parsed.args) == 1 and said:
                found.append(Note(line=line, text=said[0]))
            case name if name in ["ignore", "defer"] or tracked:
                found.append(
                    Malformed(
                        line=line,
                        text=text,
                        problem=f"`{name}` is missing what it needs, or unknown",
                    )
                )
            case _:
                found.append(Note(line=line, text=text))
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
    places = [
        *(
            Placed(kind="class", name=node.name, line=node.lineno)
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        ),
        *(
            Placed(kind="signature", name=node.name, line=node.lineno)
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        ),
        *(
            Placed(kind="signature", name=f"{node.name}.{item.name}", line=item.lineno)
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            for item in node.body
            if isinstance(item, ast.FunctionDef)
        ),
    ]
    exported = []
    if path.name == "__init__.py":
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                exported = list(ast.literal_eval(node.value))
                assert isinstance(node.value, ast.List | ast.Tuple)
                places.extend(
                    Placed(kind="export", name=entry.value, line=entry.lineno)
                    for entry in node.value.elts
                    if isinstance(entry, ast.Constant) and isinstance(entry.value, str)
                )
    return Surface(
        exported=exported,
        classes=classes,
        signatures=[*functions, *methods],
        places=places,
    )


class FakeEngine(Checker):
    """The typed engine, scripted from markers in the content it's given."""

    def __init__(self) -> None:
        self.checked: list[list[Source]] = []
        self.selections: list[list[Selected]] = []
        """The rule selections each check was sent, in order."""
        self.runners: list[Runner] = []
        """The runner each check and importers pass was sent, in order."""
        self.importers_asked: list[list[Path]] = []
        self.importer_reports: list[FileReport] = []
        self.listed_for: list[list[Selected]] = []
        """The rule selections each listing was asked for, in order."""
        self.running: list[str] = ["regex", "tuple-shape"]
        """The rules any selection runs, by id: a fake resolves none."""

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

    def rules(self, selected: list[Selected] | None = None) -> list[Rule]:
        """Two rules, for a declaration to hold or flag by name; those of them `running` names, for a selection."""
        table = [
            Rule(
                id=rule,
                mistake=f"The mistake {rule} prevents.",
                steer=f"Where {rule} steers.",
                examples=Examples(flags=[]),
            )
            for rule in ["regex", "tuple-shape"]
        ]
        if selected is None:
            return table
        self.listed_for.append(selected)
        return [rule for rule in table if rule.id in self.running]

    def check(
        self,
        root: Path,
        sources: list[Source],
        selected: list[Selected],
        runner: Runner,
    ) -> list[FileReport]:
        self.checked.append(sources)
        self.selections.append(selected)
        self.runners.append(runner)
        return [self.report(root, source) for source in sources]

    def importers(
        self, root: Path, changed: list[Path], runner: Runner
    ) -> list[FileReport]:
        self.importers_asked.append(changed)
        self.runners.append(runner)
        return self.importer_reports


class FakeParser(Parser):
    """The engine's reading of a file's parse alone: the fake engine's directives and surface, scripted from the same markers, with no finding."""

    def __init__(self) -> None:
        self.parsed_asked: list[list[Source]] = []
        """The sources each request was sent, in order."""

    def parsed(self, root: Path, sources: list[Source]) -> list[FileReport]:
        self.parsed_asked.append(sources)

        def read(source: Source) -> FileReport:
            content = source.content
            if content is None:
                content = (root / source.path).read_text()
            return FileReport(
                path=source.path,
                directives=directives(content),
                surface=surface(source.path, content),
            )

        return [read(source) for source in sources]


class FakeLinter(Linter):
    """ruff, scripted from `# RUFF <code>` markers.

    `# FIXABLE <code>` is one of ruff's findings with a safe fix.
    """

    def __init__(self) -> None:
        self.runners: list[Runner] = []
        """The runner each run was sent, in order."""

    def findings(
        self, root: Path, sources: list[Source], runner: Runner
    ) -> list[Finding]:
        self.runners.append(runner)

        def content(source: Source) -> str:
            return (
                source.content
                if source.content is not None
                else (root / source.path).read_text()
            )

        def fixable(source: Source) -> list[Finding]:
            return [
                each.model_copy(update={"fixable": True})
                for each in marked(source.path, content(source), "# FIXABLE ", "ruff")
            ]

        return [
            finding
            for source in sources
            for finding in [
                *marked(source.path, content(source), "# RUFF ", "ruff"),
                *fixable(source),
            ]
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


@pytest.fixture
def clock() -> FakeClock:
    """A clock the test drives: it moves only when slept on."""
    return FakeClock()


@pytest.fixture(autouse=True)
def reachable_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take GitHub's issues as reachable without asking `gh`, which would reach the network."""

    def reachable(self: GitHubIssues) -> str | None:
        return None

    monkeypatch.setattr(GitHubIssues, "unreachable", reachable)


@pytest.fixture(autouse=True)
def outside_a_room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run `lup-dev` as on the host, where no room's request socket is mounted.

    Where the suite itself runs in a room, `/run/lup/request.sock` is there, and
    `rules check` would ask the real host service each issue's state, which asks
    GitHub. A test of the room's path gives `cli.RoomClient` a socket of its own.
    """
    unmounted = tmp_path / "room" / "request.sock"

    def room() -> RoomClient:
        return RoomClient(socket=unmounted)

    monkeypatch.setattr(cli, "RoomClient", room)


@pytest.fixture(autouse=True)
def utc() -> Iterator[None]:
    """Read local times as UTC, so what's said of a moment is the same on every machine."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = before
        time.tzset()


class FakeSpawner(Spawner):
    def __init__(self) -> None:
        self.spawned: list[Path] = []

    def spawn(self, worktree: Path, log: Path) -> None:
        self.spawned.append(worktree)


class FakeRuntime(Runtime):
    def __init__(self, name: str = "asking", *, inside: bool = False) -> None:
        self.called = name
        self.within = inside

    def name(self) -> str:
        return self.called

    def inside(self) -> bool:
        return self.within


def git(root: Path, *arguments: str) -> str:
    return run("git", *arguments, cwd=root).text().strip()


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


class Uv:
    """uv in a test's scratch projects, as `offline_uv` keeps it."""

    def lock(self, root: Path) -> None:
        """Lock a scratch project, as a worktree's `uv.lock` is committed."""
        run("uv", "lock", "--quiet", cwd=root)

    def sync(self, root: Path) -> None:
        """Make a scratch project's environment, as `uv sync` does."""
        run("uv", "sync", "--frozen", "--quiet", cwd=root)


@pytest.fixture(scope="module")
def offline_uv(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Uv]:
    """uv kept offline, on the running Python, with a cache of its own.

    The operator's `UV_*` variables, `uv.toml`, cache and Pythons stay out of it. A
    scratch project with no dependencies locks and installs offline, uv's own build
    backend included. For a whole module, since an engine started in one test serves
    the next with the environment it started with.
    """
    with pytest.MonkeyPatch.context() as patch:
        for name in [name for name in os.environ if name.startswith("UV_")]:
            patch.delenv(name)
        patch.setenv("UV_OFFLINE", "1")
        patch.setenv("UV_NO_CONFIG", "1")
        patch.setenv("UV_PYTHON_DOWNLOADS", "never")
        patch.setenv("UV_PYTHON", sys.executable)
        patch.setenv("UV_CACHE_DIR", str(tmp_path_factory.mktemp("uv-cache")))
        yield Uv()


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


class Announced(Announcing):
    """Records each hold put before the operator, and who made it; and answers it at once with `answering`, where one is given, as an operator watching would."""

    def __init__(
        self, layout: Layout, clock: FakeClock, answering: Response | None
    ) -> None:
        self.layout = layout
        self.clock = clock
        self.answering = answering
        self.holding_all = True
        """Whether the operator holds each flagged write, of every conversation: on
        by default, so a test sees every change that asks held, and turned off
        to see the project's own defaults."""
        self.holds: list[Hold] = []
        self.files: list[list[ChangedFile]] = []
        self.runtimes: list[str] = []
        self.asked: list[str] = []
        """Each conversation the switch was asked about, as `runtime/session/agent`."""

    def announced(
        self, hold: Hold, runtime: str, repository: Path, files: list[ChangedFile]
    ) -> None:
        del repository
        self.holds.append(hold)
        self.files.append(files)
        self.runtimes.append(runtime)
        if self.answering is not None:
            answer(
                self.layout,
                hold.key,
                self.answering,
                [],
                self.clock,
                worktree=hold.worktree,
            )

    def holding(self, runtime: str, session: str, agent: str | None) -> bool:
        self.asked.append(f"{runtime}/{session}/{agent}")
        return self.holding_all


class Flags(Flagging):
    """Records each flagged write put before the operator, gathering a conversation's flagged writes to one file into one item as the inbox does, until the test marks it read (`read`); or refuses each, as an unreachable host would, with `refusing`."""

    def __init__(self) -> None:
        self.shown: list[ShowGathering] = []
        """Each time the judge asked for the item a write would join."""
        self.asked: list[AskFlag] = []
        self.items: dict[int, AskFlag] = {}
        """Each item by its number, as its latest write made it."""
        self.read: list[int] = []
        self.refusing = ""

    def gathering(self, asked: ShowGathering) -> Gathering:
        self.shown.append(asked)
        if self.refusing:
            raise HostError(self.refusing)
        found = [
            (number, kept)
            for number, kept in self.items.items()
            if number not in self.read
            and kept.sender == asked.sender
            and kept.flagged.worktree == asked.worktree
            and kept.flagged.path == asked.path
        ]
        if not found:
            return Gathering()
        number, kept = found[-1]
        return Gathering(number=number, file=kept.file)

    def flagged(self, asking: AskFlag) -> None:
        self.asked.append(asking)
        joins = asking.joining is not None and asking.joining not in self.read
        if asking.refreshing and not joins:
            return
        number = asking.joining if joins and asking.joining else len(self.items) + 1
        self.items[number] = asking


class Kit:
    """A bench with its fakes, for one test."""

    def __init__(
        self,
        state: Path,
        runtime: FakeRuntime,
        answering: Response | None = None,
    ) -> None:
        self.engine = FakeEngine()
        self.parser = FakeParser()
        self.linter = FakeLinter()
        self.clock = FakeClock()
        self.spawner = FakeSpawner()
        # lup's data under the test's directory too: the copies of `lup-dev`
        # trust installs live there.
        self.layout = Layout(state=state, data=state.parent / "data")
        self.runtime = runtime
        self.announced = Announced(self.layout, self.clock, answering)
        self.flags = Flags()
        self.facts = StubFacts(
            home=Path("/home/nobody-here"), user="nobody-here", hostname="no-such-box"
        )
        """The host as the judge reads it where it builds a list of values never
        published: made up, so only a test that means to finds one."""
        self.bench = Bench(
            runtime=runtime,
            services=Services(
                checker=self.engine,
                linter=self.linter,
                clock=self.clock,
                layout=self.layout,
                spawner=self.spawner,
                integration="dev",
                announcing=self.announced,
                flagging=self.flags,
                facts=self.facts,
            ),
        )


@pytest.fixture
def runtimes() -> list[FakeRuntime]:
    """Two runtimes, neither running this test inside one of its sessions."""
    return [FakeRuntime("first"), FakeRuntime("second")]


@pytest.fixture
def kit(tmp_path: Path) -> Kit:
    """A bench for a runtime whose file tools say what they'll write before they write it, each hold approved as it's put before the operator."""
    return Kit(tmp_path / "state", FakeRuntime("asking"), Response(approved=True))


@pytest.fixture
def holding_kit(tmp_path: Path) -> Kit:
    """A bench for a runtime whose writes are all judged at the checkpoint, each hold left for the test to answer."""
    return Kit(tmp_path / "state", FakeRuntime("holding"))


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    """lup's state and data under `tmp_path`, outside any runtime's session."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    return Layout(state=tmp_path / "xdg" / "lup", data=tmp_path / "xdg-data" / "lup")


@pytest.fixture
def fakes(kit: Kit, state: Layout, monkeypatch: pytest.MonkeyPatch) -> Kit:
    """The `lup-dev` command, its engine, ruff and services the kit's fakes."""
    services = kit.bench.services.model_copy(update={"layout": state})

    def engine() -> Checker:
        return kit.engine

    def linter() -> Linter:
        return kit.linter

    def configured() -> Services:
        return services

    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(cli, "Ruff", linter)
    monkeypatch.setattr(cli, "services", configured)
    return kit


class NoRecords(Records):
    """A runtime that keeps no records."""

    def kept(self, under: list[Path]) -> list[Record]:
        return []

    def conversation(self, session: str, agent: str | None) -> Path | None:
        return None


class InProcess(MutableModel, LaunchModules, arbitrary_types_allowed=True):
    """A launch's modules served in the test's own process, from a declaration resolved here: the worker's answers, without its process."""

    resolved: Resolved
    records: Records = NoRecords()
    layout: Layout = Layout(state=Path("/nowhere"), data=Path("/nowhere"))
    """Where lup keeps its data, each module's own among it: a test that runs
    hooks gives its own."""
    servings: dict[str, Serving] = {}
    closed: list[str] = []
    told: list[Happening] = []

    async def open(self, launch: Register) -> Offered:
        serving = Serving(
            launch=launch,
            resolved=self.resolved,
            records=self.records,
            layout=self.layout,
        )
        self.servings[launch.launch] = serving
        return serving.offered()

    async def ask(self, launch: Register, request: Request) -> Reply:
        serving = self.servings[launch.launch]
        match request:
            case Listing():
                return serving.offered()
            case Calling():
                return Called(answer=await serving.call(request))
            case Relaying(request=sent):
                reply = await serving.answer(Sent.model_validate(sent))
                return Relayed(reply=reply.model_dump())
            case Happening():
                self.told.append(request)
                return await serving.happen(request)
            case _:
                message = f"a launch's modules take no `{request.kind}`"
                raise AssertionError(message)

    async def close(self, launch: Register) -> None:
        self.servings.pop(launch.launch, None)
        self.closed.append(launch.launch)


@pytest.fixture
def default_modules() -> InProcess:
    """lup's default modules, the GitHub module among them, served in the test's own process."""
    return InProcess(resolved=resolve(Project()))


@pytest.fixture
def in_process() -> type[InProcess]:
    """Serves a launch's modules in the test's own process, from the declaration it's given."""
    return InProcess


class StubFacts(Facts):
    """A host whose account, ssh configuration and GitHub answers a test gives: made-up values, never the machine's own."""

    def __init__(
        self,
        home: Path = Path("/home/op"),
        user: str = "op",
        hostname: str = "kestrel-box",
        aliases: dict[str, str] | None = None,
        visible: dict[str, Visibility | GitHubError] | None = None,
    ) -> None:
        self.home = home
        self.user = user
        self.hostname = hostname
        self.aliases = aliases or {}
        """What ssh resolves each host to; a host not here, to itself."""
        self.visible = visible or {}
        """GitHub's answer for each `owner/name`; one not here is public."""
        self.asked: list[str] = []

    def machine(self) -> Machine:
        return Machine(home=self.home, user=self.user, hostname=self.hostname)

    def resolved(self, host: str) -> str | None:
        return self.aliases.get(host, host)

    async def visibility(
        self, directory: Path, repository: GitHubRepository
    ) -> Visibility:
        self.asked.append(str(repository))
        answer = self.visible.get(str(repository), "public")
        if isinstance(answer, GitHubError):
            raise answer
        return answer


@pytest.fixture
def stub_facts() -> type[StubFacts]:
    """A host a test describes, with made-up values."""
    return StubFacts
