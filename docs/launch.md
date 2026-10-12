# Launch: a terminal session in a room, compiled from the declaration

**One sentence:** `lup launch claude` (or `codex`) starts the runtime's CLI in a podman container holding the repository, with every setting compiled at launch from the project's declaration into lup's own files outside the repository, and the one hook carrying each event to lup's host service, where the judge runs.

This is the first of #56's four pieces, each a note and a branch, each on both runtimes:
1. **this one:** the room, the compiled settings and guidance, the one hook, and the host service it reaches;
2. lup's MCP server in a launched session, the inbox and `lup inbox`, and the credential actions (git through a remote helper, GitHub through lup's tools);
3. `propose` and holds, replacing the drafts flow and the checkpoint;
4. the dependency guard.

It pulls `DESIGN.md`'s build steps 3 (rooms) and 5 (launch) ahead of tools and runs, scoped to what a maintaining session needs, with the host service's skeleton from step 6. `DESIGN.md` is the design; the facts this note rests on, measured or read for it, are in `docs/field-notes.md` (*Claude Code 2.1.296: launching a session*, *Codex 0.162.1: launching a session*, *Rooms*). A choice the operator hasn't confirmed is marked **(leaning)** where it's stated.

What it leaves to other pieces:
- everything in pieces 2 to 4. Until piece 2 lands, a launched session can't push or reach GitHub, so lup's own sessions move onto launch with piece 2 (*Building it*);
- rooms from code: `Room` as an `Agent`, with `ask` and `spawn` in a container. The check `DESIGN.md` owed for it is answered: the SDK on the host drove the CLI in a container over stdio, and the CLI reached an in-process tool on the host;
- the clipboard, the editor handoff (Ctrl+G), devices and a browser in the room, each with the first lup's evidence in `docs/field-notes.md`; none blocks a maintaining session;
- trust on launch, budgets and `accounts`.

**It builds on the declaration's slice A (leaning)** (`docs/declaration.md`, *Building it*). A launch reads `Core`'s session settings, each module's guidance and requirements, and the runner, all parts of modules. Launch built on today's minimal `Project` would be a shape to replace once modules exist. So slice A lands first, and the command is `lup-dev launch` until slice C makes it `lup launch`.

## The command

```
lup-dev launch claude [-- <the runtime's own arguments>]
lup-dev launch codex  [-- <the runtime's own arguments>]
lup-dev host [stop]
```

A launch starts in the worktree it's run from. Arguments after `--` reach the CLI as given (`--resume`, a first prompt). `lup-dev host` runs the host service in the foreground, for watching it; `lup-dev host stop` stops it.

A launch, in order:
1. loads the declaration from the integration branch's tip, as the judge does, so a branch can't change the room it runs in;
2. checks the host's requirements (podman) and starts the host service if none is running;
3. builds the room's image if its definition changed;
4. compiles the runtime's home, settings and guidance into a launch directory under lup's state;
5. registers the launch with the host service, which opens the launch's hook socket;
6. runs the container in the foreground with a terminal: its first process checks the modules' requirements inside the room, all at once, then becomes the CLI;
7. when the CLI exits: the container is removed, the launch unregistered, its directory removed. The session's history stays (*History*).

Measured: a container starts in 0.55 to 0.9 s; an image already built costs nothing more.

## The room

### The image

