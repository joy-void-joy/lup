"""The CLI cache: each runtime's channel through a stubbed HTTP transport, no network.

Each runtime's fake channel publishes releases as its vendor's does: Claude Code's
`latest`, manifests and zstd binary; Codex's release descriptions and package.
"""

import hashlib
import io
import json
import tarfile
from abc import ABC, abstractmethod
from compression import zstd
from typing import TYPE_CHECKING, override

import httpx
import pytest

from lup.sessions.terminal import Cli
from lup_dev.adapters.claude import ClaudeChannel
from lup_dev.adapters.codex import CodexChannel
from lup_dev.launch.clis import Channel, CliCache, CliError
from lup_dev.layout import CliCacheLayout, Layout
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from pathlib import Path


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class Server:
    """A release channel's files by address, answering through `httpx.MockTransport`."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.requested: list[str] = []
        self.offline = False

    def answer(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        if self.offline:
            message = "Name or service not known"
            raise httpx.ConnectError(message, request=request)
        if url not in self.files:
            return httpx.Response(404, request=request)
        return httpx.Response(200, content=self.files[url], request=request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.answer)


class Vendor(ABC):
    """One runtime's channel, published by a fake server, and its versions as the cache keeps them."""

    channel: Channel

    @abstractmethod
    def publish(self, server: Server, version: str, *, tampered: bool = False) -> None:
        """Publish `version`; tampered, its file isn't the one its checksum names."""

    @abstractmethod
    def make_latest(self, server: Server, version: str) -> None:
        """Make `version` the channel's latest."""

    @abstractmethod
    def keep(self, layout: CliCacheLayout, version: str) -> None:
        """Put `version` in the cache, as a download would have left it."""

    @abstractmethod
    def cli(self, layout: CliCacheLayout, version: str) -> Cli:
        """Say what the cache should return for `version`."""

    @abstractmethod
    def program(self, version: str) -> bytes:
        """Return what `version`'s binary holds."""


class ClaudeVendor(Vendor):
    channel = ClaudeChannel()
    root = "https://downloads.claude.ai/claude-code-releases"

    @override
    def program(self, version: str) -> bytes:
        return f"#!/bin/sh\necho {version} '(Claude Code)'\n".encode()

    @override
    def publish(self, server: Server, version: str, *, tampered: bool = False) -> None:
        binary = self.program(version)
        packed = zstd.compress(binary)
        served = zstd.compress(binary + b"# planted\n") if tampered else packed
        server.files |= {
            f"{self.root}/{version}/manifest.json": self.manifest(
                version, "claude", binary
            ),
            f"{self.root}/{version}/manifest.zst.json": self.manifest(
                version, "claude.zst", packed
            ),
            f"{self.root}/{version}/linux-x64/claude.zst": served,
        }

    @staticmethod
    def manifest(version: str, name: str, content: bytes) -> bytes:
        build = {"binary": name, "checksum": sha256(content), "size": len(content)}
        platforms = {
            "darwin-arm64": {**build, "checksum": "0" * 64},
            "linux-x64": build,
        }
        return json.dumps(
            {
                "version": version,
                "manifestSignatureEnforcement": "flag",
                "platforms": platforms,
            }
        ).encode()

    @override
    def make_latest(self, server: Server, version: str) -> None:
        server.files[f"{self.root}/latest"] = version.encode()

    @override
    def keep(self, layout: CliCacheLayout, version: str) -> None:
        layout.version(version).mkdir(parents=True)
        (layout.version(version) / "claude").write_bytes(self.program(version))

    @override
    def cli(self, layout: CliCacheLayout, version: str) -> Cli:
        return Cli(program=layout.version(version) / "claude")


