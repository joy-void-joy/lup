"""Each runtime's latest CLI, from its vendor's release channel, kept in lup's cache.

A launch runs the latest CLI, whatever the host has installed (`docs/launch.md`,
*The CLIs*). At each launch, the cache asks the runtime's release channel, the one
its vendor's own installer uses, for its latest version: one small request. When
that's newer than every version kept, it's downloaded into a staging directory,
checked against the checksum the channel publishes, and only then moved among the
versions, so a download that doesn't match is never used. The cache keeps the
newest version and the one before it, which a session started earlier may still
be running, and removes the rest.

When the channel can't give its latest, unreachable or its download refused, the
newest version kept runs, and the result says why; with none kept, there's nothing
to run. Nothing is retried within a launch: the next launch asks again.

Each runtime's channel, where its versions are listed and what a version
downloads, is spelled in its adapter (`lup_dev.adapters`), which implements
`Channel` with the helpers here.
"""

import hashlib
import shutil
import stat
import tarfile
import tempfile
from abc import ABC, abstractmethod
from compression import zstd
from pathlib import Path

import httpx
from filelock import FileLock
from packaging.version import InvalidVersion, Version
from pydantic import ValidationError

from lup.sessions.terminal import Cli
from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.layout import CliCacheLayout


class CliError(LupDevError):
    """No CLI for a launch to run: its channel couldn't give one, and none is kept."""


class ChannelError(LupDevError):
    """A release channel that couldn't give a version: unreachable, unreadable, or its download refused."""


class ChecksumError(ChannelError):
    """A download whose checksum isn't the one its channel publishes: discarded, never used."""


def text(client: httpx.Client, url: str) -> str:
    """Return the text at `url`."""
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as failed:
        message = f"{url} couldn't be fetched: {failed}"
        raise ChannelError(message) from failed
    return response.text


def document[Read: Model](client: httpx.Client, url: str, model: type[Read]) -> Read:
    """Return the JSON document at `url`, read as `model`."""
    try:
        return model.model_validate_json(text(client, url))
    except ValidationError as failed:
        message = f"{url} doesn't read as a {model.__name__}: {failed}"
        raise ChannelError(message) from failed


def download(client: httpx.Client, url: str, into: Path) -> str:
    """Download `url` into the file `into`, and return its SHA-256 as hex, for the caller to check."""
    digest = hashlib.sha256()
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with into.open("wb") as file:
                for chunk in response.iter_bytes():
                    digest.update(chunk)
                    file.write(chunk)
    except httpx.HTTPError as failed:
        message = f"{url} couldn't be downloaded: {failed}"
        raise ChannelError(message) from failed
    return digest.hexdigest()


def check(url: str, digest: str, published: str) -> None:
    """Refuse what was downloaded from `url` unless its digest, spelled as its channel spells it, is the one published."""
    if digest != published:
        message = (
            f"{url} doesn't match the checksum its channel publishes: "
            f"it's {digest}, where {published} is published"
        )
        raise ChecksumError(message)


def decompress(archive: Path, into: Path) -> str:
    """Decompress the zstd file `archive` into the file `into`, and return its SHA-256 as hex."""
    try:
        with zstd.open(archive) as source, into.open("wb") as file:
            shutil.copyfileobj(source, file)
    except zstd.ZstdError as failed:
        message = f"{archive.name} doesn't decompress: {failed}"
        raise ChannelError(message) from failed
    with into.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def executable(program: Path) -> None:
    """Let anyone run `program`, as an installer leaves a binary it downloaded."""
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def extract(archive: Path, into: Path) -> None:
    """Extract the tar archive `archive`, compressed or not, into the directory `into`.

    Python's `data` filter refuses a member that would land outside `into`, a link
    pointing outside it, and a device file.
    """
    try:
        with tarfile.open(archive) as bundle:
            bundle.extractall(into, filter="data")
    except tarfile.TarError as failed:
        message = f"{archive.name} doesn't extract: {failed}"
        raise ChannelError(message) from failed


