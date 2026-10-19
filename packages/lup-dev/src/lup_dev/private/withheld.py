"""The values never published from a repository: the details lup reads on the host, and the person's own.

`docs/private.md`. A launch builds the list on the host from the declaration at
the approved commit (`built`), and keeps it in the `Private` module's own data
directory for the repository (`kept`), which no room mounts: the judge, the
module's hooks and its handler, and the gate on the host read it there. What a
room ever hears of it is a kind and a place, never a value (`Said`).

The details, each read on the host through `Facts`, which tests stub:
- `home`: the operator's home, as the account database has it, and where it
  resolves where that differs;
- `user`: their user name;
- `hostname`: the machine's name;
- `alias`: each host a URL of the repository's remotes names (as its `config`
  writes it and as git rewrites it, `git url-parse -c host`) that ssh's
  configuration resolves to another name: an alias of the operator's;
- `repository-path`: the project's own repository (its git directory, its main
  worktree, the tree a room mounts) and each related repository, by its path on
  the host, each also as `~/…` where it's under the home;
- `private-repository`: each related repository GitHub says is private or
  internal, or that has no copy there, by its name, and by its `owner/name` and
  name on GitHub where it has one. GitHub is asked at each launch; where it
  can't answer, its answer at the last launch stands, and a repository it never
  answered for is left out, said.

The person's own values are plain strings, given in their own layer
(`lup_project.local.py`), which git ignores: one written in a committed
declaration is published by its commit.
"""

import asyncio
import os
import pwd
import socket
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, get_args, override

from lup.programs import ProgramError, run
from lup.types import Model
from lup_dev.forge.github import GitHubError, Visibility, visibility
from lup_dev.git import Git
from lup_dev.host.protocol import GitHubRepository

type Detail = Literal[
    "home", "user", "hostname", "alias", "repository-path", "private-repository"
]
"""A kind of detail lup reads on the host, each never published."""

type Kind = Detail | Literal["value"]
"""What a value never published is: a detail of the host's, or one of the
person's own."""

DETAILS: list[Detail] = list(get_args(Detail.__value__))
"""Every detail lup reads, in the order a refusal prefers them."""


class Said(Model):
    """What a refusal or a finding says of a value of one kind: never the value."""

    what: str
    steer: str


def said(kind: Kind) -> Said:
    """Say what a value of `kind` is, and how it's written instead.

    >>> said("home").what
    "the operator's home path"
    """
    match kind:
        case "home":
            return Said(
                what="the operator's home path",
                steer="write it as `~`, or a path in the repository from its root",
            )
        case "user":
            return Said(
                what="the operator's user name",
                steer="leave it out, or write `<user>`",
            )
        case "hostname":
            return Said(what="the host's name", steer="leave it out, or write `<host>`")
        case "alias":
            return Said(
                what="an SSH alias in the repository's remote",
                steer="leave it out, or write `<alias>`; GitHub's own host is `github.com`",
            )
        case "repository-path":
            return Said(
                what="a repository's path on the host",
                steer=(
                    "write a path in this repository from its root, and another "
                    "repository by its name, as your guidance gives it"
                ),
            )
        case "private-repository":
            return Said(
                what="the name of a repository that isn't public",
                steer=(
                    "leave it out of what's published: GitHub says it's private, or "
                    "it has no copy there"
                ),
            )
        case "value":
            return Said(
                what="one of the operator's private values",
                steer=(
                    "leave it out of what's published; the operator, who listed it, "
                    "knows which it is"
                ),
            )


class Held(Model):
    """One value never published, and what it is."""

    kind: Kind
    text: str


class Seen(Model):
    """GitHub's word on who reads a repository, kept for a launch it can't answer."""

    repository: str
    """`owner/name`."""
    visibility: Visibility


class Withheld(Model):
    """The values never published from one repository, as a launch built them on the host."""

    held: list[Held] = []
    """Each value, the longest first, none twice."""
    seen: list[Seen] = []
    """GitHub's last word on each related repository it has a copy of."""


