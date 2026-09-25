"""Review services authenticate reuse and stop after their final harness owner."""

import os
import shutil
import signal
import socket
import sys
import webbrowser
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier, Event
from textwrap import dedent

import httpx
import pytest
import sh
from pydantic import BaseModel, SecretStr
from typer.testing import CliRunner

from lup.coordination.identity import MEMBER_ENV
from lup.devtools.dev import review_service
from lup.devtools.dev.questions import create_questions_app
from lup.devtools.dev.review_service import (
    ReviewInboxService,
    ReviewServiceRecord,
    ReviewServiceStore,
    open_review_inbox,
    review_inbox_session,
    review_inbox_status,
    service_health,
    stop_review_inbox,
)
from lup.devtools.harness.preflight import NONCE_VARIABLE
from lup.harness.review_environment import REVIEW_INBOX_URL_ENV
from lup.policy.identity import AGENT_IDENTITY_ENV
from lup.workspace.context import SESSION_DIR_ENV, SESSION_ID_ENV
from lup.web import serve as web_serve


class ServiceFixture(BaseModel, arbitrary_types_allowed=True):
    """Every real worker belongs to this fixture and is reaped at teardown."""

    root: Path
    state_home: Path
    children: list[sh.RunningCommand] = []
    launchers: list[sh.RunningCommand] = []
    owners: list[ExitStack] = []
    opened: list[str] = []

    def start(
        self,
        root: Path | None = None,
        *,
        open_page: bool = True,
        port: int = 8766,
        host: str = "127.0.0.1",
        timeout_seconds: float = 30,
    ) -> ReviewInboxService:
        owner = ExitStack()
        self.owners.append(owner)
        return owner.enter_context(
            review_inbox_session(
                root or self.root,
                state_home=self.state_home,
                open_page=open_page,
                port=port,
                host=host,
                timeout_seconds=timeout_seconds,
            )
        )


@pytest.fixture
def operator_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        NONCE_VARIABLE,
        MEMBER_ENV,
        AGENT_IDENTITY_ENV,
        SESSION_DIR_ENV,
        SESSION_ID_ENV,
        REVIEW_INBOX_URL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operator_environment: None,
) -> Iterator[ServiceFixture]:
    del operator_environment
    root = tmp_path / "repository"
    sh.git("init", "--initial-branch=main", str(root))
    sh.git(
        "-C",
        str(root),
        "-c",
        "user.name=Service test",
        "-c",
        "user.email=service@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "Fixture",
    )
    fixture = ServiceFixture(root=root, state_home=tmp_path / "operator-state")
    launch = review_service.launch_review_worker

    def owned(store: ReviewServiceStore) -> sh.RunningCommand:
        child = launch(store)
        fixture.children.append(child)
        return child

    def opened(url: str) -> bool:
        fixture.opened.append(url)
        return True

    monkeypatch.setattr(review_service, "launch_review_worker", owned)
    monkeypatch.setattr(webbrowser, "open", opened)
    try:
        yield fixture
    finally:
        try:
            for launcher in fixture.launchers:
                if launcher.is_alive():
                    launcher.terminate()
            for owner in reversed(fixture.owners):
                owner.close()
            stop_review_inbox(fixture.root, state_home=fixture.state_home)
        finally:
            for child in (*fixture.launchers, *fixture.children):
                if child.is_alive():
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except sh.TimeoutException:
                    child.kill()
                    try:
                        child.wait(timeout=5)
                    except sh.ErrorReturnCode as error:
                        assert error.exit_code in (-15, -9, -2, 130)
                except sh.ErrorReturnCode as error:
                    assert error.exit_code in (0, 1, -15, -9, -2, 130)
                assert not child.is_alive()


