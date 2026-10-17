# A worktree's links, and the host's git

A room writes the repository's git directory, all but `config` and `hooks/` (`docs/launch.md`, *The mounts*), and every worktree. Among what it writes are the files telling git which git directory a worktree belongs to, and so which `config` it reads: a room can aim the host's next git at a `config` of its own, whose `core.sshCommand`, `core.fsmonitor`, `core.hooksPath`, pager or filter then runs with the operator's hands (#54). What's built pins the host's git where it runs in the git directory; the check of each worktree's links, for git that finds its directory through a worktree, isn't built.

## What we have

Paths are under `packages/lup-dev/src/lup_dev/` unless they name another package.

### The files that redirect git

All room-writable:
- a linked worktree's `.git` file, `gitdir: <path>`;
- `<git dir>/worktrees/<name>/commondir`, with `gitdir` beside it, the path back to the common directory;
- a `commondir` at the top of the common git directory itself, which a bare common directory never has: git told the directory by `--git-dir`, `-C` or `GIT_DIR` alone, or run inside it, follows that file to the git directory it names and reads that one's `config`. Only `GIT_DIR` and `GIT_COMMON_DIR` set together resist it (`docs/field-notes.md`, *Host-side git in a repository the room writes*, on git 2.55.0).

A clone's `.git` could be moved aside and replaced under the tree's mount, so the room mounts it on its own, which a move can't shift (`launch/room.py`). `safe.directory` is no backstop: under `--userns=keep-id` the room's files are the operator's (field notes, same section).

### Pinned where git runs in the git directory

`git.py`: `pinning(common)` puts `env GIT_DIR=<common> GIT_COMMON_DIR=<common>` before the program, and `Git.pinned(common)` runs git that way, so the only `config` of the repository's it reads is the common directory's own. It goes through `env` since `sh` and asyncio replace a program's environment whole where they're given one. Pinned:
- the remote helper's host side, pushes and fetches (`remote/protocol.py`, `Remotes.git`);
- `gh` and every GitHub tool (`forge/github.py`), whose git inherits the pin;
- the room's git configuration, read from the repository's `config` (`remote/config.py`, `room_config`; `launch/room.py`, `room_git`);
- the main worktree read from a registered repository (`cli.py`, `proposed_after` and `acted_on`), and the worktrees the transcripts module copies records for (`packages/lup/src/lup/transcripts/hooks.py`).

`proposed_after`, asking trust's approval after a push moved the integration branch, also skips a repository holding a `commondir` at its top, saying so in the service's log, since trust then reads it unpinned. `Git`'s runner turns off `core.fsmonitor` and hooks for every git (`core.hooksPath=/dev/null`), not `core.sshCommand`, a pager or filters; `Remotes.git` keeps `core.sshCommand` as the repository's read-only `config` sets it, which pinned is the only one read.

### Where the host's git still finds its directory through a worktree

Each of these runs `Git(cwd=<worktree>)` and lets git find the git directory through the worktree's `.git`, so a redirected link misleads it:
- trust on launch (`launch/trust.py`), and the launch itself (`cli.py`, `launched`), whose `rev-parse --git-common-dir` becomes the registration's `repository`: the directory every pinned git above trusts;
- `launch/room.py` (`repository`, and through it `related` and `maintaining_room`, which also reads `user.name` and `user.email` there), `launch/session.py` (`approved_declaration`), `declaration/load.py` (`person_layer`);
- the judge: `policy/worktrees.py` (`place`), `policy/store.py` (`Store.repository`), `policy/checkpoint.py` (`Worktree.at`), `policy/holds.py` (`answer`);
- the command line's own (`cli.py`: `toplevel`, `scanned`, `rules_check`, `verdicts`).

Only the judge's snapshot store names a directory the room can't reach: its own, under lup's state (`--git-dir`, `Store.snapshots`).

## Where it's going

A check that a worktree's links name the repository's own git directory and nothing else, before the host's git reads it:
- **What's right:** in lup's layout, a bare `<git dir>` with worktrees under `<git dir>/tree/<name>`, `<git dir>` holds no `commondir` or `gitdir`; each worktree's `.git` is a file reading `gitdir: <git dir>/worktrees/<name>`; that directory's `commondir` resolves to `<git dir>` (git writes `../..`) and its `gitdir` back to the worktree's `.git`. In a clone, `.git` is a directory with no redirect file in it, and its worktrees' `.git` files point into `.git/worktrees/<name>`. Any link resolving outside the repository's own git directory is wrong.
- **When:** at launch, before the common directory goes into the registration, so every later host git is handed a checked directory; and before each host git that reads a worktree, since a room can plant a link between launches.
- **A wrong link:** the host's git doesn't run, the operator is told which file is wrong, what it reads and what it should read, and the repair is plain file writes of those known strings, never git run from the suspect tree, which would read the planted `config` first.
- **The standing fix is spawn's:** worktrees created and removed through the host, their link files mounted read-only, after which the check only confirms the mounts held. Until then, the operator's own git in a worktree a room has run in (their shell, their editor's git integration) reads whatever the room left, between lup's checks.
