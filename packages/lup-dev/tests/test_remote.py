"""git through the host: the room's helper run by real git, against the host service, on scratch repositories.

The repository is laid out as lup's own is: a bare git directory with its
worktree under `tree/`, its remote `origin` a bare "forge" on disk. The room's
git runs in the worktree with the room's own configuration and the helper as a
launch writes them (`RoomGit`), the helper's socket pointed at the test's
service, which serves in a thread of its own and runs git on the host for real.
Nothing reaches the network, and no test sleeps or reads the clock.
"""

import asyncio
import json
import os
import socketserver
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup.rooms.container import Mask, Mount
from lup.types import Model
from lup_dev import Project
from lup_dev.declaration.resolve import resolve
from lup_dev.errors import LupDevError
from lup_dev.host.client import HostClient, RoomClient, Starter, asked
from lup_dev.host.courier import Courier, Heard, Printed, Telling
from lup_dev.host.protocol import (
    Done,
    GitHubRepository,
    HostError,
    Limits,
    Register,
    Reply,
    Stop,
)
from lup_dev.host.service import Answerer, Asked, HostService, Judged
from lup_dev.launch.room import RoomError, RoomGit, programs, refreshed, room_git
from lup_dev.layout import ROOM_PATH, HostLayout, LaunchLayout, LaunchSockets, Layout
from lup_dev.private import hooks
from lup_dev.private.withheld import Facts, Held, Machine, Withheld, kept
from lup_dev.remote.config import Gating, room_config
from lup_dev.remote.protocol import (
    Advertised,
    Fetched,
    Fetching,
    Lease,
    Listing,
    Pushed,
    Pushing,
    Ref,
    Remotes,
    Update,
    Updated,
    Wanted,
    refusal,
    routes,
)
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Generator

    from conftest import FakeClock, InProcess, StubFacts

    from lup_dev.forge.github import Visibility
    from lup_dev.host.workers import LaunchModules


@pytest.fixture(autouse=True)
def own_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git configuration out of the host's git, as the room's is, with an identity of its own to commit with."""
    own = tmp_path / "gitconfig"
    own.write_text("[user]\n\tname = test\n\temail = test@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(own))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def git(cwd: Path, *arguments: str) -> str:
    """Run git on the host, outside the room; spawned without forking, as a service's thread may run."""
    ran = subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=True
    )
    return ran.stdout.strip()


class Stub(Answerer):
    def runtimes(self) -> list[str]:
        return ["first"]

    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        return ""


class Deaf(Courier):
    def heard(self, runtime: str, payload: str) -> Heard:
        message = "no hook reaches the service in these tests"
        raise AssertionError(message)

    def told(
        self, runtime: str, payload: str, answer: str, telling: Telling
    ) -> Printed:
        return Printed(text=answer)

    def woken(self, runtime: str, session: str, text: str) -> str | None:
        return None


async def no_judge(asked: Asked) -> Judged:
    message = f"no judge runs in these tests: {asked.command}"
    raise AssertionError(message)


class Nothing(Starter):
    def start(self, log: Path) -> None:
        message = "the test's service is started by the test"
        raise AssertionError(message)


class Background:
    """A service serving in a thread of its own, on its own event loop."""

    def __init__(self, service: HostService) -> None:
        self.service = service
        self.bound = threading.Event()
        self.failure: BaseException | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        async def serve() -> None:
            async with self.service.serving() as serving:
                self.bound.set()
                await serving.stopped.wait()

        try:
            asyncio.run(serve())
        except BaseException as failure:
            self.failure = failure
        finally:
            self.bound.set()

    def stop(self) -> None:
        if self.thread.is_alive():
            asked(self.service.layout.control, Stop(), Done, timedelta(minutes=1))
        self.thread.join(timeout=60)
        assert not self.thread.is_alive()


DEFAULT = Limits(
    actions=["fetch", "push", "read-issues"],
    protected=["refs/heads/main", "refs/tags/*"],
)

UNGATED = Gating(command=["false"], refs=[])
"""A room whose pushes run no gate: no ref is gated."""

GATE = """
import json, os, sys
from pathlib import Path

log, commit = Path(sys.argv[1]), sys.argv[2]
seen = {"commit": commit, "cwd": os.getcwd(), "git_dir": os.environ.get("GIT_DIR")}
with log.open("a") as written:
    written.write(json.dumps(seen) + "\\n")
print(f"the gate's report on {commit}")
sys.exit(1 if (log.parent / "failing").exists() else 0)
"""
"""A gate that records each commit it ran on, where and with which git
directory, prints a report, and fails where a `failing` file is beside its log."""


