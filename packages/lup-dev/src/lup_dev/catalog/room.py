"""The room's defaults: what every room's image starts from, its machine, its editors, and how its sessions run.

`Core` reads the machine and the sessions (`lup_dev.declaration.modules.core`;
`docs/launch.md`, *The image* and *The settings compiled for each runtime*), and a
project changes them as it changes any module's part, with a layer on `Core`. The
base and the editors are lup's, read by the launch (`lup_dev.launch`). A package
is named as Arch Linux's repositories name it, the room's image being Arch's.
"""

from datetime import date
from pathlib import Path
from typing import Literal

from lup.types import Model


class RoomBase(Model):
    """What every room's image starts from: Arch Linux's image, and the day of its archive the packages come from.

    The image and the archive's day are pinned together, so a build installs
    packages exactly as old as the base's own and upgrades none of the base's:
    the Arch Linux Archive's 2026-08-15 snapshot matched the image of 2026-08-16
    (`docs/field-notes.md`, *Rooms*), and a full upgrade against it found nothing
    to upgrade. Every package is at least as old as the pin, the minimum package
    age `DESIGN.md` asks for (*Policy*). Moving the pin is a release's decision,
    checked when it's chosen, since some days are missing from the archive
    (2026-08-16's `core.db` answers 404).
    """

    image: str = (
        "docker.io/library/archlinux:base-20260816.0.574111"
        "@sha256:4bf33b21a715aac0b48ce6e9eaed4782a898eae96f88f5da3635572129c2584a"
    )
    """Arch Linux's official image, by its dated tag and the digest of its index,
    so every build starts from the same files."""
    snapshot: date = date(2026, 8, 15)
    """The day of the Arch Linux Archive every package is installed from."""
    archive: str = "https://archive.archlinux.org/repos"
    """Where the Arch Linux Archive keeps each day's repositories."""
    locale: str = "en_US.UTF-8"
    """The locale generated in the image, beside the base's own `C.UTF-8`."""
    charmap: str = "UTF-8"
    """The character set the locale is generated with."""


class Group(Model):
    """Packages in the room's image for one reason."""

    why: str
    names: list[str]
    """Each package's name in Arch Linux's repositories."""


class StandardMachine(Model):
    """The packages every room has, whatever the host: `Core`'s default.

    Every agent meets the same machine: bash and the usual tools, and none of the
    operator's shell setup, since the runtimes run an agent's commands in the
    user's shell, aliases included. The set starts from the first lup's, which its
    sessions used for months, less three: bun, a project's own where it uses one;
    github-cli, since the room holds no GitHub login; and the virtual display behind
    the first lup's clipboard, which the host's clipboard replaced. To it are added
    what agents in rooms reached for and didn't find: `man`, `time` and `tmux`
    (`docs/field-notes.md`, *What agents reached for in rooms*).
    """

    groups: list[Group] = [
        Group(
            why="the shell and the usual tools, the same in every room",
            names=[
                "bash",
                "coreutils",
                "findutils",
                "grep",
                "sed",
                "gawk",
                "diffutils",
                "file",
                "which",
                "less",
                "tree",
                "procps-ng",
                "util-linux",
                "lsof",
                "inetutils",
                "tzdata",
            ],
        ),
        Group(
            why=(
                "an agent's everyday work: version control, fetching over HTTPS, "
                "reading JSON and YAML, searching files"
            ),
            names=[
                "git",
                "curl",
                "ca-certificates",
                "openssh",
                "jq",
                "go-yq",
                "ripgrep",
                "fd",
            ],
        ),
        Group(
            why=(
                "searching code by its syntax rather than its text, and applying "
                "or unpacking what an agent downloads: a patch, a zip archive"
            ),
            names=["ast-grep", "patch", "unzip", "zip"],
        ),
        Group(
            why=(
                "measuring and debugging: timing a command properly, a command's "
                "peak memory through `/usr/bin/time`, arithmetic in the shell, "
                "tracing what a process does, waiting on a file to change rather "
                "than polling it"
            ),
            names=["hyperfine", "time", "bc", "strace", "inotify-tools"],
        ),
        Group(
            why=(
                "reads a program's manual with `man`, as `git help` does: the image "
                "keeps every package's English man pages, and indexes them"
            ),
            names=["man-db"],
        ),
        Group(
            why="the manual of Linux's system calls and C library",
            names=["man-pages"],
        ),
        Group(
            why=(
                "runs a program that needs a terminal and drives it from commands, "
                "as `git add -p` needs"
            ),
            names=["tmux"],
        ),
        Group(
            why=(
                "`sqlite3`, to read a SQLite database by hand; the base has it "
                "already, for its own libraries"
            ),
            names=["sqlite"],
        ),
        Group(why="runs a project's Makefile", names=["make"]),
        Group(why="runs a script outside a project's environment", names=["python"]),
        Group(
            why="carries each hook event from the room to lup's host service",
            names=["socat"],
        ),
        Group(
            why="renders a PDF's pages with `pdftoppm`, as a runtime's file reader does",
            names=["poppler"],
        ),
        Group(
            why="one font family, so anything that renders text finds a face",
            names=["ttf-liberation"],
        ),
        Group(
            why="the editors Ctrl+G opens as `$EDITOR`, whichever the operator uses",
            names=["vim", "neovim", "nano", "emacs-nox", "helix"],
        ),
    ]
    """The packages, each group with its reason, which each of its packages carries."""


