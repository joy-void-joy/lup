"""A checkout's companion is shared by its sessions and stopped after the last.

Real processes and real ports, because what is pinned is lifetime and
reachability: a companion started by one launcher outlives it while another
session still holds it, is stopped when the last lets go, is started once
however many launchers race for it, and is swept free of a launcher that died
holding it. Two checkouts are given distinct ports, each kept for its
checkout, and the command and the url are spelled with the port given; a
host service following that port is ``test_host_services``'s.

A stand-in launcher (``fixtures/companion_session.py``) is a process of its
own wherever a launcher has to end, die or race; a session in the test's own
process stands in everywhere else.
"""

import shlex
import socket
import sys
import time
import webbrowser
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
import sh

from lup.devtools.envfiles import HostSecrets, SecretsLocation
from lup.devtools.harness.companions import (
    Beside,
    CompanionSlot,
    companions_running,
    given_ports,
)
from lup.harness.companions import HostCompanion
from lup.harness.models import Harness, PromptDocument
from lup.sandbox.process import process_is_alive, process_is_zombie
from lup.types import EnvVars
from tests.unit.fixtures.companion_session import SessionSpec

HELPER = Path(__file__).parent / "fixtures" / "companion_session.py"
"""The stand-in launcher."""

PLAIN: EnvVars = {"PATH": "/bin:/usr/bin"}
"""An inherited environment carrying nothing but where programs are."""


def eventually(condition: Callable[[], bool], seconds: float = 10.0) -> bool:
    """Whether a condition becomes true within a few seconds, polling briefly."""
    deadline = time.monotonic() + seconds
    for _ in iter(lambda: time.monotonic() < deadline, False):
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def free_port() -> int:
    """A port nothing listens on now, for a companion to prefer."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def answers(port: int) -> bool:
    """Whether something accepts a connection on this loopback port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def serving(
    starts: Path, preferred: int, open_it: bool = False, name: str = "preview"
) -> HostCompanion:
    """An HTTP server on its given port, counting every start in ``starts``."""
    script = (
        f"echo started >> {shlex.quote(str(starts))}; "
        f'exec {shlex.quote(sys.executable)} -m http.server "$0" --bind 127.0.0.1'
    )
    return HostCompanion(
        name=name,
        command=["sh", "-c", script, "{ports.http}"],
        ports={"http": preferred},
        url="http://127.0.0.1:{ports.http}/",
        open=open_it,
    )


class Checkout:
    """One checkout on this machine: its root, and its companions' home in a shared cache."""

    def __init__(self, tmp_path: Path, name: str) -> None:
        self.root = tmp_path / name
        self.root.mkdir()
        self.home = tmp_path / "cache" / name
        self.store = HostSecrets.of(
            "adlib", SecretsLocation(xdg_config_home=tmp_path / "config")
        )
        self.config = tmp_path / "config"

    def session(
        self,
        declared: list[HostCompanion],
        browser: Callable[[str], bool] = lambda _url: True,
    ) -> AbstractContextManager[Beside]:
        """One session in this process, joined to the checkout's companions."""
        return companions_running(
            declared, self.root, self.home, self.store, PLAIN, browser=browser
        )


class Launcher:
    """A stand-in launcher running as a process of its own."""

    def __init__(self, checkout: Checkout, declared: list[HostCompanion], name: str):
        directory = checkout.root.parent / "launchers" / name
        directory.mkdir(parents=True)
        self.learned = directory / "learned.json"
        self.release = directory / "release"
        spec = directory / "spec.json"
        spec.write_text(
            SessionSpec(
                declared=declared,
                root=checkout.root,
                home=checkout.home,
                config=checkout.config,
                learned=self.learned,
                release=self.release,
            ).model_dump_json(),
            encoding="utf-8",
        )
        self.running = sh.Command(sys.executable)(
            str(HELPER),
            str(spec),
            _bg=True,
            _bg_exc=False,
            _return_cmd=True,
        )

    def joined(self) -> Beside:
        """What it learned joining, once it has."""
        assert eventually(self.learned.exists, 30.0)
        return Beside.model_validate_json(self.learned.read_text(encoding="utf-8"))

    def let_go(self) -> None:
        """End its session and wait for the launcher to exit."""
        self.release.touch()
        self.running.wait(timeout=30)

    def die(self) -> None:
        """Kill it where it stands, holding what it holds."""
        self.running.kill()
        try:
            self.running.wait(timeout=30)
        except sh.SignalException:
            return


