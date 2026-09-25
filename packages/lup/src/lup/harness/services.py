"""Services on the host's loopback a contained session reaches, and only by name.

A filtered session has no route to the host at all — the internal network it
sits on has no gateway, and the proxy refuses the host's own addresses — which
is the point of it. Some work still needs one particular thing running there:
a model server holding the GPU, a helper holding a key that must not enter the
container. Widening the network to reach it would reach everything else the
host serves on its loopback too, so each such service is instead declared by
name and carried across alone.

The carrying is a relay rather than a route. The launcher listens on one Unix
socket per declared service, in a directory it makes for the launch and
mounts into the container, and forwards each connection to the service's port
on the host's loopback. Inside, the entrypoint listens on the container's own
loopback at the port the service is reached at and forwards to its socket.
The session sees ``http://127.0.0.1:<port>``, which its proxy variables
already exempt, and nothing else on the host answers there: a service not
declared has no socket, and the container has no other way out to the host.

Under the ``host`` network the container shares the host's loopback already,
so nothing is relayed and the session is pointed at the service's own port.
"""

import atexit
import logging
import shutil
import socket
import socketserver
import tempfile
import threading
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from lup.harness.notice import Notice
from lup.types import EnvVars

logger = logging.getLogger(__name__)

# lup: ignore[dict-str-payload] — keyed by the names a project declares its
# services under, an open set checked against the declaration where it is read
type ServicePorts = dict[str, int]
"""The host port each named service listens on here, where it differs from declared."""


class HostService(BaseModel, frozen=True):
    """One service on the host's loopback that a contained session may reach.

    Declared with the port it listens on and, optionally, the variable the
    session finds its address under — so a project names the variable its own
    code reads, and the address is the launcher's to compute rather than a
    string written into the code that uses it.
    """

    name: str = Field(
        pattern=r"^[a-z][a-z0-9_-]*$",
        max_length=64,
        description="What the service is called; also its socket's name",
    )
    port: int = Field(
        ge=1,
        le=65535,
        description="The port it listens on, on the host's loopback",
    )
    inside_port: int | None = Field(
        default=None,
        ge=1024,
        le=65535,
        description=(
            "The port the session reaches it at on the container's loopback; "
            "unset is the host's port. At least 1024, because the session "
            "holds no capability to bind below it"
        ),
    )
    variable: str = Field(
        default="",
        pattern=r"^([A-Z_][A-Z0-9_]*)?$",
        description=(
            "The environment variable the session's address for it is "
            "exported under; empty exports none"
        ),
    )
    scheme: str = Field(
        default="http",
        pattern=r"^[a-z][a-z0-9+.-]*$",
        description="The scheme the exported address is spelled with",
    )
    because: str = Field(
        default="",
        description=(
            "What needs it. A service reachable from inside is a hole in the "
            "boundary, and the reason is what lets the next reader decide "
            "whether it still has to be one"
        ),
    )

    @model_validator(mode="after")
    def reachable_port_binds_unprivileged(self) -> "HostService":
        """Refuse a service reached below 1024 by default, which no session can bind."""
        if self.inside_port is None and self.port < 1024:
            raise ValueError(
                f"host service {self.name!r} listens on {self.port}, which a "
                "session cannot bind inside; declare an inside_port of 1024 "
                "or above"
            )
        return self

    def reached_at(self) -> int:
        """The port the session reaches this service at."""
        return self.inside_port or self.port

    def address(self, port: int) -> str:
        """The address the session is given, reaching a relay or the host itself."""
        return f"{self.scheme}://127.0.0.1:{port}"


class RelayHandler(socketserver.BaseRequestHandler):
    """Carry one connection from the session's socket to the service on the host."""

    def handle(self) -> None:
        """Pump both directions until either side closes."""
        relay = self.server
        if not isinstance(relay, RelayServer):
            return
        try:
            upstream = socket.create_connection(("127.0.0.1", relay.port))
        except OSError as error:
            logger.warning(
                "host service %s did not answer on port %s: %s",
                relay.name,
                relay.port,
                error,
            )
            return
        client = self.request

        def pumped(source: socket.socket, sink: socket.socket) -> None:
            """Copy one direction, then tell the far side nothing more is coming."""
            try:
                for chunk in iter(lambda: source.recv(65536), b""):
                    sink.sendall(chunk)
            except OSError:
                logger.debug("relay for %s closed mid-stream", relay.name)
            finally:
                try:
                    sink.shutdown(socket.SHUT_WR)
                except OSError:
                    logger.debug("relay for %s was already closed", relay.name)

        returning = threading.Thread(
            target=pumped, args=(upstream, client), daemon=True
        )
        returning.start()
        pumped(client, upstream)
        returning.join()
        upstream.close()


