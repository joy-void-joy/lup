"""Operator-owned review inbox services, reusable across repository worktrees."""

import asyncio
import errno
import fcntl
import hmac
import logging
import os
import secrets
import socket
import sys
import time
import webbrowser
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from hashlib import sha256
from itertools import count
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import uuid4

import httpx
import sh
import typer
from pydantic import BaseModel, Field, SecretStr, TypeAdapter, field_serializer

from lup.coordination.identity import MEMBER_ENV
from lup.devtools.harness.preflight import NONCE_VARIABLE
from lup.harness.review_environment import ReviewInboxEnvironment
from lup.policy.identity import AGENT_IDENTITY_ENV
from lup.sandbox.rail import repository_layout, sibling_worktrees
from lup.workspace.context import SESSION_DIR_ENV, SESSION_ID_ENV


type ReviewHost = Literal["127.0.0.1", "localhost", "::1"]


class ReviewOperatorEnvironment(ReviewInboxEnvironment):
    """Inherited session markers and the credential-free endpoint relay."""

    boundary: str = Field(default="", validation_alias=NONCE_VARIABLE)
    member: str = Field(default="", validation_alias=MEMBER_ENV)
    agent: str = Field(default="", validation_alias=AGENT_IDENTITY_ENV)
    session_dir: str = Field(default="", validation_alias=SESSION_DIR_ENV)
    session_id: str = Field(default="", validation_alias=SESSION_ID_ENV)

    @property
    def agent_session(self) -> bool:
        return any(
            (self.boundary, self.member, self.agent, self.session_dir, self.session_id)
        )


def require_review_operator() -> None:
    """Refuse inherited agent authority before opening any private service state."""
    if ReviewOperatorEnvironment().agent_session:
        raise ValueError(
            "The review inbox service requires an independent operator terminal "
            "outside the agent session."
        )


class ReviewInboxService(BaseModel, frozen=True):
    """A ready service; its browser capability has a redacted representation."""

    endpoint: str
    instance: str
    launch_url: SecretStr
    pid: int
    started: bool
    browser_opened: bool = False


class ReviewServiceHealth(BaseModel, frozen=True, extra="forbid"):
    """Authenticated identity and the checkouts this service actually watches."""

    service: Literal["lup.review-inbox"] = "lup.review-inbox"
    protocol: Literal[1] = 1
    session_owned: bool = False
    instance: str
    repository: Path
    roots: list[Path]
    pid: int


class ReviewServiceStatus(BaseModel, frozen=True):
    """Operator-readable status carrying no browser credential."""

    running: bool | None
    verified: bool = True
    endpoint: str = ""
    pid: int | None = None
    sessions: int | None = None
    detail: str


