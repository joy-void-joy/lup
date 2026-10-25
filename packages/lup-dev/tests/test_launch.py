"""A launch, its whole flow with every seam stubbed: trust, the host service's client, the CLI's channel, podman and the room's tools.

git runs for real on the test's repositories, with the operator's own git
configuration kept out. No test runs podman, reaches the network or a real host
service, or reads the clock; the hook command runs under `sh` with a stand-in
`socat`, against a stand-in service where it must reach one.
"""

import io
import json
import shlex
import subprocess
import sys
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from filelock import FileLock
from typer.testing import CliRunner

import lup
from lup import events
from lup.programs import Ran, run
from lup.rooms.engine import Podman, Process
from lup.sessions.bridge import Bridge
from lup.sessions.terminal import (
    Cli,
    SessionSettings,
    TerminalError,
    TerminalSettings,
    ToolServer,
)
from lup_dev import Core, Modules, Project, Session, cli
from lup_dev.adapters import Adapter, claude, codex
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.catalog.room import SessionDefaults
from lup_dev.codescan.contract import Examples, Rule
from lup_dev.codescan.engine import EngineError
from lup_dev.declaration.requirements import Printed, Tools
from lup_dev.declaration.resolve import Selected, resolve
from lup_dev.forge.github import GitHubError, Visibility
from lup_dev.host.client import HostClient, Starter
from lup_dev.host.names import container_name
from lup_dev.host.protocol import (
    GitHubRepository,
    HostError,
    Limits,
    Register,
    Registered,
)
from lup_dev.launch.clis import Channel, ChannelError
from lup_dev.launch.guidance import OPENING
from lup_dev.launch.room import RoomError
from lup_dev.launch.session import (
    LaunchError,
    SessionParts,
    approved_declaration,
    hooked,
    piped,
    session_settings,
    terminal_settings,
    trusted,
)
from lup_dev.launch.trust import Outcome, Unchanged
from lup_dev.layout import Layout
from lup_dev.private.withheld import Facts, Withheld
from lup_dev.private.withheld import Machine as PrivateMachine
from lup_dev.private.withheld import kept as withheld_kept
from lup_dev.settings import TerminalVariables
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx
    from conftest import FakeClock, Shell

    from lup.events import SessionEvent

DECLARED = '''"""A project's declaration, with a guidance section and limits of its own."""

from pathlib import Path

from lup_dev import (
    Actions,
    Core,
    Credentials,
    Guidance,
    Module,
    Modules,
    Plain,
    Project,
    Python,
    Refs,
    Section,
)


class Own(Module):
    """The project's own module."""

    name = "own"
    guidance: Guidance = Guidance.of(Section(name="own", path=Path("AGENTS.md")))


limits = Credentials(
    actions=Actions().add("force-push"),
    protected=Refs().add("refs/heads/release/*"),
)
project = Project(
    modules=Modules.default()
    .edit(Python(runner=Plain()))
    .edit(Core(credentials=limits))
    .add(Own())
)
'''

runner = CliRunner()

RUNNING = [
    Rule(
        id="elif",
        mistake="A chain of conditions hides the value's structure.",
        steer="Decide on a value's structure with `match`.",
        examples=Examples(flags=[]),
    )
]
"""The rules the stand-in engine says any selection runs."""


@pytest.fixture(autouse=True)
def own_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git configuration out, and their homes, and any session."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ["CLAUDE_CONFIG_DIR", "CLAUDE_CODE_CHILD_SESSION", "CODEX_THREAD_ID"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))


