"""Content-addressed lifecycle tests for installed Codex plugins."""

import json
from pathlib import Path

import pytest
import sh

from lup.providers.codex import harness_runtime
from lup.providers.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
    PluginCacheEvidence,
    cachebusted_plugin_version,
    plugin_cache_evidence,
    plugin_content_digest,
    stage_cachebusted_marketplace,
)


def plugin_source(root: Path, version: str = "0.2.0") -> Path:
    """Create one local marketplace and its plugin source."""
    source = root / ".codex" / "plugins" / "lup"
    manifest = source / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "lup", "version": version}) + "\n")
    (source / "hook.py").write_text("POLICY = 'safe'\n")
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": "lup-test",
                "plugins": [
                    {
                        "name": "lup",
                        "source": {
                            "source": "local",
                            "path": "./.codex/plugins/lup",
                        },
                    }
                ],
            }
        )
        + "\n"
    )
    return source


def test_content_revision_selects_an_immutable_cache_version(tmp_path: Path) -> None:
    source = plugin_source(tmp_path / "project")
    config = PluginCacheConfig(codex_home=tmp_path / "home", marketplace="lup-test")
    first = plugin_cache_evidence(source, config)
    revision = plugin_content_digest(source)

    assert revision is not None
    assert first.installed_root.name == cachebusted_plugin_version(source, revision)
    (source / "hook.py").write_text("POLICY = 'safer'\n")
    second = plugin_cache_evidence(source, config)

    assert second.installed_root != first.installed_root


def test_cachebuster_is_written_only_to_a_staged_marketplace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = plugin_source(project)
    config = PluginCacheConfig(codex_home=tmp_path / "home", marketplace="lup-test")
    revision = plugin_content_digest(source)
    assert revision is not None
    version = cachebusted_plugin_version(source, revision)
    staged = stage_cachebusted_marketplace(source, project, config, version)
    staged_source = staged / source.relative_to(project)
    original_manifest = json.loads(
        (source / ".codex-plugin" / "plugin.json").read_text()
    )
    staged_manifest = json.loads(
        (staged_source / ".codex-plugin" / "plugin.json").read_text()
    )

    assert original_manifest["version"] == "0.2.0"
    assert staged_manifest["version"] == version
    assert plugin_content_digest(staged_source) == revision
    assert (staged / ".agents" / "plugins" / "marketplace.json").is_file()


def test_ensure_never_removes_a_revision_an_active_session_may_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = plugin_source(tmp_path / "project")
    before = PluginCacheEvidence(
        source_root=source,
        installed_root=tmp_path / "home" / "old",
        source_digest="source",
        installed_digest="old",
        ready=False,
    )
    after = before.model_copy(
        update={"installed_root": tmp_path / "home" / "new", "ready": True}
    )
    evidence = iter([before, after])
    monkeypatch.setattr(
        harness_runtime,
        "plugin_cache_evidence",
        lambda source_root, config: next(evidence),
    )
    monkeypatch.setattr(
        harness_runtime,
        "stage_cachebusted_marketplace",
        lambda source_root, cwd, config, version: tmp_path / "staged",
    )
    calls: list[tuple[str, ...]] = []

    def command(executable: str):
        def run(*arguments: str, **_kwargs: object) -> str:
            calls.append(arguments)
            return ""

        return run

    monkeypatch.setattr(sh, "Command", command)
    installer = CodexPluginInstaller(
        PluginCacheConfig(codex_home=tmp_path / "home", marketplace="lup-test")
    )
    monkeypatch.setattr(installer, "plugin_environment", lambda: {})

    installer.ensure(source, tmp_path / "project")

    assert not any(arguments[:2] == ("plugin", "remove") for arguments in calls)
