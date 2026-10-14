#!/usr/bin/env python3
"""`git-remote-lup`: git's remote helper in a room, which pushes and fetches through lup's host service.

`docs/host-tools.md`, *git through a remote helper*. The room's git configuration
rewrites each of the repository's remotes to `lup::<url>` (`remote/config.py`),
so git runs this for them, with the remote's name and its address
(`gitremote-helpers(7)`). It speaks git's helper protocol on its input and
output, and turns each batch git sends into one request on the launch's request
socket, which the room's git configuration names (`lup.requestSocket`); the host
carries it out with the operator's credentials, in the repository's own git
directory, within the limits the project's declaration sets
(`remote/protocol.py`), and this prints its answer in git's terms:
- `capabilities`: `push`, `fetch` and `option`;
- `list`, and `list for-push` before a push: the remote's refs, as the host
  lists them;
- `option`: a push's `dry-run`, `atomic`, `force`, `cas` (each lease of
  `--force-with-lease`) and `push-option`, kept for the push they come before;
- `push`: each source resolved in the room with `git rev-parse --verify`, since
  git hands over the revision as written (`HEAD~1`), and sent as an object id
  with its destination and whether it's forced (`+`); an empty source is a
  deletion. Each destination's `ok`, or `error` with why;
- `fetch`: the objects fetched on the host into the repository's own store,
  which the room shares, so git writes the room's refs itself.

The room's Python runs it, with the standard library alone (an import contract
keeps it so): it writes the host's requests as JSON by hand, so a test runs it
under git and reads what it sends as the host's models.
"""

import json
import socket

# lup: ignore("subprocess", why="the room's Python has no sh: the helper runs on the standard library alone")
import subprocess
import sys
from itertools import takewhile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
"""A JSON value, as the host's requests and replies are written."""


def failed(reason: str) -> SystemExit:
    """Return the exit that ends the helper, saying `reason` on its standard error, which git shows."""
    return SystemExit(f"lup: {reason}")


def git(*arguments: str) -> str | None:
    """Run git in the room's repository, and return what it printed, or none where it failed.

    git gives the helper the repository it runs for (`GIT_DIR`), which this
    inherits.
    """
    ran = subprocess.run(
        ["git", *arguments], capture_output=True, text=True, check=False
    )
    return ran.stdout.strip() if ran.returncode == 0 else None


def parted(text: str) -> list[str]:
    """Return the two sides of `text` around its last `:`, as git writes a push's refspec and a lease.

    >>> parted("HEAD:refs/heads/main")
    ['HEAD', 'refs/heads/main']
    """
    # lup: ignore("string-split", why="a refspec, `<src>:<dst>`, and a lease, `<ref>:<oid>`, are read by their last `:`: a ref's full name can't hold one (git-check-ref-format(1)), and the room's Python has no parser for either")
    sides = text.rsplit(":", 1)
    if len(sides) != 2:
        message = f"git gave {text!r}, which holds no `:`"
        raise failed(message)
    return sides


def update(refspec: str) -> dict[str, Json]:
    """Return one update of a push as the host reads it, from git's `[+]<src>:<dst>`.

    The source is resolved in the room's repository; an empty one is a deletion.
    """
    source, destination = parted(refspec.removeprefix("+"))
    resolved = (
        git("rev-parse", "--verify", "--quiet", "--end-of-options", source)
        if source
        else None
    )
    if source and resolved is None:
        message = f"`{source}` names no object in this repository"
        raise failed(message)
    return {
        "source": resolved,
        "destination": destination,
        "forced": refspec.startswith("+"),
    }


def lease(value: str) -> dict[str, Json]:
    """Return one lease of `--force-with-lease` as the host reads it, from git's `<ref>:<oid>`."""
    ref, expected = parted(value)
    return {"ref": ref, "expected": expected}