class CodexVendor(Vendor):
    channel = CodexChannel()
    root = "https://releases.openai.com/codex"
    package = "codex-package-x86_64-unknown-linux-musl.tar.gz"

    @override
    def program(self, version: str) -> bytes:
        return f"#!/bin/sh\necho codex-cli {version}\n".encode()

    def files(self, version: str, *, holds: str | None = None) -> dict[str, bytes]:
        manifest = {
            "layoutVersion": 1,
            "version": holds or version,
            "target": "x86_64-unknown-linux-musl",
            "variant": "codex",
            "entrypoint": "bin/codex",
            "resourcesDir": "codex-resources",
            "pathDir": "codex-path",
        }
        return {
            "codex-package.json": json.dumps(manifest).encode(),
            "bin/codex": self.program(version),
            "bin/codex-code-mode-host": b"host",
            "codex-path/rg": b"rg",
            "codex-resources/bwrap": b"bwrap",
        }

    @staticmethod
    def archive(files: dict[str, bytes]) -> bytes:
        written = io.BytesIO()
        with tarfile.open(fileobj=written, mode="w:gz") as bundle:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mode = 0o755
                bundle.addfile(member, io.BytesIO(content))
        return written.getvalue()

    def release(self, version: str, archive: bytes) -> bytes:
        url = f"{self.root}/releases/{version}/{self.package}"
        assets = [
            {
                "name": "codex-x86_64-unknown-linux-musl.tar.gz",
                "browser_download_url": f"{self.root}/releases/{version}/codex.tar.gz",
                "digest": "sha256:" + "0" * 64,
            },
            {
                "name": self.package,
                "browser_download_url": url,
                "digest": f"sha256:{sha256(archive)}",
            },
        ]
        return json.dumps({"tag_name": f"rust-v{version}", "assets": assets}).encode()

    @override
    def publish(
        self,
        server: Server,
        version: str,
        *,
        tampered: bool = False,
        holds: str | None = None,
    ) -> None:
        archive = self.archive(self.files(version, holds=holds))
        planted = self.archive({**self.files(version), "bin/codex": b"planted"})
        server.files |= {
            f"{self.root}/releases/{version}/release.json": self.release(
                version, archive
            ),
            f"{self.root}/releases/{version}/{self.package}": planted
            if tampered
            else archive,
        }

    @override
    def make_latest(self, server: Server, version: str) -> None:
        server.files[f"{self.root}/channels/latest"] = server.files[
            f"{self.root}/releases/{version}/release.json"
        ]

    @override
    def keep(self, layout: CliCacheLayout, version: str) -> None:
        for name, content in self.files(version).items():
            path = layout.version(version) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    @override
    def cli(self, layout: CliCacheLayout, version: str) -> Cli:
        return Cli(
            program=layout.version(version) / "bin" / "codex",
            directory=layout.version(version),
        )


@pytest.fixture(params=[ClaudeVendor, CodexVendor], ids=["claude", "codex"])
def vendor(request: pytest.FixtureRequest) -> Vendor:
    return request.param()


@pytest.fixture
def server() -> Server:
    return Server()


@pytest.fixture
def layout(tmp_path: Path) -> CliCacheLayout:
    return Layout(state=tmp_path / "state", cache=tmp_path / "cache").clis("runtime")


def cache(layout: CliCacheLayout, vendor: Vendor, server: Server) -> CliCache:
    return CliCache(layout=layout, channel=vendor.channel, transport=server.transport())


def kept(layout: CliCacheLayout) -> list[str]:
    return sorted(entry.name for entry in layout.versions.iterdir())


def staged(layout: CliCacheLayout) -> list[Path]:
    return list(layout.staging.rglob("*"))


