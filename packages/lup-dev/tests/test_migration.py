"""Moving a repository's records from the operator's own runtime directory into its rooms' home: each file kept as it is, nothing followed through a link, nothing removed that isn't moved.

The operator's directory and the home here are directories the tests write; no
test reads the operator's own.
"""

import errno
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest
from filelock import FileLock
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.accounts import AccountError
from lup_dev.adapters import Adapter, claude, codex
from lup_dev.adapters.claude import ClaudeRecords, ClaudeWritten, folder_named
from lup_dev.adapters.codex import CodexRecords, CodexWritten
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.host.homes import Found, home_of
from lup_dev.host.homes import kept as hostkept
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.records import Record
from lup_dev.host.written import Places
from lup_dev.layout import Layout
from lup_dev.migration import (
    HostRuntime,
    Left,
    Migrating,
    Migration,
    MigrationError,
    Moved,
    running_launches,
)
from lup_dev.stored import write_model

runner = CliRunner()

FOLDER = PurePosixPath("projects", "-w-lup-git-tree-dev")
HISTORY = PurePosixPath("file-history", "s1")


def written(path: Path, text: str, *, mtime: int = 1_700_000_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, ns=(mtime * 10**9, mtime * 10**9))
    return path


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    """An operator's runtime directory with one session's records of the repository: its record, a subagent's, and its file history."""
    directory = tmp_path / "operator"
    written(directory / FOLDER / "s1.jsonl", '{"cwd": "/w/lup.git/tree/dev"}\n')
    written(directory / FOLDER / "s1" / "subagents" / "agent-a1.jsonl", "{}\n")
    written(directory / HISTORY / "f@v1", "before")
    return directory


def migration(directory: Path, home: Path) -> Migration:
    return Migration(
        runtime="made-up",
        directory=directory,
        home=home,
        records=[
            Record(home=directory, whose="host", place=FOLDER),
            Record(home=directory, whose="host", place=HISTORY),
        ],
    )


