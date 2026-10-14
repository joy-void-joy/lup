"""A launch, its whole flow with every seam stubbed: trust, the host service's client, the CLI's channel, podman and the room's tools.

git runs for real on the test's repositories, with the operator's own git
configuration kept out. No test runs podman, reaches the network or a real host
service, or reads the clock; the hook command runs under `sh` with a stand-in
`socat`.
"""

import json
import shlex
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
import sh
from filelock import FileLock
from typer.testing import CliRunner

import lup
from lup.rooms.engine import Exited, Podman, Process
from lup.sessions.terminal import Cli, SessionSettings, TerminalSettings, ToolServer
from lup_dev import Core, Modules, Project, Session, cli
from lup_dev.adapters import Adapter, claude, codex
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.catalog.room import SessionDefaults
from lup_dev.declaration.requirements import Printed, Tools
from lup_dev.declaration.resolve import resolve
from lup_dev.forge.github import GitHubError
from lup_dev.host.client import HostClient, Starter
from lup_dev.host.protocol import GitHubRepository, HostError, Limits, Register
from lup_dev.launch.clis import Channel, ChannelError
from lup_dev.launch.guidance import OPENING
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
from lup_dev.settings import TerminalVariables
from lup_dev.stored import write_model

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx
    from conftest import FakeClock, Shell

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
    def register(self, launch: Register) -> Path:
        self.events.record(f"register {launch.runtime} {launch.container}")
        self.served.append(launch)
        return self.sockets

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

    def __call__(self, process: Process) -> Exited:
        self.processes.append(process)
        program, command, *rest = process.arguments
        assert program == "podman"
        match [command, *rest]:
            case ["image", "exists", _]:
                self.record("image")
                return Exited(status=0)
            case ["container", "exists", name]:
                self.record(f"container {name}")
                return Exited(status=1 if name in self.gone else 0)
            case ["run", *_]:
                self.record("run")
                return Exited(status=self.ran)
            case _:
                message = f"podman asked {process.arguments}"
                raise AssertionError(message)

    def run(self) -> list[str]:
        [ran] = [
            each.arguments for each in self.processes if each.arguments[1] == "run"
        ]
        return ran


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
    ) -> None:
        self.events = Events()
        self.unnamed = unnamed
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
        )
        self.adapter = claude.adapter().model_copy(
            update={"channel": Offline(events=self.events)}
        )

    def trust(self, root: Path) -> Outcome:
        self.events.record("trust")
        commit = sh.git("rev-parse", "dev", _cwd=str(root)).strip()
        common = Path(
            sh.git(
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
                _cwd=str(root),
            ).strip()
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
        )
        write_model(self.layout.approved(common), approval)
        return Unchanged(commit=commit, approval=approval)

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
    project: Path, tmp_path: Path, clock: FakeClock
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
    [registered] = [each for each in said if each.startswith("register ")]
    container = registered.removeprefix("register claude ")
    launch = container.removeprefix("lup-")
    assert [each for each in said if not each.startswith("The host zone")] == [
        "trust",
        "found podman",
        "found gh",
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
                "read-issues",
                "file-issue",
                "comment",
                "draft-pull-request",
            ],
            protected=["refs/heads/main", "refs/tags/*", "refs/heads/release/*"],
        ),
        github=GitHubRepository(owner="someone", name="work"),
    )
    run = machine.engine.run()
    assert f"--name={container}" in run
    assert f"--mount=type=bind,source={machine.sockets},destination=/run/lup" in run
    assert run[-1] == "--resume"
    assert str(machine.layout.clis("claude").version("2.1.300") / "cli") in run


