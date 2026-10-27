"""Accounts: each a login per runtime, kept by its name, listed and logged out on the host (`docs/launch.md`, *Accounts and profiles*).

An account keeps each runtime's login in a directory of that runtime's own
(`AccountLayout`), the file its sign-in writes inside, where the runtime's
adapter places it. `default` is always an account, whether or not anything
signed in to it yet; the rest are each directory there by an account's name.

Logging out empties the login file rather than removing it. A single-file
mount of it can't be removed from under the room, which a runtime's own
logout finds (`docs/field-notes.md`, *Rooms*), and removing it on the host
would leave such a mount on the login it had; emptied in place, the mount
sees it emptied. An empty file
is no login, as a missing one is. Nothing is revoked with the provider: the
login is forgotten here alone.
"""

from collections.abc import Callable
from pathlib import Path

from lup.types import Model
from lup_dev.declaration.grammar import listed
from lup_dev.declaration.profiles import DEFAULT, directory_named
from lup_dev.errors import LupDevError
from lup_dev.layout import AccountsLayout


class AccountError(LupDevError):
    """An account named that can't be one, or a runtime no adapter names."""


class RuntimeLogin(Model, arbitrary_types_allowed=True):
    """One runtime lup knows, by its adapter's name, and where its adapter keeps its login in a home of its own."""

    name: str
    login: Callable[[Path], Path]
    """The file its sign-in writes, in the directory given."""


class Login(Model):
    """One runtime's login in an account: where it's kept, and whether it holds one."""

    runtime: str
    path: Path

    def held(self) -> bool:
        """Say whether it holds a login: a file that isn't empty."""
        return self.path.is_file() and self.path.stat().st_size > 0


class Account(Model):
    """One account's logins, a runtime each."""

    name: str
    logins: list[Login]

    def said(self) -> str:
        """Say which runtimes it holds a login for, in a line.

        >>> Account(name="work", logins=[]).said()
        'work: no login'
        """
        held = [each.runtime for each in self.logins if each.held()]
        missing = [each.runtime for each in self.logins if not each.held()]
        if not held:
            return f"{self.name}: no login"
        if not missing:
            return f"{self.name}: a login for {listed(held)}"
        return f"{self.name}: a login for {listed(held)}, none for {listed(missing)}"


class Accounts(Model):
    """Every account on this machine, by the runtimes lup knows."""

    layout: AccountsLayout
    runtimes: list[RuntimeLogin]

    def names(self) -> list[str]:
        """List every account by its name: `default` first, then each directory by an account's name, in order."""
        found = (
            sorted(each.name for each in self.layout.home.iterdir() if each.is_dir())
            if self.layout.home.is_dir()
            else []
        )

        def named(name: str) -> bool:
            try:
                directory_named(name)
            except ValueError:
                return False
            return name != DEFAULT

        return [DEFAULT, *(name for name in found if named(name))]

    def account(self, name: str) -> Account:
        """Return the account `name`'s logins, one per runtime, whether or not it's there yet.

        Raise `AccountError` where `name` can't name an account.
        """
        try:
            directory_named(name)
        except ValueError as malformed:
            raise AccountError(str(malformed)) from malformed
        place = self.layout.account(name)
        return Account(
            name=name,
            logins=[
                Login(runtime=each.name, path=each.login(place.runtime(each.name)))
                for each in self.runtimes
            ],
        )

    def listed(self) -> list[str]:
        """Say every account and the runtimes it holds a login for, a line each."""
        return [self.account(name).said() for name in self.names()]

    def logout(self, name: str, runtime: str | None = None) -> list[str]:
        """Log the account `name` out of `runtime`, or of every runtime where it's none, and say what was done, a line each.

        Each login held is emptied in place, keeping its file and its mode
        (the module's docstring says why). Raise `AccountError` where `name`
        can't name an account, or where `runtime` names no runtime lup knows.
        """
        known = [each.name for each in self.runtimes]
        if runtime is not None and runtime not in known:
            message = (
                f"no runtime is called `{runtime}`: the runtimes are {listed(known)}"
            )
            raise AccountError(message)
        logins = [
            each
            for each in self.account(name).logins
            if runtime is None or each.runtime == runtime
        ]
        held = [each for each in logins if each.held()]
        unheld = [each.runtime for each in logins if each not in held]
        for each in held:
            each.path.write_bytes(b"")
        said = [
            f"Logged `{name}` out of `{each.runtime}`: its login at {each.path} is "
            "emptied, so a launch on the account signs in again. It isn't revoked "
            "with the provider."
            for each in held
        ]
        if unheld:
            said.append(
                f"`{name}` holds no login for {listed(unheld)}: nothing to log out."
            )
        return said
