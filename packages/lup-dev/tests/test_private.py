"""The `Private` module: its list built on the host, how a value is found, and how the declaration chooses them.

Every value here is made up: a home `/home/op`, a user `op`, a host
`kestrel-box`, an alias `forge-op`. The host's account, ssh and GitHub are a
stub (`StubFacts`); git runs for real on a scratch repository.
"""

import asyncio
import os
import shutil
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import Modules, Private, Project, ProjectError, Values, cli
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.serving import Related, answering
from lup_dev.forge.github import GitHubError
from lup_dev.host.client import RoomClient, asked
from lup_dev.host.courier import Courier, Heard, Printed, Telling
from lup_dev.host.protocol import Action, Done, Limits, Register, Registered, Stop
from lup_dev.host.service import Answerer, HostService
from lup_dev.host.workers import LaunchJudge
from lup_dev.layout import HostLayout, Layout
from lup_dev.private import scanning
from lup_dev.private.found import added_lines, counted, found, textual
from lup_dev.private.module import Details
from lup_dev.private.withheld import (
    Held,
    Seen,
    Withheld,
    built,
    kept,
    said,
)
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Generator

    from conftest import InProcess, Shell, StubFacts

    from lup_dev.host.workers import LaunchModules

HOME = "/home/op"
USER = Held(kind="user", text="op")
WITHHELD = Withheld(
    held=[
        Held(kind="repository-path", text="/home/op/src/demo.git"),
        Held(kind="home", text=HOME),
        Held(kind="value", text="Kestrel Labs"),
        USER,
    ]
)


def places(text: str, withheld: Withheld = WITHHELD) -> list[tuple[str, int, int]]:
    return [(each.held.kind, each.line, each.column) for each in found(text, withheld)]


# Finding a value


def test_a_value_is_found_whatever_its_case_and_placed_by_line_and_column() -> None:
    assert places("first\nOP said so\n  kestrel labs too") == [
        ("user", 2, 1),
        ("value", 3, 3),
    ]


def test_a_value_inside_a_longer_word_isnt_found() -> None:
    assert places("the operator ran a loop in /home/opal; ops") == []


def test_a_value_beside_punctuation_or_in_a_dashed_path_is_found() -> None:
    assert places("op@kestrel-box, -home-op-src-, `op`, (op)") == [
        ("user", 1, 1),
        ("user", 1, 23),
        ("user", 1, 33),
        ("user", 1, 39),
    ]


def test_of_overlapping_values_the_longest_is_found() -> None:
    assert places("cd /home/op/src/demo.git/tree and /home/op/x") == [
        ("repository-path", 1, 4),
        ("home", 1, 35),
    ]


def test_a_place_counts_characters_as_written_past_wide_and_folding_ones() -> None:
    assert places("🦊 é Straße op") == [("user", 1, 12)]
    assert places(
        "STRASSE op", Withheld(held=[Held(kind="value", text="straße"), USER])
    ) == [
        ("value", 1, 1),
        ("user", 1, 9),
    ]


def test_a_file_that_isnt_text_is_counted_ignoring_ascii_case() -> None:
    assert textual(b"\x89PNG\x00/HOME/OP") is None
    assert counted(
        b"\x89PNG\x00/HOME/OP and /home/opal", Held(kind="home", text=HOME)
    ) == [5]


def test_only_lines_a_change_adds_count_for_a_push() -> None:
    assert added_lines(None, "a\nb\n") == [1, 2]
    assert added_lines("a\nb\nc\n", "a\nc\n") == []
    assert added_lines("a\nb\n", "a\nB\nc\n") == [2, 3]


def test_what_a_refusal_says_of_a_kind_never_holds_a_value() -> None:
    assert said("value").what == "one of the operator's private values"
    assert said("home").steer.startswith("write it as `~`")


# Building the list on the host