def test_startup_reuses_authenticated_service_and_opens_only_one_tab(
    service: ServiceFixture,
) -> None:
    first = service.start(port=0)
    second = service.start()
    status = review_inbox_status(service.root, state_home=service.state_home)
    assert first.started and first.browser_opened
    assert not second.started and not second.browser_opened
    assert first.endpoint == second.endpoint == status.endpoint
    assert first.pid == second.pid == status.pid
    assert status.running and status.verified
    assert len(service.children) == len(service.opened) == 1
    assert first.launch_url.get_secret_value() == service.opened[0]
    assert "token=" not in repr(first)
    reopened = open_review_inbox(service.root, state_home=service.state_home)
    assert not reopened.started and reopened.browser_opened
    assert len(service.opened) == 2
    stopped = stop_review_inbox(service.root, state_home=service.state_home)
    assert not stopped.running
    assert not review_inbox_status(service.root, state_home=service.state_home).running


@pytest.mark.parametrize("selected_root", [False, True])
def test_serve_stays_in_foreground_without_registering_a_detached_service(
    service: ServiceFixture, monkeypatch: pytest.MonkeyPatch, selected_root: bool
) -> None:
    from fastapi import FastAPI

    requested = service.root
    if selected_root:
        requested = service.root.parent / "selected"
        sh.git("init", "--initial-branch=main", str(requested))
    listeners: list[tuple[str, int]] = []

    def foreground(
        app: FastAPI,
        *,
        host: str,
        port: int,
        access_log: bool,
        timeout_graceful_shutdown: int,
    ) -> None:
        assert app is not None and access_log is False
        assert timeout_graceful_shutdown == 2
        listeners.append((host, port))

    monkeypatch.setattr("uvicorn.run", foreground)
    arguments = ["serve", "--no-open", "--port", "9876"]
    if selected_root:
        arguments.extend(["--root", str(requested)])
    result = CliRunner().invoke(create_questions_app(service.root), arguments)
    assert result.exit_code == 0, result.exception
    assert listeners == [("127.0.0.1", 9876)]
    assert not service.children and not service.opened
    assert not review_inbox_status(requested, state_home=service.state_home).running


def test_open_without_a_harness_owner_does_not_start_a_service(
    service: ServiceFixture,
) -> None:
    with pytest.raises(ValueError, match="harness|questions serve"):
        open_review_inbox(service.root, state_home=service.state_home)
    assert not service.children and not service.opened
    assert not review_inbox_status(service.root, state_home=service.state_home).running


def test_manual_foreground_serve_stops_its_listener_on_interrupt(
    service: ServiceFixture,
) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    script = service.root.parent / "manual-server.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "from lup.devtools.dev import questions\n"
        "questions.secrets.token_urlsafe = lambda _length: 'manual-test-secret'\n"
        "app = questions.create_questions_app(Path(sys.argv[1]))\n"
        "app(args=['serve', '--port', sys.argv[2], '--no-open'], "
        "standalone_mode=False)\n"
    )
    log = service.root.parent / "manual-server.log"
    with log.open("w") as output:
        launcher = sh.Command(sys.executable)(
            str(script),
            str(service.root),
            str(port),
            _out=output,
            _err_to_out=True,
            _bg=True,
            _bg_exc=False,
            _new_session=True,
        )
    service.launchers.append(launcher)
    endpoint = f"http://127.0.0.1:{port}"
    delay = Event()
    with httpx.Client(trust_env=False, timeout=0.5) as client:
        for _ in range(200):
            assert launcher.is_alive(), f"Manual serve exited; inspect {log}."
            try:
                response = client.get(endpoint)
            except httpx.TransportError:
                delay.wait(0.05)
                continue
            assert response.status_code == 200
            break
        else:
            pytest.fail(f"Manual serve did not become ready; inspect {log}.")
        with client.stream(
            "GET",
            f"{endpoint}/api/events",
            headers={"Authorization": "Bearer manual-test-secret"},
        ) as stream:
            assert stream.status_code == 200
            launcher.signal(signal.SIGINT)
            try:
                launcher.wait(timeout=10)
            except sh.ErrorReturnCode as error:
                assert error.exit_code in (-signal.SIGINT, 130)
            assert not launcher.is_alive()
        with pytest.raises(httpx.TransportError):
            client.get(endpoint)
    assert not service.children
    assert not review_inbox_status(service.root, state_home=service.state_home).running


