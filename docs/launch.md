# Launch: a terminal session in a room, compiled from the declaration

**One sentence:** `lup launch claude` (or `codex`) starts the latest CLI in a podman container holding the repository, with the operator's own login and history, every setting of lup's compiled at launch from the project's declaration and passed outside the repository, and the one hook carrying each event to lup's host service, where the judge runs.

This is the first of #56's four pieces, each a note and a branch, each on both runtimes:
1. **this one:** the room, the compiled settings and guidance, the one hook, and the host service it reaches;
2. lup's MCP server in a launched session, the inbox and `lup inbox`, and the credential actions (git through a remote helper, GitHub through lup's tools);
3. `propose` and holds, replacing the drafts flow and the checkpoint;
4. the dependency guard.

It pulls `DESIGN.md`'s build steps 3 (rooms) and 5 (launch) ahead of tools and runs, scoped to what a maintaining session needs, with the host service's skeleton from step 6. `DESIGN.md` is the design; the facts this note rests on, measured or read for it, are in `docs/field-notes.md` (*Claude Code 2.1.296: launching a session*, *Codex 0.162.1: launching a session*, *Rooms*). A choice the operator hasn't confirmed is marked **(leaning)** where it's stated.

What it leaves to other pieces:
- everything in pieces 2 to 4. Until piece 2 lands, a launched session can't push or reach GitHub, so lup's own sessions move onto launch with piece 2 (*Building it*);
- rooms from code: `Room` as an `Agent`, with `ask` and `spawn` in a container. The check `DESIGN.md` owed for it is answered: the SDK on the host drove the CLI in a container over stdio, and the CLI reached an in-process tool on the host;
- the clipboard, devices and a browser in the room, each with the first lup's evidence in `docs/field-notes.md`. The clipboard comes later; none blocks a maintaining session;
- budgets and `accounts`.

**It builds on the declaration's slice A** (`docs/declaration.md`, *Building it*). A launch reads `Core`'s session settings, each module's guidance, packages and requirements, and the runner, all parts of modules. So slice A lands first, and the command is `lup-dev launch` until slice C makes it `lup launch`.

## The command

```
lup-dev launch claude [<the runtime's own arguments>]
lup-dev launch codex  [<the runtime's own arguments>]
lup-dev host [stop]
```

A launch starts in the worktree it's run from. Any argument lup doesn't know reaches the CLI as given, so `lup-dev launch claude --resume` resumes. `lup-dev host` runs the host service in the foreground, for watching it; `lup-dev host stop` stops it.

A launch, in order:
1. loads the declaration from the integration branch's tip, as the judge does, so a branch can't change the room it runs in;
2. checks the host zone against the copy the operator approved, and where it changed, shows the diff and asks (*Trust on launch*);
3. checks the host's requirements (podman) and starts the host service if none is running, or restarts it on a copy just approved;
4. fetches the runtime's latest CLI if a newer one is out (*The CLIs*);
5. builds the room's image if its definition changed;
6. compiles lup's settings and guidance into a launch directory under lup's state;
7. registers the launch with the host service, which opens the launch's hook socket;
8. runs the container in the foreground with a terminal: its first process checks the modules' requirements inside the room, all at once, then becomes the CLI;
9. when the CLI exits: the container is removed, the launch unregistered, its directory removed.

Measured: a container starts in 0.55 to 0.9 s; an image already built and a CLI already current cost nothing more.

## Trust on launch

The code that runs on the operator's machine, outside every room, is approved before it runs (`DESIGN.md`, *Policy*, *Trust on launch*). There is no install step to remember: the launch itself asks, the way the first lup's launcher asked adlib's operator, "the first time, and whenever adlib's own code has changed since". `lup-dev install` goes.

- **The host zone** is what the host runs for a project:
  - its declaration (`lup_project.py`, or the package `lup_project/`), and the files a selected module names that the host imports (its conditions module, later its rule tables);
  - the `lup-dev` it runs: for lup's own repository, `lup-dev`'s and `lup`'s source and the engine's, which the operator builds from; for any other project, the `lup-dev` release its lock file pins.