def test_a_dry_run_says_what_would_move_and_changes_nothing(
    directory: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    moved = migration(directory, home).moved(dry=True)
    assert moved == [
        Moved(
            place=FOLDER,
            files=2,
            size=34,
            placed=[
                FOLDER / "s1" / "subagents" / "agent-a1.jsonl",
                FOLDER / "s1.jsonl",
            ],
        ),
        Moved(place=HISTORY, files=1, size=6, placed=[HISTORY / "f@v1"]),
    ]
    assert not home.exists()
    assert (directory / FOLDER / "s1.jsonl").is_file()


def test_each_record_moves_into_the_home_as_the_same_file_its_times_kept(
    directory: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    record = directory / FOLDER / "s1.jsonl"
    before = record.stat()
    moved = migration(directory, home).moved(dry=False)
    assert [each.left for each in moved] == [[], []]
    landed = (home / FOLDER / "s1.jsonl").stat()
    assert (landed.st_ino, landed.st_mtime_ns, landed.st_atime_ns) == (
        before.st_ino,
        before.st_mtime_ns,
        before.st_atime_ns,
    )
    assert (home / FOLDER / "s1" / "subagents" / "agent-a1.jsonl").read_text() == "{}\n"
    assert (home / HISTORY / "f@v1").read_text() == "before"
    # Emptied, each record's directory goes; the directories holding them stay.
    assert sorted(each.name for each in (directory / "projects").iterdir()) == []
    assert (directory / "file-history").is_dir()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_on_another_filesystem_a_record_is_copied_its_mode_and_times_kept(
    directory: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def across(*arguments: object, **named: object) -> None:
        del arguments, named
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", across)
    record = directory / FOLDER / "s1.jsonl"
    record.chmod(0o640)
    before = record.stat()
    home = tmp_path / "home"
    migration(directory, home).moved(dry=False)
    landed = (home / FOLDER / "s1.jsonl").stat()
    assert (landed.st_mtime_ns, landed.st_atime_ns, stat.S_IMODE(landed.st_mode)) == (
        before.st_mtime_ns,
        before.st_atime_ns,
        0o640,
    )
    assert (
        home / FOLDER / "s1.jsonl"
    ).read_text() == '{"cwd": "/w/lup.git/tree/dev"}\n'
    assert not record.exists()


def test_a_link_aimed_inside_what_moves_is_aimed_at_its_place_in_the_home(
    directory: Path, tmp_path: Path
) -> None:
    # A resumed session's subagents are links to the first session's records.
    subagents = directory / FOLDER / "s2" / "subagents"
    subagents.mkdir(parents=True)
    first = directory / FOLDER / "s1" / "subagents" / "agent-a1.jsonl"
    (subagents / "agent-a1.jsonl").symlink_to(first)
    (subagents / "agent-a2.jsonl").symlink_to(
        Path("..", "..", "s1", "subagents", "agent-a1.jsonl")
    )
    home = tmp_path / "home"
    moved = migration(directory, home).moved(dry=False)
    assert moved[0].links == 2
    landed = home / FOLDER / "s2" / "subagents"
    assert (landed / "agent-a1.jsonl").readlink() == (
        home / FOLDER / "s1" / "subagents" / "agent-a1.jsonl"
    )
    assert (landed / "agent-a2.jsonl").readlink() == Path(
        "..", "..", "s1", "subagents", "agent-a1.jsonl"
    )
    assert (landed / "agent-a2.jsonl").read_text() == "{}\n"


def test_a_link_aimed_out_of_what_moves_is_left_never_followed(
    directory: Path, tmp_path: Path
) -> None:
    secret = written(tmp_path / "ssh" / "id_ed25519", "the operator's key")
    planted = directory / FOLDER / "s1" / "leak.txt"
    planted.symlink_to(secret)
    home = tmp_path / "home"
    [folder, _] = migration(directory, home).moved(dry=False)
    assert folder.left == [
        Left(
            place=FOLDER / "s1" / "leak.txt",
            why=(
                f"a link to {secret}, out of what moves: left, never followed, as "
                "a room could have made it"
            ),
        )
    ]
    assert planted.is_symlink()
    assert not (home / FOLDER / "s1" / "leak.txt").exists()
    assert [path.name for path in home.rglob("*") if path.is_file()].count(
        "id_ed25519"
    ) == 0


def test_what_the_home_holds_already_stays_and_so_does_what_would_go_there(
    directory: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    theirs = written(home / FOLDER / "s1.jsonl", "a room's own")
    (home / "file-history").mkdir(parents=True)
    (home / HISTORY).symlink_to(tmp_path / "elsewhere")
    [folder, history] = migration(directory, home).moved(dry=False)
    assert folder.left == [
        Left(
            place=FOLDER / "s1.jsonl",
            why="the rooms' home holds one there already: left",
        )
    ]
    assert folder.files == 1
    assert history.left == [
        Left(
            place=HISTORY,
            why=(
                "the rooms' home holds something other than a directory there: "
                "left, with what's in it"
            ),
        )
    ]
    assert theirs.read_text() == "a room's own"
    assert (directory / FOLDER / "s1.jsonl").is_file()
    assert (directory / HISTORY / "f@v1").read_text() == "before"
    assert not (tmp_path / "elsewhere").exists()


def test_a_pipe_is_left_never_waited_on(directory: Path, tmp_path: Path) -> None:
    os.mkfifo(directory / FOLDER / "s9.jsonl")
    [folder, _] = migration(directory, tmp_path / "home").moved(dry=False)
    assert folder.left == [
        Left(
            place=FOLDER / "s9.jsonl",
            why="not a file, a directory or a link, as no record is: left",
        )
    ]
    assert stat.S_ISFIFO((directory / FOLDER / "s9.jsonl").lstat().st_mode)


def test_a_record_reached_through_a_link_on_its_way_is_left(tmp_path: Path) -> None:
    directory = tmp_path / "operator"
    elsewhere = written(tmp_path / "elsewhere" / FOLDER.name / "s1.jsonl", "{}\n")
    directory.mkdir()
    (directory / "projects").symlink_to(elsewhere.parent.parent)
    home = tmp_path / "home"
    [moved] = Migration(
        runtime="made-up",
        directory=directory,
        home=home,
        records=[Record(home=directory, whose="host", place=FOLDER)],
    ).moved(dry=False)
    assert moved == Moved(
        place=FOLDER,
        left=[
            Left(
                place=FOLDER,
                why="`projects` on its way isn't a directory of its own: left",
            )
        ],
    )
    assert elsewhere.is_file()


def test_a_move_stopped_between_a_file_s_two_names_finishes(
    directory: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / FOLDER).mkdir(parents=True)
    os.link(directory / FOLDER / "s1.jsonl", home / FOLDER / "s1.jsonl")
    [folder, _] = migration(directory, home).moved(dry=False)
    assert (folder.files, folder.left) == (2, [])
    assert not (directory / FOLDER / "s1.jsonl").exists()


def test_a_home_that_isn_t_a_directory_of_its_own_takes_nothing(
    directory: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.symlink_to(tmp_path / "operator")
    with pytest.raises(MigrationError, match="isn't a directory of its own"):
        migration(directory, home).moved(dry=False)
    assert (directory / FOLDER / "s1.jsonl").is_file()


def test_a_launch_of_the_repository_runs_while_its_launcher_holds_its_lock(
    tmp_path: Path,
) -> None:
    layout = Layout(state=tmp_path / "state", runtime=tmp_path / "runtime")
    repository = tmp_path / "lup.git"

    def recorded(launch: str, of: Path) -> Register:
        registered = Register(
            launch=launch,
            runtime="made-up",
            worktree=of / "tree" / "dev",
            repository=of,
            judge=tmp_path / "judge",
            limits=Limits(actions=[], protected=[]),
            github=None,
        )
        layout.host.launches.mkdir(parents=True, exist_ok=True)
        layout.host.record(launch).write_text(registered.model_dump_json())
        layout.launch(launch).lock.parent.mkdir(parents=True, exist_ok=True)
        return registered

    held = recorded("held", repository)
    recorded("gone", repository)
    recorded("other", tmp_path / "other.git")
    layout.launch("gone").lock.touch()
    lock = FileLock(layout.launch("held").lock)
    other = FileLock(layout.launch("other").lock)
    with lock, other:
        assert running_launches(layout, repository) == [held]
    assert running_launches(layout, repository) == []


# The whole command: a repository's records of each runtime moved into its
# rooms' home, what stays said once, and what a host session acts on checked.


def on(adapter: Adapter, directory: Path) -> Adapter:
    """`adapter` with the operator's own directory at `directory`, its records and its check there."""
    match adapter.runtime.name():
        case "claude":
            records: ClaudeRecords | CodexRecords = ClaudeRecords(directory=directory)
            check = ClaudeWritten(directory=directory).checked
        case _:
            records = CodexRecords(home=directory)
            check = CodexWritten(home=directory).checked
    return adapter.model_copy(
        update={"directory": directory, "records": records, "written": check}
    )


@pytest.fixture
def operator(tmp_path: Path) -> Path:
    """The operator's home, holding their own runtime directories."""
    return tmp_path / "operator-home"


@pytest.fixture
def adapters(operator: Path) -> list[Adapter]:
    return [
        on(claude.adapter(), operator / ".claude"),
        on(codex.adapter(), operator / ".codex"),
    ]


@pytest.fixture
def hosts(adapters: list[Adapter]) -> list[HostRuntime]:
    return [
        HostRuntime(
            name=each.runtime.name(),
            directory=each.directory,
            records=each.records,
            written=each.written,
            recorded=each.recorded,
        )
        for each in adapters
    ]


def sessions_of(bare: Path, operator: Path) -> Path:
    """Write one session of the repository's worktree into the operator's own directory, beside another directory's; return the repository's folder."""
    worktree = bare / "tree" / "main"
    directory = operator / ".claude"
    ours = directory / "projects" / folder_named(worktree)
    written(ours / "s1.jsonl", json.dumps({"cwd": str(worktree)}) + "\n")
    written(directory / "file-history" / "s1" / "f@v1", "before")
    written(directory / "projects" / "-w-other" / "s2.jsonl", '{"cwd": "/w/other"}\n')
    return ours


def test_a_repository_s_sessions_move_into_its_rooms_home_and_the_rest_stay(
    bare: Path, state: Layout, operator: Path, hosts: list[HostRuntime]
) -> None:
    ours = sessions_of(bare, operator)
    size = (ours / "s1.jsonl").stat().st_size + len("before")
    migrating = Migrating(layout=state, repository=bare, runtimes=hosts, home=operator)
    home = state.room_home(bare, "claude", shared=False)
    dry = migrating.said(move=False)
    stays = (
        "Records of other directories stay in ~/.claude as they are, 1 record: "
        "every room could write those too, so a session resumed from one on the "
        "host resumes what a room may have changed."
    )
    assert dry[:7] == [
        (
            "A dry run: nothing moves until `lup-dev account migrate --move`. End "
            "every session of this repository first, in a room or on the host: one "
            "still running writes on where its record was."
        ),
        (
            f"claude: 2 records of this repository's sessions, 2 files and {size} B, "
            f"would move from ~/.claude into {home}, where its rooms resume them:"
        ),
        f"- projects/{ours.name}: 1 file, {size - 6} B",
        "- file-history/s1: 1 file, 6 B",
        "The host would read its session there from then on, as a room resuming it does.",
        stays,
        "codex: ~/.codex isn't there, so nothing of it moves.",
    ]
    assert not home.exists()
    moved = migrating.said(move=True)
    assert moved[0] == (
        f"claude: 2 records of this repository's sessions, 2 files and {size} B, "
        f"moved from ~/.claude into {home}, where its rooms resume them:"
    )
    assert moved[-1] == (
        "Resume one in a room with `lup-dev launch <runtime> --resume <id>`, or "
        "`--resume` for the picker."
    )
    assert (home / "projects" / ours.name / "s1.jsonl").is_file()
    assert (home / "file-history" / "s1" / "f@v1").read_text() == "before"
    assert (operator / ".claude" / "projects" / "-w-other" / "s2.jsonl").is_file()
    assert not ours.exists()
    # Moved, the operator's directory holds none of the session, and the
    # migration keeps its home, so the host reads it there, as a room resuming
    # it has it, and a room of another project naming it first can't claim it.
    assert not ClaudeRecords(directory=operator / ".claude").held("s1")
    assert ClaudeRecords(directory=operator / ".claude", host=state.host).conversation(
        "s1", None
    ) == Found(record=home / "projects" / ours.name / "s1.jsonl", root=home)
    elsewhere = state.homes.project(Path("/w/other.git"), "claude")
    hostkept(state.host, "claude", "s1", elsewhere)
    assert home_of(state.host, "claude", "s1") == home


def test_a_session_whose_record_stays_with_the_operator_keeps_no_home(
    bare: Path, state: Layout, operator: Path, hosts: list[HostRuntime]
) -> None:
    ours = sessions_of(bare, operator)
    home = state.room_home(bare, "claude", shared=False)
    written(home / "projects" / ours.name / "s1.jsonl", "a room's own\n")
    Migrating(layout=state, repository=bare, runtimes=hosts, home=operator).said(
        move=True
    )
    assert (ours / "s1.jsonl").is_file()
    assert home_of(state.host, "claude", "s1") is None
    assert ClaudeRecords(directory=operator / ".claude", host=state.host).conversation(
        "s1", None
    ) == Found(record=ours / "s1.jsonl", root=operator / ".claude")


def test_a_move_waits_on_each_launch_of_the_repository_still_running(
    bare: Path,
    state: Layout,
    operator: Path,
    hosts: list[HostRuntime],
    tmp_path: Path,
) -> None:
    ours = sessions_of(bare, operator)
    state = state.model_copy(update={"runtime": tmp_path / "runtime"})
    registered = Register(
        launch="main",
        runtime="claude",
        worktree=bare / "tree" / "main",
        repository=bare,
        judge=bare / "judge",
        limits=Limits(actions=[], protected=[]),
        github=None,
        name="handoff",
    )
    state.host.launches.mkdir(parents=True)
    state.host.record("main").write_text(registered.model_dump_json())
    state.launch("main").lock.parent.mkdir(parents=True)
    migrating = Migrating(layout=state, repository=bare, runtimes=hosts, home=operator)
    with FileLock(state.launch("main").lock):
        assert (
            f"Still running: `handoff`, claude in {bare / 'tree' / 'main'}, which "
            "`--move` waits on."
        ) in migrating.said(move=False)
        with pytest.raises(MigrationError, match="still runs, `handoff`"):
            migrating.said(move=True)
    assert (ours / "s1.jsonl").is_file()


def test_the_command_is_the_operator_s_in_their_own_terminal_on_an_approved_repository(
    bare: Path,
    state: Layout,
    operator: Path,
    adapters: list[Adapter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions_of(bare, operator)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(operator.parent / "run"))
    monkeypatch.chdir(bare / "tree" / "main")
    monkeypatch.setattr(cli, "adapters", lambda: adapters)
    unapproved = runner.invoke(cli.app, ["account", "migrate"])
    assert isinstance(unapproved.exception, AccountError)
    assert "nothing is approved for" in str(unapproved.exception)
    write_model(
        state.approved(bare),
        Approval(
            commit="0" * 40,
            fingerprint="approved",
            paths=[Path("lup_project.py")],
            tool=ReleaseTool(
                name="lup-dev", version="0.4.0", registry="index", pins={}
            ),
            time=datetime(2026, 10, 28, tzinfo=UTC),
        ),
    )
    dry = runner.invoke(cli.app, ["account", "migrate"])
    assert dry.exit_code == 0, dry.output
    assert dry.output.startswith("A dry run")
    moved = runner.invoke(cli.app, ["account", "migrate", "--move", "--shared"])
    assert moved.exit_code == 0, moved.output
    assert (state.homes.shared("claude") / "file-history" / "s1" / "f@v1").is_file()
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    inside = runner.invoke(cli.app, ["account", "migrate"])
    assert isinstance(inside.exception, AccountError)
    assert "from your own terminal" in str(inside.exception)


# What a host session acts on in the operator's own directories, checked as it
# stands: what's there, what of it looks planted, and what to do.


def test_claude_code_s_directory_is_checked_for_what_a_host_session_acts_on(
    tmp_path: Path,
) -> None:
    home = tmp_path / "h"
    directory = home / ".claude"
    worktree = Path("/w/lup.git/tree/dev")
    written(
        directory / "settings.json",
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "notify-send done"},
                                {
                                    "type": "command",
                                    "command": f"bash {worktree}/hooks/start.sh",
                                },
                            ]
                        }
                    ]
                },
                "env": {"NODE_OPTIONS": "--require /x"},
                "permissions": {"allow": ["Bash(rm:*)"], "ask": ["Bash"], "deny": []},
                "skipDangerousModePermissionPrompt": True,
                "enabledPlugins": {"helper@market": True, "off@market": False},
            }
        ),
    )
    written(directory / "CLAUDE.md", "be brief\nand kind\n")
    written(directory / "skills" / "tidy" / "SKILL.md", "---\nname: tidy\n---\n")
    written(directory / "skills" / "synced" / "a" / "tidy" / "SKILL.md", "---\n")
    (directory / "skills" / "planted").symlink_to(worktree / "skills" / "planted")
    written(directory / "plugins" / "installed_plugins.json", "{}")
    written(directory / "shell-snapshots" / "snapshot-bash-1.sh", "alias ls=rm")
    written(directory / "session-env" / "s1" / "hook-0.sh", "export X=1")
    (directory / "session-env" / "s2").mkdir()
    written(directory / "daemon" / "control.key", "key")
    written(
        directory / "projects" / "-w-secret" / "0.jsonl",
        json.dumps({"cwd": str(worktree)}),
    )
    written(directory / ".credentials.json", '{"claudeAiOauth": {}}')
    places = Places(home=home, written=[directory, Path("/w/lup.git")])
    assert ClaudeWritten(directory=directory).checked(places) == [
        (
            "`settings.json` runs on the host `notify-send done`; "
            f"`bash {worktree}/hooks/start.sh` (it names a directory rooms write: a "
            "room could change what it runs); it sets in every host session's "
            "environment `NODE_OPTIONS`; it lets a host session act without asking: "
            "allows `Bash(rm:*)`; skips the warning before bypassing permissions. "
            "Each is yours only if you set it. It asks before 1 kind of call and "
            "denies 0: a room could have taken one out, so check each you set is "
            "there."
        ),
        "`CLAUDE.md`, 2 lines, is read into every host session: check it's all yours.",
        (
            "`skills/`: 1 skill a host session can load, 2 copies in all, `tidy`: "
            "check each is yours."
        ),
        (
            "`plugins/`: `helper@market` turned on, whose code under `plugins/` runs "
            "in host sessions and a room could have changed: reinstall each "
            "(`/plugin`)."
        ),
        (
            f"`skills/planted` is a link to `{worktree}/skills/planted`, in a "
            "directory rooms write: Claude Code makes none there, so check it's "
            "yours."
        ),
        (
            "`shell-snapshots/`: 1 snapshot. A host session runs its own before each "
            "command, and a room could have written any: with no host session "
            "running, `rm ~/.claude/shell-snapshots/*`; a session makes a new one as "
            "it starts."
        ),
        (
            "`session-env/`: 2 sessions' environments, 1 holding a file, which a "
            "session runs before each of its commands, a resumed one too: with no "
            "host session running, `rm -r ~/.claude/session-env/*`."
        ),
        (
            "`daemon/`, the state of the supervisor that runs background sessions, "
            "its `control.key` among it: rooms could read and write it, and lup "
            "can't tell what of it a room changed: with no background session "
            "running, look through it, or remove it."
        ),
        (
            f"`projects/-w-secret` says its sessions ran in {worktree}, whose folder "
            "Claude Code names `-w-lup-git-tree-dev`: a room could have written it "
            "so; lup reads it as no directory's, and moves none of it."
        ),
        (
            "Your host login, `.credentials.json`, was readable by every room: in a "
            "Claude Code session on the host, run `/logout` then `/login`, so the "
            "refresh token they could read is replaced. Whether `/logout` revokes it "
            "with the provider isn't documented."
        ),
    ]


