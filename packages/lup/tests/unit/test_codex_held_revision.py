"""A contained Codex session runs the hooks it was launched with, whatever it writes.

Codex runs a plugin's hooks from the revision installed in its home, and the
home is the session's to write. So the launch writes the same revision again
on the host, outside the checkout, and mounts it read-only over the path it
has in the home. These pin each half: the snapshot is the installed revision
byte for byte where it matters, preparation reports which revision it
installed as data, the argv carries the mount, and — with real mounts — the
hook scripts and runtime cannot be written from inside while the rest of the
home can.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import sh
from typer.testing import CliRunner

import lup.devtools.harness.launch as launch
import lup.providers.codex.install as installation
from lup.devtools.harness.launch import held_revision, with_read_only
from lup.providers.codex.harness_runtime import plugin_content_digest, revision_snapshot
from lup.providers.codex.install import PreparedPlugin
from lup.sandbox.rail import Lease
from tests.unit.test_container_holds import inside, mounted


def plugin_source(root: Path) -> Path:
    """A plugin laid out as the generated one is: manifest, hook scripts, runtime."""
    source = root / ".codex" / "plugins" / "sample"
    files = {
        ".codex-plugin/plugin.json": json.dumps({"name": "sample", "version": "0.2.0"}),
        "hooks/hooks.json": "{}\n",
        "hooks/scripts/policy.py": "print('judged')\n",
        "hooks/runtime/policy_data.py": "RULES = []\n",
        "hooks/runtime/kernel/decision.py": "ALLOW = 'allow'\n",
    }
    for path, content in files.items():
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        (source / path).write_text(content, encoding="utf-8")
    return source


def test_the_snapshot_is_the_revision_the_home_installs(tmp_path: Path) -> None:
    """The source with its manifest naming the revision, and nothing else changed."""
    source = plugin_source(tmp_path / "checkout")
    revision = "0.2.0+codex.abc123"

    snapshot = revision_snapshot(source, revision, tmp_path / "snapshots")
    again = revision_snapshot(source, revision, tmp_path / "snapshots")

    assert snapshot == again
    assert plugin_content_digest(snapshot) is not None
    manifest = json.loads(
        (snapshot / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == revision
    assert (snapshot / "hooks" / "runtime" / "policy_data.py").read_text(
        encoding="utf-8"
    ) == "RULES = []\n"
    assert (tmp_path / "checkout") not in snapshot.parents


def test_a_prepared_revision_is_held_over_its_path_in_the_home(tmp_path: Path) -> None:
    source = plugin_source(tmp_path / "checkout")
    installed = Path("/home/agent/.codex/plugins/cache/lup/sample/0.2.0+codex.abc")

    held = held_revision(
        PreparedPlugin(installed_root=installed), source, tmp_path / "snapshots"
    )

    [(snapshot, target)] = held.items()
    assert target == installed.as_posix()
    assert (
        json.loads(
            (snapshot / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )["version"]
        == installed.name
    )
    assert held_revision(PreparedPlugin(), source, tmp_path / "snapshots") == {}


def test_the_mount_joins_the_container_options(tmp_path: Path) -> None:
    opening = ["podman", "run", "--rm", "-v", "/a:/a:rw", "image:tag"]

    held = with_read_only(opening, {tmp_path / "snap": "/home/agent/.codex/rev"})

    assert held == [
        "podman",
        "run",
        "-v",
        f"{tmp_path / 'snap'}:/home/agent/.codex/rev:ro",
        "--rm",
        "-v",
        "/a:/a:rw",
        "image:tag",
    ]
    assert with_read_only(opening, {}) == opening


def test_preparation_reports_its_revision_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--report`` puts the JSON on stdout and nothing else there."""
    installed = tmp_path / "home" / "plugins" / "cache" / "lup" / "sample" / "0.2.0"
    monkeypatch.setattr(
        installation,
        "install_codex_plugin",
        lambda *args: PreparedPlugin(installed_root=installed),
    )

    result = CliRunner().invoke(
        installation.app,
        ["--root", str(tmp_path), "--home", str(tmp_path / "home"), "--report"],
    )

    assert result.exit_code == 0, result.output
    assert PreparedPlugin.model_validate_json(result.stdout).installed_root == installed


def test_a_contained_preparation_is_read_back_from_its_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = Path("/home/agent/.codex/plugins/cache/lup/sample/0.2.0")
    ran: list[list[object]] = []

    def engine(*args: object, **_kwargs: object) -> str:
        ran.append(list(args))
        return PreparedPlugin(installed_root=installed).model_dump_json()

    monkeypatch.setattr(sh, "Command", lambda _name: engine)

    prepared = launch.prepare_codex_plugin(
        ["podman", "run", "image"], Path("/home/agent/.codex"), tmp_path, {}
    )

    assert prepared.installed_root == installed
    assert "--report" in ran[0]


@mounted
def test_a_normal_codex_session_cannot_rewrite_the_hooks_judging_it(
    tmp_path: Path,
) -> None:
    """The installed revision is read-only; the rest of the home stays the session's."""
    source = plugin_source(tmp_path / "checkout")
    home = tmp_path / "codex-home"
    installed = home / "plugins" / "cache" / "lup" / "sample" / "0.2.0+codex.abc"
    installed.mkdir(parents=True)
    held = held_revision(
        PreparedPlugin(installed_root=installed), source, tmp_path / "snapshots"
    )
    lease = Lease(writable={home: home.as_posix()}, read_only=held)

    for judged in [
        installed / "hooks" / "scripts" / "policy.py",
        installed / "hooks" / "runtime" / "policy_data.py",
        installed / "hooks" / "runtime" / "kernel" / "decision.py",
    ]:
        assert not inside(lease, f"echo x >> {judged}")
    assert not inside(lease, f"echo x > {installed}/hooks/runtime/planted.py")
    assert inside(lease, f"cat {installed}/hooks/scripts/policy.py > /dev/null")
    assert inside(lease, f"echo 'model = \"x\"' > {home}/config.toml")
    assert inside(lease, f"mkdir -p {home}/sessions && echo s > {home}/sessions/one")


def test_a_host_launch_holds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the host there is no container to mount into; the home is the operator's."""
    monkeypatch.setattr(
        launch, "install_codex_plugin", Mock(return_value=PreparedPlugin())
    )

    prepared = launch.prepare_codex_plugin([], tmp_path / "home", tmp_path, {})

    assert prepared == PreparedPlugin()
