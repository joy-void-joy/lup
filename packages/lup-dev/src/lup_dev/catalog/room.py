"""The room's defaults: the machine every room starts from, and how its sessions run.

`Core` reads both (`lup_dev.declaration.modules.core`; `docs/launch.md`, *The
image* and *The settings compiled for each runtime*), and a project changes them
as it changes any module's part, with a layer on `Core`. A package is named as
Arch Linux's repositories name it, the room's image being Arch's.
"""

from typing import Literal

from lup.types import Model


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
    the first lup's clipboard, which waits for the clipboard's own piece.
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


type CacheLifetime = Literal["5m", "1h"]
"""How long a prompt's cache lasts: the model API offers 5 minutes or an hour."""


class SessionDefaults(Model):
    """How every session runs unless the project says otherwise: `Core`'s session.

    In neutral terms, which each runtime's adapter spells (`DESIGN.md`,
    *Sessions*).
    """

    subagent_cache: CacheLifetime = "1h"
    """How long the prompt cache of a session's subagents lasts: an hour, as the
    main conversation's does on a subscription, so a worker that waits a while
    doesn't pay to rebuild its context. Theirs is 5 minutes otherwise."""
    auto_memory: bool = False
    """Whether a runtime keeps its own memory across sessions: off, so every
    session starts from what the repository and its guidance say, and one
    session's notes don't steer another unseen."""
    removed_tools: list[str] = [
        "Artifact",
        "SendFeedback",
        "Workflow",
        "ScheduleWakeup",
        "ReportFindings",
        "EnterWorktree",
        "ExitWorktree",
        "SendMessage",
        "ListAgents",
    ]
    """A runtime's built-in tools removed from a session's context, by name.

    - `Artifact`, `SendFeedback`, `Workflow`, `ScheduleWakeup` and
      `ReportFindings` weigh in every turn and go unused in lup's sessions: an
      interactive session carries 113 KB of built-in tool schemas, `Artifact`
      alone 55 KB;
    - `EnterWorktree`, `ExitWorktree`, `SendMessage` and `ListAgents` are the
      native worktree and messaging tools, which `DESIGN.md` denies in favour of
      lup's own (*Sessions*).

    A runtime that can't remove a built-in tool by name removes none, and its
    adapter says so.
    """