class ReviewServiceRecord(BaseModel, frozen=True, extra="forbid"):
    """Private startup and readiness state; never returned by an HTTP endpoint."""

    repository: Path
    instance: str
    token: SecretStr
    host: ReviewHost = "127.0.0.1"
    port: int = Field(default=8766, ge=0, le=65535)
    endpoint: str = ""
    pid: int = 0
    stopping: bool = False
    session_owned: bool = False

    @classmethod
    def from_path(cls, path: Path) -> "ReviewServiceRecord | None":
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if (
            path.is_symlink()
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError(
                "Review inbox credential records require operator-only access."
            )
        try:
            return cls.model_validate_json(path.read_bytes())
        except ValueError:
            return None

    @field_serializer("token", when_used="json")
    def private_token(self, token: SecretStr) -> str:
        """The private credential file must retain the capability for the operator."""
        return token.get_secret_value()

    def ready(self, *, started: bool) -> ReviewInboxService:
        return ReviewInboxService(
            endpoint=self.endpoint,
            instance=self.instance,
            launch_url=SecretStr(
                f"{self.endpoint}/#token={self.token.get_secret_value()}"
            ),
            pid=self.pid,
            started=started,
        )


class ReviewServiceStore(BaseModel, frozen=True):
    """One host-private directory, keyed by the repository's common Git directory."""

    repository: Path
    directory: Path

    @classmethod
    def for_root(
        cls, root: Path, state_home: Path | None = None
    ) -> "ReviewServiceStore":
        require_review_operator()
        repository = repository_layout(root).common.resolve(strict=True)
        home = state_home or Path.home() / ".local" / "state" / "lup" / "review-inbox"
        if any(
            home.resolve().is_relative_to(checkout.resolve())
            for checkout in (repository, root, *sibling_worktrees(repository))
        ):
            raise ValueError(
                "Review inbox credentials must stay outside Git checkouts."
            )
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        cls.private_directory(home)
        identity = sha256(str(repository).encode()).hexdigest()
        directory = home / identity
        directory.mkdir(mode=0o700, exist_ok=True)
        cls.private_directory(directory)
        return cls(repository=repository, directory=directory)

    @staticmethod
    def private_directory(path: Path) -> None:
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise ValueError("Review inbox state must be owned by the operator.")
        path.chmod(0o700)

    @property
    def record_path(self) -> Path:
        return self.directory / "service.json"

    @property
    def log_path(self) -> Path:
        return self.directory / "service.log"

    @contextmanager
    def lock(self) -> Iterator[None]:
        descriptor = os.open(
            self.directory / "service.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(descriptor, "a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self) -> ReviewServiceRecord | None:
        record = ReviewServiceRecord.from_path(self.record_path)
        return (
            record
            if record is not None and record.repository == self.repository
            else None
        )

    def write(self, record: ReviewServiceRecord, *, readiness: bool = False) -> None:
        target = self.readiness_path(record.instance) if readiness else self.record_path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.private_directory(target.parent)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(record.model_dump_json(exclude_defaults=True))
                handle.flush()
                os.fsync(handle.fileno())
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)

    def bundle_root(self, instance: str) -> Path:
        identity = sha256(instance.encode()).hexdigest()
        return self.directory / "bundles" / identity

    def lease_root(self, instance: str) -> Path:
        identity = sha256(instance.encode()).hexdigest()
        return self.directory / "leases" / identity

    def readiness_path(self, instance: str) -> Path:
        identity = sha256(instance.encode()).hexdigest()
        return self.directory / "readiness" / f"{identity}.json"

    def forget(self, instance: str) -> None:
        recorded = self.read()
        if recorded is not None and recorded.instance == instance:
            self.record_path.unlink(missing_ok=True)


def service_health(
    record: ReviewServiceRecord, root: Path, *, timeout_seconds: float = 1
) -> ReviewServiceHealth | None:
    """Verify the token, instance, repository and exact requested checkout."""
    if not record.endpoint:
        return None
    try:
        endpoint = httpx.URL(record.endpoint)
    except httpx.InvalidURL:
        return None
    if (
        endpoint.scheme != "http"
        or endpoint.host != record.host
        or endpoint.userinfo
        or endpoint.path != "/"
        or endpoint.query
        or endpoint.fragment
    ):
        return None
    try:
        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.get(
                f"{record.endpoint}/api/service",
                headers={"Authorization": f"Bearer {record.token.get_secret_value()}"},
            )
        if response.status_code != 200:
            return None
        health = ReviewServiceHealth.model_validate_json(response.content)
    except (httpx.HTTPError, ValueError):
        return None
    if (
        health.repository != record.repository
        or not hmac.compare_digest(health.instance.encode(), record.instance.encode())
        or health.pid != record.pid
        or root.resolve() not in health.roots
    ):
        return None
    return health


def open_service_browser(service: ReviewInboxService) -> ReviewInboxService:
    """Open the private link for the operator without putting it in a transcript."""
    try:
        opened = webbrowser.open(service.launch_url.get_secret_value())
    except OSError:
        opened = False
    return service.model_copy(update={"browser_opened": bool(opened)})


def snapshot_review_bundle(store: ReviewServiceStore, instance: str) -> None:
    """Retain this service's index and assets after its source checkout disappears."""
    from lup.web.serve import bundle_root

    source = bundle_root("reviews")
    target = store.bundle_root(instance) / "reviews"
    assets = target / "assets"
    assets.mkdir(mode=0o700, parents=True, exist_ok=True)
    (target / "index.html").write_bytes(source.joinpath("index.html").read_bytes())
    for asset in source.joinpath("assets").iterdir():
        if asset.is_file():
            (assets / asset.name).write_bytes(asset.read_bytes())