def texts(beside: Beside) -> list[str]:
    """What a session's banner says of its companions."""
    return [notice.text for notice in beside.notices]


def serving_pid(checkout: Checkout, name: str = "preview") -> int:
    """The companion's process as its checkout keeps it."""
    state = CompanionSlot(directory=checkout.home / name).read(checkout.root)
    assert state.running is not None
    return state.running.process.pid


def running(pid: int) -> bool:
    """Whether a process with this id still exists and is not a zombie."""
    return process_is_alive(pid, None) and not process_is_zombie(pid)


def test_a_shared_companion_outlives_the_first_session_and_stops_after_the_last(
    tmp_path: Path,
) -> None:
    """The first launcher starts it and exits; the second session still reaches it."""
    checkout = Checkout(tmp_path, "adlib")
    starts = tmp_path / "starts"
    declared = [serving(starts, free_port())]
    first = Launcher(checkout, declared, "first")
    started = first.joined()
    [port] = started.ports.values()
    assert texts(started)[0].startswith(
        f"Companion preview: started, http://127.0.0.1:{port}/ (log: "
    )

    with checkout.session(declared) as second:
        assert texts(second)[0].startswith(
            f"Companion preview: reused (2 sessions), http://127.0.0.1:{port}/"
        )
        assert second.ports == started.ports
        pid = serving_pid(checkout)
        first.let_go()
        assert answers(port)
        assert running(pid)

    assert eventually(lambda: not running(pid))
    assert not answers(port)
    assert starts.read_text(encoding="utf-8").splitlines() == ["started"]


def test_two_checkouts_get_distinct_ports_each_kept_for_its_checkout(
    tmp_path: Path,
) -> None:
    preferred = free_port()
    first = Checkout(tmp_path, "adlib")
    second = Checkout(tmp_path, "adlib-feature")
    declared = [serving(tmp_path / "starts", preferred)]

    with first.session(declared) as one, second.session(declared) as other:
        assert one.ports == {"preview.http": preferred}
        [elsewhere] = other.ports.values()
        assert elsewhere != preferred
        assert answers(preferred) and answers(elsewhere)
        assert texts(other)[0].startswith("Companion preview: started")

    with second.session(declared) as again:
        assert again.ports == other.ports


def test_a_port_another_checkout_keeps_is_not_given_even_while_it_is_free() -> None:
    declared = HostCompanion(
        name="preview", command=["serve"], ports={"ui": 8777, "pieces": 8779}
    )

    given = given_ports(declared, [], [8777, 8779], free=lambda _port: True)

    assert [(port.name, port.port) for port in given] == [
        ("ui", 8778),
        ("pieces", 8780),
    ]


def test_the_placeholder_is_the_port_the_checkout_was_given() -> None:
    declared = HostCompanion(
        name="preview",
        command=["bun", "serve", "--port", "{ports.ui}", "--pieces={ports.pieces}"],
        ports={"ui": 8777, "pieces": 8779},
        url="http://127.0.0.1:{ports.ui}/?pieces=http://127.0.0.1:{ports.pieces}",
    )

    placed = declared.at({"ui": 8790, "pieces": 8791})

    assert placed.command == ["bun", "serve", "--port", "8790", "--pieces=8791"]
    assert placed.url == "http://127.0.0.1:8790/?pieces=http://127.0.0.1:8791"


def test_a_placeholder_naming_no_declared_port_is_refused() -> None:
    with pytest.raises(
        ValueError, match=r"\{ports\.pices\} but declares ports: pieces"
    ):
        HostCompanion(
            name="preview", command=["serve", "{ports.pices}"], ports={"pieces": 8779}
        )


