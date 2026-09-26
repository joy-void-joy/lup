"""Where a project's configured values are kept: in the checkout, or on the host alone.

The setup wizard answers most integrations into ``.env.local``, the gitignored
file beside the checkout's ``.env``. That file is inside the checkout, and the
checkout is what every contained session mounts and every session reads -- the
right place for a value the application itself runs on, and exactly the wrong
one for a secret a session must never hold: a key a *host companion* uses, a
listener running beside the session on the operator's machine.

Such a key is declared host-only and kept in the operator's **host store**
instead, one file per project under their configuration home::

    $XDG_CONFIG_HOME/lup/secrets/<project>.env     (~/.config where unset)

The directory is its owner's alone (0700) and so is the file (0600) -- from
the moment it exists, not once a write finishes: every change is made to a
private copy beside it and renamed over it, so no reader meets half a file and
no instant leaves a copy anybody else may read. The project is named by the
``[project]`` table of the manifest its operator approved.

Nothing a session reads holds the store. A contained launch refuses a mount
that would carry its directory into the container, a launch takes every
host-only name out of the environment the session inherits, even where the
operator's shell exported one, and the store's values leave it only for the
host companions that name them.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import dotenv_values, set_key, unset_key
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from lup.trust.approved import declarations_root
from lup.types import EnvVars
from lup.workspace.paths import read_project_name


class SecretsLocation(BaseSettings, populate_by_name=True):
    """Where this machine keeps its configuration, per the XDG convention."""

    xdg_config_home: Path | None = Field(
        default=None, validation_alias="XDG_CONFIG_HOME"
    )

    def directory(self) -> Path:
        """The directory every project's host store lives in.

        A relative ``XDG_CONFIG_HOME`` is ignored, as the convention says it
        must be: it would name a different directory from every working
        directory it was read in.
        """
        configured = self.xdg_config_home
        home = (
            configured
            if configured is not None and configured.is_absolute()
            else Path.home() / ".config"
        )
        return home / "lup" / "secrets"


class ContainedHint(BaseSettings, populate_by_name=True):
    """Whether this process says it runs inside a lup container, as the image bakes it.

    A hint rather than a boundary: the image sets ``LUP_CONTAINED`` and a
    process can unset it. What it catches is the honest mistake -- the wizard
    run inside a session -- which would otherwise write a host-only secret into
    the container's own configuration home, where the host's companions never
    read it and the session can, and report it saved.
    """

    lup_contained: str = Field(default="", validation_alias="LUP_CONTAINED")

    def refusal(self, command: str) -> str:
        """Why a host-only write is refused here, naming the host command; "" on the host.

        ``command`` is what follows ``lup-launch run``, such as ``setup gemini``.
        """
        if self.lup_contained in ("", "0"):
            return ""
        return (
            "This runs inside a lup container (LUP_CONTAINED is set), where a "
            "host-only secret would land in the container's own configuration "
            "rather than the operator's host store. Set it from a host terminal: "
            f"`lup-launch run {command}`."
        )


class HostOnlyRefused(RuntimeError):
    """A host-only write attempted where the host store is not the host's."""


class EnvFile(BaseModel, ABC, frozen=True):
    """One dotenv file the wizard keeps answers in, and says a key lives in.

    Read with ``dotenv``, the parser pydantic-settings reads the application's
    own files with, so the wizard sees exactly the values the application
    does. Written by the same library's ``set_key``, which keeps every other
    line, comment and the order where they were -- applied to a private copy
    that then replaces the file in one rename.
    """

    path: Path

    @abstractmethod
    def label(self) -> str:
        """What the wizard calls this file where somebody decides where a key lives."""

    @abstractmethod
    def mode(self) -> int:
        """The permissions the file is written with."""

    def prepare(self) -> None:
        """Make the directory the file is written into."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def said(self) -> str:
        """The file named for a sentence: what it is, and where."""
        return f"{self.label()} ({self.path})"

    def read(self) -> EnvVars:
        """Every value the file holds, or nothing where there is no file."""
        if not self.path.is_file():
            return {}
        return {
            key: value
            for key, value in dotenv_values(self.path).items()
            if value is not None
        }

    def write(self, values: EnvVars) -> None:
        """Set these keys, keeping everything else the file holds."""
        if not values:
            return

        def assigned(staging: Path) -> None:
            for key, value in values.items():
                set_key(staging, key, value, quote_mode="never")

        self.edited(assigned)

    def clear(self, keys: Iterable[str]) -> None:
        """Drop these keys; a key the file does not hold is no change at all."""
        held = self.read()
        present = [key for key in keys if key in held]
        if not present:
            return

        def removed(staging: Path) -> None:
            for key in present:
                unset_key(staging, key)

        self.edited(removed)

    def edited(self, edit: Callable[[Path], None]) -> None:
        """Apply one edit to a private copy of the file, then put the copy in its place.

        The copy is created readable by its owner alone, beside the file so
        the rename stays on one filesystem, and given the file's mode before
        it replaces it. An edit that fails leaves the file as it was and the
        copy gone.
        """
        self.prepare()
        with NamedTemporaryFile(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".partial",
            delete=False,
        ) as created:
            staging = Path(created.name)
        try:
            if self.path.is_file():
                staging.write_bytes(self.path.read_bytes())
            edit(staging)
            staging.chmod(self.mode())
            staging.replace(self.path)
        finally:
            staging.unlink(missing_ok=True)


class CheckoutEnv(EnvFile, frozen=True):
    """A checkout's ``.env.local``: read by the application, and by every session."""

    def label(self) -> str:
        return self.path.name

    def mode(self) -> int:
        """The file's own mode where it has one; a file created here is its owner's."""
        return self.path.stat().st_mode & 0o777 if self.path.is_file() else 0o600


class HostSecrets(EnvFile, frozen=True):
    """One project's host store: outside every checkout, and never mounted into one."""

    project: str = Field(
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
        description="The project the store belongs to, as its manifest names it",
    )

    @classmethod
    def of(cls, project: str, location: SecretsLocation | None = None) -> "HostSecrets":
        """The store for one project, under this machine's configuration home."""
        chosen = location if location is not None else SecretsLocation()
        return cls(project=project, path=chosen.directory() / f"{project}.env")

    @classmethod
    def for_checkout(
        cls, root: Path, location: SecretsLocation | None = None
    ) -> "HostSecrets":
        """The store of the project a checkout is.

        Named from the approved snapshot where the installed launcher handed
        one over, since that manifest is the one its operator approved; from
        the checkout's own otherwise.
        """
        return cls.of(read_project_name(declarations_root(root)), location)

    def label(self) -> str:
        return "host store"

    def mode(self) -> int:
        return 0o600

    def prepare(self) -> None:
        """Make the directory, and hold it to its owner whatever made it first.

        Refused inside a container, before anything is made: whatever surface
        asked should have refused already, naming its own command, and this is
        what stops one that did not from writing into the wrong store silently.
        """
        refused = ContainedHint().refusal("setup")
        if refused:
            raise HostOnlyRefused(refused)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
