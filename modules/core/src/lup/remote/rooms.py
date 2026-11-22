"""What a session's room is given for its git to push and fetch through `remote`: its git configuration, sending each of the repository's remotes through `git-remote-lup`, and that helper, on its `PATH`.

The machine writes both among the session's own files, which the room mounts
read-only (`lup/rooms/README.md`), as a room starts.
"""

import asyncio
import shlex
from pathlib import Path

from lup.doors.parts import Program
from lup.programs.git.answers import nul_separated
from lup.programs.git.running import Git, unconfigured
from lup.programs.git.stores import Store


async def configured(store: Store, file: Path, through: Program | None = None) -> None:
    """Write to `file` the git configuration of a room of the repository whose store is `store`.

    Each URL its `config` gives a remote, to fetch or push, is rewritten to
    `lup::<url>`, so git runs `git-remote-lup` for it: the repository's own
    remotes alone, so a room still clones or fetches anything else as it would
    with nobody's credentials. A push names the current branch where it names
    none (`push.default`), and no upstream is recorded (`branch.autoSetupMerge`),
    since a room can't write `config`. Raise `GitError` where git can't.
    """
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
    await asyncio.to_thread(file.write_text, "")
    git = Git(through=through)
    settings = [
        *(("--add", f"url.lup::{url}.insteadOf", url) for url in dict.fromkeys(urls)),
        ("push.default", "current"),
        ("branch.autoSetupMerge", "false"),
    ]
    for setting in settings:
        await git.done("config", "--file", str(file), *setting, env=unconfigured())


def launcher(python: Path) -> str:
    """Return `git-remote-lup` for a room: a script running the helper on the machine's own lup, its `python` mounted at its own path, as the room's hooks run.

    >>> print(launcher(Path("/srv/lup/bin/python")), end="")
    #!/bin/sh
    exec /srv/lup/bin/python -I -m lup.environment.remote "$@"
    """
    command = shlex.join([str(python), "-I", "-m", "lup.environment.remote"])
    return f'#!/bin/sh\nexec {command} "$@"\n'