def launch_review_worker(store: ReviewServiceStore) -> sh.RunningCommand:
    """Detach a worker with credentials only in its private record, never argv."""
    record = store.read()
    if record is None:
        raise ValueError("No review inbox startup record is available.")
    descriptor = os.open(
        store.log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "ab") as output:
        return sh.Command(sys.executable)(
            "-m",
            "lup.devtools.dev.review_service",
            str(store.record_path),
            record.instance,
            _cwd=str(store.repository),
            _bg=True,
            _bg_exc=False,
            _new_session=True,
            _out=output,
            _err_to_out=True,
        )


@contextmanager
def hold_review_lease(store: ReviewServiceStore, instance: str) -> Iterator[None]:
    """Keep one launch alive through a kernel lock released even on process death."""
    directory = store.lease_root(instance)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{uuid4().hex}.lock"
    descriptor = os.open(
        path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def live_review_leases(store: ReviewServiceStore, instance: str) -> int:
    """Count held launch locks and remove abandoned files while registry is locked."""
    directory = store.lease_root(instance)
    if not directory.exists():
        return 0
    active = 0
    for path in directory.iterdir():
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            continue
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                active += 1
            else:
                path.unlink(missing_ok=True)
        finally:
            os.close(descriptor)
    return active


def request_review_shutdown(
    store: ReviewServiceStore, record: ReviewServiceRecord
) -> None:
    """Request authenticated shutdown for the instance held under the registry lock."""
    current = store.read()
    if current is None or current.instance != record.instance:
        return
    with httpx.Client(timeout=2, trust_env=False) as client:
        response = client.post(
            f"{record.endpoint}/api/service/stop",
            headers={
                "Authorization": f"Bearer {record.token.get_secret_value()}",
                "Origin": record.endpoint,
            },
            json={},
        )
        response.raise_for_status()
    store.write(record.model_copy(update={"stopping": True}))


def wait_review_shutdown(
    store: ReviewServiceStore, instance: str, *, timeout_seconds: float = 10
) -> None:
    """Wait outside the registry lock so the retiring worker can release its record."""
    deadline = time.monotonic() + timeout_seconds
    for _ in count():
        current = store.read()
        if current is None or current.instance != instance:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Review inbox accepted shutdown but has not stopped.")
        time.sleep(0.1)


def wait_review_release(store: ReviewServiceStore, instance: str) -> None:
    """Wait for the last session's worker without stopping a concurrent new owner."""
    deadline = time.monotonic() + 10
    for _ in count():
        with store.lock():
            record = store.read()
            if record is None or record.instance != instance:
                return
            if live_review_leases(store, instance):
                return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Review inbox did not stop after its last session; inspect {store.log_path}."
            )
        time.sleep(0.1)


@contextmanager
def review_inbox_session(
    root: Path,
    *,
    open_page: bool = True,
    state_home: Path | None = None,
    port: int = 8766,
    host: str = "127.0.0.1",
    timeout_seconds: float = 30,
) -> Iterator[ReviewInboxService]:
    """Own one shared host inbox for exactly one native harness invocation."""
    store = ReviewServiceStore.for_root(root, state_home)
    with ExitStack() as leases:
        service = ensure_review_inbox(
            root,
            leases=leases,
            open_page=open_page,
            state_home=state_home,
            port=port,
            host=host,
            timeout_seconds=timeout_seconds,
        )
        try:
            yield service
        finally:
            leases.close()
            wait_review_release(store, service.instance)


