"""`git-remote-lup`: git's remote helper in a room, which pushes and fetches through the project's `remote` part, with the operator's credentials.

The room's git configuration rewrites each URL of the repository's remotes to
`lup::<url>`, so git runs this for them, with the remote's name and its URL
(`gitremote-helpers(7)`). It speaks git's helper protocol on its input and
output, and turns each batch git hands it into one call of `Remotes`' services,
carried through the room's socket (`LUP_CALLING`), which says the call is the
session's agent's (`lup/remote/README.md`):
- `capabilities`: `push`, `fetch` and `option`;
- `list`, and `list for-push` before a push: the remote's refs, as the part
  lists them;
- `option`: a push's `dry-run`, `atomic`, `force`, `cas` (each lease of
  `--force-with-lease`) and `push-option`, kept for the push they come before;
- `push`: each source resolved in the room's repository to an object id, since
  git hands it over as written (`HEAD~1`), sent with its destination and
  whether it's forced (`+`), an empty source a deletion; each destination's
  `ok`, or `error` with why, what a part refusing at `Publishing` said printed
  on git's standard error first, since git shows one line a ref;
- `fetch`: the objects fetched into the repository's store, which the room
  shares, so git writes the room's refs itself.
"""

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lup.doors.door import RefusedError
from lup.doors.service import CARRYING
from lup.environment.running.container import Outward
from lup.environment.settings import LupSettings
from lup.errors import LupError
from lup.programs.git.answers import line
from lup.programs.git.running import Git
from lup.remote.remotes import (
    Fetching,
    Lease,
    Listing,
    Pushed,
    Remotes,
    Update,
    Updates,
    Wanted,
)
from lup.types import MutableModel

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator


class HelperError(LupError):
    """What ends the helper: git shows its words, and the push or fetch fails."""


def parted(text: str, separator: str, count: int) -> list[str]:
    """Return `text` taken apart at its first `count` `separator`s, the rest whole: a line of git's helper protocol, a refspec, a lease.

    >>> parted("option push-option a b", " ", 2), parted("refs/a:refs/b", ":", 1)
    (['option', 'push-option', 'a b'], ['refs/a', 'refs/b'])
    """
    # lup: ignore("string-split", why="git's remote helper protocol is lines of words apart by one space, its last word the rest of the line, and a refspec or a lease is two names apart by a `:`, which a ref's name can't hold (git-check-ref-format(1)): nothing parses either")
    return text.split(separator, count)


async def resolved(source: str) -> str:
    """Return the object `source` names in the room's repository, as git hands a push's source over as written (`HEAD~1`).

    Raise `HelperError` where it names none.
    """
    ran = await Git().ran(
        "rev-parse", "--verify", "--quiet", "--end-of-options", source
    )
    if ran.status != 0:
        message = f"`{source}` names no object in this repository"
        raise HelperError(message)
    return line(ran)