@pytest.fixture
def demo(tmp_path: Path, shell: Shell) -> Path:
    """A bare repository whose remotes name an SSH alias and GitHub's own host."""
    git = tmp_path / "home" / "op" / "src" / "demo.git"
    git.mkdir(parents=True)
    shell.git(git, "init", "-q", "--bare")
    shell.git(git, "remote", "add", "origin", "forge-op:op/demo.git")
    shell.git(git, "remote", "add", "mirror", "https://github.com/op/demo")
    shell.git(git, "config", "remote.mirror.pushurl", "ssh://git@forge-op:22/op/demo")
    return git


def building(
    facts: StubFacts,
    git: Path,
    *,
    related: list[Related] | None = None,
    details: list[str] | None = None,
    values: list[str] | None = None,
    last: Withheld | None = None,
) -> tuple[list[tuple[str, str]], list[str], list[Seen]]:
    chosen = Private(details=Details.only(*details)) if details else Private()
    made = asyncio.run(
        built(
            facts,
            git,
            own=[git],
            related=related or [],
            details=chosen.chosen_details(),
            values=values or [],
            last=last,
        )
    )
    held = [(each.kind, each.text) for each in made.withheld.held]
    return held, made.notes, made.withheld.seen


def test_the_list_holds_the_machine_the_alias_and_the_repository_s_paths(
    demo: Path, stub_facts: type[StubFacts]
) -> None:
    home = demo.parents[1]
    facts = stub_facts(home=home, aliases={"forge-op": "github.com"})
    held, notes, _ = building(facts, demo, values=[" Kestrel Labs "])
    assert held == sorted(
        [
            ("repository-path", str(demo)),
            ("repository-path", "~/src/demo.git"),
            ("home", str(home)),
            ("hostname", "kestrel-box"),
            ("alias", "forge-op"),
            ("value", "Kestrel Labs"),
            ("user", "op"),
        ],
        key=lambda each: -len(each[1]),
    )
    assert notes == []


OLDER_GIT = """#!/bin/sh
for word in "$@"; do
  if [ "$word" = url-parse ]; then
    echo "git: 'url-parse' is not a git command. See 'git --help'." >&2
    exit 1
  fi
done
exec {git} "$@"
"""
"""A git older than the room's, which has no `url-parse`, otherwise the real one."""