def ensure_review_inbox(
    root: Path,
    *,
    leases: ExitStack,
    open_page: bool = True,
    state_home: Path | None = None,
    port: int = 8766,
    host: str = "127.0.0.1",
    timeout_seconds: float = 30,
) -> ReviewInboxService:
    """Reuse an authenticated service or start one, opening only its first tab."""
    require_review_operator()
    if timeout_seconds <= 0:
        raise ValueError("Review inbox startup timeout must be positive.")
    root = root.resolve(strict=True)
    store = ReviewServiceStore.for_root(root, state_home)
    for _ in count():
        with store.lock():
            record = store.read()
            health = service_health(record, root) if record is not None else None
            if record is not None and health is not None and not health.session_owned:
                if not record.stopping:
                    request_review_shutdown(store, record)
                retiring = record.instance
            else:
                if record is not None and health is not None and not record.stopping:
                    leases.enter_context(hold_review_lease(store, record.instance))
                    return record.ready(started=False)
                proposed = ReviewServiceRecord(
                    repository=store.repository,
                    instance=secrets.token_hex(16),
                    token=SecretStr(secrets.token_urlsafe(32)),
                    port=port,
                    host=TypeAdapter(ReviewHost).validate_python(host),
                    session_owned=True,
                )
                snapshot_review_bundle(store, proposed.instance)
                leases.enter_context(hold_review_lease(store, proposed.instance))
                store.write(proposed)
                try:
                    worker = launch_review_worker(store)
                except (Exception, KeyboardInterrupt):
                    store.forget(proposed.instance)
                    raise
                deadline = time.monotonic() + timeout_seconds
                try:
                    for _ in count():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not worker.is_alive():
                            raise RuntimeError(
                                f"Review inbox did not become ready; inspect {store.log_path}."
                            )
                        record = ReviewServiceRecord.from_path(
                            store.readiness_path(proposed.instance)
                        )
                        if (
                            record is not None
                            and record.instance == proposed.instance
                            and record.repository == proposed.repository
                            and record.token == proposed.token
                            and service_health(
                                record, root, timeout_seconds=min(1, remaining)
                            )
                            is not None
                        ):
                            store.write(record)
                            service = record.ready(started=True)
                            return (
                                open_service_browser(service) if open_page else service
                            )
                        time.sleep(min(0.1, remaining))
                except (Exception, KeyboardInterrupt):
                    if worker.is_alive():
                        worker.terminate()
                    try:
                        worker.wait(timeout=5)
                    except sh.TimeoutException:
                        worker.kill()
                        try:
                            worker.wait(timeout=5)
                        except sh.ErrorReturnCode:
                            pass
                    except sh.ErrorReturnCode:
                        pass
                    finally:
                        store.forget(proposed.instance)
                    raise
                raise RuntimeError(
                    "Review inbox startup ended without a ready service."
                )
        wait_review_shutdown(store, retiring)
    raise RuntimeError("Review inbox startup ended without a ready service.")


def review_inbox_status(
    root: Path, *, state_home: Path | None = None
) -> ReviewServiceStatus:
    """Report an inherited advertisement or inspect authenticated operator state."""
    environment = ReviewOperatorEnvironment()
    if environment.agent_session:
        detail = (
            "Endpoint advertised to this session; operator health was not checked."
            if environment.endpoint
            else "No inbox endpoint was advertised to this session; use an operator terminal to open it."
        )
        return ReviewServiceStatus(
            running=None, verified=False, endpoint=environment.endpoint, detail=detail
        )
    store = ReviewServiceStore.for_root(root, state_home)
    with store.lock():
        record = store.read()
        if record is not None and service_health(record, root) is not None:
            return ReviewServiceStatus(
                running=True,
                endpoint=record.endpoint,
                pid=record.pid,
                sessions=live_review_leases(store, record.instance)
                if record.session_owned
                else None,
                detail=(
                    "Shared harness inbox; it stops after the last session exits. "
                    "Stop now with dev questions stop."
                    if record.session_owned
                    else "Independently started inbox; stop it with dev questions stop."
                ),
            )
    return ReviewServiceStatus(
        running=False,
        detail="No verified background inbox is ready; start a harness or run questions serve in the foreground.",
    )


def open_review_inbox(
    root: Path, *, state_home: Path | None = None
) -> ReviewInboxService:
    """Open an existing operator inbox without creating an ownerless background service."""
    store = ReviewServiceStore.for_root(root, state_home)
    with store.lock():
        record = store.read()
        if record is None or record.stopping or service_health(record, root) is None:
            raise ValueError(
                "No background review inbox is running. Start a harness, or run "
                "uv run lup-devtools dev questions serve in the foreground."
            )
        service = record.ready(started=False)
    return open_service_browser(service)


def stop_review_inbox(
    root: Path, *, state_home: Path | None = None, timeout_seconds: float = 10
) -> ReviewServiceStatus:
    """Stop only a service that authenticates its recorded identity."""
    store = ReviewServiceStore.for_root(root, state_home)
    with store.lock():
        record = store.read()
        if record is None or service_health(record, root) is None:
            return ReviewServiceStatus(
                running=False,
                detail="No verified service was found; no process was stopped.",
            )
        request_review_shutdown(store, record)
    wait_review_shutdown(store, record.instance, timeout_seconds=timeout_seconds)
    return ReviewServiceStatus(running=False, detail="Background review inbox stopped.")