- **lup's base, then the modules' packages.** The image is `archlinux` with its mirror set to one day's snapshot of the Arch Linux Archive, which lup's release pins, then one `pacman -Sy` of the packages the selected modules' requirements name. Measured: git alone builds in 7 s and adds 137 MB to the 408 MB base; with nodejs, 21 s and 637 MB in all.
- **The packages come from the requirements (leaning).** `Requirement` gains `package`: the Arch package providing the tool in lup's image (`Requirement(tool="node", …, package="nodejs")`). The image is then derived from the requirements and can't drift from them, and a requirement inside the room is still probed when it starts. A requirement with no package must be met by a mount (the runner's, below), or the launch fails naming it and its module.
  - A Containerfile the project writes beside its requirements would be a second source for the same thing.
  - Mounting the host's binaries fails on linkage: the host's `uv` needed `libjemalloc.so.2`, and Arch's `node` links abseil and icu.
- **The pinned snapshot** makes a build reproducible, and every package is at least as old as the pin: the minimum package age `DESIGN.md` asks for (*Policy*). Moving the pin is a release's decision, checked when it's chosen, since some days are missing from the archive (2026-08-16's `core.db` answers 404).
- **What isn't in it:** the CLIs (*The CLIs*), Python (the project's own interpreter is mounted), editors, browsers, fonts and X. The first lup's image was 4.5 GB: a 2 GB package layer with five editors and a virtual display, and a 1 GB layer of CLIs, rebuilt whenever a CLI released, which was most days.
- **Tagged by its definition's digest** (`lup-room:<digest>`), and built when that tag is missing. Each project's images carry its label; after a build, the project's older lup images that no container uses are removed (`DESIGN.md`, *Footprint and cleanup*). The first lup's readable per-checkout tags kept 46 images of 4.5 to 5.5 GB alive.
- **Every build is recorded,** with its duration and size, one JSON line in lup's state. The first lup recorded neither, which left its size to archaeology.

### The CLIs

- **From the project's environment:** the binary each SDK bundles (`claude_agent_sdk/_bundled/claude`, `codex_cli_bin/bin/codex`), so a launched session runs the CLI the lock file pins, as an ask does (`docs/library.md`, *Pinned runtimes*): Claude Code 2.1.294 and codex-cli 0.162.0 today. It changes with a lup release, never by itself: Claude Code's updater and Codex's update check are off. Checked: both run on the bare base image (Claude's is linked against glibc only, Codex's is static); Claude embeds ripgrep, and Codex ships its own `rg` and `bwrap`.
- **So `lup-dev` gains lup's runtime extras (leaning):** `lup-dev[claude]` and `lup-dev[codex]` bring `lup[claude]` and `lup[codex]`, and launching a runtime whose extra isn't installed fails naming it, as an ask does. This is a dependency change, the operator's.
  - The CLI on the host's `PATH` is unpinned, and is installed for the host, not the image.
  - Installing the CLI in the image rebuilds it at every release, as the first lup's did.

### The mounts

Everything is mounted at its host path: a linked worktree's `.git` file and the environment's links hold absolute paths.

| What | Mode | Why |
|---|---|---|
| The repository's git directory | read-write | commits, branches, objects |
| Its `config` and `hooks/` | read-only | what runs outside the room: a hook, or a `core.fsmonitor`, would run at the host's next git command. Inside, `git config` fails with "Device or resource busy" |
| Each worktree's `.git` file | read-only | #54: a pointer moved would send the host's git elsewhere |
| The repository's worktrees | read-write | *The repository, not one worktree*, below |
| What the runner needs (*The project's environment*) | as it says | uv's interpreters and cache |
| lup's cache, `$XDG_CACHE_HOME/lup` | read-write | pyright's source, which the gate builds the engine from |
| The launch's home, and its history directory | read-write | *Each runtime's home* |
| The launch's socket directory, at `/run/lup` | read-write | the hook. The directory, not the socket: a socket mounted as a file pins the old one when the service restarts |
| `/etc/localtime` | read-only | the first lup's sessions ran in UTC |
| A tmpfs at the host's home path, as `HOME` | read-write | with `--userns=keep-id`, podman sets `HOME` to the working directory, so the CLIs would write their state into the worktree |

**Not mounted:** the SSH agent, `gh`'s login, the rest of `~/.claude` and `~/.codex`, and the rest of the home. `~/.gitconfig` isn't either: it holds the operator's aliases and an LFS filter the image lacks, so the git identity is passed as `GIT_AUTHOR_*` and `GIT_COMMITTER_*`, read from the host's git.

**The repository, not one worktree (leaning).** `AGENTS.md`'s workflow has a session branch into a sibling worktree and land it from the `dev` checkout. With one worktree mounted, a `git worktree add` would write into the container and vanish with it. Narrowing the mount to the session's worktree comes with `DESIGN.md`'s worktrees and landing (build step 7), which replace that workflow. The spike showed the narrow mount works: a tmpfs over the worktrees' directory, mounted with `notmpcopyup`, since podman otherwise copies what it hides into the tmpfs. The git directory is writable either way, and so are its refs: an agent can move or delete a branch, as it can today, and the reflog keeps what was moved.

### The user, the process, the network

- `--userns=keep-id`: the operator's uid inside, so what the agent writes is the operator's on the host.
- `--init`: without it, the first lup piled 4,045 zombies against its pids limit, and an unrelated test run failed.
- `--cap-drop=all` and `no-new-privileges`, so no inherited capability carries in (`DESIGN.md`, *Policy*).
- No memory or pids limit by default. The pids limit counts threads, and the first lup's 4,096 broke a test run.
- **podman's own network, not the host's (leaning).** Egress is open, as `DESIGN.md` leans, and the host's loopback stays out of reach: the dashboard, a database, anything listening on localhost. The first lup gave its own sessions the host's network for sign-in callbacks and ssh. A token login needs no callback, and pushes happen on the host (piece 2).
- **A terminal:** `-it`, with `TERM`, `COLORTERM`, `LANG` and `TZ` passed. The terminal's size carries through. The first lup's sessions lost colour, their locale and their time zone until it passed these.

## The project's environment, shared with the host

- **One environment.** The worktree's `.venv` is the host's, used as it is. The first lup gave each container its own (`.venv-contained`), 25 GB across 31 directories today, whose scripts went stale when a repository moved.
- **The runner says what a room must mount (leaning):** `Runner.room()` returns mounts and environment variables. `Uv()` gives uv's interpreters read-only and uv's cache read-write, at their host paths, with `UV_CACHE_DIR` and `UV_PYTHON_DOWNLOADS=never`. `Plain()` mounts nothing, and a project's own runner says what it needs.
- **The interpreter must resolve inside.** A launch checks that the environment's interpreter resolves under the room's mounts, and refuses otherwise, naming it. Without the interpreter, `uv run` printed "Ignoring existing virtual environment linked to non-existent Python interpreter" and set about recreating the shared `.venv`; `UV_PYTHON_DOWNLOADS=never` stops it before it can, and the check says why. An environment on a system interpreter, outside uv's store, is refused with how to move it onto one uv manages.
- **Checked:** with these mounts, `uv run --frozen pytest` audited the environment and wrote nothing to `.venv`, and lup's whole suite passed in the room in 417 s, against 418 s on the host, with nodejs in the image for the engine.

## Each runtime's home, login and history

### Homes

**A home per launch, compiled fresh (leaning),** under lup's state, mounted read-write: Claude Code's `CLAUDE_CONFIG_DIR`, Codex's `CODEX_HOME`. It holds only what lup compiles, and it's removed when the launch ends. In the first lup, concurrent starts on one home corrupted Claude Code's `.claude.json` (16 starts left `{"autoUpdates": false}`) and raced on Codex's `config.toml`; a home per launch has nothing to race on. Homes live under lup's state rather than `/tmp`, since Codex refuses to make its helper links under a temporary directory.

### History

The directories each runtime writes its sessions to (Claude Code's `projects/`, Codex's `sessions/` and its index) are bound into each launch's home from a directory kept per repository, so `lup-dev launch claude -- --resume` finds the sessions before it. They aren't among the operator's own sessions in `~/.claude`, as sessions from code aren't (`DESIGN.md`, *Calling agents from code*), so a launched session is resumed in its room, never outside it. Whether Codex's resume also needs its state databases is a check owed.

### Claude Code's login: a long-lived token (leaning)

`claude setup-token` makes a one-year subscription token that "can only make model requests". A launch reads it from `LUP_CLAUDE_TOKEN` in the operator's environment (one of `lup-dev`'s settings) and passes it into the room as `CLAUDE_CODE_OAUTH_TOKEN`; without one, it refuses and says how to make it. Read from `CLAUDE_CODE_OAUTH_TOKEN` itself, the token would also switch the operator's own sessions on the host to it, since it outranks `/login`. lup stores no token: where it's kept is the operator's choice.
- **No login file is shared.** Claude Code replaces `.credentials.json` on a refresh, which a mount can't follow, and a copy goes stale. The first lup kept copies in step with a companion syncing them every 30 s, and a refresh in one place could still rotate the token out from under the others.
- **The account's claude.ai connectors stay out of the room.** With the full login, the spike's container connected Google Drive, with its share and trash tools.
- **The gap:** the agent's commands can read the variable. It's the runtime's own login, readable today by a session with no container, so nothing gets worse. Hiding it waits on a check `DESIGN.md` already owes (the runtime's own sandbox, nested in the room).
- The alternative is the operator's `.credentials.json`, read-only: it worked for a call, but a refresh in the room would fail, and could rotate the token the host holds.