def kept(data: Path) -> Path:
    """Say where the list is kept in the `Private` module's own data directory for the repository, `data`."""
    return data / "withheld.json"


class Machine(Model):
    """What the host's account database and kernel say of the operator and the machine."""

    home: Path
    user: str
    hostname: str


class Facts(ABC):
    """What lup asks the host to build the list: the machine, ssh's configuration, and GitHub."""

    @abstractmethod
    def machine(self) -> Machine:
        """Return the operator's home and user name, and the machine's name."""

    @abstractmethod
    def resolved(self, host: str) -> str | None:
        """Return the name ssh's configuration connects to for `host`; none where ssh can't say."""

    @abstractmethod
    async def visibility(
        self, directory: Path, repository: GitHubRepository
    ) -> Visibility:
        """Say who GitHub lets read `repository`, asked from the git directory `directory`.

        Raise `GitHubError` where GitHub can't be asked.
        """


class HostFacts(Facts):
    """The host's own: the account database, the kernel, `ssh -G`, and `gh`."""

    @override
    def machine(self) -> Machine:
        entry = pwd.getpwuid(os.getuid())
        return Machine(
            home=Path(entry.pw_dir), user=entry.pw_name, hostname=socket.gethostname()
        )

    @override
    def resolved(self, host: str) -> str | None:
        """Read `ssh -G`'s `hostname` line for `host`, its lines read word by word."""
        try:
            printed = run("ssh", "-G", "--", host).output.decode()
        except ProgramError:
            return None
        named = [
            words[1]
            for line in printed.splitlines()
            if len(words := line.split()) == 2 and words[0] == "hostname"
        ]
        return next(iter(named), None)

    @override
    async def visibility(
        self, directory: Path, repository: GitHubRepository
    ) -> Visibility:
        return await visibility(directory, repository)


class Neighbour(Model):
    """A related repository, as a launch found it on the host."""

    name: str
    path: Path
    """Absolute and resolved."""
    github: str | None
    """Its `owner/name` on GitHub, where its entry gives one."""


class Built(Model):
    """The list a launch built, and what it says in the operator's terminal of what it couldn't read."""

    withheld: Withheld
    notes: list[str] = []


def remote_hosts(git: Git) -> list[str]:
    """Return each host a URL of the repository's remotes names, as its `config` writes it and as git rewrites it."""
    remotes = git.run("remote").output.decode().splitlines()

    def urls(remote: str) -> list[str]:
        asked = [
            ["config", "--local", "--get-all", f"remote.{remote}.url"],
            ["config", "--local", "--get-all", f"remote.{remote}.pushurl"],
            ["remote", "get-url", "--all", remote],
            ["remote", "get-url", "--push", "--all", remote],
        ]
        return [
            url
            for words in asked
            for url in git.run(*words, ok=[0, 1, 2]).output.decode().splitlines()
        ]

    def host(url: str) -> str | None:
        parsed = git.run("url-parse", "-c", "host", "--", url, ok=[0, 128])
        return parsed.output.decode().strip() or None if parsed.status == 0 else None

    every = [
        found for remote in remotes for url in urls(remote) if (found := host(url))
    ]
    return list(dict.fromkeys(every))


def tilded(path: Path, home: Path) -> list[str]:
    """Return `path`, and `~/…` where it's under `home`.

    >>> tilded(Path("/home/op/src/demo.git"), Path("/home/op"))
    ['/home/op/src/demo.git', '~/src/demo.git']
    """
    if path.is_relative_to(home) and path != home:
        return [str(path), f"~/{path.relative_to(home)}"]
    return [str(path)]


class Answer(Model):
    """GitHub's word on one repository at a launch, or the last launch's where it gave none, and what's said of it."""

    seen: Seen | None = None
    note: str | None = None