@pytest.mark.parametrize("host", ["localhost", "::1"])
def test_managed_service_accepts_supported_loopback_hosts(
    service: ServiceFixture, host: str
) -> None:
    started = service.start(port=0, host=host, open_page=False)
    assert httpx.URL(started.endpoint).host == host
    reused = service.start()
    assert not reused.started and reused.pid == started.pid


def test_private_credentials_refuse_repository_locations(
    service: ServiceFixture,
) -> None:
    for home in (service.root / "local-state", service.root / ".git" / "state"):
        with pytest.raises(ValueError, match="outside Git checkouts"):
            with review_inbox_session(service.root, state_home=home):
                pytest.fail("Repository-local credentials were accepted.")
        assert not home.exists()


def test_reuse_checks_new_sibling_checkout_and_shares_repository_identity(
    service: ServiceFixture,
) -> None:
    initial = service.start(open_page=False, port=0)
    sibling = service.root.parent / "sibling"
    sh.git("-C", str(service.root), "worktree", "add", "-b", "sibling", str(sibling))
    reused = service.start(sibling)
    assert not reused.started
    assert reused.pid == initial.pid
    store = ReviewServiceStore.for_root(sibling, service.state_home)
    record = store.read()
    assert record is not None
    health = service_health(record, sibling)
    assert health is not None and {service.root, sibling} <= set(health.roots)
    assert len(service.children) == 1


def external_owner(service: ServiceFixture) -> sh.RunningCommand:
    """A real launcher releases normally on SIGUSR1, or abruptly on SIGTERM."""
    script = service.root.parent / "launcher.py"
    script.write_text(
        "import signal\nimport sys\nfrom pathlib import Path\n"
        "from threading import Event\n"
        "from lup.devtools.dev.review_service import review_inbox_session\n"
        "release = Event()\n"
        "signal.signal(signal.SIGUSR1, lambda *_args: release.set())\n"
        "with review_inbox_session(Path(sys.argv[1]), "
        "state_home=Path(sys.argv[2]), port=0, open_page=False) as service:\n"
        "    print(service.model_dump_json(), flush=True)\n"
        "    release.wait()\n"
    )
    ready = Event()
    output: list[str] = []

    def receive(line: str) -> None:
        output.append(line)
        ready.set()

    launcher = sh.Command(sys.executable)(
        str(script),
        str(service.root),
        str(service.state_home),
        _out=receive,
        _bg=True,
        _bg_exc=False,
        _new_session=True,
    )
    service.launchers.append(launcher)
    assert ready.wait(timeout=20), "The external launcher did not become ready."
    launched = ReviewInboxService.model_validate_json("".join(output))
    assert launched.pid == service.children[0].pid
    return launcher


def test_two_process_owners_keep_the_service_until_the_last_release(
    service: ServiceFixture,
) -> None:
    started = service.start(port=0, open_page=False)
    owner = external_owner(service)
    service.owners[0].close()
    status = review_inbox_status(service.root, state_home=service.state_home)
    assert status.running and status.pid == started.pid
    assert service.children[0].is_alive()
    owner.signal(signal.SIGUSR1)
    owner.wait(timeout=15)
    service.children[0].wait(timeout=10)
    assert not review_inbox_status(service.root, state_home=service.state_home).running


def test_launcher_death_releases_kernel_lease_and_watchdog_stops_worker(
    service: ServiceFixture,
) -> None:
    service.start(port=0, open_page=False)
    owner = external_owner(service)
    service.owners[0].close()
    assert service.children[0].is_alive()
    owner.terminate()
    with pytest.raises(sh.ErrorReturnCode) as terminated:
        owner.wait(timeout=5)
    assert terminated.value.exit_code == -signal.SIGTERM
    service.children[0].wait(timeout=15)
    assert not review_inbox_status(service.root, state_home=service.state_home).running


def test_last_owner_shutdown_closes_an_authenticated_live_event_stream(
    service: ServiceFixture,
) -> None:
    started = service.start(port=0, open_page=False)
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    record = store.read()
    assert record is not None
    with httpx.Client(trust_env=False, timeout=10) as client:
        with client.stream(
            "GET",
            f"{started.endpoint}/api/events",
            headers={"Authorization": f"Bearer {record.token.get_secret_value()}"},
        ) as stream:
            assert stream.status_code == 200
            service.owners[0].close()
            service.children[0].wait(timeout=5)
    assert not review_inbox_status(service.root, state_home=service.state_home).running