class Editor(Model):
    """An editor of the standard machine, and where the operator keeps its configuration."""

    programs: list[str]
    """The names `$EDITOR` or `$VISUAL` may give it by, as a program's name or a
    path's last part."""
    configuration: list[Path]
    """Its configuration, from the operator's home."""


class Editors(Model):
    """The standard machine's editors, whose configuration a room mounts read-only for the one the operator names.

    Ctrl+G opens `$EDITOR` in the room, so it opens as the operator knows it
    (`docs/launch.md`, *The mounts*). Only what exists on the host is mounted.
    Each program is one the image installs: Arch's helix installs `helix`, not
    upstream's `hx`, and its vim installs no `vi`.
    """

    editors: list[Editor] = [
        Editor(
            programs=["vim", "vimdiff", "rvim"],
            configuration=[Path(".vimrc"), Path(".vim"), Path(".config/vim")],
        ),
        Editor(programs=["nvim"], configuration=[Path(".config/nvim")]),
        Editor(
            programs=["nano", "rnano"],
            configuration=[Path(".nanorc"), Path(".config/nano")],
        ),
        Editor(
            programs=["emacs", "emacsclient"],
            configuration=[Path(".emacs"), Path(".emacs.d"), Path(".config/emacs")],
        ),
        Editor(programs=["helix"], configuration=[Path(".config/helix")]),
    ]


type CacheLifetime = Literal["5m", "1h"]
"""How long a prompt's cache lasts: the model API offers 5 minutes or an hour."""


class SessionDefaults(Model):
    """How every session runs unless the person's own runtime settings or the project say otherwise: `Core`'s session.

    In neutral terms, which each runtime's adapter spells (`docs/launch.md`,
    *The settings compiled for each runtime*). A person's own settings outrank these, and a field the
    project's declaration sets outranks theirs.
    """

    subagent_cache: CacheLifetime = "1h"
    """How long the prompt cache of a session's subagents lasts: an hour, as the
    main conversation's does on a subscription, so a worker that waits a while
    doesn't pay to rebuild its context. Theirs is 5 minutes otherwise."""
    auto_memory: bool = False
    """Whether a runtime keeps its own memory across sessions: off, so every
    session starts from what the repository and its guidance say, and one
    session's notes don't steer another unseen."""
    idle_compaction: bool = False
    """Whether a runtime compacts a long conversation while the session sits
    idle: off, so a session left waiting, on the operator or on a hold, comes
    back to its conversation as it was rather than to a summary made
    meanwhile. Compaction when the context fills stays the runtime's own: off,
    a full session would stop."""
    removed_tools: list[str] = [
        "Artifact",
        "SendFeedback",
        "Workflow",
        "ScheduleWakeup",
        "ReportFindings",
        "EnterWorktree",
        "ExitWorktree",
    ]
    """A runtime's built-in tools removed from a session's context, by name.

    - `Artifact`, `SendFeedback`, `Workflow`, `ScheduleWakeup` and
      `ReportFindings` weigh in every turn and go unused in lup's sessions: an
      interactive session carries 113 KB of built-in tool schemas, `Artifact`
      alone 55 KB;
    - `EnterWorktree` and `ExitWorktree` are the native worktree tools: a
      worktree for another agent's work is lup's spawn's to make (#117), and a
      session makes its own with git.

    The native messaging tools (`SendMessage`, `ListAgents`) stay until lup's
    spawn exists, with the native `Agent`: a session resumes a subagent it
    started through `SendMessage`, so removing them alone would strand one.

    A runtime that can't remove a built-in tool by name removes none, and its
    adapter says so.
    """
    account_connectors: bool = False
    """Whether a session fetches the connectors the operator's account brings
    with its login: off. Their tools reach the operator's mail and files (the
    spike's account carried a file store's share and trash tools), so a room
    fetches none unless the project turns them on."""
