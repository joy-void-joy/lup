"""`Withholding`: the machine's part holding the list of what never leaves under the operator's name, which checks what's about to leave and says where it found something, never what.

The list is built on the operator's machine, for each project, and never
leaves it, not even for `Private`'s own part (`README.md` here):
- **what lup finds:** the operator's home path, their user name, the machine's
  name, each host of the project's remotes that their ssh configuration
  resolves to another name (an alias), and the project's own path, each also
  as `~/…`;
- **what the operator adds:** `Private.values`, in the machine's layer
  (`~/.config/lup/lup_project.local.py`), which no room mounts;
- **an inbox item's number** in prose, by its shape.

Each detail is withheld unless the declaration drops it (`Private.details`).
"""

import getpass
import socket
from pathlib import Path

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Codebase, Machine, Operator
from lup.doors.parts import Part, Program
from lup.hosting.projects import Locating, Projects
from lup.private.checking import Binary, Checked, Checking, Place, Text
from lup.private.cited import numbered
from lup.private.found import Held, Kind, counted, found
from lup.programs.git.answers import line, nul_separated
from lup.programs.git.running import Git, unconfigured
from lup.types import Model
lazy from lup.private.module import Private, Values


class Listed(Model):
    """A project's list: each value withheld, and whether an item's number is."""

    held: list[Held] = []
    numbers: bool = True


def said(kind: Kind) -> str:
    """Say what a value is by its kind, never the value, as a refusal names it.

    >>> said("home")
    "the operator's home path"
    """
    match kind:
        case "home":
            return "the operator's home path"
        case "user":
            return "the operator's user name"
        case "hostname":
            return "the machine's name"
        case "alias":
            return "an alias of the operator's ssh configuration"
        case "repository-path":
            return "the project's path on the operator's machine"
        case "value":
            return "a value the operator withholds"
        case "item-number":
            return "an inbox item's number, which on GitHub mentions a user"


def steer(kind: Kind) -> str:
    """Say how to write what's found instead.

    >>> steer("home")
    'write it as `~`, or a path in the repository from its root'
    """
    match kind:
        case "home" | "repository-path":
            return "write it as `~`, or a path in the repository from its root"
        case "item-number":
            return "say what the item said, in your own words"
        case "user" | "hostname" | "alias" | "value":
            return "leave it out"


def tilded(path: Path, home: Path) -> list[str]:
    """Return `path` as written, and as `~/…` where it's under `home`.

    >>> tilded(Path("/home/op/src/a.git"), Path("/home/op"))
    ['/home/op/src/a.git', '~/src/a.git']
    """
    if not path.is_relative_to(home):
        return [str(path)]
    return [str(path), str(Path("~") / path.relative_to(home))]


class Withholding(Part, machine=True, shared=True):
    """The machine's part holding the list of what never leaves under the operator's name, checking what's about to leave."""

    module: Private
    git: Program = Program(
        name="git",
        optional=True,
        why="reads a project's remotes, whose aliases the list withholds",
        install="https://git-scm.com",
    )
    ssh: Program = Program(
        name="ssh",
        optional=True,
        why="resolves the hosts of a project's remotes, an alias among them",
        install="https://www.openssh.com",
    )
    lists: dict[str, Listed] = {}
    """Each project's list, by its repository, built once while the machine's
    parts run."""

    async def listed(self, repository: str) -> Listed:
        """Return the list of `repository`'s project, built where it isn't yet: what lup finds on the machine, and the operator's values, each detail the declaration keeps.

        A project the machine doesn't run, as lup answering in a process of
        its own has none, has no path or remotes to withhold, and the rest is.
        """
        kept = self.lists.get(repository)
        if kept is not None:
            return kept
        try:
            located = await Projects.located(Locating(repository=repository))
        except RefusedError:
            common = None
        else:
            common = located.opening.common
        home = Path.home()
        homes = list(dict.fromkeys([str(home), str(home.resolve())]))
        roots = (
            []
            if common is None
            else [common, *([common.parent] if common.name == ".git" else [])]
        )
        aliases = [] if common is None else await self.aliases(common)
        found: list[Held] = [
            *(Held(kind="home", text=each) for each in homes),
            Held(kind="user", text=getpass.getuser()),
            Held(kind="hostname", text=socket.gethostname()),
            *(
                Held(kind="repository-path", text=each)
                for root in roots
                for each in tilded(root, home)
            ),
            *(Held(kind="alias", text=each) for each in aliases),
            *(Held(kind="value", text=each) for each in self.module.held(Values)),
        ]
        details = self.module.withheld()
        listed = Listed(
            held=[each for each in found if each.kind in details and each.text],
            numbers="item-number" in details,
        )
        self.lists = {**self.lists, repository: listed}
        return listed

    async def aliases(self, common: Path) -> list[str]:
        """Return each host the repository's remotes name that the operator's ssh configuration resolves to another name."""
        store = Git.pinned(common, through=self.git)
        listed = await store.ran(
            "config",
            "get",
            "--local",
            "--all",
            "--regexp",
            "-z",
            r"^remote\..*\.(push)?url$",
        )
        urls = nul_separated(listed.output) if listed.status == 0 else []
        git = Git(through=self.git)
        parsed = [
            await git.ran("url-parse", "-c", "host", "--", url, env=unconfigured())
            for url in urls
        ]
        hosts = list(
            dict.fromkeys(line(ran) for ran in parsed if ran.status == 0 and line(ran))
        )
        resolved = [(await self.ssh.ran("-G", "--", host)).text() for host in hosts]
        return [
            host
            for host, printed in zip(hosts, resolved, strict=True)
            if f"\nhostname {host}\n" not in f"\n{printed}"
        ]

    @lup.service
    async def checked(
        self, checking: Checking, by: Codebase | Agent | Operator | Machine
    ) -> Checked:
        """Check what's about to leave against the list of the project it's of, and say where each value withheld is in it, by its kind, never the value: the caller's own project, where it's a project's code, else the one it names.

        Raise `RefusedError` where the list can't be built, so nothing leaves.
        """
        repository = by.repository if isinstance(by, Codebase) else checking.repository
        if repository is None:
            message = "a check names the project it's of, where its caller isn't one of that project's parts"
            raise RefusedError(message)
        listed = await self.listed(repository)
        return Checked(
            places=[
                *(
                    place
                    for text in checking.texts
                    for place in self.in_text(text, listed)
                ),
                *(
                    place
                    for binary in checking.binaries
                    for place in self.in_binary(binary, listed)
                ),
            ]
        )

    def in_text(self, text: Text, listed: Listed) -> list[Place]:
        """Return each place in `text`, line by line, a value withheld is, and in prose each item's number cited where the list withholds them."""
        return [
            Place(
                within=text.within,
                line=each.number,
                column=at.column,
                what=said(at.held.kind),
                steer=steer(at.held.kind),
            )
            for each in text.lines
            for at in [
                *found(each.text, listed.held),
                *(numbered(each.text) if text.prose and listed.numbers else []),
            ]
        ]

    def in_binary(self, binary: Binary, listed: Listed) -> list[Place]:
        """Return each place in a file that isn't text where a value withheld is, by its byte."""
        return [
            Place(
                within=binary.within,
                byte=offset,
                what=said(held.kind),
                steer=steer(held.kind),
            )
            for held in listed.held
            for offset in counted(binary.content, held)
        ]