### Codex's login: the operator's `auth.json`

The operator's `auth.json` is bind-mounted as one file into the home, with `cli_auth_credentials_store = "file"`. Codex rewrites the file in place (it truncates, never renames), so a refresh in the room writes the one real copy. A ChatGPT login has no long-lived token. Codex re-reads the file before a refresh and skips one another process already made, but no lock spans processes, so a refresh on the host and one in the room at the same moment can race, and the loser's token is marked spent. Whether that happens in practice is a check owed.

## The settings compiled for each runtime

| What | Claude Code | Codex |
|---|---|---|
| Where they go | `--settings <launch>/settings.json`, with `--setting-sources user`: "user" is the launch's home, so the repository's `.claude/settings.json`, `.mcp.json`, skills and `CLAUDE.md` don't load | the home's `config.toml`, with `--no-daemon`: Codex's shared daemon keeps "file settings and defaults" until it restarts |
| No prompts: the room is the wall | `--permission-mode bypassPermissions`, and `skipDangerousModePermissionPrompt` in the home's settings | `--dangerously-bypass-approvals-and-sandbox`, which is `-s danger-full-access -a never` |
| First-run screens | the home's `.claude.json`: onboarding done; the worktree and the main repository trusted (Claude Code asks about the main repository for a linked worktree) | `projects` with each trusted, as an inline table: a dotted `-c` key splits at every `.`, which breaks a path like `lup.git` |
| The one hook | `hooks` in `settings.json` | lup's hooks as managed hooks, in an `/etc/codex/requirements.toml` mounted into the room, with `allow_managed_hooks_only` so a repository's own hooks are dropped **(leaning)**; or else `--dangerously-bypass-hook-trust` |
| Session settings | `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h`, the removed tools as bare names in `permissions.deny` | memories off |
| lup's own needs | `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`, so a held call isn't moved to the background after 2 minutes (piece 3); `DISABLE_AUTOUPDATER` | `check_for_update_on_startup = false`; `features.plugins = false`, which stops a sync from GitHub at each start |
| Guidance | `--append-system-prompt-file <launch>/guidance.md` | `developer_instructions`, with `project_doc_max_bytes = 0` |