@pytest.fixture
def project(tmp_path: Path, shell: Shell, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project on `dev`, its declaration committed, launched from its root."""
    root = tmp_path / "repos" / "work"
    root.mkdir(parents=True)
    (root / "lup_project.py").write_text(DECLARED)
    (root / "AGENTS.md").write_text("# The project\n\nAs committed.\n")
    shell.git(root, "init", "-q", "-b", "dev")
    shell.git(root, "config", "user.email", "test@example.com")
    shell.git(root, "config", "user.name", "Test")
    shell.git(root, "config", "commit.gpgsign", "false")
    shell.commit(root, "first")
    monkeypatch.chdir(root)
    return root


class Events:
    """What each seam was asked, in order."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def record(self, event: str) -> None:
        self.said.append(event)


class Host(HostClient):
    """The host service's client, with no service behind: each call recorded."""

    events: Events
    served: list[Register] = []
    sockets: Path

    @override
    def ensure(self) -> None:
        self.events.record("host")

    @override
    def launches(self) -> list[Register]:
        self.events.record("launches")
        return self.served

    @override
    def register(self, launch: Register) -> Registered:
        """Serve `launch` by the name it asks, its container named as the service names it."""
        container = launch.container or container_name(
            launch.repository, launch.name or ""
        )
        self.events.record(f"register {launch.runtime} {container}")
        self.served.append(launch.model_copy(update={"container": container}))
        return Registered(
            directory=self.sockets, name=launch.name or "", container=container
        )

    @override
    def unregister(self, launch: str) -> None:
        self.events.record(f"unregister {launch}")


class Nothing(Starter):
    @override
    def start(self, log: Path) -> None:
        message = "no service starts in a test"
        raise AssertionError(message)


class Offline(Channel, arbitrary_types_allowed=True):
    """A release channel that can't be reached, so the newest version kept runs."""

    events: Events

    @override
    def latest(self, client: httpx.Client) -> str:
        self.events.record("cli")
        message = "the channel is offline"
        raise ChannelError(message)

    @override
    def download(self, client: httpx.Client, version: str, into: Path) -> None:
        message = "nothing downloads offline"
        raise AssertionError(message)

    @override
    def cli(self, directory: Path) -> Cli:
        return Cli(program=directory / "cli")


class Found(Tools):
    """Every program on the `PATH` but those `missing`; no probe runs."""

    def __init__(
        self, record: Callable[[str], None], missing: list[str] | None = None
    ) -> None:
        self.record = record
        self.missing = missing or []

    @override
    def found(self, program: str) -> bool:
        self.record(f"found {program}")
        return program not in self.missing

    @override
    def run(self, command: list[str]) -> Printed:
        message = f"no probe runs: {command}"
        raise AssertionError(message)


class Engine:
    """podman, answering each command as a test scripts it."""

    def __init__(
        self, record: Callable[[str], None], *, gone: list[str], ran: int
    ) -> None:
        self.record = record
        self.gone = gone
        self.ran = ran
        self.processes: list[Process] = []
        self.guidance: str | None = None
        self.gitconfig: str | None = None
        self.linked: dict[str, Path] = {}
        """The links among the launch's commands while the room ran, by name."""
        self.unshared: list[list[str]] = []

    def __call__(self, process: Process) -> Ran:
        self.processes.append(process)
        program, command, *rest = process.arguments
        assert program == "podman"
        match [command, *rest]:
            case ["image", "exists", _]:
                self.record("image")
                return Ran(command=process.arguments, status=0)
            case ["container", "exists", name]:
                self.record(f"container {name}")
                return Ran(
                    command=process.arguments, status=1 if name in self.gone else 0
                )
            case ["unshare", *unshared]:
                self.unshared.append(unshared)
                return Ran(command=process.arguments, status=0)
            case ["run", *_]:
                self.record("run")
                flag = "--append-system-prompt-file"
                if flag in rest:
                    self.guidance = Path(rest[rest.index(flag) + 1]).read_text()
                [global_config] = [
                    each.removeprefix("--env=GIT_CONFIG_GLOBAL=")
                    for each in rest
                    if each.startswith("--env=GIT_CONFIG_GLOBAL=")
                ]
                self.gitconfig = Path(global_config).read_text()
                commands = Path(global_config).parent / "bin"
                self.linked = {
                    each.name: each.readlink()
                    for each in commands.iterdir()
                    if each.is_symlink()
                }
                return Ran(command=process.arguments, status=self.ran)
            case _:
                message = f"podman asked {process.arguments}"
                raise AssertionError(message)

    def run(self) -> list[str]:
        [ran] = [
            each.arguments for each in self.processes if each.arguments[1] == "run"
        ]
        return ran


class Here(Facts):
    """The host as a launch's list of private values reads it: made-up, its remotes' hosts their own names, every repository public."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def machine(self) -> PrivateMachine:
        return PrivateMachine(home=self.home, user="op", hostname="kestrel-box")

    def resolved(self, host: str) -> str | None:
        return host

    async def visibility(
        self, directory: Path, repository: GitHubRepository
    ) -> Visibility:
        return "public"


class Machine:
    """A launch's machine, every seam a stub recording into one list."""

    def __init__(
        self,
        tmp_path: Path,
        clock: FakeClock,
        *,
        ran: int = 7,
        missing: list[str] | None = None,
        unnamed: str | None = None,
        local: str | None = None,
    ) -> None:
        self.events = Events()
        self.unnamed = unnamed
        self.local = local
        self.listed_for: list[list[Selected]] = []
        """The rule selections the launch asked the engine to list, in order."""
        self.refusing: str | None = None
        """Why the stand-in engine refuses every selection, where it does."""
        record = self.events.record
        self.layout = Layout(
            state=tmp_path / "state",
            runtime=tmp_path / "run",
            cache=tmp_path / "cache" / "lup",
            data=tmp_path / "data",
        )
        self.sockets = tmp_path / "run" / "host" / "launches" / "this"
        self.sockets.mkdir(parents=True)
        self.engine = Engine(record, gone=["lup-dead"], ran=ran)
        self.host = Host(
            layout=self.layout.host,
            clock=clock,
            starter=Nothing(),
            events=self.events,
            sockets=self.sockets,
        )
        kept = self.layout.clis("claude").version("2.1.300")
        kept.mkdir(parents=True)
        (kept / "cli").write_text("")
        self.launcher = cli.Launcher(
            layout=self.layout,
            trust=self.trust,
            host=self.host,
            podman=Podman(execute=self.engine),
            tools=Found(record, missing),
            clock=clock,
            terminal=TerminalVariables(
                term="xterm-kitty",
                colorterm=None,
                lang=None,
                tz=None,
                editor=None,
                visual=None,
            ),
            say=record,
            github=self.github,
            facts=Here(tmp_path / "home"),
            rules=self.rules,
        )
        self.adapter = claude.adapter().model_copy(
            update={"channel": Offline(events=self.events)}
        )

    def trust(self, root: Path) -> Outcome:
        self.events.record("trust")
        commit = run("git", "rev-parse", "dev", cwd=root).text().strip()
        common = Path(
            run(
                "git",
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
                cwd=root,
            )
            .text()
            .strip()
        )
        approval = Approval(
            commit=commit,
            fingerprint="f",
            paths=[Path("lup_project.py")],
            tool=ReleaseTool(
                name="lup-dev",
                version="0.4.0",
                registry="https://pypi.org/simple",
                pins={},
            ),
            time=self.host.clock.now(),
            local=self.local,
        )
        write_model(self.layout.approved(common), approval)
        return Unchanged(commit=commit, approval=approval)

    def rules(self, selected: list[Selected]) -> list[Rule]:
        """Stand in for the engine: `RUNNING` for any selection, or its refusal."""
        self.listed_for.append(selected)
        if self.refusing is not None:
            raise EngineError(self.refusing)
        return RUNNING

    def github(self, repository: Path) -> GitHubRepository:
        self.events.record(f"github {repository.name}")
        if self.unnamed is not None:
            raise GitHubError(self.unnamed)
        return GitHubRepository(owner="someone", name="work")

    def launching(self, say: Callable[[str], None]) -> cli.Launcher:
        """Stand in for the command's machine, whatever it would say through."""
        del say
        return self.launcher

    def judge(self, root: Path) -> Path:
        common = root / ".git"
        return self.layout.judge(common).command("lup-dev")


def dead(project: Path) -> Register:
    """A launch whose launcher died and whose container is gone."""
    return Register(
        launch="dead",
        runtime="claude",
        worktree=project,
        repository=project / ".git",
        judge=Path("/nowhere/lup-dev"),
        container="lup-dead",
        limits=resolve(Project()).limits,
        github=None,
    )


def live(project: Path) -> Register:
    """A launch whose launcher still runs, though its container isn't there yet."""
    return dead(project).model_copy(update={"launch": "live", "container": "lup-live"})


def test_a_launch_runs_each_step_in_order_and_ends_its_registration(
    project: Path, tmp_path: Path, clock: FakeClock, shell: Shell
) -> None:
    machine = Machine(tmp_path, clock)
    machine.host.served.extend([dead(project), live(project)])
    (machine.layout.launch("dead").directory).mkdir(parents=True)
    (project / "AGENTS.md").write_text("# The project\n\nUncommitted.\n")
    (project / "AGENTS.local.md").write_text("Mine.\n")
    (project / "lup_project.py").write_text(
        DECLARED.replace('add("force-push")', 'add("force-push", "delete-ref")')
    )
    held = FileLock(machine.layout.launch("live").lock)
    machine.layout.launches.mkdir(parents=True, exist_ok=True)

    with held:
        status = cli.launched(machine.adapter, ["--resume"], project, machine.launcher)

    assert status == 7
    said = machine.events.said
    [launch] = [
        each.launch
        for each in machine.host.served
        if each.launch not in ["dead", "live"]
    ]
    container = "lup-work-dev"
    assert [each for each in said if not each.startswith("The host zone")] == [
        "trust",
        "found podman",
        "found git",
        "found gh",
        "found notify-send",
        "found wl-paste",
        "found qrencode",
        "github .git",
        "host",
        "cli",
        (
            "claude 2.1.300, kept, runs: its release channel couldn't give the "
            "latest. the channel is offline"
        ),
        "image",
        "launches",
        "container lup-dead",
        "unregister dead",
        (
            f"Ended launch dead, claude in {project}: its launcher and its "
            "container, lup-dead, are gone."
        ),
        f"register claude {container}",
        "This launch is `dev`.",
        "image",
        "run",
        f"unregister {launch}",
    ]
    assert not machine.layout.launch("dead").directory.exists()
    assert not machine.layout.launch(launch).directory.exists()
    assert not machine.layout.launch(launch).lock.exists()
    [own] = [each for each in machine.host.served if each.launch == launch]
    assert own == Register(
        launch=launch,
        runtime="claude",
        worktree=project,
        repository=project / ".git",
        judge=machine.judge(project),
        container=container,
        limits=Limits(
            actions=[
                "fetch",
                "push",
                "force-push",
                "delete-merged",
                "read-issues",
                "file-issue",
                "edit-issue",
                "close-issue",
                "comment",
                "edit-comment",
                "draft-pull-request",
            ],
            protected=["refs/heads/main", "refs/tags/*", "refs/heads/release/*"],
            gated=["refs/heads/dev"],
        ),
        github=GitHubRepository(owner="someone", name="work"),
        name="dev",
        runner=[],
    )
    run = machine.engine.run()
    assert f"--name={container}" in run
    assert f"--mount=type=bind,source={machine.sockets},destination=/run/lup" in run
    assert run[-1] == "--resume"
    assert str(machine.layout.clis("claude").version("2.1.300") / "cli") in run
    directory = machine.layout.launch(launch).directory
    lent = machine.layout.launch(launch).lent
    stage = machine.layout.launch(launch).stage
    assert (
        f"--mount=type=bind,source={lent},destination=/lent,bind-propagation=rslave"
        in run
    )
    assert machine.engine.unshared == [
        ["mount", "--bind", str(lent), str(lent)],
        ["mount", "--make-shared", str(lent)],
        ["mount", "--bind", str(stage), str(stage)],
        ["mount", "--make-private", str(stage)],
        ["umount", "--recursive", str(lent)],
        ["umount", "--recursive", str(stage)],
    ]
    assert not lent.exists()
    assert not stage.exists()
    assert f"--env=GIT_CONFIG_GLOBAL={directory / 'gitconfig'}" in run
    assert (
        f"--env=PATH={directory / 'bin'}:/usr/local/sbin:/usr/local/bin:/usr/sbin:"
        "/usr/bin:/sbin:/bin"
    ) in run
    for written in [directory / "bin", directory / "gitconfig"]:
        assert (
            f"--mount=type=bind,source={written},destination={written},ro=true" in run
        )
    seen = tmp_path / "seen-gitconfig"
    seen.write_text(machine.engine.gitconfig or "")
    # The project's declaration runs its tools as the `PATH` finds them (`Plain`).
    assert json.loads(
        shell.git(tmp_path, "config", "--file", str(seen), "lup.gate")
    ) == ["lup-dev", "check", "--at"]
    assert json.loads(
        shell.git(tmp_path, "config", "--file", str(seen), "lup.gated")
    ) == ["refs/heads/dev"]


def test_a_repository_whose_config_the_room_could_change_doesnt_launch(
    project: Path, tmp_path: Path, clock: FakeClock, shell: Shell
) -> None:
    machine = Machine(tmp_path, clock)
    shell.git(project, "config", "include.path", "shared.cfg")

    with pytest.raises(RoomError, match=r"includes .*shared.cfg, inside the room's"):
        cli.launched(machine.adapter, [], project, machine.launcher)

    assert not any(each.startswith("register") for each in machine.events.said)
    assert not machine.layout.launches.exists() or not any(
        machine.layout.launches.iterdir()
    )


def test_a_launch_compiles_the_approved_declarations_guidance_and_hooks(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    (project / "AGENTS.md").write_text("# The project\n\nUncommitted.\n")
    (project / "AGENTS.local.md").write_text("Mine.\n")
    commit = run("git", "rev-parse", "dev", cwd=project).text().strip()
    directory = tmp_path / "launch"
    hooks = hooked(claude.hooks)

    with approved_declaration(project, commit, local=None) as declared:
        settings = terminal_settings(
            declared,
            project,
            directory,
            Cli(program=Path("/opt/cli")),
            hooks,
            tools=cli.served_tools(declared.resolved),
            neighbours=[],
            shared={"transcripts": tmp_path / "transcripts"},
            rules=RUNNING,
        )
        exported = declared.root
        choices = declared.resolved.session
        own = [section.name for section in declared.resolved.guidance]
    assert not exported.exists()

    assert own[-1] == "own"
    assert settings.directory == directory
    assert settings.cli == Cli(program=Path("/opt/cli"))
    assert settings.hooks == claude.hooks(
        partial(piped, timeout=timedelta(hours=25)), timedelta(hours=25)
    )
    assert settings.servers == [
        ToolServer(
            name="lup",
            socket=Path("/run/lup/mcp.sock"),
            timeout=timedelta(hours=25),
            pushes=True,
        )
    ]
    assert settings.messages == Path("/run/lup/messages.sock")
    assert settings.trusted == [project]
    assert settings.session == session_settings(choices).declared
    assert settings.defaults == session_settings(choices).defaults
    guidance = settings.guidance or ""
    assert guidance.startswith(OPENING)
    assert "# The room" in guidance
    assert "As committed." in guidance
    assert "Uncommitted." not in guidance
    assert "## lup's tools" in guidance
    assert "- `wait_inbox`: Wait until something reaches your inbox." in guidance
    assert "- `judged`: Read the judge's verdicts and holds." in guidance
    assert guidance.index("As committed.") < guidance.index("## lup's tools")
    assert guidance.endswith("Mine.\n")


def test_a_launch_in_a_repository_holding_replace_refs_says_so(
    project: Path, tmp_path: Path, clock: FakeClock, shell: Shell
) -> None:
    other = shell.git(project, "commit-tree", "HEAD^{tree}", "-m", "a room's own")
    shell.git(project, "replace", shell.git(project, "rev-parse", "HEAD"), other)
    machine = Machine(tmp_path, clock)
    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7
    assert [each for each in machine.events.said if "replace refs" in each] == [
        (
            "This repository holds replace refs (`refs/replace/`), which a room "
            "can write to hand git other content for an object: lup's git ignores "
            "them. `git replace -l` lists them, and `git replace -d` removes one."
        )
    ]


def test_a_launch_says_once_that_desktop_notices_are_off_without_notify_send(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)
    machine.launcher = machine.launcher.model_copy(
        update={"tools": Found(machine.events.record, missing=["notify-send"])}
    )
    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7
    off = [each for each in machine.events.said if each.startswith("Turned off")]
    assert off == [
        (
            "Turned off, for want of a tool: `notify-send`, for `lup-dev inbox` "
            "(raises a desktop notice when something reaches your inbox): not on "
            "the `PATH`. Install: your system's `libnotify` package."
        )
    ]


def editing(machine: Machine, **variables: str) -> None:
    """Give the launch's terminal these editor variables."""
    terminal = machine.launcher.terminal.model_copy(update=variables)
    machine.launcher = machine.launcher.model_copy(update={"terminal": terminal})


def test_a_launch_says_once_that_it_doesnt_know_the_operator_s_editor(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)
    editing(machine, editor="nvim", visual="kak -n")

    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7

    assert [each for each in machine.events.said if "editor" in each] == [
        (
            "Your editor, `kak` (`$VISUAL`, else `$EDITOR`), isn't one lup knows "
            "the package of, so the room doesn't install it, and Ctrl+G there "
            "won't find it unless your own layer, `lup_project.local.py`, adds its "
            "package to `Core`. Every room has `nano`."
        )
    ]
    assert machine.engine.linked == {}


def test_a_launch_says_nothing_of_an_editor_it_knows_and_links_hx_to_helix(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)
    editing(machine, editor="hx")

    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7

    assert not [each for each in machine.events.said if "editor" in each]
    assert machine.engine.linked == {"hx": Path("/usr/bin/helix")}


def test_a_launch_without_gh_says_so_once_and_names_no_repository(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock, missing=["gh"])

    cli.launched(machine.adapter, [], project, machine.launcher)

    said = machine.events.said
    off = [each for each in said if "gh" in each and not each.startswith("found")]
    assert off == [
        (
            "Turned off, for want of a tool: `gh`, for `lup-dev launch` (reaches "
            "GitHub with your login for lup's GitHub tools, and for the gate's issue "
            "states in a room): not on the `PATH`. Install: your system's "
            "`github-cli` package, then `gh auth login`."
        )
    ]
    assert not [each for each in said if each.startswith("github")]
    [registered] = machine.host.served
    assert registered.github is None


def test_a_repository_gh_cant_name_is_said_once_and_registered_without_one(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(
        tmp_path, clock, unnamed="none of the git remotes point to GitHub"
    )

    cli.launched(machine.adapter, [], project, machine.launcher)

    said = machine.events.said
    assert [each for each in said if "GitHub" in each] == [
        (
            "lup's GitHub tools won't reach GitHub from this launch: none of the "
            "git remotes point to GitHub."
        )
    ]
    [registered] = machine.host.served
    assert registered.github is None


MINE = '''"""The person's own layer: the repositories they relate, made up."""

from pathlib import Path

from lup_dev import Module, Modules, Project, Repositories, Repository


class Mine(Module):
    """The repositories beside the project, as this person has them."""

    name = "mine"

    repositories: Repositories = Repositories.of(
        Repository(
            name="notes",
            path=Path("notes.git"),
            about="the notes",
            github="someone/notes",
        ),
        Repository(name="gone", path=Path("gone.git"), about="not here"),
    )


project = Project(modules=Modules().add(Mine()))
'''


def test_the_approved_layer_s_repositories_are_mounted_said_and_listed(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    notes = tmp_path / "repos" / "notes.git"
    notes.mkdir()
    (project / "lup_project.local.py").write_text(
        MINE.replace('"notes.git"', '"edited-in-a-room.git"')
    )
    machine = Machine(tmp_path, clock, local=MINE)

    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7

    here = notes.resolve()
    gone = (tmp_path / "repos" / "gone.git").resolve()
    said = machine.events.said
    assert [each for each in said if "for sessions to read" in each] == [
        (
            f"The repository `gone` the declaration names for sessions to read "
            f"isn't at {gone}, so the room doesn't mount it, and its guidance says "
            "it's missing."
        )
    ]
    run = machine.engine.run()
    assert f"--mount=type=bind,source={here},destination={here},ro=true" in run
    assert not [each for each in run if str(gone) in each]
    assert not [each for each in run if "edited-in-a-room" in each]
    guidance = machine.engine.guidance or ""
    assert "edited-in-a-room" not in guidance
    assert guidance.index("## lup's tools") < guidance.index("## Other repositories")
    assert (
        f"- `notes`, the notes. At `{here}`, mounted. On GitHub as `someone/notes`."
    ) in guidance
    assert (
        f"- `gone`, not here. At `{gone}`, missing: it isn't on this machine, so "
        "it isn't mounted."
    ) in guidance


def test_a_codex_launch_refuses_guidance_past_what_codex_takes_before_registering(
    project: Path, tmp_path: Path, clock: FakeClock, shell: Shell
) -> None:
    (project / "AGENTS.md").write_text(
        "# The project\n\n" + "A long section.\n" * 3_000
    )
    shell.commit(project, "a long guidance")
    machine = Machine(tmp_path, clock)
    kept = machine.layout.clis("codex").version("0.163.0")
    kept.mkdir(parents=True)
    (kept / "cli").write_text("")
    on_codex = codex.adapter().model_copy(
        update={"channel": Offline(events=machine.events)}
    )

    with pytest.raises(
        TerminalError, match=r"^the guidance is [\d,]+ bytes.* past the 10,000 Codex"
    ):
        cli.launched(on_codex, [], project, machine.launcher)

    said = machine.events.said
    assert not [each for each in said if each.startswith("register")]
    assert "run" not in said


def test_a_launch_lists_the_rules_the_approved_declaration_runs_where_a_section_asks(
    project: Path, tmp_path: Path, clock: FakeClock, shell: Shell
) -> None:
    (project / "AGENTS.md").write_text("# The project\n\nWrite so:\n\n{{ rules() }}\n")
    shell.commit(project, "the rules in the guidance")
    machine = Machine(tmp_path, clock)

    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7

    assert machine.listed_for == [resolve(Project()).rules]
    guidance = machine.engine.guidance or ""
    listed = "Write so:\n\n- `elif`: Decide on a value's structure with `match`.\n"
    assert listed in guidance


def test_a_selection_the_engine_refuses_stops_the_launch_after_its_declaration(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)
    machine.refusing = "`code-rules`'s rules: `Rules.drop` names `gone`"

    with pytest.raises(EngineError, match=r"`Rules.drop` names `gone`"):
        cli.launched(machine.adapter, [], project, machine.launcher)

    said = machine.events.said
    assert not [each for each in said if each.startswith("github")]
    assert not [each for each in said if each.startswith("register")]
    assert "run" not in said


def test_the_registration_ends_when_the_cli_fails(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock, ran=125)

    with pytest.raises(Exception, match="status 125"):
        cli.launched(machine.adapter, [], project, machine.launcher)

    said = machine.events.said
    [launch] = [each.launch for each in machine.host.served]
    assert said[-2:] == ["run", f"unregister {launch}"]
    assert not machine.layout.launch(launch).directory.exists()
    assert not machine.layout.launch(launch).lock.exists()


def test_an_end_the_service_refuses_is_said_and_the_status_kept(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)

    class Refusing(Host):
        @override
        def unregister(self, launch: str) -> None:
            message = "no host service answers"
            raise HostError(message)

    refusing = Refusing(
        layout=machine.layout.host,
        clock=clock,
        starter=Nothing(),
        events=machine.events,
        sockets=machine.sockets,
    )
    launcher = machine.launcher.model_copy(update={"host": refusing})

    assert cli.launched(machine.adapter, [], project, launcher) == 7
    assert machine.events.said[-1].startswith("The host service didn't end launch ")


def test_nothing_launches_without_an_approval(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)

    def declined(root: Path) -> Outcome:
        message = "you declined"
        raise LaunchError(message)

    launcher = machine.launcher.model_copy(update={"trust": declined})
    with pytest.raises(LaunchError, match="you declined"):
        cli.launched(machine.adapter, [], project, launcher)
    assert machine.events.said == []


def stubbed(machine: Machine) -> Callable[[], list[Adapter]]:
    def adapters() -> list[Adapter]:
        return [
            machine.adapter,
            codex.adapter().model_copy(
                update={"channel": Offline(events=machine.events)}
            ),
        ]

    return adapters


def test_the_command_passes_every_argument_it_doesnt_know_to_the_cli(
    project: Path, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = Machine(tmp_path, clock)
    monkeypatch.setattr(cli, "adapters", stubbed(machine))
    monkeypatch.setattr(cli, "launching", machine.launching)

    result = runner.invoke(
        cli.app, ["launch", "claude", "--resume", "--model", "opus", "-p", "hi"]
    )

    assert result.exit_code == 7, result.output
    assert machine.engine.run()[-5:] == ["--resume", "--model", "opus", "-p", "hi"]


def test_the_command_lends_each_directory_it_s_given_and_lists_it_in_the_guidance(
    project: Path, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = Machine(tmp_path, clock)
    monkeypatch.setattr(cli, "adapters", stubbed(machine))
    monkeypatch.setattr(cli, "launching", machine.launching)
    reading = tmp_path / "reading"
    writing = tmp_path / "writing"
    reading.mkdir()
    writing.mkdir()

    result = runner.invoke(
        cli.app,
        [
            "launch",
            "claude",
            "--mount",
            str(reading),
            "--mount-rw",
            str(writing),
            "--resume",
        ],
    )

    assert result.exit_code == 7, result.output
    run = machine.engine.run()
    assert run[-1] == "--resume"
    assert f"--mount=type=bind,source={reading},destination={reading},ro=true" in run
    assert f"--mount=type=bind,source={writing},destination={writing}" in run
    guidance = machine.engine.guidance or ""
    assert "## Lent to this launch" in guidance
    assert f"- `{reading}`, read-only." in guidance
    assert f"- `{writing}`, which you may write." in guidance


def test_the_command_refuses_to_lend_what_s_neither_a_directory_nor_a_module(
    project: Path, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = Machine(tmp_path, clock)
    monkeypatch.setattr(cli, "adapters", stubbed(machine))
    monkeypatch.setattr(cli, "launching", machine.launching)

    named = runner.invoke(
        cli.app, ["launch", "claude", "--mount", str(tmp_path / "nowhere")]
    )
    writable = runner.invoke(
        cli.app, ["launch", "claude", "--mount-rw", str(tmp_path / "nowhere")]
    )

    assert isinstance(named.exception, LaunchError)
    assert str(named.exception) == (
        f"`--mount {tmp_path / 'nowhere'}` names neither a directory nor a "
        "module whose data a launch lends: those are transcripts"
    )
    assert writable.exit_code == 2


def test_transcripts_are_mounted_and_told_in_every_launch(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    common = (
        run(
            "git",
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            cwd=project,
        )
        .text()
        .strip()
    )
    kept = Machine(tmp_path / "plain", clock)
    plain = cli.launched(kept.adapter, [], project, kept.launcher)
    lending = Machine(tmp_path / "lending", clock)
    lent = cli.launched(
        lending.adapter, [], project, lending.launcher, modules=["transcripts"]
    )

    assert (plain, lent) == (7, 7)
    for machine in [kept, lending]:
        data = machine.layout.module_data("transcripts", Path(common))
        assert f"--mount=type=bind,source={data},destination={data},ro=true" in (
            machine.engine.run()
        )
        guidance = machine.engine.guidance or ""
        assert (
            f"# Past sessions\n\nEvery session of this repository is kept, whole, at "
            f"`{data}`"
        ) in guidance
        assert "lup-dev transcripts search" in guidance


def test_the_command_refuses_inside_an_agents_session(
    project: Path, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = Machine(tmp_path, clock)
    monkeypatch.setattr(cli, "adapters", stubbed(machine))
    monkeypatch.setattr(cli, "launching", machine.launching)
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")

    result = runner.invoke(cli.app, ["launch", "claude"])

    assert isinstance(result.exception, LaunchError)
    assert "inside a claude session" in str(result.exception)
    assert machine.events.said == []


def test_the_command_names_the_runtimes_it_knows(
    project: Path, tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = Machine(tmp_path, clock)
    monkeypatch.setattr(cli, "adapters", stubbed(machine))
    monkeypatch.setattr(cli, "launching", machine.launching)

    result = runner.invoke(cli.app, ["launch", "other"])

    assert result.exit_code != 0
    assert "no runtime named `other`" in result.output
    assert machine.events.said == []


# The hook in the room


def test_the_hook_pipes_the_payload_to_the_launchs_socket() -> None:
    program, flag, script = piped(events.CallStarted, timedelta(hours=25))

    assert [program, flag] == ["sh", "-c"]
    piping, *_ = script.splitlines()
    assert shlex.split(piping)[:7] == [
        "answer=$(socat",
        "-t",
        "90000",
        "-",
        "UNIX-CONNECT:/run/lup/hook.sock,retry=120,interval=0.5",
        "&&",
        "echo",
    ]


def test_the_hook_waits_for_the_service_as_long_as_lups_bridge_does() -> None:
    _, _, script = piped(events.CallStarted)
    _, options = shlex.split(script.splitlines()[0])[4].split(",", 1)
    bridge = Bridge(Path("/run/lup/mcp.sock"), io.StringIO())

    assert options == "retry=120,interval=0.5"
    assert bridge.retry == 0.5
    assert bridge.patience == 120 * 0.5


def socat(tmp_path: Path, script: str) -> Path:
    """A stand-in `socat` on its own `PATH`: it logs its arguments, and runs `script`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "socat"
    fake.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/arguments"\n{script}\n')
    fake.chmod(0o755)
    return bin_dir


def hook(
    path: Path, payload: str, event: type[SessionEvent] = events.CallStarted
) -> Ran:
    program, *arguments = piped(event)
    return run(
        program,
        *arguments,
        stdin=payload,
        env={"PATH": f"{path}:/usr/bin:/bin"},
        checked=False,
    )


def test_the_hook_prints_the_answer_unchanged(tmp_path: Path) -> None:
    path = socat(tmp_path, 'cat > "$0.payload"\nprintf \'{"answer": 1}\\n\\n\'')
    ran = hook(path, '{"hook_event_name": "SessionStart"}')

    assert ran.status == 0
    assert ran.output.decode() == '{"answer": 1}\n\n'
    assert ran.error.decode() == ""
    assert (tmp_path / "arguments").read_text() == (
        "-t 90000 - UNIX-CONNECT:/run/lup/hook.sock,retry=120,interval=0.5\n"
    )
    assert json.loads((path / "socat.payload").read_text()) == {
        "hook_event_name": "SessionStart"
    }


UNREACHED = (
    "lup: this hook couldn't reach lup's host service on /run/lup/hook.sock, so it "
    "wasn't judged. On the host, `lup-dev host` serves this session again."
)


@pytest.mark.parametrize("status", [1, 2, 127])
def test_a_hook_that_cant_reach_the_service_ends_with_status_1_and_says_why(
    tmp_path: Path, status: int
) -> None:
    path = socat(tmp_path, f"echo 'socat: connect failed' >&2\nexit {status}")
    ran = hook(path, "{}")

    assert ran.status == 1
    assert ran.output.decode() == ""
    assert ran.error.decode().splitlines() == ["socat: connect failed", UNREACHED]


GONE = (
    "lup: the host service went away before it answered this hook, as it does when "
    "it restarts,"
)
HELD = (
    "A write lup held for the operator's review stays held, and their answer "
    "reaches you at a later call."
)


@pytest.mark.parametrize(
    ("event", "status", "said"),
    [
        (
            events.CallStarted,
            2,
            f"{GONE} so this call didn't run: make it again. {HELD}",
        ),
        (
            events.CallFinished,
            2,
            f"{GONE} so what was written is judged at your next call. {HELD}",
        ),
        (
            events.TurnEnded,
            2,
            f"{GONE} so what was written is judged at your next call. {HELD}",
        ),
        (
            events.ConversationEnded,
            2,
            f"{GONE} so what was written is judged at your next call. {HELD}",
        ),
        (events.SessionStarted, 1, f"{GONE} so its answer was lost."),
        (events.TurnStarted, 1, f"{GONE} so its answer was lost."),
    ],
)
def test_a_hook_whose_connection_ends_unanswered_fails_saying_why(
    tmp_path: Path, event: type[SessionEvent], status: int, said: str
) -> None:
    """`socat` ends with status 0 and nothing printed where the service closes the
    connection, exits or is killed while the hook waits (`docs/field-notes.md`,
    *The room's hook when the service goes away*), and the service answers every
    hook with something: this is a lost connection, never no decision. Status 2
    keeps a write from landing unreviewed and tells the agent; at a session's or
    a turn's start, 1, which drops no prompt."""
    path = socat(tmp_path, "cat > /dev/null")
    ran = hook(path, "{}", event)

    assert ran.status == status
    assert ran.output.decode() == ""
    assert ran.error.decode().splitlines() == [said]


SERVICE = """
import os, signal, socket, sys
path, mode = sys.argv[1:]
listening = socket.socket(socket.AF_UNIX)
listening.bind(path)
listening.listen()
print("listening", flush=True)
connection, _ = listening.accept()
while connection.recv(65536):
    pass
print("read", flush=True)
match mode:
    case "close":
        connection.close()
        signal.pause()
    case "exit":
        os._exit(0)
    case "killed":
        signal.pause()
"""
"""A stand-in host service, a process of its own: it reads a hook's payload to
its end, then closes the connection, exits with it open, or waits to be killed."""


STAND_IN = """
import socket, sys
connection = socket.socket(socket.AF_UNIX)
try:
    connection.connect({socket!r})
except OSError as failed:
    sys.exit(f"socat: connect failed: {{failed}}")
connection.sendall(sys.stdin.buffer.read())
connection.shutdown(socket.SHUT_WR)
try:
    while chunk := connection.recv(65536):
        sys.stdout.buffer.write(chunk)
except ConnectionResetError as reset:
    sys.exit(f"socat: read: {{reset}}")
"""
"""`socat` as the room's hook runs it, on a socket of the test's: the payload sent
and the write side shut, the answer printed until the connection ends, which is
status 0 however it ends but a reset, as the real one was found to do."""


@pytest.mark.parametrize("mode", ["close", "exit", "killed"])
def test_a_hook_the_service_leaves_unanswered_mid_wait_fails_closed(
    tmp_path_factory: pytest.TempPathFactory, mode: str
) -> None:
    # A socket's path is limited in length, so its directory is short.
    base = tmp_path_factory.mktemp("hook")
    hook_socket = base / "hook.sock"
    bin_dir = base / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "socat"
    fake.write_text(f"#!{sys.executable}\n{STAND_IN.format(socket=str(hook_socket))}")
    fake.chmod(0o755)
    service = subprocess.Popen(
        [sys.executable, "-c", SERVICE, str(hook_socket), mode],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert service.stdout is not None
        assert service.stdout.readline() == "listening\n"
        program, *arguments = piped(events.CallStarted)
        room = subprocess.Popen(
            [program, *arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        )
        assert room.stdin is not None
        room.stdin.write(b'{"hook_event_name": "PreToolUse"}')
        room.stdin.close()
        assert service.stdout.readline() == "read\n"
        if mode == "killed":
            service.kill()
        assert room.stdout is not None
        assert room.stderr is not None
        output, error = room.stdout.read(), room.stderr.read()
        status = room.wait()
    finally:
        service.kill()
        service.wait()
    assert (status, output) == (2, b"")
    assert error.decode().splitlines() == [
        f"{GONE} so this call didn't run: make it again. {HELD}"
    ]


# What's trusted, and the session's settings


def test_a_linked_worktree_trusts_its_repositorys_main_worktree(
    project: Path, tmp_path: Path, shell: Shell
) -> None:
    linked = tmp_path / "repos" / "feat"
    shell.git(project, "worktree", "add", "-q", "-b", "feat", str(linked))

    assert trusted(project) == [project]
    assert trusted(linked) == [linked, project]


def test_the_session_settings_are_cores_in_the_librarys_terms() -> None:
    choices = resolve(Project()).session

    assert session_settings(choices) == SessionParts(
        declared=SessionSettings(),
        defaults=SessionSettings(
            subagent_cache=timedelta(hours=1),
            auto_memory=False,
            idle_compaction=False,
            removed_tools=choices.removed_tools,
            account_connectors=False,
        ),
    )
    five = choices.model_copy(update={"subagent_cache": "5m", "auto_memory": True})
    assert session_settings(five).defaults.subagent_cache == timedelta(minutes=5)
    assert session_settings(five).defaults.auto_memory


def test_each_session_setting_is_named_as_the_library_names_it() -> None:
    assert list(SessionSettings.model_fields) == list(Session.model_fields)


def declaring(session: Session) -> Project:
    """A project whose declaration changes `Core`'s session settings."""
    return Project(modules=Modules.default().edit(Core(session=session)))


def test_the_fields_a_project_declares_are_imposed_and_the_rest_are_defaults() -> None:
    parts = session_settings(resolve(declaring(Session(auto_memory=False))).session)

    assert parts.declared == SessionSettings(auto_memory=False)
    assert parts.defaults == SessionSettings(
        subagent_cache=timedelta(hours=1),
        idle_compaction=False,
        removed_tools=SessionDefaults().removed_tools,
        account_connectors=False,
    )


def test_a_launch_imposes_what_the_project_declares_and_its_defaults_yield_to_the_operator_s(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"autoMemoryEnabled": True, "disableClaudeAiConnectors": False})
    )
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        "[features]\nmemories = true\napps = true\n"
    )
    launch = tmp_path / "launch"
    parts = session_settings(resolve(declaring(Session(auto_memory=False))).session)
    given = TerminalSettings(
        directory=launch,
        cli=Cli(program=Path("/opt/cli")),
        session=parts.declared,
        defaults=parts.defaults,
    )

    on_claude = json.loads(lup.Claude().terminal(given).files[launch / "settings.json"])
    on_codex = lup.Codex().terminal(given).command

    assert on_claude["env"] == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "1h",
    }
    assert "disableClaudeAiConnectors" not in on_claude
    assert on_claude["idleCompaction"] is False
    assert "features.memories=false" in on_codex
    assert not any(argument.startswith("features.apps") for argument in on_codex)


QUIET = '''"""This person's own values, and the repository beside the project."""

from pathlib import Path

from lup_dev import Module, Modules, Private, Project, Repositories, Repository, Values


class Mine(Module):
    """The repository beside the project, as this person has it."""

    name = "mine"

    repositories: Repositories = Repositories.of(
        Repository(name="atlas", path=Path("atlas.git"), about="a neighbour"),
    )


project = Project(
    modules=Modules().add(Mine()).edit(Private(values=Values().add("Kestrel Labs")))
)
'''


def test_a_launch_keeps_the_list_of_private_values_where_its_module_reads_it(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock, local=QUIET)

    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7

    kept = read_model(
        withheld_kept(machine.layout.module_data("private", project / ".git")),
        Withheld,
    )
    assert kept is not None
    texts = {each.kind: each.text for each in kept.held}
    assert texts["value"] == "Kestrel Labs"
    assert texts["user"] == "op"
    assert texts["private-repository"] == "atlas"
    assert str(project / ".git") in [each.text for each in kept.held]
    assert not [each for each in machine.events.said if "Kestrel" in each]


def test_a_launch_whose_declaration_drops_private_keeps_no_list(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock)
    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7
    kept = withheld_kept(machine.layout.module_data("private", project / ".git"))
    assert kept.is_file()
    machine.local = (
        '"""Not this one."""\n\nfrom lup_dev import Modules, Project\n\n'
        'project = Project(modules=Modules().drop("private", why="a scratch copy"))\n'
    )
    assert cli.launched(machine.adapter, [], project, machine.launcher) == 7
    assert not kept.exists()