def test_static_assets_and_discovery_survive_launch_worktree_removal(
    service: ServiceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    sibling = service.root.parent / "launch-worktree"
    sh.git("-C", str(service.root), "worktree", "add", "-b", "launch", str(sibling))
    bundle = service.root.parent / "disposable-review-bundle"
    (bundle / "assets").mkdir(parents=True)
    index = '<!doctype html><script src="/assets/keep.js"></script>'
    script = "console.log('retained review assets')"
    (bundle / "index.html").write_text(index)
    (bundle / "assets" / "keep.js").write_text(script)
    monkeypatch.setattr(web_serve, "bundle_root", lambda _surface: bundle)
    started = service.start(sibling, port=0, open_page=False)
    sh.git("-C", str(service.root), "worktree", "remove", str(sibling))
    shutil.rmtree(bundle)
    assert not sibling.exists() and not bundle.exists()
    with httpx.Client(trust_env=False, timeout=3) as client:
        page = client.get(started.endpoint)
        asset = client.get(f"{started.endpoint}/assets/keep.js")
    assert page.status_code == asset.status_code == 200
    assert page.text == index and asset.text == script
    reused = service.start()
    assert not reused.started and reused.pid == started.pid


def test_concurrent_launches_share_one_ready_service(service: ServiceFixture) -> None:
    barrier = Barrier(3)

    def launch(_index: int) -> ReviewInboxService:
        barrier.wait(timeout=10)
        return service.start(port=0)

    with ThreadPoolExecutor(max_workers=3) as workers:
        results = list(workers.map(launch, range(3)))
    assert sum(result.started for result in results) == 1
    assert len({result.pid for result in results}) == 1
    assert len(service.children) == len(service.opened) == 1


def legacy_service(service: ServiceFixture) -> ReviewInboxService:
    """Run an authenticated pre-lease server with its original health contract."""
    script = service.root.parent / "legacy-service.py"
    script.write_text(
        dedent(
            """\
            import asyncio
            import os
            import secrets
            import socket
            import sys
            from pathlib import Path

            import uvicorn
            from fastapi import BackgroundTasks
            from pydantic import BaseModel, SecretStr

            from lup.devtools.dev.questions import ReviewStore, review_app
            from lup.devtools.dev.review_service import (
                ReviewServiceHealth, ReviewServiceRecord, ReviewServiceStore,
            )

            class LegacyRecord(BaseModel, extra="forbid"):
                repository: Path
                instance: str
                token: SecretStr
                host: str = "127.0.0.1"
                port: int = 8766
                endpoint: str = ""
                pid: int = 0
                stopping: bool = False

            root = Path(sys.argv[1])
            store = ReviewServiceStore.for_root(root, Path(sys.argv[2]))
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(128)
                endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}"
                record = ReviewServiceRecord(
                    repository=store.repository,
                    instance=secrets.token_hex(16),
                    token=SecretStr(secrets.token_urlsafe(32)),
                    endpoint=endpoint,
                    pid=os.getpid(),
                )
                app = review_app(endpoint, record.token.get_secret_value(), (root,))
                reviews = ReviewStore(roots=(root,), discover=True)
                server = uvicorn.Server(uvicorn.Config(app, access_log=False))

                @app.get("/api/service")
                def health():
                    return ReviewServiceHealth(
                        instance=record.instance,
                        repository=record.repository,
                        roots=list(reviews.checkout_roots()),
                        pid=record.pid,
                    ).model_dump(mode="json", exclude={"session_owned"})

                @app.post("/api/service/stop")
                def stop(tasks: BackgroundTasks):
                    async def shutdown():
                        await asyncio.sleep(0.3)
                        server.should_exit = True

                    tasks.add_task(shutdown)
                    return {"running": True, "detail": "Shutdown requested."}

                store.write(record)
                print(record.ready(started=True).model_dump_json(), flush=True)
                try:
                    server.run(sockets=[listener])
                finally:
                    with store.lock():
                        LegacyRecord.model_validate_json(store.record_path.read_bytes())
                        store.forget(record.instance)
            """
        )
    )
    ready = Event()
    output: list[str] = []

    def receive(line: str) -> None:
        output.append(line)
        ready.set()

    child = sh.Command(sys.executable)(
        str(script),
        str(service.root),
        str(service.state_home),
        _out=receive,
        _bg=True,
        _bg_exc=False,
        _new_session=True,
    )
    service.children.append(child)
    assert ready.wait(timeout=20), "The pre-lease review service did not start."
    result = ReviewInboxService.model_validate_json("".join(output))
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    record = store.read()
    assert record is not None
    health = service_health(record, service.root, timeout_seconds=5)
    assert health is not None and not health.session_owned
    return result


def test_authenticated_pre_lease_service_is_replaced_with_a_session_owned_worker(
    service: ServiceFixture,
) -> None:
    legacy = legacy_service(service)
    replacement = service.start(port=0, open_page=False)
    assert replacement.started and replacement.pid != legacy.pid
    service.children[0].wait(timeout=5)
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    record = store.read()
    assert record is not None and record.session_owned
    health = service_health(record, service.root)
    assert health is not None and health.session_owned
    service.owners[0].close()
    service.children[1].wait(timeout=10)
    assert store.read() is None


def test_concurrent_legacy_upgrades_share_and_preserve_one_replacement(
    service: ServiceFixture,
) -> None:
    legacy = legacy_service(service)
    barrier = Barrier(3)

    def upgrade(_index: int) -> ReviewInboxService:
        barrier.wait(timeout=10)
        return service.start(port=0, open_page=False)

    with ThreadPoolExecutor(max_workers=3) as workers:
        results = list(workers.map(upgrade, range(3)))
    assert sum(result.started for result in results) == 1
    assert len({result.pid for result in results}) == 1
    assert results[0].pid != legacy.pid
    assert len(service.children) == 2
    service.children[0].wait(timeout=5)
    assert service.children[1].is_alive()
    service.owners[0].close()
    service.owners[1].close()
    assert service.children[1].is_alive()
    service.owners[2].close()
    service.children[1].wait(timeout=10)
    assert not review_inbox_status(service.root, state_home=service.state_home).running


def test_worker_cleanup_waits_for_registry_lock_and_preserves_replacement(
    service: ServiceFixture,
) -> None:
    service.start(port=0, open_page=False)
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    record = store.read()
    assert record is not None
    replacement = record.model_copy(update={"instance": "replacement"})
    with store.lock():
        with httpx.Client(trust_env=False, timeout=3) as client:
            response = client.post(
                f"{record.endpoint}/api/service/stop",
                headers={
                    "Authorization": f"Bearer {record.token.get_secret_value()}",
                    "Origin": record.endpoint,
                },
                json={},
            )
        assert response.status_code == 200
        with pytest.raises(sh.TimeoutException):
            service.children[0].wait(timeout=2)
        store.write(replacement)
    service.children[0].wait(timeout=5)
    assert store.read() == replacement


def test_concurrent_stop_and_launch_preserve_the_replacement_service(
    service: ServiceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = service.start(port=0, open_page=False)
    marked = Event()
    write = ReviewServiceStore.write

    def written(store: ReviewServiceStore, record: ReviewServiceRecord) -> None:
        write(store, record)
        if record.stopping:
            marked.set()

    monkeypatch.setattr(ReviewServiceStore, "write", written)
    with ThreadPoolExecutor(max_workers=2) as workers:
        stopped = workers.submit(
            stop_review_inbox, service.root, state_home=service.state_home
        )
        assert marked.wait(timeout=10)
        launched = workers.submit(
            service.start,
            port=0,
            open_page=False,
        )
        assert stopped.result(timeout=15).running is False
        replacement = launched.result(timeout=30)
    assert replacement.started and replacement.pid != initial.pid
    status = review_inbox_status(service.root, state_home=service.state_home)
    assert status.running and status.pid == replacement.pid


def test_occupied_port_falls_back_without_touching_the_listener(
    service: ServiceFixture,
) -> None:
    with socket.socket() as unrelated:
        unrelated.bind(("127.0.0.1", 0))
        unrelated.listen(1)
        port = unrelated.getsockname()[1]
        started = service.start(port=port, open_page=False)
        assert httpx.URL(started.endpoint).port != port
        assert unrelated.getsockname()[1] == port
        assert unrelated.fileno() >= 0


def test_stale_record_never_authorizes_killing_its_recorded_pid(
    service: ServiceFixture,
) -> None:
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    store.write(
        ReviewServiceRecord(
            repository=store.repository,
            instance="stale",
            token=SecretStr("expired-secret"),
            endpoint="http://127.0.0.1:1",
            pid=os.getpid(),
        )
    )
    assert not stop_review_inbox(service.root, state_home=service.state_home).running
    started = service.start(port=0, open_page=False)
    assert started.started and started.pid != os.getpid()
    record = store.read()
    assert record is not None and service_health(record, service.root) is not None


def test_stale_worker_rejects_a_replacement_record_before_binding(
    service: ServiceFixture,
) -> None:
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    replacement = ReviewServiceRecord(
        repository=store.repository,
        instance="replacement",
        token=SecretStr("replacement-secret"),
        port=0,
        session_owned=True,
    )
    store.write(replacement)
    with pytest.raises(ValueError, match="startup record"):
        review_service.run_review_worker(
            store.record_path, expected_instance="retired-instance"
        )
    assert store.read() == replacement
    assert not service.children


def test_delayed_worker_cannot_publish_over_a_replacement_registry(
    service: ServiceFixture,
) -> None:
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    stale = ReviewServiceRecord(
        repository=store.repository,
        instance="delayed-instance",
        token=SecretStr("delayed-secret"),
        port=0,
        session_owned=True,
    )
    review_service.snapshot_review_bundle(store, stale.instance)
    owner = ExitStack()
    service.owners.append(owner)
    owner.enter_context(review_service.hold_review_lease(store, stale.instance))
    store.write(stale)
    script = service.root.parent / "delayed-worker.py"
    script.write_text(
        dedent(
            """\
            import signal
            import sys
            from pathlib import Path
            from threading import Event

            from lup.devtools.dev import questions, review_service

            release = Event()
            signal.signal(signal.SIGUSR1, lambda *_args: release.set())
            original = questions.review_app

            def paused(*args, **kwargs):
                print("Validated startup record", flush=True)
                release.wait()
                return original(*args, **kwargs)

            questions.review_app = paused
            review_service.run_review_worker(Path(sys.argv[1]), sys.argv[2])
            """
        )
    )
    validated = Event()

    def receive(_line: str) -> None:
        validated.set()

    child = sh.Command(sys.executable)(
        str(script),
        str(store.record_path),
        stale.instance,
        _out=receive,
        _bg=True,
        _bg_exc=False,
        _new_session=True,
    )
    service.children.append(child)
    assert validated.wait(timeout=15), "Worker did not reach the validation barrier."
    replacement = stale.model_copy(update={"instance": "replacement-instance"})
    with store.lock():
        store.write(replacement)
    child.signal(signal.SIGUSR1)
    child.wait(timeout=15)
    assert not child.is_alive()
    assert store.read() == replacement


@pytest.mark.parametrize("mismatch", ["token", "instance", "repository", "root", "pid"])
def test_reuse_refuses_wrong_authority_or_watch_scope(
    service: ServiceFixture, mismatch: str
) -> None:
    service.start(open_page=False, port=0)
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    record = store.read()
    assert record is not None
    root = service.root
    match mismatch:
        case "token":
            record = record.model_copy(update={"token": SecretStr("another-secret")})
        case "instance":
            record = record.model_copy(update={"instance": "another-instance"})
        case "repository":
            record = record.model_copy(update={"repository": service.state_home})
        case "root":
            root = service.state_home
        case "pid":
            record = record.model_copy(update={"pid": os.getpid()})
    assert service_health(record, root) is None


def test_credentials_stay_private_and_health_and_shutdown_require_authentication(
    service: ServiceFixture,
) -> None:
    result = service.start(open_page=False, port=0)
    store = ReviewServiceStore.for_root(service.root, service.state_home)
    record = store.read()
    assert record is not None
    token = record.token.get_secret_value()
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert store.record_path.stat().st_mode & 0o777 == 0o600
    assert not store.directory.is_relative_to(service.root)
    assert token.encode() not in Path(f"/proc/{result.pid}/cmdline").read_bytes()
    assert token.encode() not in Path(f"/proc/{result.pid}/environ").read_bytes()
    assert token not in store.log_path.read_text()
    for descriptor in Path(f"/proc/{result.pid}/fd").iterdir():
        try:
            target = descriptor.readlink()
        except FileNotFoundError:
            continue
        assert not target.is_relative_to(store.lease_root(record.instance))
    with httpx.Client(trust_env=False, timeout=3) as client:
        page = client.get(result.endpoint)
        health = client.get(f"{result.endpoint}/api/service")
        stop = client.post(f"{result.endpoint}/api/service/stop", json={})
        cross_origin = client.post(
            f"{result.endpoint}/api/service/stop",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://other.invalid",
            },
            json={},
        )
    assert token not in page.text
    assert health.status_code == stop.status_code == 401
    assert cross_origin.status_code == 403
    assert review_inbox_status(service.root, state_home=service.state_home).running


@pytest.mark.parametrize(
    "marker",
    [NONCE_VARIABLE, MEMBER_ENV, AGENT_IDENTITY_ENV, SESSION_DIR_ENV, SESSION_ID_ENV],
)
@pytest.mark.parametrize("operation", ["ensure", "open", "stop", "worker"])
def test_agent_markers_refuse_before_accessing_private_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operator_environment: None,
    marker: str,
    operation: str,
) -> None:
    del operator_environment
    monkeypatch.setenv(marker, "requesting-session")
    private = tmp_path / "must-not-create"
    with pytest.raises(ValueError, match="independent operator terminal"):
        match operation:
            case "ensure":
                with review_inbox_session(tmp_path, state_home=private):
                    pytest.fail("Agent authority was accepted.")
            case "open":
                open_review_inbox(tmp_path, state_home=private)
            case "stop":
                stop_review_inbox(tmp_path, state_home=private)
            case "worker":
                review_service.run_review_worker(private / "service.json")
    assert not private.exists()


