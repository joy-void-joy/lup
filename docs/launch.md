# Launch: a session in a room

`lup-dev launch claude` (or `codex`) starts the runtime's latest CLI in a podman container holding the repository, the room, with the operator's own login and history. The session's settings and guidance are compiled from the project's declaration at the commit the operator approved (`docs/trust.md`), and passed outside the repository. One hook carries each of the session's events to lup's host service on the operator's machine (`docs/host.md`), which judges its writes and serves lup's tools.

## The command

```
lup-dev launch claude|codex [--name NAME] [--mount DIR|MODULE]… [--mount-rw DIR]… [<the runtime's own arguments>]
lup-dev mount [--rw] [--launch LAUNCH] DIR|MODULE
lup-dev rename LAUNCH NAME
lup-dev sessions [--all]
```

- **A launch starts in the worktree it's run from,** and passes every argument it doesn't know to the CLI, so `--resume`, `-p` and `--model` reach it. It exits with the CLI's status, and refuses to run inside an agent's session.
- **`--mount`** lends a directory to this launch alone, read-only, at its own path, and `--mount-rw` writable; the guidance lists each under *Lent to this launch*. `--mount transcripts` lends a module's data instead. A repository every session should read belongs in the person's own layer (*Related repositories*).
- **`lup-dev mount`** lends a directory to a room that's already running, under its `/lent`, and tells the session where through the inbox.
- **`rename` and `sessions`** name and list the launches (*Names*).

**What a launch does,** in order (`launched`, `cli.py`):
1. checks the code the host runs against the copy the operator approved, and asks where it changed (`docs/trust.md`);
2. reads the declaration at the approved commit, exported from git's objects, so neither a branch nor an edit made in a room changes the room a launch runs in;
3. checks the host's requirements: podman and git, and `gh`, `notify-send` and a clipboard program, each optional and said where missing; and names the repository on GitHub;
4. starts the host service where none answers, and fetches the runtime's latest CLI where a newer one is out (*The CLIs*);
5. finds the related repositories, builds the list of values never published (`docs/private.md`), and makes the room, refusing what can't be mounted safely before an image build that may take minutes;
6. builds the room's image where it's missing, and compiles the session's settings and renders its guidance;
7. registers with the host service, which opens the launch's sockets, writes the settings into the launch's own directory under lup's state, and runs the container in the foreground;
8. when the CLI exits, ends the registration and removes the launch's directory.

A container starts in under a second; an image already built and a CLI already current cost nothing more.

## Names

A launch has an id, which never changes and under which everything of it is filed, and a name, for people and commands (`host/names.py`):
- **At launch** it's `--name` exactly, refused where another running launch holds it; otherwise the worktree's branch in a name's shape (`feat/x` is `feat-x`), numbered while taken.
- **It changes** with the session's `rename` tool or `lup-dev rename`. Nothing is filed by name, so a rename moves nothing, and a name is looked up each time it's used: the first lup kept paths by name, and its sessions met an earlier session's stale socket.
- **A subagent is named under its conversation** (`dev/explore-auth`), so its rename can't take its session's name. It keeps the name its parent gave at the spawn, where one did; otherwise it's asked to name itself.
- **The container is `lup-<repository>-<name>`,** renamed with the launch, so `podman ps` says which session each runs.
- **The runtime's own title follows** where the runtime has a way: Claude Code's through `SessionStart`'s `sessionTitle`. Codex sets a thread's name only through its app server, which nothing outside its process reaches, a gap its adapter declares with its evidence (`lup_dev/adapters/codex.py`).
- **A resumed conversation takes its name back,** where no running launch holds it.

## The room

**The image** (`launch/images.py`) is Arch Linux pinned to one day's snapshot of its archive (`RoomBase`, `catalog/room.py`), with the packages the selected modules ask for, each with its reason (`Packages`), so a build is reproducible and every package is at least as old as the pin. `Core`'s default is the standard machine (`StandardMachine`): the shell's tools, git, jq, ripgrep and fd, the editors Ctrl+G opens, and what lup and the runtimes need. Every agent meets the same machine, without the operator's own shell setup, which aliases `cp`, `grep` and `ls` on this host. The image is tagged by a digest of its definition and project, and built when the tag is missing; after a build, the project's older images that no container uses are removed. The first lup left 46 tags of 4.5 to 5.5 GB each, kept alive by readable names.

**The mounts** (`maintaining_room`, `launch/room.py`). The repository, the environment and the operator's own directories are each at their host path, since a linked worktree's `.git` file and the environment's links hold absolute paths, and the runtimes key their history on the working directory:

