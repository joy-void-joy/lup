"""The maintaining session's room, from a resolved declaration and the worktree it's launched in.

A `lup.rooms.Container` on the host's network, its image the declaration's
(`launch/images.py`), with these mounted, each at its host path (`docs/launch.md`,
*The mounts*):
- the repository as one tree, read-write: its git directory and every worktree,
  so `git worktree add` and `remove` work as on the host, and an agent reads any
  other worktree it's pointed at. The tree is the nearest directory holding them
  all; one that would hold the operator's home is refused, since the whole of it
  would be writable;
- the git directory's `config` and `hooks/` read-only over it: they run on the
  host, so a hook or a `core.fsmonitor` written there would run at the
  operator's next git command. `hooks/` is made if it's missing, so the room
  can't make it;
- what the project's runner needs for its environment (`Runner.room`);
- pyright's source in lup's cache, read-write, which the gate builds the engine
  from. Only that part: the cache holds the CLIs rooms run, which a room
  mustn't rewrite;
- the configuration of the editor `$EDITOR` or `$VISUAL` names, read-only, where
  it exists, so Ctrl+G opens it as the operator knows it;
- `/etc/localtime`, read-only, so the room's clock reads in the operator's zone.

Its variables are the runner's, the git identity, read from the host's git as
`GIT_AUTHOR_*` and `GIT_COMMITTER_*` since `~/.gitconfig` isn't mounted, the
terminal's (`TerminalVariables`), and `XDG_CACHE_HOME` as the host's lup has it
(`Layout.cache`'s parent), so the engine's build in the room finds pyright's
source where it's mounted: the build takes the path from the same layout. What
the launch adds is the terminal compile's
and the launch command's: the launch's directory, its socket directory, the CLI
and the runtime's home.

The environment's interpreter must resolve under the room's mounts, or the room
refuses with the runner's remedy: without it, `uv run` in the room set about
remaking the shared `.venv` (`docs/launch.md`, *The project's environment,
shared with the host*). A system interpreter is outside every mount.
"""

from pathlib import Path
from shlex import split
from typing import TYPE_CHECKING

from lup.rooms.container import Container, Image, Mount
from lup.types import Model
from lup_dev.catalog.room import Editors, RoomBase
from lup_dev.declaration.requirements import Needed, Requirement
from lup_dev.errors import LupDevError
from lup_dev.forge.github import PROGRAM
from lup_dev.git import Git, nul_separated
from lup_dev.launch.images import definition
from lup_dev.layout import LOCALTIME

if TYPE_CHECKING:
    from lup_dev.declaration.requirements import Tools
    from lup_dev.declaration.resolve import Resolved
    from lup_dev.declaration.runner import Interpreter
    from lup_dev.layout import Layout
    from lup_dev.settings import TerminalVariables


class RoomError(LupDevError):
    """A room the declaration and the machine can't make as they stand."""


def host_needs() -> list[Needed]:
    """Return what the host needs to run a room, as requirements checked at once.

    Podman, rootless; and, optional, `gh`, without which lup's GitHub tools and
    the gate's issue states in a room are off, and `notify-send`, without which
    the inbox raises no desktop notice.
    """
    podman = Requirement(
        tool="podman",
        why="runs each session's room, rootless",
        install="your system's `podman` package, set up for rootless containers",
    )
    gh = Requirement(
        tool=PROGRAM,
        optional=True,
        why=(
            "reaches GitHub with your login for lup's GitHub tools, and for the "
            "gate's issue states in a room"
        ),
        install="your system's `github-cli` package, then `gh auth login`",
    )
    notices = Requirement(
        tool="notify-send",
        optional=True,
        why="raises a desktop notice when something reaches your inbox",
        install="your system's `libnotify` package",
    )
    return [
        Needed(module="lup-dev launch", requirement=podman),
        Needed(module="lup-dev launch", requirement=gh),
        Needed(module="lup-dev inbox", requirement=notices),
    ]


class Repository(Model):
    """A repository as a room mounts it."""

    git: Path
    """Its git directory, which every worktree shares (`git rev-parse --git-common-dir`)."""
    worktrees: list[Path]
    """Each worktree's root that exists, as `git worktree list` gives it; a bare
    repository's own directory among them."""
    main: Path
    """The main worktree, which `git worktree list` gives first: a clone's root, or
    a bare repository's own directory. The runtimes ask about it for a linked
    worktree, so a launch trusts it too."""
    tree: Path
    """The nearest directory holding the git directory and every worktree, mounted whole."""