def test_a_git_without_url_parse_lists_no_alias_and_says_so(
    demo: Path,
    stub_facts: type[StubFacts],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = tmp_path / "older"
    older.mkdir()
    (older / "git").write_text(OLDER_GIT.format(git=shutil.which("git")))
    (older / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{older}{os.pathsep}{os.environ['PATH']}")
    facts = stub_facts(home=demo.parents[1], aliases={"forge-op": "github.com"})
    held, notes, _ = building(facts, demo, details=["alias", "user"])
    assert held == [("user", "op")]
    assert notes == [
        (
            "git here has no `url-parse`, so no SSH alias in the repository's "
            "remotes is listed: a git as recent as the room's reads them"
        )
    ]


def test_a_detail_dropped_isn_t_read(demo: Path, stub_facts: type[StubFacts]) -> None:
    facts = stub_facts(home=demo.parents[1], aliases={"forge-op": "github.com"})
    held, _, _ = building(facts, demo, details=["user", "home"])
    assert [kind for kind, _ in held] == ["home", "user"]


def test_a_related_repository_that_isn_t_public_is_kept_by_its_names(
    demo: Path, stub_facts: type[StubFacts], tmp_path: Path
) -> None:
    facts = stub_facts(
        home=Path("/home/elsewhere"),
        visible={
            "op/atlas": "private",
            "op/gull": GitHubError("gh couldn't reach GitHub"),
            "op/tern": GitHubError("gh couldn't reach GitHub"),
        },
    )
    related = [
        Related(name="gannet", path=tmp_path / "gannet", github=None),
        Related(name="atlas", path=tmp_path / "atlas", github="op/atlas"),
        Related(name="public-one", path=tmp_path / "pub", github="op/pub"),
        Related(name="gull", path=tmp_path / "gull", github="op/gull"),
        Related(name="tern", path=tmp_path / "tern", github="op/tern"),
    ]
    last = Withheld(seen=[Seen(repository="op/gull", visibility="private")])
    held, notes, seen = building(
        facts, demo, related=related, details=["private-repository"], last=last
    )
    assert sorted(text for _, text in held) == sorted(
        ["gannet", "atlas", "op/atlas", "gull", "op/gull"]
    )
    assert facts.asked == ["op/atlas", "op/pub", "op/gull", "op/tern"]
    assert notes == [
        (
            "GitHub didn't say whether `op/gull` is public (gh couldn't reach "
            "GitHub): its word at the last launch, private, stands"
        ),
        (
            "GitHub didn't say whether `op/tern` is public (gh couldn't reach "
            "GitHub): its name isn't checked until it does"
        ),
    ]
    assert [each.repository for each in seen] == ["op/atlas", "op/pub", "op/gull"]


def test_a_value_given_twice_whatever_its_case_is_kept_once(
    demo: Path, stub_facts: type[StubFacts]
) -> None:
    facts = stub_facts(home=Path("/home/elsewhere"))
    held, _, _ = building(facts, demo, details=["user"], values=["OP", "kestrel"])
    assert held == [("value", "kestrel"), ("user", "op")]


# Declaring it


def test_private_is_one_of_lup_s_default_modules_and_drops_with_its_reason() -> None:
    assert "private" in [each.name for each in resolve(Project()).modules]
    dropped = Project(
        modules=Modules.default().drop("private", why="a scratch project")
    )
    assert "private" not in [each.name for each in resolve(dropped).modules]


def test_a_person_s_values_and_a_dropped_detail_compose_over_the_project_s() -> None:
    project = Modules.default().edit(Private(values=Values().add("kestrel")))
    person = Modules().edit(
        Private(
            values=Values().add("gull"),
            details=Details().drop("hostname", why="it's an ordinary word here"),
        )
    )
    resolved = resolve(Project(modules=person.over(project)))
    [private] = [each for each in resolved.modules if isinstance(each, Private)]
    assert private.chosen_values() == ["kestrel", "gull"]
    assert "hostname" not in private.chosen_details()


def test_a_detail_that_isn_t_one_or_a_blank_value_is_refused_where_written() -> None:
    with pytest.raises(ProjectError, match=r"`Details` has no detail `hostnme`"):
        Details().drop("hostnme")
    with pytest.raises(ProjectError, match=r"blank or spans lines"):
        Values().add("two\nlines")


# The gate's `private` step


runner = CliRunner()

GATED = Withheld(
    held=[
        Held(kind="value", text="Kestrel Labs"),
        Held(kind="home", text="/home/op"),
    ]
)
"""Made-up values never published, as a launch would list them on the host."""


@pytest.fixture
def forged(
    bare: Path, tmp_path: Path, shell: Shell, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The bare repository's worktree, run from, its remote `origin` a forge on disk holding `main`."""
    forge = tmp_path / "forge.git"
    shell.git(tmp_path, "init", "-q", "--bare", str(forge))
    shell.git(bare, "remote", "set-url", "origin", str(forge))
    shell.git(bare, "push", "-q", "origin", "main")
    worktree = bare / "tree" / "main"
    monkeypatch.chdir(worktree)
    return worktree


def gated(worktree: Path, shell: Shell) -> str:
    """Leave a value in an untracked file, another in a commit's message the remote lacks, and one in a file git ignores; return the commit's short id."""
    (worktree / "docs").mkdir()
    (worktree / "docs" / "notes.md").write_text("See /home/op/x.\n")
    (worktree / ".lup").mkdir()
    (worktree / ".lup" / "scratch.md").write_text("/home/op\n")
    shell.git(worktree, "commit", "-q", "--allow-empty", "-m", "For Kestrel Labs")
    return shell.git(worktree, "rev-parse", "--short", "HEAD").strip()


QUIET_LAYER = (
    '"""This person\'s own values."""\n\n'
    "from lup_dev import Modules, Private, Project, Values\n\n"
    'project = Project(modules=Modules().edit(Private(values=Values().add("Kestrel Labs"))))\n'
)
"""A person's own layer, approved with the commit, adding a value of theirs."""


EXPECTED = (
    "docs/notes.md:1:5 - private: the operator's home path\n"
    "    steer: write it as `~`, or a path in the repository from its root\n"
    "{short}'s message:1:5 - private: one of the operator's private values\n"
    "    steer: leave it out of what's published; the operator, who listed it, "
    "knows which it is\n"
)


def test_the_gate_on_the_host_fails_on_a_value_in_a_file_or_a_new_commit(
    forged: Path, shell: Shell, state: Layout
) -> None:
    short = gated(forged, shell)
    write_model(kept(state.module_data("private", forged.parents[1])), GATED)
    result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 1
    assert result.output.startswith(EXPECTED.format(short=short))
    assert result.output.endswith("1 commit for values never published: 2 found.\n")
    assert "Kestrel" not in result.output
    assert "/home/op" not in result.output


def test_the_gate_on_a_machine_no_launch_ran_on_says_so_and_passes(
    forged: Path, shell: Shell, state: Layout
) -> None:
    gated(forged, shell)
    result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 0
    assert result.output.startswith(
        "Not read: no launch was approved for this repository on this machine, "
        "so no list of values never published is built here, and nothing was "
        "read.\n"
    )


def test_the_gate_on_the_host_builds_a_missing_list_as_a_launch_would(
    forged: Path,
    shell: Shell,
    state: Layout,
    stub_facts: type[StubFacts],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short = gated(forged, shell)
    common = forged.parents[1]
    approval = Approval(
        commit=shell.git(forged, "rev-parse", "HEAD").strip(),
        fingerprint="f",
        paths=[],
        tool=ReleaseTool(
            name="lup-dev", version="0.4.0", registry="https://pypi.org/simple", pins={}
        ),
        time=datetime(2026, 10, 19, tzinfo=UTC),
        local=QUIET_LAYER,
    )
    write_model(state.approved(common), approval)
    monkeypatch.setattr(cli, "HostFacts", lambda: stub_facts(home=Path("/home/op")))
    result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 1
    assert result.output.startswith(EXPECTED.format(short=short))
    built = read_model(kept(state.module_data("private", common)), Withheld)
    assert built is not None
    assert Held(kind="value", text="Kestrel Labs") in built.held


def test_a_remote_that_can_t_be_listed_leaves_the_commits_unread_said(
    forged: Path, shell: Shell, state: Layout
) -> None:
    gated(forged, shell)
    shell.git(
        forged.parents[1], "remote", "add", "gone", str(forged.parents[2] / "gone.git")
    )
    write_model(kept(state.module_data("private", forged.parents[1])), GATED)
    result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 1
    assert (
        "Not read: `HEAD`'s commits weren't read: `gone` couldn't be listed, so "
        "which commits are new wasn't known.\n"
    ) in result.output
    assert "'s message" not in result.output


@contextmanager
def hosted(
    tmp_path_factory: pytest.TempPathFactory,
    registered: Register,
    modules: LaunchModules | None,
) -> Generator[Path]:
    """Serve `registered` in a host service of its own thread with `modules`, or none as an older service; yield its room's request socket."""
    base = tmp_path_factory.mktemp("host")
    layout = HostLayout(sockets=base / "run", state=base / "state")
    service = HostService(
        layout=layout,
        answerer=Nobody(),
        courier=Deaf(),
        judge=Unjudged(),
        say=lambda line: None,
        modules=modules,
    )
    bound = threading.Event()

    def run() -> None:
        async def serve() -> None:
            async with service.serving() as serving:
                bound.set()
                await serving.stopped.wait()

        asyncio.run(serve())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    bound.wait()
    patience = timedelta(seconds=30)
    asked(layout.control, registered, Registered, patience)
    try:
        yield layout.launch(registered.launch).request
    finally:
        asked(layout.control, Stop(), Done, patience)
        thread.join(timeout=60)


class Nobody(Answerer):
    def runtimes(self) -> list[str]:
        return ["claude"]

    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        return ""


class Deaf(Courier):
    def heard(self, runtime: str, payload: str) -> Heard:
        return Heard(event="call-started", session="s1", judged=False, fits=10_000)

    def told(
        self, runtime: str, payload: str, answer: str, telling: Telling
    ) -> Printed:
        return Printed(text=answer)


class Unjudged(LaunchJudge):
    """A launch's judge no hook reaches."""

    async def judged(self, launch: Register, payload: str) -> str:
        message = f"no hook reaches a judge here: {payload}"
        raise AssertionError(message)


def registered(worktree: Path, actions: list[Action] | None = None) -> Register:
    judge = worktree.parents[2] / "judge"
    judge.touch()
    return Register(
        launch="one",
        runtime="claude",
        worktree=worktree,
        repository=worktree.parents[1],
        judge=judge,
        container="lup-one",
        limits=Limits(
            actions=["fetch", "push"] if actions is None else actions, protected=[]
        ),
        github=None,
    )


def in_the_room(socket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def room() -> RoomClient:
        return RoomClient(socket=socket)

    monkeypatch.setattr(cli, "RoomClient", room)


def test_the_gate_in_a_room_asks_the_host_which_never_says_a_value(
    forged: Path,
    shell: Shell,
    *,
    in_process: type[InProcess],
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short = gated(forged, shell)
    layout = Layout(state=tmp_path / "host-state", data=tmp_path / "host-data")
    write_model(kept(layout.module_data("private", forged.parents[1])), GATED)
    modules = in_process(resolved=resolve(Project()), layout=layout)
    with hosted(tmp_path_factory, registered(forged), modules) as socket:
        in_the_room(socket, monkeypatch)
        result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 1
    assert result.output.startswith(EXPECTED.format(short=short))


def test_the_gate_in_a_room_whose_launch_has_no_list_has_the_host_build_it(
    forged: Path,
    shell: Shell,
    *,
    in_process: type[InProcess],
    stub_facts: type[StubFacts],
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short = gated(forged, shell)
    layout = Layout(state=tmp_path / "host-state", data=tmp_path / "host-data")
    declared = Modules.default().edit(Private(values=Values().add("Kestrel Labs")))
    modules = in_process(resolved=resolve(Project(modules=declared)), layout=layout)
    monkeypatch.setattr(
        scanning, "HostFacts", lambda: stub_facts(home=Path("/home/op"))
    )
    with hosted(tmp_path_factory, registered(forged), modules) as socket:
        in_the_room(socket, monkeypatch)
        result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 1
    assert result.output.startswith(EXPECTED.format(short=short))
    assert read_model(kept(layout.module_data("private", forged.parents[1])), Withheld)


def test_the_gate_in_a_room_whose_host_doesn_t_answer_says_so_and_passes(
    forged: Path,
    shell: Shell,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gated(forged, shell)
    with hosted(tmp_path_factory, registered(forged), None) as socket:
        in_the_room(socket, monkeypatch)
        result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 0
    assert result.output == (
        "Values never published weren't read: the host said no handler for "
        "`private-scan`; a room's request socket answers list, show-holding.\n"
    )


def test_a_launch_whose_limits_leave_out_fetching_reads_the_files_alone(
    forged: Path,
    shell: Shell,
    *,
    in_process: type[InProcess],
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gated(forged, shell)
    layout = Layout(state=tmp_path / "host-state", data=tmp_path / "host-data")
    write_model(kept(layout.module_data("private", forged.parents[1])), GATED)
    modules = in_process(resolved=resolve(Project()), layout=layout)
    with hosted(tmp_path_factory, registered(forged, ["push"]), modules) as socket:
        in_the_room(socket, monkeypatch)
        result = runner.invoke(cli.app, ["private", "check"])
    assert result.exit_code == 1
    assert "'s message" not in result.output
    assert (
        "Not read: `HEAD`'s commits weren't read, since listing the remotes is fetching"
        in result.output
    )


def test_private_brings_its_gate_step_its_handler_and_its_hook() -> None:
    resolved = resolve(Project())
    assert [each.name for each in resolved.gate][-1] == "private"
    assert [each.command for each in resolved.gate if each.name == "private"] == [
        ["lup-dev", "private", "check"]
    ]
    assert "private-scan" in [
        answering(each.handler).named() for each in resolved.handled
    ]
    assert "PrivateHooks" in [each.hooks.__name__ for each in resolved.hooked]