def test_a_launch_compiles_the_approved_declarations_guidance_and_hooks(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    (project / "AGENTS.md").write_text("# The project\n\nUncommitted.\n")
    (project / "AGENTS.local.md").write_text("Mine.\n")
    commit = sh.git("rev-parse", "dev", _cwd=str(project)).strip()
    directory = tmp_path / "launch"
    hooks = hooked(claude.hooks)

    with approved_declaration(project, commit) as declared:
        settings = terminal_settings(
            declared, project, directory, Cli(program=Path("/opt/cli")), hooks
        )
        exported = declared.root
        choices = declared.resolved.session
        own = [section.name for section in declared.resolved.guidance]
    assert not exported.exists()

    assert own[-1] == "own"
    assert settings.directory == directory
    assert settings.cli == Cli(program=Path("/opt/cli"))
    assert settings.hooks == claude.hooks(piped(), timedelta(hours=25))
    assert settings.servers == [
        ToolServer(
            name="lup",
            socket=Path("/run/lup/mcp.sock"),
            timeout=timedelta(hours=25),
        )
    ]
    assert settings.trusted == [project]
    assert settings.session == session_settings(choices).declared
    assert settings.defaults == session_settings(choices).defaults
    guidance = settings.guidance or ""
    assert guidance.startswith(OPENING)
    assert "# The room" in guidance
    assert "As committed." in guidance
    assert "Uncommitted." not in guidance
    assert guidance.endswith("Mine.\n")


def test_a_launch_without_gh_says_so_once_and_names_no_repository(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock, missing=["gh"])

    cli.launched(machine.adapter, [], project, machine.launcher)

    said = machine.events.said
    off = [each for each in said if "gh" in each and not each.startswith("found")]
    assert off == [
        (
            "Off: `gh`, for `lup-dev launch` (reaches GitHub with your login for "
            "lup's GitHub tools, and for the gate's issue states in a room): not on "
            "the `PATH`. Install: your system's `github-cli` package, then `gh auth "
            "login`."
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


def test_the_registration_ends_when_the_cli_fails(
    project: Path, tmp_path: Path, clock: FakeClock
) -> None:
    machine = Machine(tmp_path, clock, ran=125)

    with pytest.raises(Exception, match="status 125"):
        cli.launched(machine.adapter, [], project, machine.launcher)

    said = machine.events.said
    [registered] = [each for each in said if each.startswith("register ")]
    launch = registered.removeprefix("register claude lup-")
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
    program, flag, script = piped(timedelta(hours=25))

    assert [program, flag] == ["sh", "-c"]
    assert shlex.split(script) == [
        "socat",
        "-t",
        "90000",
        "-",
        "UNIX-CONNECT:/run/lup/hook.sock",
        "||",
        "{",
        "echo",
        (
            "lup: this hook couldn't reach lup's host service on /run/lup/hook.sock, "
            "so it wasn't judged. On the host, `lup-dev host` serves this session "
            "again."
        ),
        ">&2;",
        "exit",
        "1;",
        "}",
    ]


def socat(tmp_path: Path, script: str) -> Path:
    """A stand-in `socat` on its own `PATH`: it logs its arguments, and runs `script`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "socat"
    fake.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/arguments"\n{script}\n')
    fake.chmod(0o755)
    return bin_dir


def hook(path: Path, payload: str) -> sh.RunningCommand:
    program, *arguments = piped()
    return sh.Command(program)(
        *arguments,
        _in=payload,
        _env={"PATH": f"{path}:/usr/bin:/bin"},
        _ok_code=list(range(256)),
        _return_cmd=True,
    )


def test_the_hook_prints_the_answer_unchanged(tmp_path: Path) -> None:
    path = socat(tmp_path, 'cat > "$0.payload"\nprintf \'{"answer": 1}\\n\'')
    ran = hook(path, '{"hook_event_name": "SessionStart"}')

    assert ran.exit_code == 0
    assert ran.stdout.decode() == '{"answer": 1}\n'
    assert ran.stderr.decode() == ""
    assert (tmp_path / "arguments").read_text() == (
        "-t 90000 - UNIX-CONNECT:/run/lup/hook.sock\n"
    )
    assert json.loads((path / "socat.payload").read_text()) == {
        "hook_event_name": "SessionStart"
    }


@pytest.mark.parametrize("status", [1, 2, 127])
def test_a_hook_that_cant_reach_the_service_ends_with_status_1_and_says_why(
    tmp_path: Path, status: int
) -> None:
    path = socat(tmp_path, f"echo 'socat: connect failed' >&2\nexit {status}")
    ran = hook(path, "{}")

    assert ran.exit_code == 1
    assert ran.stdout.decode() == ""
    assert ran.stderr.decode().splitlines() == [
        "socat: connect failed",
        (
            "lup: this hook couldn't reach lup's host service on /run/lup/hook.sock, "
            "so it wasn't judged. On the host, `lup-dev host` serves this session "
            "again."
        ),
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
