"""Publish native installs without letting native cache pruning reach live homes."""

import json
import shutil
from pathlib import Path

import pytest
import sh
import tomlkit

from lup.providers.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
)


@pytest.mark.skipif(shutil.which("codex") is None, reason="native Codex CLI required")
def test_native_updates_preserve_live_revisions_and_unrelated_configuration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "plugin"
    manifest = source / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "lup", "version": "1.0.0"}))
    marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": "lup-isolated-test",
                "plugins": [
                    {
                        "name": "lup",
                        "source": {"source": "local", "path": "./plugin"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                    }
                ],
            }
        )
    )
    config = PluginCacheConfig(
        codex_home=tmp_path / "home", marketplace="lup-isolated-test"
    )
    config.codex_home.mkdir()
    settings = config.codex_home / "config.toml"
    settings.write_text(
        '# Keep this comment.\nmodel = "fixture"\n[plugins."other@elsewhere"]\nenabled = true\n'
    )
    installer = CodexPluginInstaller(config)

    first = installer.ensure(source, tmp_path)
    original = (first.installed_root / ".codex-plugin" / "plugin.json").read_bytes()
    (source / "second.txt").write_text("Another immutable revision.\n")
    second = installer.ensure(source, tmp_path)

    assert second.ready
    assert first.installed_root != second.installed_root
    assert (
        first.installed_root / ".codex-plugin" / "plugin.json"
    ).read_bytes() == original
    assert not (first.installed_root / "second.txt").exists()
    document = tomlkit.parse(settings.read_text())
    assert document["model"] == "fixture"
    assert document["plugins"]["other@elsewhere"]["enabled"] is True
    assert "# Keep this comment." in settings.read_text()
    listed = sh.Command("codex")(
        "plugin",
        "list",
        "--json",
        _cwd=str(tmp_path),
        _env=installer.plugin_environment(),
    )
    assert second.installed_root.name in str(listed)
    assert (
        first.installed_root / ".codex-plugin" / "plugin.json"
    ).read_bytes() == original
