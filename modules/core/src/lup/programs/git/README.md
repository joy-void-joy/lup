# git's companion

One place where lup runs git and reads what it answers, beside `lup.programs`, which every module asks git through rather than running git itself: `lup.programs.git`. Each question lup asks git is a method running one git command, and reading git's answer into a model or a value: the caller never writes git's arguments, nor takes its output apart.

```python
from lup.programs.git import Git

here = await Git.located(Path.cwd())                 # lup's own code: git through `lup.programs`
here = await Git.located(within, through=self.git)   # a part: through its own git program
here.root, here.main                                 # the worktree's root; a clone's root, or a bare repository
await here.files([Path("src")])                      # each file git would commit, as paths
await here.staged()                                  # the tree git would commit them as
store = Git.pinned(common, through=self.git)         # the machine, over a store a room writes
await store.branch("dev")                            # a commit, by its whole id
await store.held(commit)                             # its files, each object hashed against its id
```

- **A worktree** (`Git.located`, `Worktree`) is found from a directory in it as the agent's own git finds it, through its `.git`, reading the operator's configuration: for code acting on the worktree it's typed in, so what it says of the files (`files`, `tracks`, `head`, `staged`) is what their `git add` or `git commit` would. A plain clone, a bare repository's linked worktree and a clone's linked worktree each have a main worktree (`main`): a clone's root, or the bare repository's own directory, where a repository's local layer sits.
- **A store** (`Git.pinned`, `Store`) is a repository's common git directory, git pinned to it, for the machine reading or writing a repository a room writes: a commit's files read object by object, each hashed against its id (`held`, `verified`), and what landing asks (`branch`, `merged`, `fetched`, `pushed`, …).
- **Outside any repository:** a repository made (`initialised`), one of lup's own apart from everyone's (`apart`), a clone (`cloned`), and two directories compared (`diffed`).

A part passes its own git program (`through=self.git`), as every program a part runs goes through a field of its own, which a promise stands in (`lup/doors/README.md`, *Parts*); lup's own code outside any part passes none, and git runs through `lup.programs`. A failure raises `GitError`, a refusal saying which command and why; a store holding under an id what the id doesn't say raises `UnverifiedError`.

## How git is run

Every run, whoever asks:
- **Hardened:** replace refs and the commit-graph ignored, grafts read from an empty file, since a room writes all three and git reads a commit's parents and tree from them before the commit's own bytes (`docs/field-notes.md`, *What git reads a commit's parents from*); `core.fsmonitor` and hooks off, which run a program a repository's files name; nothing fetched for an object a partial clone left out, so no read reaches the network; no password asked for at the terminal, which would wait for good.
- **Held to a time** (`Git.limit`, `whole`, `crossing`): git reading a ref a room made a FIFO waits in `open` until it's killed (`docs/field-notes.md`, *Host-side git in a repository the room writes*), so a run reading a few refs or objects is killed past 30 seconds, one reading a whole worktree or crossing the network past 10 minutes.
- **A store is pinned** with `GIT_DIR` and `GIT_COMMON_DIR` both naming its common git directory: named any other way, git follows a `commondir` file a room can plant there to a `config` of the room's own, whose `core.sshCommand` or `url.*.insteadOf` would run with the operator's hands. No configuration is read but the repository's own, which a room can't write.

`staged` leaves out a repository nested in the worktree that git doesn't track, as an agent's scratch clone under `tmp/` is: one with no commit yet fails `git add --all`, and its files are its own repository's.

Read on the machine, a worktree's `.git` file and its entry's `commondir` are the room's to write, and point git wherever they say (`docs/field-notes.md`, *Host-side git in a repository the room writes*): the machine reads a repository it knows by its common git directory, as a store.

## Its promises

`promises.py` runs real git, on scratch repositories each makes in a directory of its own, through `lup.programs`, on an event loop of asyncio's own in a thread of its own, as the programs' promises do (`lup/programs/README.md`, *Its promises*); a part's git, through the harness's `RealGit` (`lup/testing/README.md`, *The harness*).