- **Session settings are `Core`'s `session` part,** in neutral terms each adapter spells: the subagents' prompt cache, auto memory, and the built-in tools removed from context (`DESIGN.md`, *Sessions*). The removed tools start from the five lup's own settings remove today (`Artifact`, `SendFeedback`, `Workflow`, `ScheduleWakeup`, `ReportFindings`). lup's own needs aren't a project's to change, since lup's mechanisms rely on them.
- **Native subagents stay on until lup's spawn exists (leaning).** `DESIGN.md` denies the native `Agent` and Codex's subagent tools by default, in favour of lup's spawn. Denied now, a session couldn't delegate at all. The deny becomes the default in the spawn piece.
- **Codex's built-in tools can't be removed by name** (0.162.1 has no setting for it), only by whole feature groups, so the removed tools are Claude Code's alone, a gap the launch states.

## Guidance

- **One document, rendered at launch** from the selected modules' `guidance` sections, in module order, with Jinja (`DESIGN.md`, *Guidance and skills*). A section names the project's commands through the runner (`{{ run("lup-dev check") }}` becomes `uv run lup-dev check`), so no section spells uv. Rendering refuses a section naming a command the project doesn't serve (`docs/declaration.md`, *Later*). Jinja is a new dependency of `lup-dev`, the operator's.
- **Delivered at system level, on both runtimes:** Claude Code's `--append-system-prompt-file` is its documented route for system-level instructions, where `CLAUDE.md` arrives as a user message "with no guarantee of strict compliance"; Codex's `developer_instructions` opens the first developer message.
- **The project's own guidance is a section of its declaration (leaning),** and in a launched session the runtimes' own loading of the repository's `CLAUDE.md` and `AGENTS.md` is off. One text then reaches both runtimes, and nothing is loaded twice. Codex would also cut an `AGENTS.md` past 32 KiB without a word, which lup's own rules forbid. lup's own declaration names `AGENTS.md` as its section. Outside lup, the runtimes still load the repository's files as before.
  - The alternative, the runtimes loading the repository's files with lup's sections appended, gives each runtime a different text, and on Claude Code it would also load a committed `.claude/settings.json`.
