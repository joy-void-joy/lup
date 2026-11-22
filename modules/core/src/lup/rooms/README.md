# Rooms

The container a session works in (`DESIGN.md`, *Who it's for*, *Defaults*): the same standard machine whatever the host, the repository it works on, a home and history of the rooms' own, its account's login, and the newest CLI of every runtime lup holds sessions on. Commands run there without asking, since the container keeps them from harming the operator's machine. Its library side is what a module declares for its sessions' rooms (`Packages`, `packages.py`) and where things are kept and land (`layout.py`); making a room is the machine's (`Rooms`, `part.py`), a part of `lup.sessions`' module, through `Containers`, behind the walls every container stands behind (`lup/hosting/README.md`, *Containers*).

## The image

Arch Linux's image, pinned with the day of its archive its packages come from, as a project's containers' is, and every package the project's declaration selects. `Core.packages` holds the standard machine: the second lup's, which its sessions used for months, and what agents in rooms reached for and didn't find (`man`, `time`, `tmux`). Any module adds its own (`Packages.of(Package(name=…, why=…))`), and the plan carries them all, so the machine builds a room's image without loading the declaration. A definition is built once, tagged by its digest.

## What a room holds

- **The repository, read-write,** at its own path: the directory holding its git directory and every worktree, so a session can look at another worktree and `git worktree remove` works. Its git `config` and `hooks/` are read-only, since a hook or a `core.fsmonitor` written there would run at the operator's next git command.
- **The session's own files, read-only:** what lup writes for its runtime, its settings and its guidance. Its runtime's own directory and its home, on disk and the session's alone.
- **The history every room of a project shares,** for each runtime, linked from the runtime's own directory. It's kept where the second lup keeps it (`~/.local/share/lup/homes/projects/<digest of the git directory>/<runtime>/`), so a session started under the second lup resumes in this one.
- **The account's login,** one file mounted alone, read-write, so a sign-in in one room is every room's. It's kept where the second lup keeps it (`~/.local/share/lup/accounts/<account>/<runtime>/`). An account with no login for a runtime mounts nothing for it.
- **The newest CLI of every runtime,** read-only, on the `PATH`, so a Claude Code session can run Codex and the other way round. Each is fetched from its vendor and checked against the vendor's checksum, its channel asked at most hourly.
- **The machine's own lup and its Python,** read-only at their own paths: the room's first program, its hooks and its tool server run from them (`lup/sessions/README.md`).
- **uv's cache and the session's environment,** one directory a project, so an environment's files are links into the cache. The worktree's own `.venv` is hidden.
- **git through lup:** the room's git configuration (`GIT_CONFIG_GLOBAL`, among the session's own files) sends each URL the repository's `config` gives a remote through `git-remote-lup`, on its `PATH` there too, so a push or a fetch is made with the operator's credentials by the project's `remote` part (`lup/remote/README.md`), and anything else is reached as nobody. The machine reads those URLs from `config`, which no room writes.
- **The room's directory of sockets** at `/run/lup`: the machine's, which says the room's calls are its session's agent's, and the session's holder's.
- **The machine's network,** so a server started in a room opens in the operator's browser.

## Promises

The sessions' promises check what a room is started with (`lup/sessions/promises.py`).