class Helper(MutableModel):
    """One run of the helper, for one remote: the options git set for the push to come, and what it answers git on."""

    remote: str
    """The remote, by the name git gave: one of the repository's, or a URL,
    which the part refuses."""
    calling: Path
    """The room's socket, through which each call is carried."""
    force: bool = False
    dry_run: bool = False
    atomic: bool = False
    leases: list[Lease] = []
    push_options: list[str] = []

    def run(self, commands: Iterator[str]) -> None:
        """Answer each command git sends, until a blank line or the end of its input."""
        for each in commands:
            match parted(each.removesuffix("\n"), " ", 2):
                case [""]:
                    return
                case ["capabilities"]:
                    self.said("push", "fetch", "option", "")
                case ["list"]:
                    self.listed(for_push=False)
                case ["list", "for-push"]:
                    self.listed(for_push=True)
                case ["option", name, value]:
                    self.said(self.option(name, value))
                case ["push", refspec]:
                    rest = [
                        parted(more.strip(), " ", 1)[-1]
                        for more in self.batch(commands)
                    ]
                    self.pushed([refspec, *rest])
                case ["fetch", wanted, name]:
                    rest = [
                        parted(more.strip(), " ", 2) for more in self.batch(commands)
                    ]
                    self.fetched(
                        [
                            Wanted(object=wanted, name=name),
                            *(Wanted(object=words[1], name=words[2]) for words in rest),
                        ]
                    )
                case _:
                    message = f"git asked {each!r}, which this helper doesn't answer"
                    raise HelperError(message)

    @staticmethod
    def batch(commands: Iterator[str]) -> Iterator[str]:
        """Return the rest of a batch git sends, up to the blank line ending it."""
        for each in commands:
            if not each.strip():
                return
            yield each

    def said(self, *lines: str) -> None:
        """Print `lines` to git, at once."""
        sys.stdout.write("".join(f"{each}\n" for each in lines))
        sys.stdout.flush()

    def option(self, name: str, value: str) -> str:
        """Keep an option git set for the push it comes before, and return the answer git reads: `ok`, or `unsupported`."""
        match name:
            case "dry-run":
                self.dry_run = value == "true"
            case "atomic":
                self.atomic = value == "true"
            case "force":
                self.force = value == "true"
            case "cas":
                ref, expected = parted(value, ":", 1)
                self.leases = [*self.leases, Lease(ref=ref, expected=expected)]
            case "push-option":
                self.push_options = [*self.push_options, value]
            case "verbosity" | "progress":
                pass
            case _:
                return "unsupported"
        return "ok"

    def carried[T](self, call: Awaitable[T]) -> T:
        """Run `call`, a call of the part's services, carried through the room's socket, and return what it answered.

        Raise `HelperError` where it's refused, saying why.
        """

        async def answered() -> T:
            CARRYING.set(Outward(calling=self.calling))
            return await call

        try:
            return asyncio.run(answered())
        except RefusedError as refused:
            raise HelperError(str(refused)) from refused

    def listed(self, *, for_push: bool) -> None:
        """Print the remote's refs, as the part lists them, each `<object> <name>`."""
        listed = self.carried(
            Remotes.listed(Listing(remote=self.remote, for_push=for_push))
        )
        self.said(*(f"{each.object} {each.name}" for each in listed.refs), "")

    def pushed(self, refspecs: list[str]) -> None:
        """Push one batch through the part, and print each destination's `ok`, or `error` with why."""

        async def update(refspec: str) -> Update:
            source, destination = parted(refspec.removeprefix("+"), ":", 1)
            return Update(
                source=await resolved(source) if source else None,
                destination=destination,
                forced=refspec.startswith("+"),
            )

        async def updates() -> list[Update]:
            return [await update(each) for each in refspecs]

        pushed = self.carried(self.updated(updates()))
        if pushed.said:
            sys.stderr.write(f"{pushed.said}\n")
            sys.stderr.flush()
        self.said(
            *(
                f"ok {each.destination}"
                if each.error is None
                else f"error {each.destination} {each.error}"
                for each in pushed.updates
            ),
            "",
        )

    async def updated(self, updates: Awaitable[list[Update]]) -> Pushed:
        """Push `updates`, with the options git set, through the part."""
        return await Remotes.pushed(
            Updates(
                remote=self.remote,
                updates=await updates,
                force=self.force,
                leases=self.leases,
                dry_run=self.dry_run,
                atomic=self.atomic,
                push_options=self.push_options,
            )
        )

    def fetched(self, wanted: list[Wanted]) -> None:
        """Fetch the objects git asked for through the part, and tell git they're there."""
        self.carried(Remotes.fetched(Fetching(remote=self.remote, wanted=wanted)))
        self.said("")


def main() -> None:
    """Answer git on standard input and output, for the remote git names first: `git-remote-lup <remote> <url>`."""
    calling = LupSettings().lup_calling
    if calling is None:
        message = (
            "lup: `LUP_CALLING` names no socket: this helper pushes and fetches "
            "through lup, from a session's room"
        )
        raise SystemExit(message)
    try:
        Helper(remote=sys.argv[1], calling=calling).run(iter(sys.stdin))
    except HelperError as failed:
        message = f"lup: {failed}"
        raise SystemExit(message) from failed
