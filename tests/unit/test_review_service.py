"""A host-owned review service authenticates reuse and outlives its launcher."""

import os
import shutil
import socket
import sys
import webbrowser
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

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
    ensure_review_inbox,
    open_review_inbox,
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
    opened: list[str] = []


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
        stop_review_inbox(fixture.root, state_home=fixture.state_home)
        for child in fixture.children:
            if child.is_alive():
                child.terminate()
            try:
                child.wait(timeout=5)
            except sh.TimeoutException:
                child.kill()
                try:
                    child.wait(timeout=5)
                except sh.ErrorReturnCode as error:
                    assert error.exit_code in (-15, -9)
            except sh.ErrorReturnCode as error:
                assert error.exit_code in (0, 1, -15, -9)
            assert not child.is_alive()


def test_startup_reuses_authenticated_service_and_opens_only_one_tab(
    service: ServiceFixture,
) -> None:
    first = ensure_review_inbox(service.root, state_home=service.state_home, port=0)
    second = ensure_review_inbox(service.root, state_home=service.state_home)
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
def test_single_repository_serve_registers_service_for_launcher_reuse(
    service: ServiceFixture, monkeypatch: pytest.MonkeyPatch, selected_root: bool
) -> None:
    requested = service.root
    if selected_root:
        requested = service.root.parent / "selected"
        sh.git("init", "--initial-branch=main", str(requested))
    original = review_service.ensure_review_inbox

    def ensure(
        root: Path, *, host: str, port: int, open_page: bool
    ) -> ReviewInboxService:
        return original(
            root,
            state_home=service.state_home,
            host=host,
            port=port,
            open_page=open_page,
        )

    monkeypatch.setattr(review_service, "ensure_review_inbox", ensure)
    arguments = ["serve", "--no-open"]
    if selected_root:
        arguments.extend(["--root", str(requested)])
    result = CliRunner().invoke(create_questions_app(service.root), arguments)
    assert result.exit_code == 0, result.exception
    reused = original(requested, state_home=service.state_home)
    assert not reused.started and reused.endpoint in result.stdout
    assert not service.opened and len(service.children) == 1
    if selected_root:
        assert not review_inbox_status(
            service.root, state_home=service.state_home
        ).running
    assert stop_review_inbox(requested, state_home=service.state_home).running is False


@pytest.mark.parametrize("host", ["localhost", "::1"])
def test_managed_service_accepts_supported_loopback_hosts(
    service: ServiceFixture, host: str
) -> None:
    started = ensure_review_inbox(
        service.root, state_home=service.state_home, port=0, host=host, open_page=False
    )
    assert httpx.URL(started.endpoint).host == host
    reused = ensure_review_inbox(service.root, state_home=service.state_home)
    assert not reused.started and reused.pid == started.pid


def test_private_credentials_refuse_repository_locations(
    service: ServiceFixture,
) -> None:
    for home in (service.root / "local-state", service.root / ".git" / "state"):
        with pytest.raises(ValueError, match="outside Git checkouts"):
            ensure_review_inbox(service.root, state_home=home)
        assert not home.exists()


def test_reuse_checks_new_sibling_checkout_and_shares_repository_identity(
    service: ServiceFixture,
) -> None:
    initial = ensure_review_inbox(
        service.root, state_home=service.state_home, open_page=False, port=0
    )
    sibling = service.root.parent / "sibling"
    sh.git("-C", str(service.root), "worktree", "add", "-b", "sibling", str(sibling))
    reused = ensure_review_inbox(sibling, state_home=service.state_home)
    assert not reused.started
    assert reused.pid == initial.pid
    store = ReviewServiceStore.for_root(sibling, service.state_home)
    record = store.read()
    assert record is not None
    health = service_health(record, sibling)
    assert health is not None and {service.root, sibling} <= set(health.roots)
    assert len(service.children) == 1


def test_detached_service_survives_the_launcher_process_exit(
    service: ServiceFixture,
) -> None:
    script = service.root.parent / "launcher.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "from lup.devtools.dev.review_service import ensure_review_inbox\n"
        "service = ensure_review_inbox(Path(sys.argv[1]), "
        "state_home=Path(sys.argv[2]), port=0, open_page=False)\n"
        "print(service.model_dump_json())\n"
    )
    output = sh.Command(sys.executable)(
        str(script), str(service.root), str(service.state_home)
    )
    launched = ReviewInboxService.model_validate_json(str(output))
    reused = ensure_review_inbox(service.root, state_home=service.state_home)
    assert not reused.started and reused.pid == launched.pid
    assert reused.endpoint == launched.endpoint
    assert not service.children and not service.opened
    assert (
        stop_review_inbox(service.root, state_home=service.state_home).running is False
    )


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
    started = ensure_review_inbox(
        sibling, state_home=service.state_home, port=0, open_page=False
    )
    sh.git("-C", str(service.root), "worktree", "remove", str(sibling))
    shutil.rmtree(bundle)
    assert not sibling.exists() and not bundle.exists()
    with httpx.Client(trust_env=False, timeout=3) as client:
        page = client.get(started.endpoint)
        asset = client.get(f"{started.endpoint}/assets/keep.js")
    assert page.status_code == asset.status_code == 200
    assert page.text == index and asset.text == script
    reused = ensure_review_inbox(service.root, state_home=service.state_home)
    assert not reused.started and reused.pid == started.pid


def test_concurrent_launches_share_one_ready_service(service: ServiceFixture) -> None:
    barrier = Barrier(3)

    def launch(_index: int) -> ReviewInboxService:
        barrier.wait(timeout=10)
        return ensure_review_inbox(service.root, state_home=service.state_home, port=0)

    with ThreadPoolExecutor(max_workers=3) as workers:
        results = list(workers.map(launch, range(3)))
    assert sum(result.started for result in results) == 1
    assert len({result.pid for result in results}) == 1
    assert len(service.children) == len(service.opened) == 1


def test_worker_cleanup_waits_for_registry_lock_and_preserves_replacement(
    service: ServiceFixture,
) -> None:
    ensure_review_inbox(
        service.root, state_home=service.state_home, port=0, open_page=False
    )
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
    initial = ensure_review_inbox(
        service.root, state_home=service.state_home, port=0, open_page=False
    )
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
            ensure_review_inbox,
            service.root,
            state_home=service.state_home,
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
        started = ensure_review_inbox(
            service.root, state_home=service.state_home, port=port, open_page=False
        )
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
    started = ensure_review_inbox(
        service.root, state_home=service.state_home, port=0, open_page=False
    )
    assert started.started and started.pid != os.getpid()
    record = store.read()
    assert record is not None and service_health(record, service.root) is not None


@pytest.mark.parametrize("mismatch", ["token", "instance", "repository", "root", "pid"])
def test_reuse_refuses_wrong_authority_or_watch_scope(
    service: ServiceFixture, mismatch: str
) -> None:
    ensure_review_inbox(
        service.root, state_home=service.state_home, open_page=False, port=0
    )
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
    result = ensure_review_inbox(
        service.root, state_home=service.state_home, open_page=False, port=0
    )
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
                ensure_review_inbox(tmp_path, state_home=private)
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
        ensure_review_inbox(
            service.root,
            state_home=service.state_home,
            open_page=False,
            port=0,
            timeout_seconds=0.2,
        )
    assert len(service.children) == 1 and not service.children[0].is_alive()
    assert ReviewServiceStore.for_root(service.root, service.state_home).read() is None