| What | Mode | Why |
|---|---|---|
| The repository: its git directory and every worktree, as one tree | read-write | the agent's work. One mount, since a mount point can't be removed from inside: with each worktree its own mount, as in the first lup, an agent couldn't remove one ("EBUSY") |
| The git directory's `config` and `hooks/` | read-only | a hook or a `core.fsmonitor` written there would run at the operator's next git command |
| The git directory itself, where it isn't the tree's root (a clone's `.git`) | read-write | under the tree's mount alone, `mv .git .git-real` succeeded and a `.git` of the room's own then stood where the host's git reads; mounted on its own, the move fails ("Device or resource busy", podman 6.1.3) |
| What the runner needs: uv's interpreters and cache | as it says | *The project's environment, shared with the host* |
| `~/.claude` or `~/.codex` | read-write | *Your login and history* |
| The CLI; pyright's source in lup's cache | read-only; read-write | *The CLIs*; the gate builds the engine from it in the room |
| The launch's directory on Claude Code; on Codex, its requirements file at `/etc/codex/requirements.toml` and the bridge; on both, its `bin/` and `gitconfig` | read-only | lup's settings, guidance and MCP bridge for this launch, and the room's programs |
| The launch's sockets, at `/run/lup` | read-write | the host service (`docs/host.md`). The directory rather than each socket, since a socket mounted as a file pins the old one when the service restarts |
| The data of each module the room mounts (past sessions, by default) | read-only, unless the module says | `docs/declaration.md`, *What a module is* |
| The editor's configuration, `/etc/localtime` | read-only | Ctrl+G opens the operator's editor as they know it, and the clock reads in their zone |
| Each related repository, whole | read-only | *Related repositories* |
| What's lent: `--mount`, `--mount-rw`, `/lent` | as lent | *The command* |
| A tmpfs at the home | read-write | podman would otherwise set `HOME` to the working directory, and the CLIs would write their state into the worktree |

Not mounted: the SSH agent, `gh`'s login, `~/.gitconfig` (it holds the operator's aliases and an LFS filter the image lacks, so the git identity is passed as variables), and the rest of the home.

**The room's git** (`room_git`): git's configuration is the room's own (`GIT_CONFIG_GLOBAL`), rewriting each remote to lup's helper, so `git push` and `git fetch` go through the host with the operator's credentials (`docs/host-tools.md`, *git through a remote helper*). A repository whose `config` sets `extensions.worktreeConfig`, or includes a file inside the room's mounts, is refused at launch: either would have the host's git read what the room wrote.

