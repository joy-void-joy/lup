"""Codex CLI evidence, cache verification, and explicit plugin installation."""

import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import sh
import tomlkit
from packaging.version import Version
from pydantic import BaseModel, Field

from lup.providers.codex.login import CODEX_LOGIN
from lup.harness.contracts import CapabilityProbe
from lup.harness.models import CapabilityEvidence
from lup.types import EnvVars


class CodexCliEvidence(BaseModel, frozen=True):
    executable: Path
    arguments: list[str] = []
    installed: bool
    output: str = ""


class PluginCacheConfig(BaseModel, frozen=True):
    codex_home: Path = Field(default_factory=lambda: Path.home() / ".codex")
    # Required for explicit shared homes and for a stable installed-cache path.
    marketplace: str
    plugin: str = "lup"
    # None derives an immutable cachebuster from deployable plugin content.
    # An explicit value selects an already-versioned external fixture.
    version: str | None = None


class PluginCacheEvidence(BaseModel, frozen=True):
    source_root: Path
    installed_root: Path
    source_digest: str
    installed_digest: str | None = None
    ready: bool


def digest_directory(root: Path, read_content: Callable[[Path], bytes]) -> str | None:
    """Hash deployable relative paths and modes with caller-normalized bytes."""
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"x" if path.stat().st_mode & 0o111 else b"-")
        digest.update(b"\0")
        digest.update(read_content(path))
        digest.update(b"\0")
    return digest.hexdigest()


def directory_digest(root: Path) -> str | None:
    """Hash exact deployable relative paths, modes, and bytes."""
    return digest_directory(root, lambda path: path.read_bytes())


def plugin_content_digest(root: Path) -> str | None:
    """Hash plugin content while treating its cachebuster version as location."""

    def content(path: Path) -> bytes:
        if path.relative_to(root) != Path(".codex-plugin/plugin.json"):
            return path.read_bytes()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version"] = ""
        return json.dumps(manifest, sort_keys=True).encode("utf-8")

    return digest_directory(root, content)


def plugin_manifest_version(source_root: Path) -> str:
    """The version segment codex caches this plugin under, from its manifest."""
    manifest = source_root / ".codex-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    match data:
        case {"version": str(version)}:
            return version
    raise ValueError(f"Codex plugin manifest lacks a version: {manifest}")


def cachebusted_plugin_version(source_root: Path, content_digest: str) -> str:
    """Name an immutable Codex cache revision for this plugin content."""
    base = Version(plugin_manifest_version(source_root)).public
    return f"{base}+codex.{content_digest}"


def plugin_cache_evidence(
    source_root: Path, config: PluginCacheConfig
) -> PluginCacheEvidence:
    """Compare the committed package to the separately installed cached copy."""
    source = plugin_content_digest(source_root)
    if source is None:
        raise FileNotFoundError(f"Codex plugin source does not exist: {source_root}")
    version = config.version or cachebusted_plugin_version(source_root, source)
    installed_root = (
        config.codex_home
        / "plugins"
        / "cache"
        / config.marketplace
        / config.plugin
        / version
    )
    installed = plugin_content_digest(installed_root)
    return PluginCacheEvidence(
        source_root=source_root,
        installed_root=installed_root,
        source_digest=source,
        installed_digest=installed,
        ready=installed == source,
    )


def stage_cachebusted_marketplace(
    source_root: Path,
    cwd: Path,
    config: PluginCacheConfig,
    version: str,
) -> Path:
    """Materialize one immutable marketplace source with a cachebusted manifest."""
    relative_source = source_root.resolve().relative_to(cwd.resolve())
    destination = (
        config.codex_home / "plugins" / "sources" / config.marketplace / version
    )
    if destination.is_dir():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(
        prefix=".staging-", dir=destination.parent
    ) as temporary_text:
        temporary = Path(temporary_text)
        marketplace = temporary / ".agents" / "plugins" / "marketplace.json"
        marketplace.parent.mkdir(parents=True)
        shutil.copy2(cwd / ".agents" / "plugins" / "marketplace.json", marketplace)
        staged_source = temporary / relative_source
        staged_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, staged_source)
        manifest = staged_source / ".codex-plugin" / "plugin.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document["version"] = version
        manifest.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            temporary.replace(destination)
        except FileExistsError:
            return destination
    return destination


class CodexCapabilityProbe(CapabilityProbe[CodexCliEvidence]):
    """Probe exactly one named Codex CLI capability through its native command."""

    def __init__(
        self,
        capability: str = "codex-cli",
        arguments: list[str] | None = None,
        executable: Path = Path("codex"),
    ) -> None:
        self.capability = capability
        self.arguments = list(arguments or ["--version"])
        self.executable = executable

    def probe(self) -> CapabilityEvidence[CodexCliEvidence]:
        try:
            command = sh.Command(str(self.executable))
            output = str(command(*self.arguments))
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            evidence = CodexCliEvidence(
                executable=self.executable,
                arguments=self.arguments,
                installed=False,
            )
            return CapabilityEvidence(
                capability=self.capability,
                supported=False,
                evidence=evidence,
                version="missing",
            )
        try:
            version = (
                output if self.arguments == ["--version"] else str(command("--version"))
            )
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            version = "unknown"
        evidence = CodexCliEvidence(
            executable=self.executable,
            arguments=self.arguments,
            installed=True,
            output=output,
        )
        return CapabilityEvidence(
            capability=self.capability,
            supported=True,
            evidence=evidence,
            version=version.strip(),
        )


