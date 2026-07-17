"""Native CLI capability probes and the Codex plugin-cache install gate.

The harness decides whether it may launch a native plugin from these
seams: a probe must classify a missing or failing CLI as unsupported
(never crash the doctor), a present CLI must yield its banner as
evidence, and :class:`CodexPluginInstaller` must short-circuit on a
verified cache, reinstall a stale one, and refuse to report success
when the installed digest still differs from the committed source.
Fake executables on disk stand in for the real CLIs, so every branch
runs offline.
"""

from pathlib import Path

import pytest

from lup.adapters.claude.harness_runtime import ClaudeCapabilityProbe
from lup.adapters.codex.harness_runtime import (
    CodexCapabilityProbe,
    CodexPluginInstaller,
    PluginCacheConfig,
)


def fake_cli(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


VERSIONED_CLI = """\
if [ "$1" = "--version" ]; then
  echo "9.9.9 (Fake CLI)"
else
  echo "subcommand help"
fi"""


class TestCapabilityProbes:
    def test_missing_executable_reports_unsupported_not_a_crash(self) -> None:
        for evidence in (
            ClaudeCapabilityProbe("claude-cli", ["--version"], Path("no-such")).probe(),
            CodexCapabilityProbe("codex-cli", ["--version"], Path("no-such")).probe(),
        ):
            assert evidence.supported is False
            assert evidence.version == "missing"

    def test_failing_subcommand_reports_unsupported(self, tmp_path: Path) -> None:
        executable = fake_cli(tmp_path, "claude", "exit 1")

        evidence = ClaudeCapabilityProbe("plugins", ["plugin"], executable).probe()

        assert evidence.supported is False
        assert evidence.version == "missing"

    def test_present_cli_yields_banner_output_and_version(self, tmp_path: Path) -> None:
        executable = fake_cli(tmp_path, "claude", VERSIONED_CLI)

        version = ClaudeCapabilityProbe(
            "claude-cli", ["--version"], executable
        ).probe()
        plugins = ClaudeCapabilityProbe(
            "plugins", ["plugin", "--help"], executable
        ).probe()

        assert version.supported and version.version == "9.9.9 (Fake CLI)"
        assert plugins.supported and "subcommand help" in plugins.evidence.output
        assert plugins.version == "9.9.9 (Fake CLI)"

    def test_codex_probe_shares_the_classification_contract(
        self, tmp_path: Path
    ) -> None:
        executable = fake_cli(tmp_path, "codex", VERSIONED_CLI)

        evidence = CodexCapabilityProbe(
            "app-server", ["app-server", "--help"], executable
        ).probe()

        assert evidence.supported and evidence.evidence.installed
        assert evidence.version == "9.9.9 (Fake CLI)"


def write_plugin_source(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text('{"name": "lup"}\n', encoding="utf-8")
    (root / "hook.py").write_text("DECISION = 'ask'\n", encoding="utf-8")


class TestPluginInstallGate:
    def cache_root(self, config: PluginCacheConfig) -> Path:
        return (
            config.codex_home
            / "plugins"
            / "cache"
            / config.marketplace
            / config.plugin
            / config.version
        )

    def test_verified_cache_short_circuits_without_invoking_codex(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "source"
        write_plugin_source(source)
        config = PluginCacheConfig(codex_home=tmp_path / "codex-home")
        write_plugin_source(self.cache_root(config))
        exploding = fake_cli(tmp_path, "codex", "exit 97")

        evidence = CodexPluginInstaller(config, exploding).ensure(source, tmp_path)

        assert evidence.ready
        assert evidence.installed_digest == evidence.source_digest

    def test_stale_cache_is_removed_then_reinstalled(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        write_plugin_source(source)
        config = PluginCacheConfig(codex_home=tmp_path / "codex-home")
        cache = self.cache_root(config)
        write_plugin_source(cache)
        (cache / "hook.py").write_text("DECISION = 'allow'\n", encoding="utf-8")
        log = tmp_path / "calls.log"
        installer_cli = fake_cli(
            tmp_path,
            "codex",
            f'echo "$1 $2" >> "{log}"\n'
            'if [ "$2" = "add" ]; then\n'
            f'  rm -rf "{cache}" && mkdir -p "{cache}" && cp -R "{source}/." "{cache}/"\n'
            "fi",
        )

        evidence = CodexPluginInstaller(config, installer_cli).ensure(source, tmp_path)

        assert evidence.ready
        assert log.read_text(encoding="utf-8").splitlines() == [
            "plugin remove",
            "plugin add",
        ]

    def test_install_that_leaves_a_differing_digest_is_refused(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "source"
        write_plugin_source(source)
        config = PluginCacheConfig(codex_home=tmp_path / "codex-home")
        lying_cli = fake_cli(tmp_path, "codex", "exit 0")

        with pytest.raises(RuntimeError, match="digest differs"):
            CodexPluginInstaller(config, lying_cli).ensure(source, tmp_path)

    def test_missing_source_tree_is_an_explicit_error(self, tmp_path: Path) -> None:
        config = PluginCacheConfig(codex_home=tmp_path / "codex-home")
        idle_cli = fake_cli(tmp_path, "codex", "exit 0")

        with pytest.raises(FileNotFoundError, match="plugin source does not exist"):
            CodexPluginInstaller(config, idle_cli).ensure(tmp_path / "ghost", tmp_path)