- **What lup's sections say in this piece:** `Core`'s, the room (what's mounted, that pushing and GitHub wait for piece 2, what's the agent's to decide and what's the operator's); `Python`'s, the runner and the gate; `CodeRules`', refusals and the `# lup:` grammar. Guidance is written once the system it describes exists, and reviewed after it lands (`DESIGN.md`, *Policy*); each later piece adds its own.
- **Skills** compile from the modules' `skills` part into the home's skills directory, on both runtimes, once a module ships one. None does yet.

## The one hook and the host service

### In the room: a pipe

Each hook command is `socat -t <hours> - UNIX-CONNECT:/run/lup/hook.sock` **(leaning)**. It sends the runtime's payload unchanged and prints the answer, so nothing in the room parses it. The host service runs the runtime's adapter on it (`adapter.hook(payload, bench)`), exactly as `lup-dev hook` does today. socat is `Core`'s requirement, with its package.
- **The judge stays on the host,** for practical reasons, not to guard it: run in the room, every project's image would carry lup-dev and the engine, the judge's state would be mounted to be shared across sessions, and each project would judge with its own copy of lup-dev rather than the installed one the operator approved.
- **If the host service is down,** socat fails. Claude Code's hooks reference takes a command's failure with any status but 2 as a non-blocking error: the call goes on, and the error shows. That's the intended outcome, since the judge steers and doesn't guard (`DESIGN.md`, *Policy*); what Codex does is a check owed.
- **The events** are today's: Claude Code's `SessionStart`, and `PreToolUse` on Edit and Write; Codex's `SessionStart`, `PreToolUse` and `PostToolUse`, since Codex is judged after each call. Piece 3 removes the checkpoint and reshapes the rest. The timeout is hours, for holds: Claude Code documents no maximum for a command hook, and Codex took 99999 s.
- **A protected path's ask on Claude Code** is the runtime's own prompt today. Whether a hook's `ask` still prompts under `bypassPermissions` is a check owed. If it doesn't, a room's Claude Code is judged as a runtime that can't ask before a call (`Runtime.asks_before`), and the change is held until it's answered with `lup-dev holds`, as on Codex.

### On the host: the service

- **One per user,** the installed `lup-dev`'s, started by the first launch that finds none, and running until it's stopped: found or started on demand, as the engine is.
- **A socket per launch (leaning),** in a directory of its own, mounted into that launch's room at `/run/lup`. The service knows which launch speaks by the socket it hears it on, and the socket goes with the launch. Seen through `SO_PEERCRED`, a room's process has the operator's uid (keep-id), so the uid can't tell a room from the operator; the socket can.
  - One socket for every room would have each request name its launch, which the room would then say of itself.
  - HTTP on the host's loopback needs the host's network in the room, which this piece declines.
- **Its control is a socket on the host only,** taking typed requests: one JSON request per connection, a pydantic model discriminated by `kind`, and one JSON reply. In this piece the kinds are a launch's registration and its end, and stopping the service. Modules register the handlers for their kinds, as `DESIGN.md` describes (*The environment: core and modules*); piece 2 adds the inbox's, and the socket lup's MCP server reaches from the room.
- **Its waits go through `lup_dev.clock`,** so its tests drive time.

## Modules and public API

### The library

DESIGN says one declaration compiles to SDK options for code and to a command line for a terminal, and that a room wraps an agent with a wall (*The library*). So the terminal compile and the room are the library's, and the environment's maintaining session is a room it declares.

```python
from lup import Claude
from lup.rooms import Container, Image, Mask, Mount, Room

room = Room(
    agent=Claude(model="opus"),
    container=Container(
        image=Image(definition=CONTAINERFILE),
        mounts=[Mount(source=repository), Mount(source=hooks, read_only=True), Mask(target=worktrees)],
    ),
)
status = room.launch(arguments=["--resume"], settings=settings)   # a terminal; returns the CLI's exit status
```

| File | What it's for | Public names |
|---|---|---|
| `rooms/container.py` | What a room's wall is made of | `Container` (`image`, `mounts`, `env`, `network`), `Image` (`definition`, tagged by its digest), `Mount` (`source`, `target`, `read_only`), `Mask` (a tmpfs hiding what's under it) |
| `rooms/engine.py` | Running containers | `ContainerEngine`, an ABC (`ensure`, `run`); `Podman`, its one implementation; `ContainerError` |
| `rooms/room.py` | An agent behind a wall | `Room` (`agent`, `container`), `launch` |
| `sessions/terminal.py` | A declaration compiled for a terminal, in neutral terms | `TerminalSettings` (`home`, `hooks`, `guidance`, `session`, `trusted`), `Hook` (`event`, `matcher`, `command`, `timeout`), `SessionSettings`, `Terminal` (`command`, `env`, `files`, `mounts`) |
| `adapters/claude/terminal.py`, `adapters/codex/terminal.py` | Each runtime's spelling of a terminal: the bundled binary, its flags, its home's files, the mounts its login needs | none beyond the declaration's method |

