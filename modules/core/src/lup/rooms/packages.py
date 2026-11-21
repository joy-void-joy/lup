"""The packages a session's room holds: the standard machine every room has, and what each module adds, each with why.

A package is named as Arch Linux's repositories name it, the room's image being
Arch's. Any module may declare the packages its sessions need, a `Packages`
field, which every layer can add to or drop from as it would any selection:
`Packages.of(Package(name="pnpm", why="installs the page's packages"))`.
"""

from typing import override

from lup.declaration.grammar import Named
from lup.types import Model


class Package(Model):
    """A package a room holds, as Arch Linux's repositories name it, and why it's there."""

    name: str
    why: str


class Packages(Named[Package]):
    """The packages a module's sessions need in their room, each by its name."""

    @override
    def named(self, entry: Package) -> str:
        return entry.name


def standard() -> list[Package]:
    """Return the packages every room has, whatever the host: the same machine for every agent, bash and the usual tools and none of the operator's shell setup.

    The second lup's standard machine, which its sessions used for months, with
    what agents reached for in rooms and didn't find (`man`, `time`, `tmux`), and
    `uv` and the editor anybody at the keyboard can use.
    """
    return [
        Package(
            name="bash", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="coreutils",
            why="the shell and the usual tools, the same in every room",
        ),
        Package(
            name="findutils",
            why="the shell and the usual tools, the same in every room",
        ),
        Package(
            name="grep", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="sed", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="gawk", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="diffutils",
            why="the shell and the usual tools, the same in every room",
        ),
        Package(
            name="file", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="which", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="less", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="tree", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="procps-ng",
            why="the shell and the usual tools, the same in every room",
        ),
        Package(
            name="util-linux",
            why="the shell and the usual tools, the same in every room",
        ),
        Package(
            name="lsof", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="inetutils",
            why="the shell and the usual tools, the same in every room",
        ),
        Package(
            name="tzdata", why="the shell and the usual tools, the same in every room"
        ),
        Package(
            name="git",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="curl",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="ca-certificates",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="openssh",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="jq",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="go-yq",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="ripgrep",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="fd",
            why="an agent's everyday work: version control, fetching over HTTPS, reading JSON and YAML, searching files",
        ),
        Package(
            name="ast-grep",
            why="searching code by its syntax, and applying or unpacking what an agent downloads",
        ),
        Package(
            name="patch",
            why="searching code by its syntax, and applying or unpacking what an agent downloads",
        ),
        Package(
            name="unzip",
            why="searching code by its syntax, and applying or unpacking what an agent downloads",
        ),
        Package(
            name="zip",
            why="searching code by its syntax, and applying or unpacking what an agent downloads",
        ),
        Package(
            name="hyperfine",
            why="measuring and debugging: timing a command, its peak memory, arithmetic in the shell, tracing a process, waiting on a file",
        ),
        Package(
            name="time",
            why="measuring and debugging: timing a command, its peak memory, arithmetic in the shell, tracing a process, waiting on a file",
        ),
        Package(
            name="bc",
            why="measuring and debugging: timing a command, its peak memory, arithmetic in the shell, tracing a process, waiting on a file",
        ),
        Package(
            name="strace",
            why="measuring and debugging: timing a command, its peak memory, arithmetic in the shell, tracing a process, waiting on a file",
        ),
        Package(
            name="inotify-tools",
            why="measuring and debugging: timing a command, its peak memory, arithmetic in the shell, tracing a process, waiting on a file",
        ),
        Package(name="man-db", why="a program's manual, as `git help` reads it"),
        Package(name="man-pages", why="a program's manual, as `git help` reads it"),
        Package(
            name="tmux", why="a program that needs a terminal, driven from commands"
        ),
        Package(name="sqlite", why="a SQLite database read by hand"),
        Package(name="make", why="a project's Makefile"),
        Package(name="python", why="a script outside a project's environment"),
        Package(name="uv", why="a project's Python environment, and its tools"),
        Package(name="gcc", why="Python's C extensions built from source"),
        Package(
            name="poppler",
            why="a PDF's pages rendered, as a runtime's file reader does",
        ),
        Package(
            name="ttf-liberation",
            why="one font family, so anything rendering text finds a face",
        ),
        Package(name="nano", why="one editor anybody at the keyboard can use"),
    ]