def test_a_newer_version_is_downloaded_checked_and_run(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.0.0")
    vendor.publish(server, "1.1.0")
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.1.0"
    assert found.fallback is None
    assert found.cli == vendor.cli(layout, "1.1.0")
    assert found.cli.program.read_bytes() == vendor.program("1.1.0")
    assert found.cli.program.stat().st_mode & 0o111 == 0o111
    assert kept(layout) == ["1.0.0", "1.1.0"]
    assert staged(layout) == []


def test_a_cache_starts_empty(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.publish(server, "1.1.0")
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.1.0"
    assert kept(layout) == ["1.1.0"]


def test_a_download_that_doesnt_match_its_checksum_is_never_used(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.0.0")
    vendor.publish(server, "1.1.0", tampered=True)
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.0"
    assert found.cli == vendor.cli(layout, "1.0.0")
    assert found.fallback is not None
    assert "doesn't match the checksum its channel publishes" in found.fallback
    assert kept(layout) == ["1.0.0"]
    assert staged(layout) == []


def test_a_binary_that_decompresses_to_another_checksum_is_never_used(
    server: Server, layout: CliCacheLayout
) -> None:
    vendor = ClaudeVendor()
    vendor.publish(server, "1.1.0")
    vendor.make_latest(server, "1.1.0")
    manifest = f"{vendor.root}/1.1.0/manifest.json"
    server.files[manifest] = vendor.manifest("1.1.0", "claude", b"another binary")

    with pytest.raises(CliError, match="decompressed"):
        cache(layout, vendor, server).current()
    assert kept(layout) == []
    assert staged(layout) == []


def test_offline_the_newest_version_kept_runs_and_says_so(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.0.9")
    vendor.keep(layout, "1.0.10")
    server.offline = True

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.10"
    assert found.cli == vendor.cli(layout, "1.0.10")
    assert found.fallback is not None
    assert "couldn't be fetched" in found.fallback
    assert "Name or service not known" in found.fallback


def test_offline_with_nothing_kept_there_is_nothing_to_run(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    server.offline = True

    with pytest.raises(CliError, match="no CLI is kept"):
        cache(layout, vendor, server).current()


def test_a_channel_that_answers_with_an_error_runs_what_is_kept(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.0.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.0"
    assert found.fallback is not None
    assert "404 Not Found" in found.fallback


def test_versions_beyond_the_one_before_are_removed(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    for version in ["0.9.0", "1.0.2", "1.0.10"]:
        vendor.keep(layout, version)
    vendor.publish(server, "1.1.0")
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.1.0"
    assert kept(layout) == ["1.0.10", "1.1.0"]


def test_a_version_already_kept_isnt_downloaded_again(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.1.0")
    vendor.publish(server, "1.1.0")
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.1.0"
    assert found.fallback is None
    assert len(server.requested) == 1
    assert server.requested[0].endswith("latest")


def test_a_channel_whose_latest_went_back_runs_the_newest_kept(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.1.0")
    vendor.publish(server, "1.0.0")
    vendor.make_latest(server, "1.0.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.1.0"
    assert found.fallback is None
    assert kept(layout) == ["1.1.0"]


def test_what_a_download_cut_off_left_staged_is_removed(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.1.0")
    left = layout.staging / "tmp-cut-off" / "1.2.0"
    left.mkdir(parents=True)
    (left / "partial").write_bytes(b"half a binary")
    vendor.publish(server, "1.1.0")
    vendor.make_latest(server, "1.1.0")

    cache(layout, vendor, server).current()

    assert staged(layout) == []


def test_a_package_holding_another_version_is_refused(
    server: Server, layout: CliCacheLayout
) -> None:
    vendor = CodexVendor()
    vendor.keep(layout, "1.0.0")
    vendor.publish(server, "1.1.0", holds="1.0.9")
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.0"
    assert found.fallback is not None
    assert "holds 1.0.9" in found.fallback
    assert kept(layout) == ["1.0.0"]


def test_a_release_without_the_package_runs_what_is_kept(
    server: Server, layout: CliCacheLayout
) -> None:
    vendor = CodexVendor()
    vendor.keep(layout, "1.0.0")
    vendor.publish(server, "1.1.0")
    release = f"{vendor.root}/releases/1.1.0/release.json"
    server.files[release] = json.dumps(
        {"tag_name": "rust-v1.1.0", "assets": []}
    ).encode()
    vendor.make_latest(server, "1.1.0")

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.0"
    assert found.fallback is not None
    assert f"lists no {vendor.package}" in found.fallback


def test_a_tag_outside_the_channels_scheme_runs_what_is_kept(
    server: Server, layout: CliCacheLayout
) -> None:
    vendor = CodexVendor()
    vendor.keep(layout, "1.0.0")
    latest = json.dumps({"tag_name": "v1.1.0", "assets": []}).encode()
    server.files[f"{vendor.root}/channels/latest"] = latest

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.0"
    assert found.fallback is not None
    assert "doesn't start rust-v" in found.fallback


def test_a_latest_that_isnt_a_version_runs_what_is_kept(
    server: Server, layout: CliCacheLayout
) -> None:
    vendor = ClaudeVendor()
    vendor.keep(layout, "1.0.0")
    server.files[f"{vendor.root}/latest"] = b"<html>unavailable in your region</html>"

    found = cache(layout, vendor, server).current()

    assert found.version == "1.0.0"
    assert found.fallback is not None
    assert "isn't a version" in found.fallback


def test_a_cache_holding_what_isnt_a_version_is_refused(
    vendor: Vendor, server: Server, layout: CliCacheLayout
) -> None:
    vendor.keep(layout, "1.0.0")
    (layout.versions / "notes").mkdir()
    server.offline = True

    with pytest.raises(CliError, match="isn't a version"):
        cache(layout, vendor, server).current()


def test_the_cache_lives_under_xdg_cache_home(tmp_path: Path) -> None:
    settings = LupDevSettings(xdg_cache_home=tmp_path / "cache")

    assert (
        Layout.of(settings).clis("runtime").home
        == tmp_path / "cache" / "lup" / "clis" / "runtime"
    )