def codex_capability_probes(
    executable: Path = Path("codex"),
) -> list[CodexCapabilityProbe]:
    """Compose independent probes without a provider-wide support table."""
    return [
        CodexCapabilityProbe("codex-cli", ["--version"], executable),
        CodexCapabilityProbe("app-server", ["app-server", "--help"], executable),
        CodexCapabilityProbe("plugins", ["plugin", "--help"], executable),
        CodexCapabilityProbe(
            "hooks",
            ["--enable", "hooks", "features", "list"],
            executable,
        ),
    ]


class CodexPluginInstaller:
    """Install only missing/stale local packages through the official CLI."""

    def __init__(
        self,
        config: PluginCacheConfig,
        executable: Path = Path("codex"),
    ) -> None:
        self.config = config
        self.executable = executable

    def plugin_environment(self) -> EnvVars:
        """Environment shared by every Codex plugin lifecycle command."""
        self.config.codex_home.mkdir(parents=True, exist_ok=True)
        return {
            **os.environ,  # lup: ignore[os-environ] — exact child-process inheritance
            **CODEX_LOGIN.environment(self.config.codex_home),
        }

    def ensure(
        self, source_root: Path, cwd: Path, force: bool = False
    ) -> PluginCacheEvidence:
        """Stage with the native CLI, then publish without pruning live revisions."""
        self.config.codex_home.mkdir(parents=True, exist_ok=True)
        with (self.config.codex_home / ".lup-plugin-install.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            before = plugin_cache_evidence(source_root, self.config)
            if before.ready and self.registered(before) and not force:
                return before
            if before.installed_root.exists() and not before.ready:
                raise RuntimeError(
                    f"Installed immutable Codex revision is corrupt: {before.installed_root}. "
                    "Select a clean Codex home; a live revision cannot be overwritten."
                )
            marketplace_root = stage_cachebusted_marketplace(
                source_root, cwd, self.config, before.installed_root.name
            )
            with TemporaryDirectory(
                prefix=".plugin-install-", dir=self.config.codex_home
            ) as temporary_text:
                staged = self.config.model_copy(
                    update={"codex_home": Path(temporary_text)}
                )
                environment = {
                    **self.plugin_environment(),
                    **CODEX_LOGIN.environment(staged.codex_home),
                }
                command = sh.Command(str(self.executable))
                command(
                    "plugin",
                    "marketplace",
                    "add",
                    str(marketplace_root),
                    _cwd=str(cwd),
                    _env=environment,
                )
                command(
                    "plugin",
                    "add",
                    f"{self.config.plugin}@{self.config.marketplace}",
                    "--json",
                    _cwd=str(cwd),
                    _env=environment,
                )
                self.publish(source_root, staged)
            return plugin_cache_evidence(source_root, self.config)

    def registered(self, evidence: PluginCacheEvidence) -> bool:
        """The native home must select this revision, not merely contain its files."""
        settings = self.config.codex_home / "config.toml"
        if not settings.exists():
            return False
        document = tomlkit.parse(settings.read_text(encoding="utf-8"))
        try:
            marketplace = document["marketplaces"][self.config.marketplace]
            plugin = document["plugins"][
                f"{self.config.plugin}@{self.config.marketplace}"
            ]
            source = marketplace["source"]
            expected = (
                self.config.codex_home
                / "plugins"
                / "sources"
                / self.config.marketplace
                / evidence.installed_root.name
            )
            return (
                plugin["enabled"] is True
                and marketplace["source_type"] == "local"
                and isinstance(source, str)
                and Path(source) == expected
            )
        except (KeyError, TypeError):
            return False

    def publish(self, source_root: Path, staged: PluginCacheConfig) -> None:
        """Retain every live path and merge only this native installation's state."""
        installed = plugin_cache_evidence(source_root, staged)
        if not installed.ready:
            raise RuntimeError(
                "Codex reported installation success but cached plugin digest differs"
            )
        destination = plugin_cache_evidence(source_root, self.config).installed_root
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            with TemporaryDirectory(prefix=".publish-", dir=destination.parent) as area:
                revision = Path(area) / "revision"
                shutil.copytree(installed.installed_root, revision)
                revision.replace(destination)
        settings = self.config.codex_home / "config.toml"
        document = (
            tomlkit.parse(settings.read_text(encoding="utf-8"))
            if settings.exists()
            else tomlkit.document()
        )
        native = tomlkit.parse(
            (staged.codex_home / "config.toml").read_text(encoding="utf-8")
        )
        for key, name in (
            ("marketplaces", self.config.marketplace),
            ("plugins", f"{self.config.plugin}@{self.config.marketplace}"),
        ):
            entries = document.setdefault(key, tomlkit.table(is_super_table=True))
            entries[name] = native[key][name]
        temporary = staged.codex_home / "published.config.toml"
        temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
        temporary.chmod(settings.stat().st_mode & 0o777 if settings.exists() else 0o600)
        temporary.replace(settings)

    def remove(self, cwd: Path) -> None:
        """Explicitly remove this plugin and its configured marketplace."""
        environment = self.plugin_environment()
        selector = f"{self.config.plugin}@{self.config.marketplace}"
        sh.Command(str(self.executable))(
            "plugin",
            "remove",
            selector,
            _cwd=str(cwd),
            _env=environment,
            _ok_code=[0, 1],
        )
        sh.Command(str(self.executable))(
            "plugin",
            "marketplace",
            "remove",
            self.config.marketplace,
            _cwd=str(cwd),
            _env=environment,
            _ok_code=[0, 1],
        )