- **Read at the integration branch's tip,** as the judge reads the declaration, so what's approved is what the judge and the host service will run, never a branch's own copy.
- **Its fingerprint is kept with the copy the operator approved,** per repository, in lup's state. A launch compares the tip's host zone with it.
- **Changed, or never approved:** the launch shows what changed since the approved copy (`git diff` over the host zone, in the terminal's pager; on the first time, every file of the zone), and asks once, yes or no. In the terminal until piece 2 brings the inbox, where `lup inbox` and the dashboard show it as any other item.
  - **Yes:** the engine is built, the zone's copy installed as the host's `lup-dev`, the host service restarted on it (its rooms keep their sockets: *On the host: the service*), the approval recorded, and the session launched.
  - **No:** the session launches on the copy approved before, and the launch says the tip isn't the code judging it. With no copy approved yet, it doesn't launch.
- **What it costs:** after a large merge, the next launch shows a large diff (the declaration's slice A was about 5,000 lines of the judge). That is the review; it comes at launch rather than at a separate step.
- The installer's review parked in the first lup's dashboard (`legacy_dashboard.py`'s `LegacyDashboard`) goes with `lup-dev install`.

## The room

### The image

- **lup's base, then the packages the selected modules ask for.** The image is `archlinux` with its mirror set to one day's snapshot of the Arch Linux Archive, which lup's release pins, then one `pacman -Sy` of every package the selected modules name. Measured on a small set: git alone builds in 7 s and adds 137 MB to the 408 MB base. Size isn't the constraint; leaving nothing behind is (*Footprint*, below).
- **Each module has a `packages` part,** a selection like every other kind, each package with its reason:

  ```python
  class Studio(Module):
      packages: Packages = Packages.of(
          Package(name="ffmpeg", why="encodes the episodes"),
          Package(name="noto-fonts-cjk", why="pages set Japanese text"),
      )
  ```

  A requirement, a tool lup checks for, names the package providing it in lup's image (`Requirement(tool="node", …, package="nodejs")`), and that package joins the image without being listed twice. The image is derived from the declaration, so it can't drift from what the modules need. Mounting the host's binaries instead fails on linkage: the host's `uv` needed `libjemalloc.so.2`, and Arch's `node` links abseil and icu.
- **`Core`'s default `packages` is a standard machine.** Every agent meets the same one, whatever the host is: bash and the usual tools, none of the operator's shell setup. The CLIs run an agent's commands in the user's shell, aliases included: on this machine that's zsh, with `cp` as rsync, `grep` as ugrep and `ls` as lsd, which tripped every research job for this note, and once nearly had uv recreate the shared `.venv` through zsh's `:r` modifier. The set starts from the first lup's, which its sessions used for months:
  - **the shell:** bash, coreutils, findutils, grep, sed, gawk, diffutils, file, which, less, tree, procps-ng, util-linux, lsof, inetutils, tzdata, and the `en_US.UTF-8` locale;
  - **work:** git, curl, ca-certificates, openssh, jq, go-yq, ripgrep, fd, python (for scripts outside a project), socat (the hook, *The one hook*);
  - **for the runtimes:** poppler, since Claude Code's Read renders a PDF's pages with `pdftoppm` ("pdftoppm is not installed. Install poppler-utils … to enable PDF page rendering", in its binary); ttf-liberation, one font family, so anything that renders text finds a face;
  - **editors,** for Ctrl+G, which opens `$EDITOR` in the room: vim, neovim, nano, emacs-nox and helix.

  From the first lup's, three leave the base: bun, which installed its CLIs and is a project's own now (adlib's studio uses it); github-cli, since the room holds no GitHub login and piece 2 reaches GitHub from the host; and the virtual display behind its clipboard, until the clipboard's piece.
- **From the modules:** nodejs with `CodeRules` (the engine is pyright's code, bundled for Node); uv with `Python`'s runner; npm with lup's own module, which builds the engine from source; ffmpeg, the Noto fonts and Chromium's libraries with adlib's own.
- **The pinned snapshot** makes a build reproducible, and every package is at least as old as the pin: the minimum package age `DESIGN.md` asks for (*Policy*). Moving the pin is a release's decision, checked when it's chosen, since some days are missing from the archive (2026-08-16's `core.db` answers 404). A tool whose snapshot version is too old for its requirement fails the launch's check, naming both versions.
- **Tagged by its definition's digest** (`lup-room:<digest>`), and built when that tag is missing.

### Footprint

The first lup left 46 images of 4.5 to 5.5 GB on this machine, kept alive by readable per-checkout tags, and 25 GB of per-project environments nothing pruned. Here:
- one image per definition, labelled with its project; after a build, the project's older lup images that no container uses are removed;
- no environment of lup's own: the project's `.venv` is shared (*The project's environment*);
- the CLI cache keeps each runtime's current version and the one before it, for a session still running;
- every build is recorded with its duration and size, one JSON line in lup's state, which the first lup never recorded.

### The CLIs

- **The latest, fetched at launch.** A launch asks each vendor's own release channel (the one its installer uses) for the latest version, downloads it into lup's cache on the host when it's newer, checks its published checksum, and mounts it read-only into the room. So `lup launch claude` runs the latest Claude Code, whatever the host has installed, or without one. Offline, the cached version runs, and the launch says so.
- **Never baked into the image:** the first lup installed its CLIs into the image from npm at every release, a 1 GB layer rebuilt on most days.
- **Asks from code keep the CLI their SDK pins** (`docs/library.md`, *Pinned runtimes*): their guarantees are checked per version, which a launched terminal, the operator's own, doesn't need. In the room, the CLI's own updater is off, since its file is read-only.
- Checked: the CLIs run on the bare base image. Claude Code's native build links only glibc; Codex's is static, and ships its own `rg` and `bwrap`.

### The mounts

Everything is mounted at its host path: a linked worktree's `.git` file and the environment's links hold absolute paths, and the runtimes key their history on the working directory's path.

| What | Mode | Why |
|---|---|---|
| The repository: its git directory and every worktree, as one tree | read-write | the agent's work, and the other worktrees it's asked to read or clean up |
| The git directory's `config` and `hooks/` | read-only | what runs on the host: a hook, or a `core.fsmonitor`, a compromised package wrote there would run at the operator's next git command. Inside, a git command that writes config (setting a branch's upstream) fails with "Device or resource busy" |
| What the runner needs (*The project's environment*) | as it says | uv's interpreters and cache |
| `~/.claude` or `~/.codex` | read-write | the operator's own login, settings and history (*Your login and history*) |
| The CLI, from lup's cache | read-only | *The CLIs* |
| lup's cache, `$XDG_CACHE_HOME/lup` | read-write | pyright's source, which the gate builds the engine from |
| The launch's directory | read-only | lup's settings and guidance for this launch |
| The launch's socket directory, at `/run/lup` | read-write | the hook. The directory, not the socket: a socket mounted as a file pins the old one when the service restarts |
| The editor's own configuration (`~/.config/nvim` for nvim, `~/.vimrc` and `~/.vim` for vim, and so on) | read-only | Ctrl+G opens the operator's editor as they know it |
| `/etc/localtime` | read-only | the first lup's sessions ran in UTC |
| A tmpfs at the host's home path, as `HOME` | read-write | with `--userns=keep-id`, podman sets `HOME` to the working directory, so the CLIs would write their state into the worktree |

- **One mount for the whole repository.** The first lup mounted each worktree on its own, and a mount point can't be deleted from inside, so agents couldn't remove a worktree they were done with ("EBUSY"). Mounted as one tree, `git worktree add` and `remove` work as on the host, and an agent reads any other worktree it's pointed at. The refs are writable too: an agent can move or delete a branch, as it can today, and the reflog keeps what was moved. A worktree's `.git` file stays writable for the same reason, so #54 stays the judge's.
- **Not mounted:** the SSH agent, `gh`'s login, and the rest of the home, the operator's shell configuration among it. `~/.gitconfig` isn't either: it holds the operator's aliases and an LFS filter the image lacks, so the git identity is passed as `GIT_AUTHOR_*` and `GIT_COMMITTER_*`, read from the host's git.

### The user, the process, the network

- `--userns=keep-id`: the operator's uid inside, so what the agent writes is the operator's on the host.
- `--init`: without it, the first lup piled 4,045 zombies against its pids limit, and an unrelated test run failed.
- `--cap-drop=all` and `no-new-privileges`, so no inherited capability carries in (`DESIGN.md`, *Policy*).
- No memory or pids limit by default. The pids limit counts threads, and the first lup's 4,096 broke a test run.
- **The host's network.** The room shares the host's localhost both ways: a preview server an agent starts opens in the operator's browser, and the agent reaches what the operator runs, for working on something together live. The sign-in's browser callback reaches the CLI too, which the first lup found failing without it. The cost: code in the room reaches anything listening on the host's loopback; the wall is for damage, not for containing the agent (`DESIGN.md`, *Policy*). A room can declare its own network instead.
- **A terminal:** `-it`, with `TERM`, `COLORTERM`, `LANG`, `TZ`, `EDITOR` and `VISUAL` passed. The terminal's size carries through. The first lup's sessions lost colour, their locale, their time zone and Ctrl+G until it passed these and installed the editors.

## The project's environment, shared with the host

- **One environment.** The worktree's `.venv` is the host's, used as it is.
  - Why the first lup didn't: its container ran the image's system Python while the host's `.venv` pointed at a uv-managed one, so each side took the other's environment as broken and rebuilt it ("so host and container stopped clobbering each other's `.venv`"). It moved to an environment per project root outside the checkout, mounted over `.venv-contained`: a mount point agents couldn't remove, which nothing on the host pruned, 25 GB across 31 directories today, whose scripts went stale when a repository moved.
  - Mounting the host's interpreter at its own path removes the cause: both sides run the same Python, so one `.venv` is valid on both. Built into the image, an environment would rebuild the image at every change of the lock; installed at each start, it's the first lup's "minutes the first time".
- **The runner says what a room must mount:** `Runner.room()` returns mounts and environment variables. `Uv()` gives uv's interpreters read-only and uv's cache read-write, at their host paths, with `UV_CACHE_DIR` and `UV_PYTHON_DOWNLOADS=never`. `Plain()` mounts nothing, and a project's own runner says what it needs.
- **The interpreter must resolve inside.** A launch checks that the environment's interpreter resolves under the room's mounts, and refuses otherwise, naming it. Without the interpreter, `uv run` printed "Ignoring existing virtual environment linked to non-existent Python interpreter" and set about recreating the shared `.venv`; `UV_PYTHON_DOWNLOADS=never` stops it before it can, and the check says why. An environment on a system interpreter, outside uv's store, is refused with how to move it onto one uv manages.
- **Checked:** with these mounts, `uv run --frozen pytest` audited the environment and wrote nothing to `.venv`, and lup's whole suite passed in the room in 417 s, against 418 s on the host, with nodejs in the image for the engine.

## Your login and history

**The operator's own `~/.claude` and `~/.codex` are mounted into the room, read-write, at their paths.** A first launch needs nothing: it's the login the operator already has.
- **One login, so nothing to keep in step.** Claude Code replaces its credentials file inside `~/.claude`, and the whole directory is the mount, so the room and the host read and write the same file; Codex rewrites `auth.json` in place. A refresh on either side is a refresh for both, as with two sessions on the host. `/login` and `codex login` work in the room, and log the host in with it.
  - The first lup copied the login into a volume per repository, so every copy held the same refresh token. When one refreshed, the provider rotated the token and stranded the others, so a companion copied the newest into every copy every 30 s, with races it never closed, and sessions that silently changed accounts. With one copy, none of that exists.
  - A token from `claude setup-token`, the alternative, needs a step on the first run, and keeps Claude Code's own login flow out of the room.
- **History is the operator's own.** Each runtime keys its sessions on the working directory's path, which is the same in the room, so `lup-dev launch claude --resume` finds the earlier sessions, and the host's `claude --resume` sees the room's.
- **The operator's preferences carry in.** `~/.claude/settings.json` holds the theme, model, editor mode and the like, with no hooks or plugins (checked), and loads in the room as the user's settings.
- **What changes in the room:**
  - Claude Code's state file (`~/.claude.json`: onboarding, folder trust) is the room's own, written fresh into the room's home at each launch with onboarding done and the repository trusted, so concurrent starts can't race on the operator's (16 starts on one file left the first lup with `{"autoUpdates": false}`);
  - the account's connectors, which arrive with the login (claude.ai's Google Drive, with its share and trash tools, connected in the spike; Codex's apps are the same thing), aren't fetched in the room unless the declaration asks for them (*The settings compiled for each runtime*);
  - Codex's plugins and the operator's own MCP servers are off in the room: they're set up for the host (`node_repl` points into the ChatGPT desktop app);
  - Codex runs with `--no-daemon`, apart from the host's daemon on the same home.
- **What the agent can read:** the login and every transcript in those directories. lup isn't containing the agent, and the login is the runtime's own, readable by any session without a container today.

## The settings compiled for each runtime

lup's settings reach each runtime as flags and files of the launch's own, never written into the operator's directories or the repository.

| What | Claude Code | Codex |
|---|---|---|
| Where they go | `--settings <launch>/settings.json`, with `--setting-sources user`: the operator's `~/.claude/settings.json` loads, and the repository's `.claude/settings.json`, `.mcp.json`, skills and `CLAUDE.md` don't | `-c` overrides on the operator's home, with `--no-daemon` |
| No prompts: the room is the wall | `--permission-mode bypassPermissions`, and `skipDangerousModePermissionPrompt` (already in the operator's settings, and in lup's) | `--dangerously-bypass-approvals-and-sandbox`, which is `-s danger-full-access -a never` |
| First-run screens | the room's own `~/.claude.json`: onboarding done; the worktree and the main repository trusted (Claude Code asks about the main repository for a linked worktree) | `projects` with each trusted, as an inline table: a dotted `-c` key splits at every `.`, which breaks a path like `lup.git` |
| The one hook | `hooks` in the launch's settings | lup's hooks as managed hooks, in an `/etc/codex/requirements.toml` the launch mounts into the room, with `allow_managed_hooks_only` so no other hook runs **(leaning)**; or else `--dangerously-bypass-hook-trust` |
| Session settings | `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h`, the removed tools as bare names in `permissions.deny` | memories off |
| What the room turns off | the account's connectors, unless the session settings ask for them: `disableClaudeAiConnectors`, so none is fetched | the account's connectors (Codex's apps), unless asked for: `features.apps = false`; `features.plugins = false`, which also stops a sync from GitHub at each start; each of the operator's MCP servers disabled by name |
| lup's own needs | `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`, so a held call isn't moved to the background after 2 minutes (piece 3); `DISABLE_AUTOUPDATER` | `check_for_update_on_startup = false` |
| Guidance | `--append-system-prompt-file <launch>/guidance.md` | `developer_instructions`, with `project_doc_max_bytes = 0` |

- **Session settings are `Core`'s `session` part,** in neutral terms each adapter spells: the subagents' prompt cache, auto memory, and the built-in tools removed from context (`DESIGN.md`, *Sessions*). lup's own needs aren't a project's to change, since lup's mechanisms rely on them.
- **The account's connectors are a session setting** (`account_connectors`, off by default): the tools an account's claude.ai connectors or Codex's apps bring reach the operator's mail and files, so a room fetches none unless its declaration turns them on. A module passing through only the connectors a project chooses can build on it later.
- **The removed tools are measured, not guessed.** An interactive session carries 113 KB of built-in tool schemas, `Artifact` alone 55 KB. The default list starts from the five lup's own settings remove today (`Artifact`, `SendFeedback`, `Workflow`, `ScheduleWakeup`, `ReportFindings`) and the native worktree tools `DESIGN.md` denies (`EnterWorktree`, `ExitWorktree`), while its native messaging tools (`SendMessage`, `ListAgents`) stay with the native `Agent` until lup's spawn exists, since a session resumes a subagent it started through them; the first live room's `/context` then shows what else weighs and goes unused (`CronCreate`, `RemoteTrigger`, `PushNotification`, `NotebookEdit` and `DesignSync` are the candidates), and the list is set from it.
- **Native subagents stay on until lup's spawn exists.** `DESIGN.md` denies the native `Agent` and Codex's subagent tools by default, in favour of lup's spawn. Denied now, a session couldn't delegate at all. The deny becomes the default in the spawn piece.
- **Codex's built-in tools can't be removed by name** (0.162.1 has no setting for it), only by whole feature groups, so the removed tools are Claude Code's alone, a gap the launch states.

## Guidance

- **One document, rendered at launch** from the selected modules' `guidance` sections, in module order, with Jinja (`DESIGN.md`, *Guidance and skills*). A section names the project's commands through the runner (`{{ run("lup-dev check") }}` becomes `uv run lup-dev check`), so no section spells uv. Rendering refuses a section naming a command the project doesn't serve (`docs/declaration.md`, *Later*). Jinja is a new dependency of `lup-dev`.
- **Delivered at system level, on both runtimes:** Claude Code's `--append-system-prompt-file`, its documented route for instructions that must hold, where any `CLAUDE.md` arrives as a user message "with no guarantee of strict compliance"; Codex's `developer_instructions`, which opens the first developer message. It's always in context, one text with one order of precedence, rather than fragments from several files that may disagree.
  - The first lup mounted its rendered guidance over a committed `.claude/CLAUDE.md`, so a repository needed a runtime tree committed, and a launch refused without one. A `CLAUDE.md` in the operator's home would be shared by every launch, where two projects running at once need two.
- **The project's own guidance is its declaration's section:** lup's own names `AGENTS.md`. A gitignored `AGENTS.local.md` beside it, if there is one, is appended after it as the person's own section, so it wins where the two differ **(leaning)**. In a launched session, the runtimes' own loading of the repository's `CLAUDE.md` and `AGENTS.md` is off, so one text reaches both runtimes and nothing is loaded twice; Codex would also cut an `AGENTS.md` past 32 KiB without a word, which lup's own rules forbid. Outside lup, the runtimes still load the repository's files as before. Nothing is kept in memory: auto memory is off on both runtimes.
- **What lup's sections say in this piece:** `Core`'s, the room (what's mounted, that pushing and GitHub wait for piece 2, what's the agent's to decide and what's the operator's); `Python`'s, the runner and the gate; `CodeRules`', refusals and the `# lup:` grammar. Guidance is written once the system it describes exists, and reviewed after it lands (`DESIGN.md`, *Policy*); each later piece adds its own.
- **Skills** compile from the modules' `skills` part into a directory of the launch's, on both runtimes, once a module ships one. None does yet.

## The one hook and the host service

### In the room: a pipe

Each hook command is `socat -t <hours> - UNIX-CONNECT:/run/lup/hook.sock`. It sends the runtime's payload unchanged and prints the answer, so nothing in the room parses it. The host service runs the runtime's adapter on it (`adapter.hook(payload, bench)`), exactly as `lup-dev hook` does today.
- **The judge stays on the host,** for practical reasons, not to guard it:
  - the judge asks a warm engine per worktree, a pyright process; on the host it's shared with the operator's own gate runs, where in each room a cold one would make the first edit wait for the whole project to type-check;
  - the installed judge, the one the operator approved, is the one that judges; in the room it would be the project's own copy, so a branch reshaping the judge would judge with its own edits;
  - holds wait for the operator's answer, which comes from the host.
- **If the host service is down,** socat fails. Claude Code's hooks reference takes a command's failure with any status but 2 as a non-blocking error: the call goes on, and the error shows. That's the intended outcome, since the judge steers and doesn't guard (`DESIGN.md`, *Policy*); what Codex does is a check owed.
- **The events** are today's: Claude Code's `SessionStart`, and `PreToolUse` on Edit and Write; Codex's `SessionStart`, `PreToolUse` and `PostToolUse`, since Codex is judged after each call. Piece 3 removes the checkpoint and reshapes the rest. The timeout is hours, for holds: Claude Code documents no maximum for a command hook, and Codex took 99999 s.
- **A protected path's ask on Claude Code** is the runtime's own prompt today. Whether a hook's `ask` still prompts under `bypassPermissions` is a check owed. If it doesn't, a room's Claude Code is judged as a runtime that can't ask before a call (`Runtime.asks_before`), and the change is held until it's answered with `lup-dev holds`, as on Codex.

### On the host: the service

The host service is a program lup runs on the operator's machine, outside every room, which rooms call for what only the host can do: in this piece, the judge for each hook; in piece 2, the inbox, and pushes and GitHub with the operator's credentials; later, spawning sessions, budgets, and the dashboard's backend (`DESIGN.md`, *The environment: core and modules*).
- **One per user,** the installed `lup-dev`'s, started by the first launch that finds none, and running until it's stopped: found or started on demand, as the engine is.
- **A socket per launch,** in a directory of its own, mounted into that launch's room at `/run/lup`. The service knows which launch speaks by the socket it hears it on, and the socket goes with the launch. Seen through `SO_PEERCRED`, a room's process has the operator's uid (keep-id), so the uid can't tell a room from the operator; the socket can.
  - One socket for every room would have each request name its launch, which the room would then say of itself.
  - HTTP on localhost, reachable from rooms on the host's network, would be reachable by every process on the machine, and couldn't tell rooms apart.
- **Its control is a socket on the host only,** taking typed requests: one JSON request per connection, a pydantic model discriminated by `kind`, and one JSON reply. In this piece the kinds are a launch's registration and its end, and stopping the service. Modules register the handlers for their kinds; piece 2 adds the inbox's, and the socket lup's MCP server reaches from the room.
  - A handler (`Handler`) names the model of its requests and answers each on the event loop; `Route.to(handler)` routes its kind there, read from the model, so the kind is spelled once. A handler's requests and replies are its module's own models, beside it, so a kind is added without editing the service or the protocol **(leaning)**. A closed union of every kind in `host/protocol.py` would have each module add its models there. Two handlers for one kind are refused when the service is built.
  - What the service can't carry out is replied as `Refused`, with why: a request that doesn't parse, a kind no handler answers, a launch registered twice or running a runtime lup doesn't know, ending a launch that isn't served, and a handler's failure, which is said with its traceback.
- **Each hook is answered in a thread of the service's pool** (256 by default), off the event loop, with the answerer `cli.py` builds from the adapters and `Bench`, which `lup-dev hook` answers through too. A hold holds its thread while it waits. A failed answer (a payload that doesn't parse; the adapters answer judging's own failures in the hook's terms) is said with its traceback, and the connection closes unanswered: socat prints nothing and ends with status 0, which the runtime takes as no decision. Where `lup-dev hook` failing ends with status 1, a non-blocking error the runtime shows, as socat's does when no service listens (measured: 0 closed unanswered, 1 with no service).
- **A launch outlives a restart of the service (leaning).** Each launch is recorded beside its socket directory, under lup's runtime directory, and a service started after one stopped serves every recorded launch again, binding `hook.sock` in the directory the room mounted. A stop closes the sockets and keeps the records; a launch's end removes its record and its directory, with whatever the room left in it. A launch whose launcher died without ending it stays recorded and served: nothing yet tells it's gone.
- **One service runs at a time:** it holds a lock for its whole life, which the OS frees, so a second `lup-dev host` refuses, naming the socket; a control socket left by a service that died is replaced. Launches starting at once may each start one; all but the first refuse, and each client waits until the socket answers.
- **A stop doesn't wait for the answers in flight (leaning):** the sockets close at once, the next service may start, and the answers' threads finish before the old process exits, so a hold is still answered and logged as usual, but its hook hears nothing.
- **Started detached** by the client, as `python -m lup_dev.cli host` with the interpreter running the client **(leaning)**: the installed `lup-dev`'s whenever the launch runs from it. What it prints is appended to `service.log` in lup's state, which the client names when it doesn't answer in time.
- **Its waits go through `lup_dev.clock`,** so its tests drive time: the client waits up to 10 seconds for a service it started to answer, and for one it stopped to be gone.

## Modules and public API

### The library

`DESIGN.md` says one declaration compiles to SDK options for code and to a command line for a terminal, and that a room wraps an agent with a wall (*The library*). So the terminal compile and the room are the library's, and the environment's maintaining session is a room it declares.

```python
from lup import Claude
from lup.rooms import Container, Image, Mount, Room

room = Room(
    agent=Claude(model="opus"),
    container=Container(
        image=Image(definition=CONTAINERFILE),
        mounts=[Mount(source=repository), Mount(source=hooks, read_only=True)],
        network="host",
    ),
)
status = room.launch(arguments=["--resume"], settings=settings)   # a terminal; returns the CLI's exit status
```

| File | What it's for | Public names |
|---|---|---|
| `rooms/container.py` | What a room's wall is made of | `Container` (`image`, `mounts`, `env`, `network`), `Image` (`definition`, tagged by its digest), `Mount` (`source`, `target`, `read_only`), `Mask` (a tmpfs hiding what's under it) |
| `rooms/engine.py` | Running containers | `ContainerEngine`, an ABC (`ensure`, `run`); `Podman`, its one implementation; `ContainerError` |
| `rooms/room.py` | An agent behind a wall | `Room` (`agent`, `container`), `launch` |
| `sessions/terminal.py` | A declaration compiled for a terminal, in neutral terms | `TerminalSettings` (`cli`, `hooks`, `guidance`, `session`, `trusted`), `Hook` (`event`, `matcher`, `command`, `timeout`), `SessionSettings`, `Terminal` (`command`, `env`, `files`, `mounts`) |
| `adapters/claude/terminal.py`, `adapters/codex/terminal.py` | Each runtime's spelling of a terminal: its flags, its files, the mounts its home needs, what a room turns off | none beyond the declaration's method |

- **`Declaration.terminal(settings) -> Terminal`,** implemented by `Claude` and `Codex`, compiles the declaration's model and effort as the runtime spells them, with the settings above. `settings.cli` names the binary; none takes the one the SDK bundles, as an ask does. In a terminal, `system_prompt` replaces the runtime's prompt as it does in an ask, and none keeps the runtime's own **(leaning)**: a terminal session is the runtime's coding agent, which an empty prompt would leave without its tools' guidance, where an ask with no prompt sends none.
- **`Room` gets `launch` alone in this piece;** it becomes an `Agent`, with `ask` and `spawn` in a container, in the slice that runs rooms from code, as a field arrives with the slice that uses it (`docs/library.md`, *What a declaration holds*).
- **The engine is a seam:** tests use a recording engine, so no test runs podman. Running podman needs only the standard library; the library gains no dependency.

### The environment

| File | What it's for |
|---|---|
| `launch/room.py` | The maintaining session's room from a resolved declaration: the image's definition, the repository's mounts, the runner's, the operator's runtime directory, the CLI, lup's cache, the editor's configuration, the launch's directories, the git identity and the terminal's variables |
| `launch/images.py` | The image's definition from the base and the modules' packages; building through the engine; the build record; removing the project's older images |
| `launch/clis.py` | The latest CLI from each vendor's release channel: the version check, the download and its checksum, the cache, keeping the current version and the one before |
| `launch/logins.py` | The operator's runtime directory in the room: the room's own Claude Code state file, and what the room turns off |
| `launch/guidance.py` | Rendering the modules' guidance sections, and a local section, into one document |
| `launch/session.py` | A launch's `TerminalSettings`: the hooks, `Core`'s session settings, the guidance, what's trusted |
| `host/service.py` | The host service (`HostService`): the control socket, a hook socket per launch answered through the `Answerer` seam, the launches recorded for the next service, the handlers modules register (`Handler`, `Route`) |
| `host/protocol.py` | The control requests and replies (`Register`, `Unregister`, `Stop`; `Registered`, `Done`, `Refused`), and `HostError` |
| `host/client.py` | Finding the service, or starting it (`HostClient`; `Starter`, and `Detached`, which starts `lup-dev host`) |
| `catalog/room.py` | lup's base image and its pinned snapshot date, the standard machine's packages, the default session settings |
| `launch/trust.py` | The host zone, its fingerprint, the copy approved, the diff shown and the answer asked, and installing an approved copy |
| `cli.py` | `launch claude\|codex` and `host [stop]`, until slice C gives each command group its file; `install` goes |

The declaration's slice A gains:
- the `Packages` kind, each module's `packages` part, and `Core`'s default, the standard machine;
- the `Session` and `Guidance` kinds, `Core.session`, and each module's `guidance` part, as `docs/declaration.md` (*Later*) reserves for the launch piece;
- `Requirement.package`;
- `Runner.room()`.

The list of adapters `cli.py` holds moves where the host service reads it too, as slice C plans (`commands/runtimes.py`). `lup-dev` downloads through `httpx`, already its dependency; Jinja is its one new dependency.

## Tests

- Each runtime's terminal compile, for a sample declaration and settings: the command, variables, files and mounts, compared whole.
- The maintaining room for a sample declaration: the image's definition from its modules' packages and requirements, byte for byte; the mounts and variables; each refusal (an environment on a system interpreter, a requirement with no package and no mount).
- The CLI cache through a stubbed HTTP client: a newer version fetched and checked, a bad checksum refused, the cached version used offline, older versions removed.
- The engine through a recording fake: no podman in any test.
- The host service on a socket under the test's temporary directory, with a stub answerer: a payload in and the answer out; parallel payloads answered at once, and the control socket answering while a hold waits; a launch's socket gone with the launch; stopping, and a service started again serving the recorded launches in their directories; a second start finding the first; a stale control socket with no service behind it; refusals; a module's handler; and the answer the same as `lup-dev hook`'s. Unix sockets are local, not network.
- Guidance: sections in module order, a local section after the project's, the runner's spelling, a section naming a command the project doesn't serve refused.
- **Live, by hand, before landing,** on a scratch project and on each runtime: a first launch reaches the prompt with no screen to dismiss and no login; an Edit with a rule finding is refused through the room's hook; a protected path asks or holds (*Checks owed*); `uv run lup-dev check` passes in the room; `--resume` finds the session before it; an agent's preview server opens in the host's browser; Ctrl+G opens the editor.

## Checks owed

- **Claude Code:**
  - whether a `PreToolUse` hook's `ask` prompts under `bypassPermissions`;
  - whether `--settings` still applies with `--setting-sources user`;
  - whether a fresh `~/.claude.json` beside the operator's `~/.claude` opens logged in, with no screen at all (the theme picker among them);
  - whether the lock files Claude Code keeps in `~/.claude` with process ids behave when a room's process ids mean nothing on the host;
  - that `disableClaudeAiConnectors` keeps every connector of the account out of the room.
- **Codex:**
  - managed hooks through a mounted `/etc/codex/requirements.toml`, with `allow_managed_hooks_only` dropping every other source;
  - the room's `--no-daemon` beside the host's daemon on the same home;
  - what a failing hook command does to the call.
- **Both:**
  - a hook held for hours through socat;
  - each vendor's release channel: where the latest version and its checksum are published.

## Building it

After the declaration's slice A, on one branch, `feat-launch`:
1. the library's rooms and each adapter's terminal compile;
2. slice A's new parts: `Packages`, `Session`, `Guidance`, `Requirement.package`, `Runner.room()`;
3. the host service, and the hook through it;
4. trust on launch, the CLI cache, the maintaining room, the logins, guidance and the command;
5. the live checks, and what they find recorded in `docs/field-notes.md`.

lup's own sessions move onto launch once piece 2 lands, since before it a launched session can't push. The committed `.claude/settings.json`, `.claude/hooks/` and `.codex/hooks.json` then go, in a change to protected paths the operator makes.