def test_settings_that_run_nothing_say_so(tmp_path: Path) -> None:
    directory = tmp_path / ".claude"
    written(directory / "settings.json", json.dumps({"model": "opus", "theme": "dark"}))
    places = Places(home=tmp_path, written=[directory])
    assert ClaudeWritten(directory=directory).checked(places) == [
        (
            "`settings.json`: nothing in it runs a command, sets a variable, or lets "
            "a session act without asking."
        )
    ]


def test_codex_s_home_is_checked_for_what_a_host_session_acts_on(
    tmp_path: Path,
) -> None:
    home = tmp_path / "h"
    directory = home / ".codex"
    written(
        directory / "config.toml",
        'notify = ["bash", "~/.codex/notify.sh"]\n'
        'approval_policy = "never"\n'
        "[mcp_servers.docs]\n"
        'command = "npx"\n'
        'args = ["docs-server"]\n'
        "[shell_environment_policy.set]\n"
        'PATH = "/w/lup.git/bin:/usr/bin"\n'
        "[model_providers.proxy]\n"
        'base_url = "http://127.0.0.1:9999"\n',
    )
    written(
        directory / "hooks.json",
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "say done"}]}]}}),
    )
    written(directory / "AGENTS.md", "one\n")
    written(directory / "rules" / "default.rules", "allow")
    written(directory / "tmp" / "arg0" / "apply_patch", "#!/bin/sh")
    written(directory / "auth.json", "{}")
    places = Places(home=home, written=[directory])
    assert CodexWritten(home=directory).checked(places) == [
        (
            "`config.toml` runs on the host its `notify`, `bash '~/.codex/notify.sh'` "
            "(it names a directory rooms write: a room could change what it runs); "
            "the MCP server `docs`, `npx docs-server`; it sets in every command's "
            "environment `PATH`; it sends its requests to `http://127.0.0.1:9999` "
            "(the provider `proxy`); it lets a host session act without asking: "
            "`approval_policy` is `never`. Each is yours only if you set it."
        ),
        "`hooks.json` runs on the host `say done`. Each is yours only if you set it.",
        "`AGENTS.md`, 1 line, is read into every host session: check it's all yours.",
        (
            "`rules/` (1 file): a host session loads each, and `rules/` can let it "
            "run a command without asking: check they're yours."
        ),
        (
            "`tmp/`: a host session runs its shell snapshot and the helpers it puts "
            "first on its commands' `PATH` from them, and a room could have written "
            "any: with no host session running, `rm -r ~/.codex/tmp/*`; a session "
            "makes its own as it starts."
        ),
        (
            "Your host login, `auth.json`, was readable by every room on Codex: on "
            "the host, run `codex logout` then `codex login`, so the refresh token "
            "they could read is replaced. Whether `codex logout` revokes it with the "
            "provider isn't documented."
        ),
    ]