def test_a_companion_opening_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="no url to open"):
        HostCompanion(name="preview", command=["serve"], open=True)


def test_two_companions_under_one_name_are_refused() -> None:
    with pytest.raises(ValueError, match="companion names must be unique"):
        Harness(
            generator_version="0",
            plugins=[],
            guidance=PromptDocument(parts=[]),
            companions=[
                HostCompanion(name="preview", command=["one"]),
                HostCompanion(name="preview", command=["two"]),
            ],
        )


def test_a_dead_launchers_lease_is_swept(tmp_path: Path) -> None:
    """Killed holding it, the launcher holds nothing: the last live session stops it."""
    checkout = Checkout(tmp_path, "adlib")
    declared = [serving(tmp_path / "starts", free_port())]
    dead = Launcher(checkout, declared, "dead")
    [port] = dead.joined().ports.values()
    pid = serving_pid(checkout)
    dead.die()

    with checkout.session(declared) as alive:
        assert texts(alive)[0].startswith("Companion preview: reused (1 session)")
        assert serving_pid(checkout) == pid

    assert eventually(lambda: not running(pid))
    assert not answers(port)
    assert (
        CompanionSlot(directory=checkout.home / "preview").read(checkout.root).leases
        == []
    )


def test_concurrent_launches_start_the_companion_once(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path, "adlib")
    starts = tmp_path / "starts"
    declared = [serving(starts, free_port())]

    launchers = [Launcher(checkout, declared, f"racing-{n}") for n in range(4)]
    learned = [launcher.joined() for launcher in launchers]
    pid = serving_pid(checkout)

    assert starts.read_text(encoding="utf-8").splitlines() == ["started"]
    said = sorted(texts(one)[0] for one in learned)
    leads = [
        "Companion preview: reused (2 sessions), ",
        "Companion preview: reused (3 sessions), ",
        "Companion preview: reused (4 sessions), ",
        "Companion preview: started, ",
    ]
    assert all(line.startswith(lead) for line, lead in zip(said, leads, strict=True))
    assert all(one.ports == learned[0].ports for one in learned)
    for launcher in launchers:
        launcher.let_go()
    assert eventually(lambda: not running(pid))


def test_open_fires_for_the_session_that_starts_it_and_no_other(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path, "adlib")
    declared = [serving(tmp_path / "starts", free_port(), open_it=True)]
    shown: list[str] = []

    def browser(url: str) -> bool:
        shown.append(url)
        return True

    with (
        checkout.session(declared, browser) as first,
        checkout.session(declared, browser),
    ):
        [port] = first.ports.values()

    assert shown == [f"http://127.0.0.1:{port}/"]


def test_a_browser_that_will_not_open_is_a_banner_line(tmp_path: Path) -> None:
    checkout = Checkout(tmp_path, "adlib")
    declared = [serving(tmp_path / "starts", free_port(), open_it=True)]

    def refusing(_url: str) -> bool:
        raise webbrowser.Error("could not locate runnable browser")

    with checkout.session(declared, refusing) as started:
        [port] = started.ports.values()
        said = texts(started)

    assert said[0].startswith("Companion preview: started")
    assert said[1] == (
        f"Companion preview: http://127.0.0.1:{port}/ did not open in a browser "
        "(could not locate runnable browser)"
    )


def test_a_changed_declaration_replaces_what_runs(tmp_path: Path) -> None:
    """The checkout's sessions share the one the approved declaration names."""
    checkout = Checkout(tmp_path, "adlib")
    preferred = free_port()
    before = serving(tmp_path / "starts", preferred)
    after = serving(tmp_path / "starts-after", preferred)

    with checkout.session([before]):
        replaced = serving_pid(checkout)
        with checkout.session([after]) as changed:
            assert texts(changed)[0].startswith("Companion preview: started")
            assert eventually(lambda: not running(replaced))
            assert serving_pid(checkout) != replaced
            current = serving_pid(checkout)
        assert running(current)

    assert eventually(lambda: not running(current))
