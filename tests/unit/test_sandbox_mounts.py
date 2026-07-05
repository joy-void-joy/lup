"""Sandbox mount topology is the single source for volumes and tool docs.

These construct a Sandbox but never start Docker, so they run in the unit
suite: mount_topology() and the tool description are derived from names set
in __init__.
"""

from pathlib import Path

from lup.sandbox.container import Sandbox
from lup.sandbox.models import NetworkMode


def make_sandbox(tmp_path: Path, network_mode: NetworkMode = "bridge") -> Sandbox:
    return Sandbox(
        session_id="mounts-test",
        shared_dir=tmp_path / "shared",
        network_mode=network_mode,
    )


class TestMountTopology:
    """The topology names both container paths and where they come from."""

    def test_shared_binds_the_host_dir_read_write(self, tmp_path: Path) -> None:
        sandbox = make_sandbox(tmp_path)
        by_path = {m.container_path: m for m in sandbox.mount_topology()}

        shared = by_path["/shared"]
        assert shared.kind == "bind"
        assert shared.mode == "rw"
        assert shared.source == str((tmp_path / "shared").resolve())

    def test_workspace_is_a_persistent_volume(self, tmp_path: Path) -> None:
        sandbox = make_sandbox(tmp_path)
        by_path = {m.container_path: m for m in sandbox.mount_topology()}

        workspace = by_path["/workspace"]
        assert workspace.kind == "volume"
        assert workspace.source == sandbox.volume_name

    def test_topology_drives_the_docker_volume_mapping(self, tmp_path: Path) -> None:
        """The volumes dict start_container builds must round-trip the topology,
        so a bind that is silently dropped here surfaces as a test failure."""
        sandbox = make_sandbox(tmp_path)
        volumes = {
            m.source: {"bind": m.container_path, "mode": m.mode}
            for m in sandbox.mount_topology()
        }

        assert volumes[str((tmp_path / "shared").resolve())] == {
            "bind": "/shared",
            "mode": "rw",
        }
        assert volumes[sandbox.volume_name]["bind"] == "/workspace"


class TestExecuteCodeDescription:
    """The tool description must name the mounted paths so the in-sandbox
    agent never has to guess where host files live."""

    def test_description_names_both_mounts_and_host_dir(self, tmp_path: Path) -> None:
        sandbox = make_sandbox(tmp_path)
        execute_code = next(
            t for t in sandbox.create_tools() if t.name == "execute_code"
        )

        assert "/shared" in execute_code.description
        assert "/workspace" in execute_code.description
        assert str((tmp_path / "shared").resolve()) in execute_code.description

    def test_description_reflects_disabled_network(self, tmp_path: Path) -> None:
        sandbox = make_sandbox(tmp_path, network_mode="none")
        execute_code = next(
            t for t in sandbox.create_tools() if t.name == "execute_code"
        )

        assert "no network access" in execute_code.description