class Channel(Model, ABC):
    """A runtime's release channel, the one its vendor's own installer uses, for Linux on x86-64.

    A room's image is Arch Linux, which is built for x86-64 alone.
    """

    @abstractmethod
    def latest(self, client: httpx.Client) -> str:
        """Ask the channel for its latest version, as it spells it, in one small request."""

    @abstractmethod
    def download(self, client: httpx.Client, version: str, into: Path) -> None:
        """Download `version` into the empty directory `into`, checked against the checksum the channel publishes.

        Raise `ChannelError` for what the channel couldn't give, and `ChecksumError`
        for a download that doesn't match.
        """

    @abstractmethod
    def cli(self, directory: Path) -> Cli:
        """Say how a room mounts and runs the version kept in `directory`.

        Raise `ChannelError` where what's kept doesn't read.
        """


class CachedCli(Model):
    """The CLI a launch runs: its version, how the room mounts and runs it, and why it's an older one, if it is."""

    version: str
    cli: Cli
    fallback: str | None = None
    """Why the newest version kept runs without the channel's latest: the channel
    unreachable, or its download refused. None when the channel answered and its
    latest is kept."""


def newer(latest: str, kept: list[str]) -> bool:
    """Say whether the channel's latest version is newer than every version kept."""
    try:
        version = Version(latest)
    except InvalidVersion as failed:
        message = f"the channel's latest, {latest!r}, isn't a version: {failed}"
        raise ChannelError(message) from failed
    return all(version > Version(each) for each in kept)


class CliCache(Model, arbitrary_types_allowed=True):
    """One runtime's CLIs in lup's cache, kept current from its release channel."""

    layout: CliCacheLayout
    channel: Channel
    keep: int = 2
    """How many versions are kept, newest first: the current one, and the one before
    it, which a session started earlier may still be running."""
    timeout: float = 10.0
    """Seconds to wait for the channel to connect, or to send more, before the launch
    runs what's kept."""
    transport: httpx.BaseTransport | None = None
    """How requests reach the channel; none for the network."""

    def current(self) -> CachedCli:
        """Return the CLI to run: the channel's latest, or the newest kept when the channel can't give it.

        The cache is updated under its lock, so launches starting at once download
        a version once.
        """
        self.layout.versions.mkdir(parents=True, exist_ok=True)
        self.layout.staging.mkdir(parents=True, exist_ok=True)
        with FileLock(self.layout.lock):
            for left in self.layout.staging.iterdir():
                shutil.rmtree(left)
            fallback = self.update()
            kept = self.kept()
            if not kept:
                message = (
                    f"no CLI is kept in {self.layout.versions}, and its release "
                    f"channel couldn't give one: {fallback}"
                )
                raise CliError(message)
            for index, version in enumerate(kept):
                if index >= self.keep:
                    shutil.rmtree(self.layout.version(version))
        [newest, *_] = kept
        try:
            cli = self.channel.cli(self.layout.version(newest))
        except ChannelError as failed:
            message = f"the CLI kept as {newest} can't be run: {failed}"
            raise CliError(message) from failed
        return CachedCli(version=newest, cli=cli, fallback=fallback)

    def update(self) -> str | None:
        """Download the channel's latest version, when it's newer than every version kept.

        Return why it couldn't, when the channel couldn't give it; none otherwise.
        """
        try:
            with httpx.Client(
                transport=self.transport, timeout=self.timeout, follow_redirects=True
            ) as client:
                latest = self.channel.latest(client)
                if not newer(latest, self.kept()):
                    return None
                with tempfile.TemporaryDirectory(dir=self.layout.staging) as scratch:
                    staged = Path(scratch) / latest
                    staged.mkdir()
                    self.channel.download(client, latest, staged)
                    staged.rename(self.layout.version(latest))
        except ChannelError as failed:
            return str(failed)
        return None

    def kept(self) -> list[str]:
        """List the versions kept, newest first."""
        names = [entry.name for entry in self.layout.versions.iterdir()]
        try:
            return sorted(names, key=Version, reverse=True)
        except InvalidVersion as failed:
            message = f"{self.layout.versions} holds what isn't a version: {failed}"
            raise CliError(message) from failed