class RelayServer(socketserver.ThreadingUnixStreamServer):
    """One service's socket, threaded so a second connection does not queue."""

    daemon_threads = True
    name: str
    port: int


class HostServices(BaseModel, frozen=True):
    """The services on the host a contained session reaches, and how they are carried."""

    services: list[HostService] = Field(
        default=[],
        description="Each service a session may reach, by name; empty reaches none",
    )
    inside: str = Field(
        default="/run/lup/services",
        description=(
            "Where the directory holding the sockets is mounted in the "
            "container. A directory rather than the sockets themselves, for "
            "the reason the clipboard bridge mounts one"
        ),
    )
    variable: str = Field(
        default="LUP_HOST_SERVICES",
        description=(
            "What tells the entrypoint which listeners to start: each "
            "service's name and the port it is reached at, as `name:port`, "
            "separated by spaces"
        ),
    )

    @model_validator(mode="after")
    def names_are_unique(self) -> "HostServices":
        """Refuse two services under one name, which would share one socket."""
        names = [service.name for service in self.services]
        if len(names) != len(dict.fromkeys(names)):
            raise ValueError(f"host services must have distinct names: {names}")
        return self

    def serve(self) -> Path | None:
        """Listen on one socket per service, and answer with the directory to mount.

        Each service's port is where it listens on this host, a machine's or
        a launch's override already resolved onto it. Nothing comes back when
        there is nothing to relay, or when the directory cannot be made — a
        launch without the services rather than one that fails, which the
        notice says.
        """
        if not self.services:
            return None
        try:
            directory = Path(tempfile.mkdtemp(prefix="lup-services-"))
        except OSError as error:
            logger.warning("host services were not relayed: %s", error)
            return None
        atexit.register(shutil.rmtree, directory, True)
        for service in self.services:
            try:
                server = RelayServer(
                    str(directory / f"{service.name}.sock"), RelayHandler
                )
            except OSError as error:
                logger.warning(
                    "host service %s was not relayed: %s", service.name, error
                )
                continue
            server.name = service.name
            server.port = service.port
            (directory / f"{service.name}.sock").chmod(0o600)
            atexit.register(server.shutdown)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        return directory

    def environment(self, relayed: bool) -> EnvVars:
        """What the session is told: each declared address, and what to listen on.

        ``relayed`` is whether the sockets were mounted; unrelayed — under
        the host's own network — each address names the service's own port,
        and the entrypoint is told to start nothing.
        """
        addresses = {
            service.variable: service.address(
                service.reached_at() if relayed else service.port
            )
            for service in self.services
            if service.variable
        }
        listeners = " ".join(
            f"{service.name}:{service.reached_at()}" for service in self.services
        )
        return {
            **addresses,
            **({self.variable: listeners} if relayed and listeners else {}),
        }

    def entrypoint(self) -> str:
        """The lines the image's entrypoint runs to listen for each relayed service.

        Read from the environment at start rather than baked, so a project
        declaring a service does not rebuild its image, and a launch that
        relays nothing starts nothing. ``socat`` is the relay the baseline
        already carries for this kind of crossing.
        """
        return (
            f"for entry in ${{{self.variable}:-}}; do\n"
            "  name=${entry%%:*}\n"
            "  port=${entry#*:}\n"
            f'  socat TCP-LISTEN:"$port",bind=127.0.0.1,reuseaddr,fork '
            f'UNIX-CONNECT:"{self.inside}/$name.sock" &\n'
            "done\n"
        )

    def notice(self, relayed: bool, origin: str) -> list[Notice]:
        """Say which host services this session reaches, and how."""
        if not self.services:
            return []
        how = "relayed by name" if relayed else "on the shared host loopback"
        reached = ", ".join(
            f"{service.name} → host port {service.port}" for service in self.services
        )
        return [
            Notice(
                text=f"Host services ({origin}): {reached}, {how}",
                urgency="boundary",
            )
        ]

    def with_ports(self, ports: ServicePorts) -> "HostServices":
        """These services with the host ports a machine or a launch moved them to.

        A name no declared service carries is refused, because an override
        that reaches nothing is a service the operator believes is reachable
        and is not.
        """
        declared = {service.name for service in self.services}
        unknown = sorted(name for name in ports if name not in declared)
        if unknown:
            raise ValueError(
                f"no host service is declared as {', '.join(unknown)}; declared: "
                f"{', '.join(sorted(declared)) or 'none'}"
            )
        return self.model_copy(
            update={
                "services": [
                    service.model_copy(
                        update={"port": ports.get(service.name, service.port)}
                    )
                    for service in self.services
                ]
            }
        )