def repository(worktree: Path) -> Repository:
    """Return the repository of the worktree at `worktree`, and the tree a room mounts for it.

    Raise `RoomError` where that tree would hold the operator's home.
    """
    git = Git(cwd=worktree)
    common = Path(git.text("rev-parse", "--path-format=absolute", "--git-common-dir"))
    listed = git.run("worktree", "list", "--porcelain", "-z").stdout
    roots = [
        Path(field.removeprefix("worktree "))
        for field in nul_separated(listed)
        if field.startswith("worktree ")
    ]
    present = [root for root in roots if root.exists()]
    tree = next(
        each
        for each in [common, *common.parents]
        if all(root.is_relative_to(each) for root in present)
    )
    home = Path.home()
    if home.is_relative_to(tree):
        places = ", ".join(str(each) for each in [common, *present])
        message = (
            f"The repository's git directory and worktrees ({places}) meet only at "
            f"{tree}, which holds your home ({home}): a room mounts them as one "
            "tree, read-write, and this one would hold everything under it. Keep "
            "the worktrees under one directory with the git directory "
            "(`git worktree move`), and launch again"
        )
        raise RoomError(message)
    [main, *_] = roots
    return Repository(git=common, worktrees=present, main=main, tree=tree)


def maintaining_room(
    resolved: Resolved,
    worktree: Path,
    layout: Layout,
    terminal: TerminalVariables,
    tools: Tools,
) -> Container:
    """Return the maintaining session's room for the worktree at `worktree`.

    `tools` is how the runner asks the host where its environment's parts are;
    a test stubs it. Raise `RoomError` where the repository's tree would hold
    the operator's home, where `$EDITOR` or `$VISUAL` isn't a command line, or
    where the environment's interpreter doesn't resolve under the room's mounts.
    """
    home = Path.home()
    held = repository(worktree)
    git = Git(cwd=worktree)
    needs = resolved.runner.room(worktree, tools)

    def configured(key: str) -> str | None:
        found = git.run("config", "--get", key, ok=[0, 1])
        return found.stdout.decode().strip() if found.exit_code == 0 else None

    def editors() -> list[Mount]:
        named = [command for command in [terminal.editor, terminal.visual] if command]
        try:
            programs = [Path(words[0]).name for words in map(split, named) if words]
        except ValueError as failed:
            message = (
                f"`$EDITOR` or `$VISUAL` isn't a command line ({failed}), so lup "
                "can't tell which editor's configuration the room mounts"
            )
            raise RoomError(message) from failed
        configuration = dict.fromkeys(
            home / path
            for editor in Editors().editors
            if any(program in editor.programs for program in programs)
            for path in editor.configuration
        )
        return [
            Mount(source=path, read_only=True)
            for path in configuration
            if path.exists()
        ]

    def reached(interpreter: Interpreter, mounts: list[Mount]) -> None:
        resolved_path = interpreter.path.resolve()
        inside = any(
            resolved_path.is_relative_to(mount.source.resolve()) for mount in mounts
        )
        if inside and resolved_path.is_file():
            return
        where = (
            "outside every mount of the room, as a system interpreter is"
            if resolved_path.is_file()
            else "and isn't there"
        )
        message = (
            f"The project's environment runs on {interpreter.path}, which resolves "
            f"to {resolved_path}, {where}: in the room the environment would have "
            "no interpreter, and its tools would set about remaking the "
            f"environment the host shares. To launch, {interpreter.remedy}"
        )
        raise RoomError(message)

    hooks = held.git / "hooks"
    hooks.mkdir(exist_ok=True)
    pyright = layout.pyright_source
    pyright.mkdir(parents=True, exist_ok=True)
    mounts = [
        Mount(source=held.tree),
        Mount(source=held.git / "config", read_only=True),
        Mount(source=hooks, read_only=True),
        *needs.mounts,
        Mount(source=pyright),
        *editors(),
        *([Mount(source=LOCALTIME, read_only=True)] if LOCALTIME.exists() else []),
    ]
    if needs.interpreter is not None:
        reached(needs.interpreter, mounts)
    name = configured("user.name")
    email = configured("user.email")
    identity = {
        **(
            {}
            if name is None
            else {"GIT_AUTHOR_NAME": name, "GIT_COMMITTER_NAME": name}
        ),
        **(
            {}
            if email is None
            else {"GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email}
        ),
    }
    return Container(
        image=Image(
            definition=definition(resolved.packages, RoomBase()),
            project=str(held.git),
        ),
        mounts=[*mounts],
        env={
            **needs.env,
            **identity,
            **terminal.passed(),
            "XDG_CACHE_HOME": str(layout.cache.parent),
        },
        network="host",
    )