- **`Declaration.terminal(settings) -> Terminal`,** implemented by `Claude` and `Codex`, compiles the declaration's model and effort as the runtime spells them, with the settings above. In a terminal, `system_prompt` replaces the runtime's prompt as it does in an ask, and none keeps the runtime's own **(leaning)**: a terminal session is the runtime's coding agent, which an empty prompt would leave without its tools' guidance, where an ask with no prompt sends none.
- **`Room` gets `launch` alone in this piece (leaning);** it becomes an `Agent`, with `ask` and `spawn` in a container, in the slice that runs rooms from code, as a field arrives with the slice that uses it (`docs/library.md`, *What a declaration holds*).
- **The engine is a seam:** tests use a recording engine, so no test runs podman. Running podman needs only the standard library; the library gains no dependency.

### The environment

| File | What it's for |
|---|---|
| `launch/room.py` | The maintaining session's room from a resolved declaration: the image's definition, the repository's mounts and masks, the runner's, lup's cache, the launch's socket directory, the git identity and the terminal's variables |
| `launch/images.py` | The image's definition from the base and the requirements' packages; building through the engine; the build record; removing the project's older images |
| `launch/homes.py` | The launch directory: each runtime's home, the history bound in per repository, the login's checks |
| `launch/guidance.py` | Rendering the modules' guidance sections into one document |
| `launch/session.py` | A launch's `TerminalSettings`: the hooks, `Core`'s session settings, the guidance, what's trusted |
| `host/service.py` | The host service: the control socket, a hook socket per launch, the handlers modules register |
| `host/protocol.py` | The control requests and replies (`Register`, `Unregister`, `Stop`) |
| `host/client.py` | Finding the service, or starting it |
| `catalog/room.py` | lup's base image and its pinned snapshot date, the default session settings |
| `cli.py` | `launch claude\|codex` and `host [stop]`, until slice C gives each command group its file |

The declaration's slice A gains:
- the `Session` and `Guidance` kinds, `Core.session`, and each module's `guidance` part, as `docs/declaration.md` (*Later*) reserves for the launch piece;
- `Requirement.package`;
- `Runner.room()`.

The list of adapters `cli.py` holds moves where the host service reads it too, as slice C plans (`commands/runtimes.py`).

## Tests

- Each runtime's terminal compile, for a sample declaration and settings: the command, variables, files and mounts, compared whole.
- The maintaining room for a sample declaration: the image's definition from its requirements, byte for byte; the mounts, masks and variables; each refusal (an environment on a system interpreter, no token, a requirement with no package and no mount).
- The engine through a recording fake: no podman in any test.
- The host service on a socket under the test's temporary directory, with a stub adapter: a payload in and the answer out; a launch's socket gone with the launch; a second start finding the first. Unix sockets are local, not network.
- Guidance: sections in module order, the runner's spelling, a section naming a command the project doesn't serve refused.
- **Live, by hand, before landing,** on a scratch project and on each runtime: the session starts with no screen to dismiss; an Edit with a rule finding is refused through the room's hook; a protected path asks or holds (*Checks owed*); `uv run lup-dev check` passes in the room; a resumed session finds the one before it.

## Checks owed

- **Claude Code:** whether a `PreToolUse` hook's `ask` prompts under `bypassPermissions`; whether `--settings` still applies with `--setting-sources user`; whether a fresh home with onboarding and trust set opens with no screen at all (the theme picker among them); that the token keeps the claude.ai connectors out.
- **Codex:** managed hooks through a mounted `/etc/codex/requirements.toml`, with `allow_managed_hooks_only` dropping a repository's own; resume across per-launch homes; a refresh racing on the one `auth.json`; what a failing hook command does to the call.
- **Both:** a hook held for hours through socat.

## Building it

After the declaration's slice A, on one branch, `feat-launch` **(leaning)**:
1. the library's rooms and each adapter's terminal compile;
2. slice A's new parts: `Session`, `Guidance`, `Requirement.package`, `Runner.room()`;
3. the host service, and the hook through it;
4. the maintaining room, homes, guidance and the command;
5. the live checks, and what they find recorded in `docs/field-notes.md`.

lup's own sessions move onto launch once piece 2 lands, since before it a launched session can't push. The committed `.claude/settings.json`, `.claude/hooks/` and `.codex/hooks.json` then go, in a change to protected paths the operator makes, and #54 is answered by the room's read-only `.git` file.