class World:
    """The host's repository, its forge, a launch of it served, and its room's git."""

    def __init__(
        self, bare: Path, tmp_path: Path, layout: HostLayout, said: list[str]
    ) -> None:
        self.project = bare
        self.worktree = bare / "tree" / "main"
        self.forge = tmp_path / "forge.git"
        git(tmp_path, "init", "-q", "--bare", str(self.forge))
        git(bare, "remote", "set-url", "origin", str(self.forge))
        git(bare, "push", "-q", str(self.forge), "main")
        self.tmp_path = tmp_path
        self.layout = layout
        self.said = said
        self.launch = LaunchLayout(directory=tmp_path / "launch")
        shim = tmp_path / "shim"
        shim.mkdir()
        (shim / "python3").symlink_to(sys.executable)
        gate = tmp_path / "gate.py"
        gate.write_text(GATE)
        self.log = tmp_path / "gate" / "ran.jsonl"
        self.log.parent.mkdir()
        self.landed: list[list[str]] = []
        self.room = RoomGit(
            repository=bare,
            launch=self.launch,
            gating=Gating(
                command=[sys.executable, str(gate), str(self.log)],
                refs=["refs/heads/dev", "refs/heads/release/*"],
            ),
        )
        self.room.write()
        git(
            tmp_path,
            "config",
            "--file",
            str(self.launch.gitconfig),
            "lup.requestSocket",
            str(layout.launch("one").request),
        )
        home = tmp_path / "home"
        home.mkdir()
        self.env = {
            **self.room.env,
            "PATH": f"{self.launch.bin}:{shim}:/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(home),
        }

    def registered(self, limits: Limits = DEFAULT) -> Register:
        judge = self.tmp_path / "judge" / "lup-dev"
        judge.parent.mkdir(parents=True, exist_ok=True)
        judge.touch()
        return Register(
            launch="one",
            runtime="first",
            worktree=self.worktree,
            repository=self.project,
            judge=judge,
            container="lup-one",
            github=None,
            limits=limits,
        )

    @contextmanager
    def served(
        self,
        clock: FakeClock,
        limits: Limits = DEFAULT,
        modules: LaunchModules | None = None,
    ) -> Generator[None]:
        remotes = Remotes(say=self.said.append, landed=self.landing, modules=modules)
        service = HostService(
            layout=self.layout,
            answerer=Stub(),
            courier=Deaf(),
            judge=no_judge,
            say=self.said.append,
            room_routes=routes(remotes),
            modules=modules,
        )
        running = Background(service)
        running.thread.start()
        running.bound.wait()
        if running.failure is not None:
            raise running.failure
        try:
            host = HostClient(layout=self.layout, clock=clock, starter=Nothing())
            host.register(self.registered(limits))
            yield
        finally:
            running.stop()

    async def landing(self, launch: Register, refs: list[str]) -> None:
        assert launch.launch == "one"
        self.landed.append(refs)

    def room_git(self, *arguments: str) -> Ran:
        """Run git in the room's worktree, as the room runs it, whatever its status.

        Spawned without forking, since the service's thread runs meanwhile.
        """
        ran = subprocess.run(
            ["git", *arguments],
            cwd=self.worktree,
            env=self.env,
            capture_output=True,
            check=False,
        )
        return Ran(exit_code=ran.returncode, stderr=ran.stderr)

    def commit(self, message: str) -> str:
        made = self.room_git("commit", "-q", "--allow-empty", "-m", message)
        assert made.exit_code == 0, made.stderr.decode()
        return git(self.worktree, "rev-parse", "HEAD")

    def wrote(self, path: str, content: str | bytes, message: str) -> str:
        """Write `path` in the room's worktree and commit it, and return the commit's short id."""
        file = self.worktree / path
        file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            file.write_bytes(content)
        else:
            file.write_text(content)
        assert self.room_git("add", "--", path).exit_code == 0
        self.commit(message)
        return git(self.worktree, "rev-parse", "--short", "HEAD")

    def gated(self) -> list[dict[str, str | None]]:
        """Return each run of the gate, in order: its commit, where it ran, and the git directory it was given."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def failing(self) -> None:
        """Have every later run of the gate fail."""
        (self.log.parent / "failing").touch()

    def on_forge(self, ref: str) -> str | None:
        found = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=self.forge,
            capture_output=True,
            text=True,
            check=False,
        )
        return found.stdout.strip() or None


class Ran(Model):
    """How the room's git ended: its status, and what it wrote to its standard error."""

    exit_code: int
    stderr: bytes


@pytest.fixture
def layout(tmp_path_factory: pytest.TempPathFactory) -> HostLayout:
    # A socket's path is limited in length, so the service's directory is short.
    base = tmp_path_factory.mktemp("host")
    return HostLayout(sockets=base / "run", state=base / "state")


@pytest.fixture
def said() -> list[str]:
    return []


@pytest.fixture
def world(bare: Path, tmp_path: Path, layout: HostLayout, said: list[str]) -> World:
    return World(bare, tmp_path, layout, said)


def stderr(ran: Ran) -> str:
    return ran.stderr.decode()


# Pushing


def test_a_push_lands_on_the_forge_by_object_id(world: World, clock: FakeClock) -> None:
    first = world.commit("first")
    second = world.commit("second")

    with world.served(clock):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")
        older = world.room_git("push", "origin", "HEAD~1:refs/heads/older")

    assert pushed.exit_code == 0, stderr(pushed)
    assert older.exit_code == 0, stderr(older)
    assert world.on_forge("refs/heads/feat") == second
    assert world.on_forge("refs/heads/older") == first
    assert any(
        f"one: pushing {second} to refs/heads/feat on `origin` ({world.forge}): done"
        in line
        for line in world.said
    )


