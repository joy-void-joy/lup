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
from lup_dev.host.client import HostClient, RoomClient, Starter, asked
from lup_dev.host.courier import Courier, Heard, Telling
from lup_dev.host.protocol import Done, HostError, Limits, Register, Reply, Stop
from lup_dev.host.service import Answerer, Asked, HostService, Judged
from lup_dev.launch.room import RoomError, RoomGit, room_git
from lup_dev.layout import ROOM_PATH, HostLayout, LaunchLayout, LaunchSockets
from lup_dev.remote.config import room_config
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

if TYPE_CHECKING:
    from collections.abc import Generator

    from conftest import FakeClock


@pytest.fixture(autouse=True)
def own_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git configuration out of the host's git, as the room's is."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
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

    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        return answer

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
        self.room = RoomGit(repository=bare, launch=self.launch)
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
            limits=limits,
        )

    @contextmanager
    def served(self, clock: FakeClock, limits: Limits = DEFAULT) -> Generator[None]:
        service = HostService(
            layout=self.layout,
            answerer=Stub(),
            courier=Deaf(),
            judge=no_judge,
            say=self.said.append,
            room_routes=routes(Remotes(say=self.said.append)),
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
        "`force-push` isn't among the actions the project's declaration allows "
        "(`Core.credentials`): it's the operator's"
    )
    assert forcing in stderr(forced)
    assert forcing in stderr(leased)
    assert "deleting `refs/heads/feat`: `delete-ref` isn't among the actions" in stderr(
        deleted
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


def test_a_fetch_the_limits_dont_allow_is_refused(
    world: World, clock: FakeClock
) -> None:
    with world.served(clock, Limits(actions=["push"], protected=[])):
        fetched = world.room_git("fetch", "origin", "main")

    assert fetched.exit_code != 0
    assert "`fetch` isn't among the actions" in stderr(fetched)


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
    git(bare, "remote", "set-url", "origin", "jvj:owner/project")
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

    room_config(bare, written, Path("/run/lup/request.sock"))

    def read(key: str) -> list[str]:
        return git(tmp_path, "config", "--file", str(written), "--get-all", key).split(
            "\n"
        )

    assert read("url.lup::jvj:owner/project.insteadOf") == ["jvj:owner/project"]
    assert read("url.lup::ssh://push.example/owner/project.insteadOf") == [
        "ssh://push.example/owner/project"
    ]
    assert read("url.lup::https://mirror.example/a b.git.insteadOf") == [
        "https://mirror.example/a b.git"
    ]
    assert read("branch.autoSetupMerge") == ["false"]
    assert read("push.default") == ["current"]
    assert read("lup.requestSocket") == ["/run/lup/request.sock"]


def test_a_launch_writes_the_helper_and_puts_it_first_on_the_room_s_path(
    bare: Path, tmp_path: Path
) -> None:
    launch = LaunchLayout(directory=tmp_path / "launch")
    room = room_git(bare, launch, [Mount(source=bare)])

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


# Refused at launch


def refused(bare: Path, tmp_path: Path, mounts: list[Mount | Mask]) -> str:
    with pytest.raises(RoomError) as refusal:
        room_git(bare, LaunchLayout(directory=tmp_path / "launch"), mounts)
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

    room_git(bare, LaunchLayout(directory=tmp_path / "launch"), [Mount(source=bare)])

    (outside / "linked.cfg").symlink_to(bare / "info" / "exclude")
    git(bare, "config", "--add", "include.path", str(outside / "linked.cfg"))
    assert f"includes {outside / 'linked.cfg'}" in refused(
        bare, tmp_path, [Mount(source=bare)]
    )
