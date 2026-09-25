"""A service on the host's loopback reaches a contained session only by its name.

The fixture is the case the design exists for: an HTTP service bound to the
host's 127.0.0.1 alone, because it holds a key that must not enter the
container. A filtered session has no route to the host, so the declared name
has to be the one way in — a socket the launcher relays to the service, and
nothing for any service that was not declared.

What a unit test cannot prove is the container's own lack of a route, which
is the engine's; what it pins is every half this repository owns: the relay
carries the bytes, the argv mounts only the relay and stays on the internal
network, the entrypoint listens where the session is told to call, and the
overrides land where they are said to.
"""

import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import typer

from lup.devtools.harness.posture import LaunchOverrides, SessionSettings
from lup.harness.image import Docker, Image
from lup.harness.models import Harness, PromptDocument
from lup.harness.requirements import Manifest
from lup.harness.services import HostService, HostServices


class Greeting(BaseHTTPRequestHandler):
    """A service that answers one fixed body, so a relayed reply is recognisable."""

    def do_GET(self) -> None:
        body = b"listener says hello"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def loopback_service() -> Iterator[int]:
    """An HTTP service bound to the host's loopback only, on a free port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Greeting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def listener(port: int) -> HostService:
    """The declared service: its host port, the port inside, the variable named."""
    return HostService(
        name="listener",
        port=port,
        inside_port=18778,
        variable="STUDIO_LISTENER_URL",
        because="the studio calls a helper holding a key the container must not see",
    )


def asked_through(socket_path: Path) -> bytes:
    """One HTTP request made over the relay's socket, as the in-container listener would."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(b"GET / HTTP/1.0\r\nHost: listener\r\n\r\n")
        return b"".join(iter(lambda: client.recv(65536), b""))


def test_a_declared_service_is_reached_through_its_relay(loopback_service: int) -> None:
    """The bytes a session sends through the service's socket reach the host's loopback."""
    relayed = HostServices(services=[listener(loopback_service)]).serve()

    assert relayed is not None
    reply = asked_through(relayed / "listener.sock")

    assert reply.startswith(b"HTTP/1.0 200")
    assert reply.endswith(b"listener says hello")


def test_only_declared_services_get_a_way_in(loopback_service: int) -> None:
    """A service nobody declared has no socket, so the relay reaches nothing else."""
    relayed = HostServices(services=[listener(loopback_service)]).serve()

    assert relayed is not None
    assert sorted(path.name for path in relayed.iterdir()) == ["listener.sock"]


def test_a_project_declaring_no_service_relays_nothing() -> None:
    assert HostServices().serve() is None
    assert HostServices().environment(True) == {}


def test_the_session_is_told_where_to_call_under_its_own_name() -> None:
    """The project's own variable carries the address, and the entrypoint its listener."""
    services = HostServices(services=[listener(8778)])

    relayed = services.environment(True)

    assert relayed == {
        "STUDIO_LISTENER_URL": "http://127.0.0.1:18778",
        "LUP_HOST_SERVICES": "listener:18778",
    }


def test_the_host_network_shares_the_loopback_and_relays_nothing() -> None:
    """Under the host's own network the address is the service's own port."""
    services = HostServices(services=[listener(8778)])

    shared = services.environment(False)

    assert shared == {"STUDIO_LISTENER_URL": "http://127.0.0.1:8778"}


def test_the_filtered_argv_mounts_the_relay_and_keeps_the_internal_network(
    tmp_path: Path,
) -> None:
    """No route to the host is added: the relay's directory is the only crossing."""
    image = Image(services=HostServices(services=[listener(8778)]))

    argv = image.session_arguments(
        tag="lup-agent:test",
        checkout=tmp_path,
        uid=1000,
        gid=1000,
        writable={},
        read_only={},
        state_volume="lup-cfg-test",
        config_home_env="CLAUDE_CONFIG_DIR",
        engine=Docker(),
        services_directory=tmp_path / "relay",
    )

    assert f"{tmp_path / 'relay'}:/run/lup/services:rw" in argv
    assert "LUP_HOST_SERVICES=listener:18778" in argv
    assert "STUDIO_LISTENER_URL=http://127.0.0.1:18778" in argv
    network = argv[argv.index("--network") + 1]
    assert network == f"lup-egress-net-{tmp_path.name}"
    assert "--add-host" not in argv
    assert not any(
        "host-gateway" in word or "host.docker.internal" in word for word in argv
    )


def test_the_entrypoint_listens_where_the_session_is_told_to_call() -> None:
    """The listener is started from the variable the launch sets, not baked."""
    image = Image(services=HostServices(services=[listener(8778)]))

    entrypoint = image.dockerfile(Manifest())

    assert "for entry in ${LUP_HOST_SERVICES:-}; do" in entrypoint
    assert 'TCP-LISTEN:"$port",bind=127.0.0.1' in entrypoint
    assert 'UNIX-CONNECT:"/run/lup/services/$name.sock"' in entrypoint


def test_a_service_reached_below_1024_by_default_is_refused() -> None:
    """The session holds no capability to bind there, so it would never listen."""
    with pytest.raises(ValueError, match="inside_port"):
        HostService(name="web", port=80)


def harness_with(services: HostServices) -> Harness:
    """A minimal harness whose image declares these services."""
    return Harness(
        generator_version="0",
        plugins=[],
        guidance=PromptDocument(parts=[]),
        image=Image(services=services),
    )


def test_a_machine_moves_a_service_and_a_flag_moves_it_again() -> None:
    """Flag over machine over the declaration, each said as where it came from."""
    harness = harness_with(HostServices(services=[listener(8778)]))

    machine = SessionSettings.resolved(harness, {"services": {"listener": 9000}})
    flagged = SessionSettings.resolved(
        harness,
        {"services": {"listener": 9000}},
        LaunchOverrides(services={"listener": 9100}),
    )

    assert machine.image(harness.image).services.services[0].port == 9000
    assert machine.origins().services == "machine"
    assert flagged.image(harness.image).services.services[0].port == 9100
    assert flagged.origins().services == "flag"


def test_an_override_naming_no_declared_service_stops_the_launch() -> None:
    harness = harness_with(HostServices(services=[listener(8778)]))

    with pytest.raises(typer.BadParameter, match="no host service is declared as"):
        SessionSettings.resolved(
            harness, None, LaunchOverrides(services={"elsewhere": 9000})
        )