def test_each_push_tells_which_refs_it_updated_and_a_dry_run_or_a_refusal_none(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")

    with world.served(clock):
        world.room_git("push", "origin", "HEAD:refs/heads/feat", "HEAD:refs/heads/dev")
        world.room_git("push", "--dry-run", "origin", "HEAD:refs/heads/other")
        world.room_git("push", "origin", "HEAD:refs/heads/main")

    assert world.landed == [["refs/heads/feat", "refs/heads/dev"]]


def test_git_push_u_still_ends_well_where_the_room_cant_write_config(
    world: World, clock: FakeClock
) -> None:
    tip = world.commit("first")
    (world.project / "config.lock").touch()

    with world.served(clock):
        pushed = world.room_git("push", "-u", "origin", "HEAD:refs/heads/feat")

    assert pushed.exit_code == 0, stderr(pushed)
    assert "unable to write upstream branch configuration" in stderr(pushed)
    assert world.on_forge("refs/heads/feat") == tip


def test_a_push_without_a_refspec_pushes_the_current_branch(
    world: World, clock: FakeClock
) -> None:
    world.room_git("switch", "-q", "-c", "topic")
    tip = world.commit("on topic")

    with world.served(clock):
        pushed = world.room_git("push", "origin")

    assert pushed.exit_code == 0, stderr(pushed)
    assert world.on_forge("refs/heads/topic") == tip


def test_a_force_a_lease_a_deletion_and_a_protected_ref_are_refused_with_their_reasons(
    world: World, clock: FakeClock
) -> None:
    pushed = world.commit("first")
    before = world.on_forge("refs/heads/main")

    with world.served(clock):
        assert world.room_git("push", "origin", "HEAD:refs/heads/feat").exit_code == 0
        world.room_git("commit", "-q", "--amend", "--allow-empty", "-m", "amended")
        forced = world.room_git("push", "--force", "origin", "HEAD:refs/heads/feat")
        leased = world.room_git(
            "push",
            f"--force-with-lease=refs/heads/feat:{pushed}",
            "origin",
            "HEAD:refs/heads/feat",
        )
        deleted = world.room_git("push", "origin", ":refs/heads/feat")
        protected = world.room_git("push", "origin", "HEAD:refs/heads/main")
        tagged = world.room_git("push", "origin", "HEAD:refs/tags/v1")

    for refused in [forced, leased, deleted, protected, tagged]:
        assert refused.exit_code != 0
    forcing = (
        "a forced update of `refs/heads/feat` (`+`, `--force` or `--force-with-lease`): "
        "the project's declaration doesn't allow `force-push` with the operator's "
        "credentials (`Core.credentials`), and allowing it is the operator's call"
    )
    assert forcing in stderr(forced)
    assert forcing in stderr(leased)
    assert (
        "deleting `refs/heads/feat`: the project's declaration doesn't allow "
        "`delete-ref`" in stderr(deleted)
    )
    assert (
        "`refs/heads/main` is protected by the project's declaration "
        "(`Core.credentials`, `refs/heads/main`): updating it is the operator's"
        in stderr(protected)
    )
    assert "(`Core.credentials`, `refs/tags/*`)" in stderr(tagged)
    assert world.on_forge("refs/heads/feat") == pushed
    assert world.on_forge("refs/heads/main") == before
    assert world.on_forge("refs/tags/v1") is None
    assert any(
        "one: refused a push to `refs/heads/main` on `origin`" in line
        for line in world.said
    )


def test_a_force_the_limits_allow_is_pushed_forced(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")
    allowing = Limits(
        actions=["fetch", "push", "force-push", "delete-ref"], protected=[]
    )

    with world.served(clock, allowing):
        assert world.room_git("push", "origin", "HEAD:refs/heads/feat").exit_code == 0
        pushed = world.on_forge("refs/heads/feat")
        world.room_git("commit", "-q", "--amend", "--allow-empty", "-m", "amended")
        amended = git(world.worktree, "rev-parse", "HEAD")
        stale = world.room_git(
            "push",
            f"--force-with-lease=refs/heads/feat:{amended}",
            "origin",
            "HEAD:refs/heads/feat",
        )
        leased = world.room_git(
            "push",
            f"--force-with-lease=refs/heads/feat:{pushed}",
            "origin",
            "HEAD:refs/heads/feat",
        )
        deleted = world.room_git("push", "origin", ":refs/heads/feat")

    assert stale.exit_code != 0
    assert leased.exit_code == 0, stderr(leased)
    assert deleted.exit_code == 0, stderr(deleted)
    assert world.on_forge("refs/heads/feat") is None


def test_a_forge_refuses_what_isnt_a_fast_forward_unforced(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")

    with world.served(clock):
        assert world.room_git("push", "origin", "HEAD:refs/heads/feat").exit_code == 0
        pushed = world.on_forge("refs/heads/feat")
        world.room_git("commit", "-q", "--amend", "--allow-empty", "-m", "amended")
        refused = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert refused.exit_code != 0
    assert world.on_forge("refs/heads/feat") == pushed


def test_a_url_that_isnt_one_of_the_repositorys_remotes_is_refused(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")
    elsewhere = world.tmp_path / "elsewhere.git"
    git(world.tmp_path, "init", "-q", "--bare", str(elsewhere))
    (world.project / "remotes").mkdir()
    (world.project / "remotes" / "planted").write_text(f"URL: lup::{elsewhere}\n")
    (world.project / "branches").mkdir()
    (world.project / "branches" / "other").write_text(f"lup::{elsewhere}\n")

    with world.served(clock):
        by_url = world.room_git("push", f"lup::{elsewhere}", "HEAD:refs/heads/x")
        forge_url = world.room_git("push", str(world.forge), "HEAD:refs/heads/x")
        planted = world.room_git("push", "planted", "HEAD:refs/heads/x")
        other = world.room_git("push", "other", "HEAD:refs/heads/x")

    for refused in [by_url, forge_url, planted, other]:
        assert refused.exit_code != 0
        assert "isn't one of the remotes" in stderr(refused)
    assert git(elsewhere, "for-each-ref") == ""
    assert world.on_forge("refs/heads/x") is None


def test_an_object_store_reading_from_elsewhere_is_refused(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")
    secret = world.tmp_path / "secret.git"
    git(world.tmp_path, "init", "-q", "--bare", str(secret))
    alternates = world.project / "objects" / "info" / "alternates"
    linked = world.project / "objects" / "pack" / "pack-stolen.pack"

    with world.served(clock):
        alternates.write_text(f"{secret / 'objects'}\n")
        through_alternates = world.room_git("push", "origin", "HEAD:refs/heads/a")
        alternates.unlink()
        linked.symlink_to(secret / "objects")
        through_link = world.room_git("push", "origin", "HEAD:refs/heads/b")
        linked.unlink()
        clean = world.room_git("push", "origin", "HEAD:refs/heads/c")

    for refused in [through_alternates, through_link]:
        assert refused.exit_code != 0
        assert "reads objects from outside it" in stderr(refused)
    assert str(alternates) in stderr(through_alternates)
    assert str(linked) in stderr(through_link)
    assert clean.exit_code == 0, stderr(clean)
    assert world.on_forge("refs/heads/a") is None
    assert world.on_forge("refs/heads/b") is None


# Fetching


def test_a_fetch_brings_the_objects_and_writes_no_ref_on_the_host(
    world: World, clock: FakeClock, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(world.forge), str(other))
    git(
        other,
        "-c",
        "user.name=Other",
        "-c",
        "user.email=other@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "from elsewhere",
    )
    git(other, "push", "-q", "origin", "HEAD:refs/heads/theirs")
    theirs = git(other, "rev-parse", "HEAD")
    refs = git(world.project, "for-each-ref")

    with world.served(clock):
        fetched = world.room_git("fetch", "origin", "theirs")

    assert fetched.exit_code == 0, stderr(fetched)
    assert git(world.project, "cat-file", "-t", theirs) == "commit"
    assert git(world.project, "for-each-ref") == refs
    assert not (world.project / "FETCH_HEAD").exists()
    assert git(world.worktree, "rev-parse", "FETCH_HEAD") == theirs
    assert any(
        f"one: fetching {theirs} as refs/heads/theirs from `origin` ({world.forge}): "
        "done" in line
        for line in world.said
    )


def test_a_tag_and_the_remote_s_head_are_fetched_as_git_asks(
    world: World, clock: FakeClock, tmp_path: Path
) -> None:
    git(world.forge, "symbolic-ref", "HEAD", "refs/heads/main")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(world.forge), str(other))
    named = ["-c", "user.name=Other", "-c", "user.email=other@example.com"]
    git(other, *named, "commit", "-q", "--allow-empty", "-m", "tagged")
    git(other, *named, "tag", "-a", "-m", "the first", "v1")
    git(other, "push", "-q", "origin", "HEAD:refs/heads/main", "refs/tags/v1")
    tag = git(other, "rev-parse", "v1")
    tip = git(other, "rev-parse", "HEAD")

    with world.served(clock):
        tagged = world.room_git("fetch", "origin", "refs/tags/v1:refs/tags/v1")
        plain = world.room_git("fetch", "origin")

    assert tagged.exit_code == 0, stderr(tagged)
    assert plain.exit_code == 0, stderr(plain)
    assert git(world.worktree, "rev-parse", "refs/tags/v1") == tag
    assert git(world.worktree, "rev-parse", "FETCH_HEAD") == tip


def test_a_fetch_the_limits_dont_allow_is_refused(
    world: World, clock: FakeClock
) -> None:
    with world.served(clock, Limits(actions=["push"], protected=[])):
        fetched = world.room_git("fetch", "origin", "main")

    assert fetched.exit_code != 0
    assert "the project's declaration doesn't allow `fetch`" in stderr(fetched)


def test_a_fetch_request_writes_no_ref_and_needs_the_object_listed(
    world: World, clock: FakeClock
) -> None:
    main = world.on_forge("refs/heads/main")
    assert main is not None
    refs = git(world.project, "for-each-ref")
    room = RoomClient(socket=world.layout.launch("one").request)

    with world.served(clock):
        listed = room.ask(Listing(remote="origin"), Advertised)
        room.ask(
            Fetching(
                remote="origin", wanted=[Wanted(object=main, name="refs/heads/main")]
            ),
            Fetched,
        )
        with pytest.raises(HostError, match="moved on `origin` since git listed it"):
            room.ask(
                Fetching(
                    remote="origin",
                    wanted=[Wanted(object="1" * 40, name="refs/heads/main")],
                ),
                Fetched,
            )

    assert Ref(object=main, name="refs/heads/main") in listed.refs
    assert git(world.project, "for-each-ref") == refs
    assert not (world.project / "FETCH_HEAD").exists()


# What the helper sends


class Recorder(socketserver.ThreadingUnixStreamServer):
    """A host that records each request the helper sends, and answers each in kind."""

    def __init__(self, path: Path, refs: list[Ref]) -> None:
        self.requests: list[str] = []
        self.refs = refs
        recorder = self

        class Handling(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                raw = self.rfile.read().decode()
                recorder.requests.append(raw)
                self.wfile.write(recorder.reply(raw).model_dump_json().encode())

        super().__init__(str(path), Handling)

    def reply(self, raw: str) -> Reply:
        match json.loads(raw)["kind"]:
            case "remote-list":
                return Advertised(refs=self.refs)
            case "remote-push":
                pushing = Pushing.model_validate_json(raw)
                return Pushed(
                    updates=[
                        Updated(destination=each.destination)
                        for each in pushing.updates
                    ]
                )
            case _:
                return Fetched()


@contextmanager
def recording(world: World, refs: list[Ref]) -> Generator[Recorder]:
    path = world.layout.launch("one").request
    path.parent.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(path, refs)
    thread = threading.Thread(target=recorder.serve_forever, daemon=True)
    thread.start()
    try:
        yield recorder
    finally:
        recorder.shutdown()
        recorder.server_close()
        thread.join(timeout=60)


def test_what_the_helper_sends_reads_as_the_hosts_models(world: World) -> None:
    first = world.commit("first")
    second = world.commit("second")
    listed = [
        Ref(object=first, name="refs/heads/leased"),
        Ref(object=first, name="refs/heads/gone"),
    ]

    with recording(world, listed) as recorder:
        pushed = world.room_git(
            "push",
            "--atomic",
            "--dry-run",
            "--push-option=ci.skip",
            "--push-option=two words",
            f"--force-with-lease=refs/heads/leased:{first}",
            "origin",
            "HEAD~1:refs/heads/older",
            "+HEAD:refs/heads/forced",
            "HEAD:refs/heads/leased",
            ":refs/heads/gone",
        )
        fetched = world.room_git("fetch", "origin", "refs/heads/leased")

    assert pushed.exit_code == 0, stderr(pushed)
    assert fetched.exit_code == 0, stderr(fetched)
    [listing, *pushes, fetch_list] = recorder.requests
    assert Listing.model_validate_json(listing) == Listing(
        remote="origin", for_push=True
    )
    [push] = pushes
    # git sends the refs the remote listed first, in its order, then the new ones.
    assert Pushing.model_validate_json(push) == Pushing(
        remote="origin",
        updates=[
            Update(source=second, destination="refs/heads/leased"),
            Update(source=None, destination="refs/heads/gone"),
            Update(source=first, destination="refs/heads/older"),
            Update(source=second, destination="refs/heads/forced", forced=True),
        ],
        leases=[Lease(ref="refs/heads/leased", expected=first)],
        dry_run=True,
        atomic=True,
        push_options=["ci.skip", "two words"],
    )
    assert Listing.model_validate_json(fetch_list) == Listing(remote="origin")


def test_the_helper_fetches_what_git_asks_for(world: World, tmp_path: Path) -> None:
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(world.forge), str(other))
    git(
        other,
        "-c",
        "user.name=Other",
        "-c",
        "user.email=other@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "from elsewhere",
    )
    theirs = git(other, "rev-parse", "HEAD")
    listed = [Ref(object=theirs, name="refs/heads/theirs")]

    with recording(world, listed) as recorder:
        fetched = world.room_git("fetch", "origin", "theirs")

    assert fetched.exit_code != 0
    [listing, fetch] = recorder.requests
    assert Listing.model_validate_json(listing) == Listing(remote="origin")
    assert Fetching.model_validate_json(fetch) == Fetching(
        remote="origin", wanted=[Wanted(object=theirs, name="refs/heads/theirs")]
    )


def test_the_helper_says_where_no_host_answers(world: World) -> None:
    pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert pushed.exit_code != 0
    assert (
        f"lup: lup's host service doesn't answer on {world.layout.launch('one').request}"
        in stderr(pushed)
    )


# The limits


def test_a_protected_pattern_is_git_s_glob_its_star_spanning_slashes(
    world: World,
) -> None:
    launch = world.registered(
        Limits(actions=["push"], protected=["refs/tags/*", "refs/heads/release/*"])
    )

    def why(destination: str) -> str | None:
        return refusal(
            Update(source="a" * 40, destination=destination),
            forced=False,
            launch=launch,
        )

    assert why("refs/tags/v1/rc") is not None
    assert why("refs/heads/release/2/hotfix") is not None
    assert why("refs/heads/releases") is None
    assert why("refs/heads/Release/2") is None


# The room's configuration


def test_the_room_s_configuration_sends_every_remote_url_through_the_helper(
    bare: Path, tmp_path: Path
) -> None:
    git(bare, "remote", "set-url", "origin", "alias:owner/project")
    git(
        bare,
        "remote",
        "set-url",
        "--push",
        "origin",
        "ssh://push.example/owner/project",
    )
    git(bare, "remote", "add", "mirror", "https://mirror.example/a b.git")
    written = tmp_path / "launch" / "gitconfig"

    room_config(
        bare,
        written,
        Path("/run/lup/request.sock"),
        Gating(
            command=["uv", "run", "lup-dev", "check", "--at"],
            refs=["refs/heads/dev"],
        ),
    )

    def read(key: str) -> list[str]:
        return git(tmp_path, "config", "--file", str(written), "--get-all", key).split(
            "\n"
        )

    assert read("url.lup::alias:owner/project.insteadOf") == ["alias:owner/project"]
    assert read("url.lup::ssh://push.example/owner/project.insteadOf") == [
        "ssh://push.example/owner/project"
    ]
    assert read("url.lup::https://mirror.example/a b.git.insteadOf") == [
        "https://mirror.example/a b.git"
    ]
    assert read("branch.autoSetupMerge") == ["false"]
    assert read("push.default") == ["current"]
    assert read("lup.requestSocket") == ["/run/lup/request.sock"]
    assert [json.loads(each) for each in read("lup.gate")] == [
        ["uv", "run", "lup-dev", "check", "--at"]
    ]
    assert [json.loads(each) for each in read("lup.gated")] == [["refs/heads/dev"]]


def test_a_launch_writes_the_helper_and_puts_it_first_on_the_room_s_path(
    bare: Path, tmp_path: Path
) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")
    room = room_git(bare, launch, [Mount(source=bare)], UNGATED)

    room.write()

    assert os.access(launch.helper, os.X_OK)
    assert launch.helper.read_text().startswith("#!/usr/bin/env python3\n")
    assert room.env == {
        "GIT_CONFIG_GLOBAL": str(launch.gitconfig),
        "PATH": ":".join(str(each) for each in [launch.bin, *ROOM_PATH]),
    }
    assert room.mounts == [
        Mount(source=launch.bin, read_only=True),
        Mount(source=launch.gitconfig, read_only=True),
    ]
    assert git(
        tmp_path, "config", "--file", str(launch.gitconfig), "lup.requestSocket"
    ) == str(LaunchSockets(directory=Path("/run/lup")).request)


# Gating


def test_a_push_to_a_gated_ref_runs_the_gate_on_its_commit_first(
    world: World, clock: FakeClock
) -> None:
    tip = world.commit("first")

    with world.served(clock):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/dev")
        released = world.room_git("push", "origin", "HEAD:refs/heads/release/1")

    assert pushed.exit_code == 0, stderr(pushed)
    assert released.exit_code == 0, stderr(released)
    assert world.on_forge("refs/heads/dev") == tip
    assert world.on_forge("refs/heads/release/1") == tip
    ran = {"commit": tip, "cwd": str(world.worktree), "git_dir": None}
    assert world.gated() == [ran, ran]
    assert f"lup: the gate, on {tip}, before it reaches refs/heads/dev" in stderr(
        pushed
    )
    assert f"the gate's report on {tip}" in stderr(pushed)


def test_an_update_whose_gate_fails_is_held_saying_why_and_the_others_go(
    world: World, clock: FakeClock
) -> None:
    tip = world.commit("first")
    world.failing()

    with world.served(clock):
        held = world.room_git(
            "push", "origin", "HEAD:refs/heads/dev", "HEAD:refs/heads/feat"
        )

    assert held.exit_code != 0
    assert world.on_forge("refs/heads/dev") is None
    assert world.on_forge("refs/heads/feat") == tip
    assert f"the gate failed on {tip}, its report above, so it isn't pushed" in (
        stderr(held)
    )
    assert f"the gate's report on {tip}" in stderr(held)


def test_an_atomic_push_with_an_update_held_pushes_none(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")
    world.failing()

    with world.served(clock):
        held = world.room_git(
            "push", "--atomic", "origin", "HEAD:refs/heads/dev", "HEAD:refs/heads/feat"
        )

    assert held.exit_code != 0
    assert world.on_forge("refs/heads/dev") is None
    assert world.on_forge("refs/heads/feat") is None
    assert "not pushed: the push is atomic, and `refs/heads/dev` was held" in stderr(
        held
    )


def test_a_ref_nothing_gates_a_dry_run_and_a_deletion_run_no_gate(
    world: World, clock: FakeClock
) -> None:
    tip = world.commit("first")
    allowing = Limits(actions=["fetch", "push", "delete-ref"], protected=[])

    with world.served(clock, allowing):
        assert world.room_git("push", "origin", "HEAD:refs/heads/dev").exit_code == 0
        feat = world.room_git("push", "origin", "HEAD:refs/heads/feat")
        dry = world.room_git("push", "--dry-run", "origin", "HEAD:refs/heads/dev")
        deleted = world.room_git("push", "origin", ":refs/heads/dev")

    for each in [feat, dry, deleted]:
        assert each.exit_code == 0, stderr(each)
    assert [each["commit"] for each in world.gated()] == [tip]
    assert world.on_forge("refs/heads/dev") is None


def test_a_gate_the_room_s_configuration_garbles_is_said(
    world: World, clock: FakeClock
) -> None:
    world.commit("first")
    git(
        world.tmp_path,
        "config",
        "--file",
        str(world.launch.gitconfig),
        "lup.gate",
        "uv run lup-dev check --at",
    )

    with world.served(clock):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/dev")

    assert pushed.exit_code != 0
    assert (
        "lup: `lup.gate` in the room's git configuration is 'uv run lup-dev check "
        "--at', not a JSON list of strings" in stderr(pushed)
    )
    assert world.on_forge("refs/heads/dev") is None


def test_a_room_s_programs_differing_from_this_copy_s_are_rewritten_in_place(
    bare: Path, tmp_path: Path
) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")
    room_git(bare, launch, [Mount(source=bare)], UNGATED).write()
    launch.helper.write_text("an older helper\n")
    mounted = launch.helper.stat().st_ino
    bridge = next(path for path in programs(launch) if path != launch.helper)

    rewritten = refreshed(launch)
    again = refreshed(launch)

    assert rewritten == [launch.helper]
    assert launch.helper.read_text() == programs(launch)[launch.helper]
    assert launch.helper.stat().st_ino == mounted
    assert os.access(launch.helper, os.X_OK)
    assert again == []
    assert not bridge.exists()


# Refused at launch


def refused(bare: Path, tmp_path: Path, mounts: list[Mount | Mask]) -> str:
    with pytest.raises(RoomError) as refusal:
        room_git(bare, LaunchLayout(directory=tmp_path / "launch"), mounts, UNGATED)
    return str(refusal.value)


def test_a_config_setting_worktree_config_is_refused_at_launch(
    bare: Path, tmp_path: Path
) -> None:
    git(bare, "config", "extensions.worktreeConfig", "yes")

    assert "sets `extensions.worktreeConfig`" in refused(
        bare, tmp_path, [Mount(source=bare)]
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("include.path", "info/evil.cfg"),
        ("includeIf.gitdir:/nowhere/.path", "evil.cfg"),
        ("includeIf.onbranch:main.path", ":(optional)info/later.cfg"),
        ("include.path", "~/.claude/git.cfg"),
    ],
)
def test_a_config_including_a_file_the_room_writes_is_refused_at_launch(
    bare: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    git(bare, "config", key, value)

    said = refused(bare, tmp_path, [Mount(source=bare), Mount(source=home / ".claude")])

    assert f"{bare / 'config'} includes" in said
    assert "inside the room's mount of" in said


def test_an_include_is_followed_through_the_files_it_includes(
    bare: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "first.cfg").write_text("[include]\n\tpath = second.cfg\n")
    (outside / "second.cfg").write_text(
        f"[include]\n\tpath = {bare / 'info' / 'x.cfg'}\n"
    )
    git(bare, "config", "include.path", str(outside / "first.cfg"))

    said = refused(bare, tmp_path, [Mount(source=bare)])

    assert f"{outside / 'second.cfg'} includes {bare / 'info' / 'x.cfg'}" in said


def test_a_link_outside_the_mounts_into_them_is_refused_and_an_include_outside_them_isnt(
    bare: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "plain.cfg").write_text("[include]\n\tpath = more.cfg\n")
    (outside / "more.cfg").write_text("[core]\n\tabbrev = 12\n")
    git(bare, "config", "include.path", str(outside / "plain.cfg"))

    room_git(
        bare,
        LaunchLayout(directory=tmp_path / "launch"),
        [Mount(source=bare)],
        UNGATED,
    )

    (outside / "linked.cfg").symlink_to(bare / "info" / "exclude")
    git(bare, "config", "--add", "include.path", str(outside / "linked.cfg"))
    assert f"includes {outside / 'linked.cfg'}" in refused(
        bare, tmp_path, [Mount(source=bare)]
    )


# A `commondir` the room plants in the git directory


def planted(project: Path, tmp_path: Path, url: str) -> Path:
    """Plant a `commondir` at the top of `project`, as a room can, naming a git directory of the room's.

    Its `config` names `origin` at `url` and sets `lup.probe`. git reads a git
    directory holding a `commondir` as a pointer to the one it names, so git
    told only `--git-dir=<project>` reads that one's `config`.
    """
    theirs = tmp_path / "planted.git"
    git(tmp_path, "init", "-q", "--bare", str(theirs))
    git(theirs, "config", "remote.origin.url", url)
    git(theirs, "config", "lup.probe", "the room's")
    (project / "commondir").write_text(f"{theirs}\n")
    return theirs


def test_host_git_reads_the_repository_s_own_config_past_a_planted_commondir(
    world: World, tmp_path: Path
) -> None:
    git(world.project, "config", "lup.probe", "the repository's")
    planted(world.project, tmp_path, str(tmp_path / "elsewhere.git"))
    launch = world.registered()
    remotes = Remotes(say=world.said.append)

    async def read() -> list[str]:
        probe = await remotes.git(launch, "config", "lup.probe")
        return [
            probe.output.strip(),
            await remotes.url(launch, "origin", push=True),
            await remotes.url(launch, "origin", push=False),
        ]

    assert asyncio.run(read()) == [
        "the repository's",
        str(world.forge),
        str(world.forge),
    ]


def test_a_push_past_a_planted_commondir_lands_on_the_repository_s_own_forge(
    world: World, clock: FakeClock, tmp_path: Path
) -> None:
    tip = world.commit("first")
    elsewhere = tmp_path / "elsewhere.git"
    git(tmp_path, "init", "-q", "--bare", str(elsewhere))
    planted(world.project, tmp_path, str(elsewhere))

    with world.served(clock):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert pushed.exit_code == 0, stderr(pushed)
    assert world.on_forge("refs/heads/feat") == tip
    assert git(elsewhere, "for-each-ref") == ""


def test_the_room_s_git_is_written_from_the_repository_s_own_config_past_a_planted_commondir(
    bare: Path, tmp_path: Path
) -> None:
    origin = git(bare, "config", "remote.origin.url")
    theirs = planted(bare, tmp_path, "planted:owner/elsewhere")
    # Including itself, the planted `config` fails any git that reads it.
    git(theirs, "config", "include.path", "config")
    launch = LaunchLayout(directory=tmp_path / "launch")

    room_git(bare, launch, [Mount(source=bare)], UNGATED).write()

    assert (
        git(
            tmp_path,
            "config",
            "--file",
            str(launch.gitconfig),
            "--get-regexp",
            r"^url\..*\.insteadof$",
        )
        == f"url.lup::{origin}.insteadof {origin}"
    )


# The door: what a push would publish, put to the modules' hooks at `publishing`


PRIVATE = Withheld(
    held=[
        Held(kind="value", text="Kestrel Labs"),
        Held(kind="home", text="/home/op"),
        Held(kind="alias", text="forge-op"),
    ]
)
"""Made-up values never published, as a launch would list them on the host."""


@pytest.fixture
def guarded(world: World, in_process: type[InProcess], tmp_path: Path) -> InProcess:
    """lup's default modules, served in the test's own process, `Private`'s list for the world's repository made up."""
    layout = Layout(state=tmp_path / "lup-state", data=tmp_path / "lup-data")
    write_model(kept(layout.module_data("private", world.project)), PRIVATE)
    return in_process(resolved=resolve(Project()), layout=layout)


def told(ran: Ran) -> str:
    """What the room's git said, which must hold no value never published."""
    said = stderr(ran)
    assert "/home/op" not in said
    assert "Kestrel" not in said
    return said


def test_a_push_carrying_a_value_is_refused_naming_commit_file_and_line(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    world.wrote("docs/clean.md", "Nothing here.\n", "clean")
    short = world.wrote("docs/notes.md", "Notes.\nSee /home/op/notes.\n", "notes")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert pushed.exit_code != 0
    assert world.on_forge("refs/heads/feat") is None
    said = told(pushed)
    assert (
        "lup refused to publish this push to `refs/heads/feat`: a module's check at "
        "the `publishing` moment found what isn't published, at each place below.\n"
        f"  {short} docs/notes.md:2:5 - the operator's home path\n"
        "      steer: write it as `~`, or a path in the repository from its root\n"
        "A push sends every commit the remote lacks, so rewrite the commit that "
        "carries it (amend it, or rebase) and push again: a commit on top leaves "
        "it in what's pushed."
    ) in said
    assert (
        "refused by lup: it would publish what isn't published, at the places "
        "listed above"
    ) in said
    assert not [line for line in world.said if "/home/op" in line]
    [publishing] = [each for each in guarded.told if each.occasion == "publishing"]
    assert publishing.conversation is None


def test_a_value_the_remote_holds_already_isnt_refused_again(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    world.wrote("docs/notes.md", "See /home/op/notes.\n", "notes")
    git(world.worktree, "push", "-q", str(world.forge), "HEAD:refs/heads/feat")
    world.wrote("README.md", "# Work\n\nMore.\n", "more")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert pushed.exit_code == 0, stderr(pushed)
    assert world.on_forge("refs/heads/feat") == git(world.worktree, "rev-parse", "HEAD")


def test_a_message_a_path_and_a_ref_s_name_carrying_a_value_are_each_refused(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    world.commit("For Kestrel Labs, at last")
    message = git(world.worktree, "rev-parse", "--short", "HEAD")
    named = world.wrote("docs/forge-op.md", "Plain.\n", "a page")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/to-forge-op")

    said = told(pushed)
    assert world.on_forge("refs/heads/to-forge-op") is None
    assert (
        "  the name of the ref it updates, at column 15 - an SSH alias in the "
        "repository's remote"
    ) in said
    assert (f"  {message}'s message:1:5 - one of the operator's private values") in said
    assert (
        f"  {named} docs/••••••••.md, in its path, at column 6 - an SSH alias in "
        "the repository's remote"
    ) in said


def test_a_file_that_isnt_text_and_a_link_are_read_for_what_they_add(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    binary = world.wrote("assets/blob.bin", b"\x00\x01HOME/OP? /home/op\x00", "a blob")
    (world.worktree / "notes").symlink_to("/home/op/notes")
    assert world.room_git("add", "notes").exit_code == 0
    world.commit("a link")
    link = git(world.worktree, "rev-parse", "--short", "HEAD")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    said = told(pushed)
    assert f"  {binary} assets/blob.bin, at byte 11 - the operator's home path" in said
    assert f"  {link} notes:1:1 - the operator's home path" in said


def test_a_value_added_and_removed_within_the_push_is_refused_where_it_was_added(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    added = world.wrote("docs/notes.md", "Kestrel Labs said so.\n", "added")
    world.wrote("docs/notes.md", "Someone said so.\n", "removed")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert world.on_forge("refs/heads/feat") is None
    said = told(pushed)
    assert f"  {added} docs/notes.md:1:1 - one of the operator's private values" in said


def test_a_merge_is_refused_for_what_its_resolution_adds_not_what_a_parent_brought(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    world.wrote("docs/notes.md", "one\n", "base")
    git(world.worktree, "push", "-q", str(world.forge), "HEAD:refs/heads/base")
    assert world.room_git("checkout", "-q", "-b", "side").exit_code == 0
    world.wrote("docs/notes.md", "side\n", "side")
    assert world.room_git("checkout", "-q", "main").exit_code == 0
    world.wrote("docs/notes.md", "main\n", "main")
    world.room_git("merge", "-q", "side", "-m", "merge")
    (world.worktree / "docs" / "notes.md").write_text("main and side, at /home/op\n")
    assert world.room_git("add", "docs/notes.md").exit_code == 0
    assert world.room_git("commit", "-q", "--no-edit").exit_code == 0
    merge = git(world.worktree, "rev-parse", "--short", "HEAD")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    said = told(pushed)
    assert said.count(" - the operator's home path") == 1
    assert f"  {merge} docs/notes.md:1:19 - the operator's home path" in said


def test_an_atomic_push_with_an_update_refused_at_publishing_pushes_none(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    clean = world.commit("clean")
    world.wrote("docs/notes.md", "See /home/op.\n", "notes")

    with world.served(clock, modules=guarded):
        pushed = world.room_git(
            "push",
            "--atomic",
            "origin",
            f"{clean}:refs/heads/clean",
            "HEAD:refs/heads/feat",
        )

    assert pushed.exit_code != 0
    assert world.on_forge("refs/heads/clean") is None
    assert world.on_forge("refs/heads/feat") is None
    assert "not pushed: the push is atomic, and `refs/heads/feat` was refused" in told(
        pushed
    )


def test_an_object_the_listing_names_that_the_store_lacks_is_skipped(
    world: World, clock: FakeClock, guarded: InProcess, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    git(tmp_path, "clone", "-q", str(world.forge), str(elsewhere))
    git(elsewhere, "commit", "-q", "--allow-empty", "-m", "theirs")
    git(elsewhere, "push", "-q", "origin", "HEAD:refs/heads/theirs")
    world.wrote("docs/clean.md", "Nothing here.\n", "clean")

    with world.served(clock, modules=guarded):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert pushed.exit_code == 0, stderr(pushed)
    assert world.on_forge("refs/heads/feat") == git(world.worktree, "rev-parse", "HEAD")


def test_a_launch_without_a_list_gets_one_at_its_first_push(
    world: World,
    clock: FakeClock,
    *,
    in_process: type[InProcess],
    stub_facts: type[StubFacts],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launch started before `Private` was approved has no list: the host builds it at the door, as a launch would, and keeps it."""
    layout = Layout(state=tmp_path / "state-none", data=tmp_path / "data-none")
    unlisted = in_process(resolved=resolve(Project()), layout=layout)
    place = kept(layout.module_data("private", world.project))
    monkeypatch.setattr(hooks, "HostFacts", lambda: stub_facts(home=Path("/home/op")))
    clean = world.wrote("docs/clean.md", "Nothing here.\n", "clean")
    carrying = world.wrote("docs/notes.md", "See /home/op/x.\n", "notes")

    with world.served(clock, modules=unlisted):
        first = world.room_git("push", "origin", f"{clean}:refs/heads/clean")
        second = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert first.exit_code == 0, stderr(first)
    assert world.on_forge("refs/heads/clean") is not None
    built = read_model(place, Withheld)
    assert built is not None
    assert Held(kind="home", text="/home/op") in built.held
    assert str(world.project) in [each.text for each in built.held]
    assert world.on_forge("refs/heads/feat") is None
    assert f"  {carrying} docs/notes.md:1:5 - the operator's home path" in told(second)


def test_a_push_whose_list_can_t_be_built_is_refused_saying_why(
    world: World,
    clock: FakeClock,
    in_process: type[InProcess],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Gone(Facts):
        def machine(self) -> Machine:
            message = "the account database is unreadable"
            raise LupDevError(message)

        def resolved(self, host: str) -> str | None:
            return host

        async def visibility(
            self, directory: Path, repository: GitHubRepository
        ) -> Visibility:
            return "public"

    unlisted = in_process(
        resolved=resolve(Project()),
        layout=Layout(state=tmp_path / "state-none", data=tmp_path / "data-none"),
    )
    monkeypatch.setattr(hooks, "HostFacts", Gone)
    world.wrote("docs/clean.md", "Nothing here.\n", "clean")

    with world.served(clock, modules=unlisted):
        pushed = world.room_git("push", "origin", "HEAD:refs/heads/feat")

    assert world.on_forge("refs/heads/feat") is None
    assert (
        "  all of it - a list of private values that couldn't be built\n"
        "      steer: the host couldn't build it (the account database is "
        "unreadable), so what it would check doesn't leave: tell the operator"
    ) in stderr(pushed)


def test_a_deletion_and_a_push_with_no_modules_ask_nothing(
    world: World, clock: FakeClock, guarded: InProcess
) -> None:
    world.wrote("docs/notes.md", "See /home/op.\n", "notes")
    git(world.worktree, "push", "-q", str(world.forge), "HEAD:refs/heads/feat")
    allowing = Limits(actions=["fetch", "push", "delete-ref"], protected=[])

    with world.served(clock, allowing, modules=guarded):
        deleted = world.room_git("push", "origin", ":refs/heads/feat")

    assert deleted.exit_code == 0, stderr(deleted)
    assert guarded.told == [
        each for each in guarded.told if each.occasion != "publishing"
    ]
