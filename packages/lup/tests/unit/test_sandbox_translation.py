"""Translating a path across the sandbox boundary, in both directions.

These build a topology directly or from a Sandbox that never starts Docker,
so they run in the unit suite. What is under test is the partiality: most
paths on either side have no counterpart, and saying so precisely is the
whole point of the surface.
"""

from pathlib import Path

from lup.sandbox.container import Sandbox
from lup.sandbox.models import Mount
from lup.sandbox.translation import MountTopology


def topology_of(sandbox: Sandbox) -> MountTopology:
    return MountTopology(mounts=sandbox.mount_topology())


def make_sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(session_id="translate-test", shared_dir=tmp_path / "shared")


class TestContainerToHost:
    """What the host calls a path the container named."""

    def test_a_shared_path_resolves_to_the_bound_host_directory(
        self, tmp_path: Path
    ) -> None:
        crossing = topology_of(make_sandbox(tmp_path)).to_host("/shared/out.csv")

        assert crossing.resolved == str((tmp_path / "shared").resolve() / "out.csv")
        assert crossing.writable

    def test_the_bare_mount_point_resolves_to_the_host_directory(
        self, tmp_path: Path
    ) -> None:
        crossing = topology_of(make_sandbox(tmp_path)).to_host("/shared")

        assert crossing.resolved == str((tmp_path / "shared").resolve())

    def test_a_workspace_path_has_no_host_name(self, tmp_path: Path) -> None:
        """The case that must not be papered over: a Docker volume is bytes
        the host cannot reach by any path, so inventing one would send a
        reader to a directory that does not exist."""
        crossing = topology_of(make_sandbox(tmp_path)).to_host("/workspace/scratch.db")

        assert crossing.resolved is None
        assert not crossing.writable

    def test_an_unreachable_path_is_told_where_it_could_have_written(
        self, tmp_path: Path
    ) -> None:
        crossing = topology_of(make_sandbox(tmp_path)).to_host("/workspace/scratch.db")

        assert "/shared" in crossing.explanation

    def test_a_sibling_of_a_mount_point_does_not_match_it(self, tmp_path: Path) -> None:
        """``/sharedx`` starts with ``/shared`` as characters and shares no
        directory with it, so matching on the string would resolve a path
        that is nowhere near the mount."""
        crossing = topology_of(make_sandbox(tmp_path)).to_host("/sharedx/out.csv")

        assert crossing.resolved is None

    def test_the_most_specific_mount_wins(self, tmp_path: Path) -> None:
        """A source root nested under another mount would otherwise resolve
        through the shallower one, into a host directory not holding the file."""
        sandbox = Sandbox(
            session_id="nested",
            shared_dir=tmp_path / "shared",
            rw_mounts={tmp_path / "outer": "/data", tmp_path / "inner": "/data/inner"},
        )
        crossing = topology_of(sandbox).to_host("/data/inner/file.txt")

        assert crossing.resolved == str((tmp_path / "inner").resolve() / "file.txt")

    def test_a_read_only_root_reports_that_it_is_not_writable(
        self, tmp_path: Path
    ) -> None:
        """The crossing exists and the host filesystem would permit the write:
        the mount's mode is the only record that it was meant to be refused."""
        sandbox = Sandbox(
            session_id="ro",
            shared_dir=tmp_path / "shared",
            source_roots={"lup": tmp_path / "lup"},
        )
        crossing = topology_of(sandbox).to_host("/sources/lup/mod.py")

        assert crossing.resolved == str((tmp_path / "lup").resolve() / "mod.py")
        assert not crossing.writable


class TestHostToContainer:
    """What the container calls a path the host named."""

    def test_a_host_path_under_the_shared_dir_resolves(self, tmp_path: Path) -> None:
        shared = (tmp_path / "shared").resolve()
        crossing = topology_of(make_sandbox(tmp_path)).to_container(
            str(shared / "in.json")
        )

        assert crossing.resolved == "/shared/in.json"

    def test_an_unmounted_host_path_has_no_container_name(self, tmp_path: Path) -> None:
        crossing = topology_of(make_sandbox(tmp_path)).to_container(
            str(tmp_path / "elsewhere" / "secret.env")
        )

        assert crossing.resolved is None
        assert "not mounted" in crossing.explanation

    def test_a_source_root_resolves_read_only(self, tmp_path: Path) -> None:
        sandbox = Sandbox(
            session_id="ro",
            shared_dir=tmp_path / "shared",
            source_roots={"lup": tmp_path / "lup"},
        )
        crossing = topology_of(sandbox).to_container(
            str((tmp_path / "lup").resolve() / "mod.py")
        )

        assert crossing.resolved == "/sources/lup/mod.py"
        assert not crossing.writable

    def test_a_path_crosses_back_to_where_it_started(self, tmp_path: Path) -> None:
        topology = topology_of(make_sandbox(tmp_path))
        out = topology.to_host("/shared/nested/out.csv")

        assert out.resolved is not None
        assert topology.to_container(out.resolved).resolved == "/shared/nested/out.csv"


class TestExchanges:
    """Where an agent that asked for an impossible crossing should go."""

    def test_only_writable_binds_are_offered(self, tmp_path: Path) -> None:
        sandbox = Sandbox(
            session_id="mixed",
            shared_dir=tmp_path / "shared",
            source_roots={"lup": tmp_path / "lup"},
        )

        assert topology_of(sandbox).exchanges() == ["/shared"]

    def test_a_volume_is_never_offered_as_an_exchange(self, tmp_path: Path) -> None:
        """``/workspace`` is writable and persistent, and reaches the host
        nowhere — which is exactly the confusion this list exists to end."""
        assert "/workspace" not in topology_of(make_sandbox(tmp_path)).exchanges()


class TestIndependenceFromDocker:
    """The permission dispatcher runs as a standalone script."""

    def test_a_topology_round_trips_through_serialization(self) -> None:
        """A hook receives the table as data, not as a live Sandbox."""
        topology = MountTopology(
            mounts=[
                Mount(
                    container_path="/shared",
                    source="/host/shared",
                    kind="bind",
                    mode="rw",
                    purpose="exchange",
                )
            ]
        )
        revived = MountTopology.model_validate_json(topology.model_dump_json())

        assert revived.to_host("/shared/a.txt").resolved == "/host/shared/a.txt"