class Helper:
    """One run of the helper, for one remote: the options git set, and where the host answers."""

    def __init__(self, remote: str, requests: Path) -> None:
        """Start a run for `remote`, asking the host on the socket at `requests`."""
        self.remote = remote
        """The remote, by the name git gave: one of the repository's, or a URL."""
        self.requests = requests
        """The launch's request socket."""
        self.force = False
        self.dry_run = False
        self.atomic = False
        self.leases: list[Json] = []
        self.push_options: list[Json] = []

    def run(self, commands: Iterator[str]) -> None:
        """Answer each command git sends, until a blank line or the end of its input."""
        for line in commands:
            match line.removesuffix("\n").split(None, 2):
                case []:
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
                    rest = takewhile(str.strip, commands)
                    self.pushed([refspec, *(each.split()[-1] for each in rest)])
                case ["fetch", wanted, name]:
                    rest = [each.split() for each in takewhile(str.strip, commands)]
                    self.fetched(
                        [
                            {"object": wanted, "name": name},
                            *({"object": words[1], "name": words[2]} for words in rest),
                        ]
                    )
                case _:
                    message = f"git asked {line!r}, which this helper doesn't answer"
                    raise failed(message)

    def said(self, *lines: str) -> None:
        """Print `lines` to git, at once."""
        sys.stdout.write("".join(f"{line}\n" for line in lines))
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
                self.leases = [*self.leases, lease(value)]
            case "push-option":
                self.push_options = [*self.push_options, value]
            case "verbosity" | "progress":
                pass
            case _:
                return "unsupported"
        return "ok"

    def asked(self, request: dict[str, Json]) -> Json:
        """Send one request to the host on the launch's request socket, and return its reply."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            try:
                connection.connect(str(self.requests))
            except OSError as gone:
                message = (
                    f"lup's host service doesn't answer on {self.requests} ({gone}): "
                    "on the host, `lup-dev host` serves this room again"
                )
                raise failed(message) from gone
            connection.sendall(json.dumps(request).encode())
            connection.shutdown(socket.SHUT_WR)
            with connection.makefile("rb") as stream:
                answer = stream.read()
        if not answer:
            message = "lup's host service closed the connection without answering"
            raise failed(message)
        return json.loads(answer)

    def listed(self, *, for_push: bool) -> None:
        """Print the remote's refs, as the host lists them, each `<object> <name>`."""
        reply = self.asked(
            {"kind": "remote-list", "remote": self.remote, "for_push": for_push}
        )
        match reply:
            case {"kind": "remote-advertised", "refs": list() as refs}:
                self.said(*(self.ref(each) for each in refs), "")
            case {"kind": "refused", "error": str() as error}:
                raise failed(error)
            case _:
                message = f"lup's host service answered {reply!r} to a listing"
                raise failed(message)

    def ref(self, listed: Json) -> str:
        """Return one ref the host listed, as git reads it: `<object> <name>`."""
        match listed:
            case {"object": str() as oid, "name": str() as name}:
                return f"{oid} {name}"
            case _:
                message = f"lup's host service listed {listed!r}, not a ref"
                raise failed(message)

    def pushed(self, refspecs: list[str]) -> None:
        """Push one batch through the host, and print each destination's `ok` or `error`."""
        updates = [update(each) for each in refspecs]
        destinations = [parted(each)[1] for each in refspecs]
        reply = self.asked(
            {
                "kind": "remote-push",
                "remote": self.remote,
                "updates": list[Json](updates),
                "force": self.force,
                "leases": self.leases,
                "dry_run": self.dry_run,
                "atomic": self.atomic,
                "push_options": self.push_options,
            }
        )
        match reply:
            case {"kind": "remote-pushed", "updates": list() as outcomes}:
                self.said(*(self.outcome(each) for each in outcomes), "")
            case {"kind": "refused", "error": str() as error}:
                self.said(*(f"error {each} {error}" for each in destinations), "")
            case _:
                message = f"lup's host service answered {reply!r} to a push"
                raise failed(message)

    def outcome(self, updated: Json) -> str:
        """Return how one update ended, as git reads it: `ok <dst>`, or `error <dst> <why>`."""
        match updated:
            case {"destination": str() as destination, "error": None}:
                return f"ok {destination}"
            case {"destination": str() as destination, "error": str() as error}:
                return f"error {destination} {error}"
            case _:
                message = f"lup's host service answered {updated!r} for an update"
                raise failed(message)

    def fetched(self, wanted: list[dict[str, Json]]) -> None:
        """Fetch the objects git asked for through the host, and tell git they're there."""
        reply = self.asked(
            {
                "kind": "remote-fetch",
                "remote": self.remote,
                "wanted": list[Json](wanted),
            }
        )
        match reply:
            case {"kind": "remote-fetched"}:
                self.said("")
            case {"kind": "refused", "error": str() as error}:
                raise failed(error)
            case _:
                message = f"lup's host service answered {reply!r} to a fetch"
                raise failed(message)


def main() -> None:
    """Answer git on standard input and output, for the remote git names first."""
    requests = git("config", "--get", "lup.requestSocket")
    if requests is None:
        message = (
            "no request socket is configured (`lup.requestSocket`): this helper "
            "pushes and fetches through lup's host service, from a launched room"
        )
        raise failed(message)
    Helper(remote=sys.argv[1], requests=Path(requests)).run(iter(sys.stdin))


if __name__ == "__main__":
    main()