@pytest.mark.parametrize("endpoint", ["", "http://127.0.0.1:9876"])
def test_agent_status_reads_only_the_advertised_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operator_environment: None,
    endpoint: str,
) -> None:
    del operator_environment
    monkeypatch.setenv(NONCE_VARIABLE, "requesting-session")
    monkeypatch.setenv(REVIEW_INBOX_URL_ENV, endpoint)
    private = tmp_path / "must-not-create"
    status = review_inbox_status(tmp_path, state_home=private)
    assert status.endpoint == endpoint
    assert status.running is None and not status.verified
    assert not private.exists()


def test_declining_inbox_removes_only_browser_commands(tmp_path: Path) -> None:
    help_text = CliRunner().invoke(
        create_questions_app(tmp_path, review_inbox_enabled=False), ["--help"]
    )
    assert help_text.exit_code == 0
    for name in ("list", "show", "answer", "reject", "cancel"):
        assert name in help_text.output
    for name in ("serve", "status", "open", "stop"):
        assert name not in help_text.output


def test_failed_startup_reports_its_log_and_reaps_its_own_worker(
    service: ServiceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = service.root.parent / "slow-worker.py"
    script.write_text("import time\ntime.sleep(60)\n")

    def slow(store: ReviewServiceStore) -> sh.RunningCommand:
        child = sh.Command(sys.executable)(
            str(script), _bg=True, _bg_exc=False, _new_session=True
        )
        service.children.append(child)
        return child

    monkeypatch.setattr(review_service, "launch_review_worker", slow)
    with pytest.raises(RuntimeError, match="did not become ready; inspect"):
        service.start(
            open_page=False,
            port=0,
            timeout_seconds=0.2,
        )
    assert len(service.children) == 1 and not service.children[0].is_alive()
    assert ReviewServiceStore.for_root(service.root, service.state_home).read() is None