def run_review_worker(record_path: Path, expected_instance: str = "") -> None:
    """Serve one private startup record; the launcher verifies actual HTTP readiness."""
    require_review_operator()
    import uvicorn
    from fastapi import BackgroundTasks, FastAPI

    from lup.devtools.dev.questions import ReviewStore, review_app

    directory = record_path.parent.resolve(strict=True)
    ReviewServiceStore.private_directory(directory)
    provisional = ReviewServiceRecord.from_path(record_path)
    if provisional is None:
        raise ValueError("No valid private review inbox startup record is available.")
    store = ReviewServiceStore(repository=provisional.repository, directory=directory)
    record = store.read()
    if (
        record is None
        or record_path != store.record_path
        or not record.session_owned
        or record.instance != expected_instance
    ):
        raise ValueError("No valid private review inbox startup record is available.")
    family = socket.AF_INET6 if record.host == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((record.host, record.port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            listener.bind((record.host, 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        authority = f"[{record.host}]" if record.host == "::1" else record.host
        endpoint = f"http://{authority}" if port == 80 else f"http://{authority}:{port}"
        ready = record.model_copy(update={"endpoint": endpoint, "pid": os.getpid()})
        app = review_app(
            endpoint,
            record.token.get_secret_value(),
            (record.repository,),
            discover=True,
            bundles=store.bundle_root(record.instance),
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=record.host,
                access_log=False,
                timeout_graceful_shutdown=2,
            )
        )
        reviews = ReviewStore(roots=(record.repository,), discover=True)

        @app.get("/api/service")
        def health() -> ReviewServiceHealth:
            return ReviewServiceHealth(
                instance=ready.instance,
                repository=ready.repository,
                roots=list(reviews.checkout_roots()),
                pid=ready.pid,
                session_owned=True,
            )

        @app.post("/api/service/stop")
        def stop(background_tasks: BackgroundTasks) -> ReviewServiceStatus:
            def shutdown() -> None:
                server.should_exit = True

            background_tasks.add_task(shutdown)
            return ReviewServiceStatus(running=True, detail="Shutdown requested.")

        def idle() -> bool:
            with store.lock():
                current = store.read()
                if current is None or current.instance != ready.instance:
                    return True
                if live_review_leases(store, ready.instance):
                    return False
                store.write(current.model_copy(update={"stopping": True}))
                return True

        async def watch_leases() -> None:
            try:
                for _ in count():
                    if await asyncio.to_thread(idle):
                        server.should_exit = True
                        return
                    await asyncio.sleep(0.1)
            except Exception:
                logging.getLogger("uvicorn.error").exception(
                    "Review inbox lease monitor failed"
                )
                server.should_exit = True

        previous_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application: FastAPI) -> AsyncIterator[None]:
            async with previous_lifespan(application):
                watcher = asyncio.create_task(watch_leases())
                try:
                    yield
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)

        app.router.lifespan_context = lifespan
        store.write(ready, readiness=True)
        try:
            server.run(sockets=[listener])
        finally:
            with store.lock():
                store.forget(ready.instance)
            store.readiness_path(ready.instance).unlink(missing_ok=True)


def register_review_service_commands(app: typer.Typer, root: Path) -> None:
    """Add operator lifecycle commands only when the inbox module is selected."""

    @app.command("status")
    def status_cmd() -> None:
        """Show authenticated review inbox readiness without exposing its credential."""
        typer.echo(review_inbox_status(root).model_dump_json(indent=2))

    @app.command("open")
    def open_cmd() -> None:
        """Open the background inbox owned by active harness sessions."""
        service = open_review_inbox(root)
        typer.echo(f"Background review inbox: {service.endpoint}")
        if not service.browser_opened:
            typer.echo(
                "The browser did not open. Operator launch URL: "
                + service.launch_url.get_secret_value()
            )

    @app.command("stop")
    def stop_cmd() -> None:
        """Stop the authenticated review inbox for this repository."""
        typer.echo(stop_review_inbox(root).model_dump_json(indent=2))


if __name__ == "__main__":
    run_review_worker(Path(sys.argv[1]), sys.argv[2])