def answered(
    repository: GitHubRepository,
    answer: Visibility | BaseException,
    last: Withheld | None,
) -> Answer:
    """Read GitHub's answer on `repository`: where it couldn't answer, its word at the last launch stands, said."""
    named = str(repository)
    match answer:
        case "public" | "private" | "internal":
            return Answer(seen=Seen(repository=named, visibility=answer))
        case GitHubError():
            earlier = [
                each for each in (last.seen if last else []) if each.repository == named
            ]
            if not earlier:
                note = (
                    f"GitHub didn't say whether `{named}` is public ({answer}): its "
                    "name isn't checked until it does"
                )
                return Answer(note=note)
            [kept_answer] = earlier
            note = (
                f"GitHub didn't say whether `{named}` is public ({answer}): its word "
                f"at the last launch, {kept_answer.visibility}, stands"
            )
            return Answer(seen=kept_answer, note=note)
        case BaseException():
            raise answer


def private_names(related: list[Neighbour], seen: list[Seen]) -> list[str]:
    """Name each related repository that isn't public: one GitHub says is private or internal, or one with no copy there; by its name, and by its `owner/name` and name on GitHub.

    >>> private_names([Neighbour(name="atlas", path=Path("/x"), github=None)], [])
    ['atlas']
    """
    hidden = [each.repository for each in seen if each.visibility != "public"]

    def names(neighbour: Neighbour) -> list[str]:
        if neighbour.github is None:
            return [neighbour.name]
        if neighbour.github not in hidden:
            return []
        on_github = GitHubRepository.read(neighbour.github)
        return [neighbour.name, neighbour.github, on_github.name]

    return [name for neighbour in related for name in names(neighbour)]


async def built(
    facts: Facts,
    repository: Path,
    *,
    own: list[Path],
    related: list[Neighbour],
    details: list[Detail],
    values: list[str],
    last: Withheld | None,
) -> Built:
    """Build the list of values never published from the repository whose git directory is `repository`.

    `own` are the project's own repository's paths, `related` the other
    repositories the declaration names, `details` the kinds read on the host,
    `values` the person's own, and `last` the list the last launch built, whose
    GitHub answers stand where GitHub gives none at this one.
    """
    machine = facts.machine()
    homes = list(dict.fromkeys([machine.home, machine.home.resolve()]))
    hosts = remote_hosts(Git.pinned(repository)) if "alias" in details else []
    aliases = [
        host
        for host in hosts
        if (resolved := facts.resolved(host)) is not None
        and resolved.casefold() != host.casefold()
    ]
    paths = [
        each
        for path in [*own, *(neighbour.path for neighbour in related)]
        for form in list(dict.fromkeys([path, path.resolve()]))
        for each in tilded(form, machine.home)
    ]
    wanted = "private-repository" in details
    on_github = [
        GitHubRepository.read(neighbour.github)
        for neighbour in related
        if neighbour.github is not None and wanted
    ]
    answers = await asyncio.gather(
        *(facts.visibility(repository, each) for each in on_github),
        return_exceptions=True,
    )
    read = [
        answered(each, answer, last)
        for each, answer in zip(on_github, answers, strict=True)
    ]
    seen = [each.seen for each in read if each.seen is not None]
    named = private_names(related, seen) if wanted else []
    candidates: list[Held] = [
        *(Held(kind="home", text=str(home)) for home in homes if "home" in details),
        *([Held(kind="user", text=machine.user)] if "user" in details else []),
        *(
            [Held(kind="hostname", text=machine.hostname)]
            if "hostname" in details
            else []
        ),
        *(Held(kind="alias", text=alias) for alias in aliases),
        *(
            Held(kind="repository-path", text=path)
            for path in paths
            if "repository-path" in details
        ),
        *(Held(kind="private-repository", text=name) for name in named),
        *(Held(kind="value", text=value.strip()) for value in values),
    ]
    held = [each for each in candidates if each.text.strip()]
    folded = [each.text.casefold() for each in held]
    once = [
        each for at, each in enumerate(held) if folded.index(each.text.casefold()) == at
    ]
    longest = sorted(once, key=lambda each: -len(each.text))
    notes = [each.note for each in read if each.note is not None]
    return Built(withheld=Withheld(held=longest, seen=seen), notes=notes)