**The user, the process, the network** (`Podman`, `packages/lup/src/lup/rooms/engine.py`):
- the operator's uid inside (`--userns=keep-id`), so what the agent writes is theirs on the host;
- `--init`, since without it the first lup piled up 4,045 zombies against its pids limit;
- every capability dropped, and `no-new-privileges`;
- podman's own pids limit, which counts threads: 2048 on podman 6.1.3 (measured in a room), where the first lup's 4,096 broke a test run, so lup means to lift it (#162);
- the host's network, shared both ways, so a server the agent starts opens in the operator's browser, and the sign-in's callback reaches the CLI. The cost is that code in the room reaches what listens on the host's loopback: the walls are there so nothing explodes, not to contain an agent (`DESIGN.md`, *Who it's for*);
- a terminal with no detach keys, so Ctrl+P reaches the program, and the operator's `TERM`, `LANG`, `TZ` and `EDITOR`, without which the first lup's sessions lost their colour, locale, time zone and Ctrl+G.

**The project's environment, shared with the host.** The worktree's `.venv` is the host's, used as it is, with the host's interpreter mounted at its own path, so one environment is valid on both sides. The runner says what a room must mount (`Runner.room()`; `docs/declaration.md`, *The runner*), and a launch refuses an environment whose interpreter wouldn't resolve inside. The first lup's room ran another Python, so each side took the other's environment as broken and rebuilt it, and its way out grew to 25 GB across 31 directories.

**The CLIs** (`launch/clis.py`). Each launch asks the vendor's own release channel for the latest version, downloads it into lup's cache with its published checksum checked, and mounts it read-only, so the latest runs whatever the host has installed; offline, the version cached runs, and the launch says so. Never baked into the image: the first lup's CLI layer, 1 GB, was rebuilt most days. Each channel is spelled in its runtime's adapter (`Channel`). The vendors' signatures aren't checked yet (#63). The cache keeps each runtime's current version and the one before, for a session still running.

**Your login and history.** The operator's own `~/.claude` and `~/.codex` are mounted, so the room and the host read and write one login: copies would strand each other when one refreshed, since the provider rotates the refresh token. History is keyed on the working directory, the same in the room, so `--resume` finds earlier sessions from either side. Claude Code's state file, `~/.claude.json`, is the room's own, written fresh with onboarding done and the repository trusted: concurrent starts on one shared file once left the first lup's holding only `{"autoUpdates": false}`.

**Related repositories.** A person names, in their own layer, the other repositories their sessions may read (`Repository`; `docs/declaration.md`, *A person's own layer*). Each is mounted whole and read-only at its host path, its own `config` and `hooks/` with it, and the guidance lists it with what it is, where, and its GitHub identity, which `read_issue` and `find_issues` take as `repository`. One missing on the host is said once and marked missing; one overlapping the room's own mounts is refused, since mounted read-only it would sit over or under what the room writes. Mounted whole means its untracked files can be read from the room: naming a repository exposes it to the room.

## The settings compiled for each runtime

lup's settings reach the runtime as flags and files of the launch's own, never written into the operator's directories or the repository (`adapters/claude/terminal.py` and `adapters/codex/terminal.py` in `lup`, whose docstrings give what each rests on):

| | Claude Code | Codex |
|---|---|---|
| Where | `--settings <launch>/settings.json` with `--setting-sources user`: the operator's own settings load; the repository's `.claude/`, `.mcp.json` and `CLAUDE.md` don't | `-c` overrides on the operator's home, and `--no-daemon` |
| No prompts, since the room is the wall | `--permission-mode bypassPermissions` | `--dangerously-bypass-approvals-and-sandbox` |
| The hook | in the launch's settings | managed hooks in a mounted `/etc/codex/requirements.toml`, with `allow_managed_hooks_only` |
| lup's tools | `--mcp-config` and `--strict-mcp-config`; `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`, so a held call isn't moved to the background after two minutes | `mcp_servers.lup`, each of the operator's own servers turned off |
| Guidance | `--append-system-prompt-file`, with `--system-prompt-snapshot off` | `additional_developer_instructions` in the requirements file |

**Session settings** are `Core`'s `session` (`SessionDefaults`, `catalog/room.py`), in neutral words each adapter spells where its runtime has the setting; Codex has none for the subagents' prompt cache, removing a built-in tool or idle compaction, gaps its adapter declares:
- **idle compaction off,** so a session left waiting on the operator comes back to its conversation, not to a summary made meanwhile;
- **the account's connectors off,** since they reach the operator's mail and files;
- **built-in tools removed:** those that weigh in every turn and go unused, since an interactive session carries 113 KB of built-in tool schemas, `Artifact` alone 55 KB; and the native worktree tools, since a worktree for another agent's work is lup's spawn's to make (#117);
- **auto memory off,** and **the subagents' prompt cache** at an hour.

They layer, lowest first: the runtime's default, lup's defaults, the person's own runtime settings, then the fields some layer of the declaration sets. What can't be imposed, such as Claude Code's connectors once a person turned them off, each adapter says.

**The model and the effort are the operator's own:** a declaration names none, so no `--model` is passed, and each runtime reads their choice.

## Guidance

One document, rendered at launch (`render`, `launch/guidance.py`, whose docstring has the details):
- **the selected modules' sections,** in the declaration's order, each read at the approved commit or from the package shipping it, and rendered with Jinja in its sandbox, since an agent can write a section's file and the rendering runs on the host;
- **then lup's tools,** each by its name and summary, since the runtimes defer them behind their tool search, and agents told nothing of deferred tools concluded they didn't exist (`docs/host-tools.md`, *Found through tool search, listed in the guidance*); then the related repositories, and what's lent to this launch;
- **then the person's own section, `AGENTS.local.md`,** last, so it holds where it differs. It's a protected path, since git ignores it and nothing else would show the operator a change to it.

**Delivered at system level,** on both runtimes: Claude Code's `--append-system-prompt-file`, its documented route for instructions that must hold, where a `CLAUDE.md` arrives as a user message "with no guarantee of strict compliance"; Codex's managed developer instructions. The runtimes' own loading of the repository's `CLAUDE.md` and `AGENTS.md` is off, so nothing arrives twice, and Codex would cut an `AGENTS.md` past 32 KiB without a word.

**A resumed conversation runs under this launch's guidance.** By default each runtime keeps a conversation's first instructions, so a path or a mount that moved would go stale without a word. Claude Code renders the prompt afresh at every request with `--system-prompt-snapshot off`; Codex sends its managed instructions again whole at a resume where they changed (`docs/field-notes.md`, *A conversation resumed in a later launch*). What the conversation's earlier turns saw still came from its earlier launch, so `Core`'s guidance says the room holds where they disagree; telling the conversation what changed is #73.

**Codex's ceiling.** Codex refuses to start past 10,000 estimated tokens of managed instructions, at 4 bytes a token, counted with the markers it sends them between and the notice opening them at a resume, so a render past it is refused at launch, naming its size and the limit. A workspace's own managed requirements outrank the system file, so a workspace setting managed instructions of its own drops lup's.
