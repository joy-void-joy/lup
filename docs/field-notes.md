# Field notes: facts that were expensive to learn

Measured or read from source, each with the version it holds for. When a runtime's version changes, its entries are checked again. The design is `DESIGN.md`.

## Claude Code 2.1.291

- **Caching.**
  - Prompt-cache lifetimes are only 5 minutes or 1 hour (an API limit). The main conversation gets 1 hour on a subscription; everything else gets 5 minutes, unless `subagentPromptCacheTtl: "1h"` is set (or `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`). The setting is ignored while a subscription is in overage.
  - A cache read resets the timer, and the lifetime counts from the start of a request. Only a request resets it: a blocking hook or tool call makes none, so a hold past the hour rebuilds the context.
  - Every turn re-reads the whole context, so a long session's cost grows roughly with the square of its length.
  - Opus 5.5 prices: input $4 per million tokens, 5-minute write $5, 1-hour write $8, read $0.20, output $20.
  - A built-in cache keepalive exists for the main conversation only, behind a server flag; it did not run in our probe.
- **Tools.**
  - A bare tool name in `--disallowedTools` or `permissions.deny` removes the tool from context, subagents included.
  - Print mode never loads `Artifact`.
  - An interactive session carries 113 KB of built-in tool schemas, of which `Artifact` is 55 KB. Claude Code's own system prompt is about 7.5 KB.
  - `autoMemoryEnabled: false` removes the memory section from the system prompt.
  - Edit refuses a file that wasn't opened with Read first: 894 "File has not been read yet" errors in the measured week, 785 of them after a read through `sed` or `cat`.
- **Sessions.**
  - `--agent Explore` runs a top-level session as that built-in type.
  - `--resume <id> --fork-session` forks a session.
  - `--bg`, `claude agents --json`, `attach`, `logs`, `stop` and `respawn` manage background sessions. Sessions in other containers aren't visible.
- **Other flags.**
  - `--autocompact <tokens>` sets the compaction window (100k to 1M).
  - `--system-prompt` replaces the whole prompt, tool guidance included.
  - `--bare` requires an API key.
  - `--json-schema` gives native structured output in print mode.
  - `--debug` writes to a log file, not the screen (`--debug-file <path>` names it).
- **Nested runs.** A nested `claude -p` does not inherit the outer session's `--plugin-dir`, but it does load the parent directory's `CLAUDE.md` and a nested repository's own `.claude/settings.json`.
- **Hooks.**
  - `updatedInput` takes effect, and `additionalContext` reaches the model.
  - A PreToolUse hold of 4 hours ran cleanly.
  - Each Bash call runs as `bash -c` in its own process group.
  - aib found that an `updatedInput` is discarded when a later hook overwrites it, so a submission gate must run last.
  - A PreToolUse hook that returns no decision sends the call through the normal permission flow. Its `ask` forces a prompt even in auto mode. Its `defer` pauses a headless run to resume later, and is ignored when several calls run at once.
  - A bare `permissions.ask` rule on `Write` prompts in auto mode (2.1.292).
  - PostToolUse hooks for parallel calls run concurrently. `PostToolBatch` fires once after a batch. `updatedToolOutput` replaces a built-in tool's result before the model sees it (hooks docs).
  - Command hooks get no terminal. `statusMessage` sets the spinner text while a hook runs.
  - Hooks are read when a session starts; a change to them reaches sessions started afterwards.
- **Permissions.** Claude Code's auto mode refuses an agent's write to its own `.claude/settings.json` as self-modification, whatever lup's judge allows.
- **Subagent writes.** Claude Code may refuse a subagent's write of a report file ("Subagents should return findings as text").
- **Terms.** OAuth is for ordinary use of Claude Code and Anthropic's own apps. Tokens may not be intermediated. Products used by other people need API keys. Plan limits assume ordinary individual use.

## The Claude Agent SDK 0.2.165 (bundling Claude Code 2.1.294)

Read from its source and checked against the bundled CLI with a scripted fake Messages API.
- Only `ClaudeSDKClient` can interrupt; `query()` runs the same protocol, with in-process tools and hook callbacks too.
- `tools=[]` removes every built-in tool. `allowed_tools` only pre-approves; `permission_mode="dontAsk"` denies whatever isn't pre-approved.
- `setting_sources=[]` loads no settings files, but auto memory is read regardless: `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` turns it off.
- `verbatim_prompts=True` stops `@path` expansion and slash commands; without it, `@/etc/hostname` in a prompt attached the file, even with no tools.
- There's no field for session persistence: `extra_args={"no-session-persistence": None}` works under the SDK, and no transcript is written.
- `create_sdk_mcp_server` validates a call's arguments with jsonschema before the handler runs, and answers the refusal itself.
- The init message lists skills, plugins and agents even when no tool can call them; only its `tools` and `mcp_servers` say what the model can call.
- A Stop hook answering `{"decision": "block", "reason": …}` continues the turn with the reason. Eight consecutive blocks are honoured and the ninth overridden (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` changes it); any tool call resets the count. Stop doesn't fire on an interrupt or an API error.
- Not logged in surfaces as `AssistantMessage.error="authentication_failed"` with `api_error_status=None`; a 529 as `error="server_error"` with `api_error_status=529`; a 429 as `error="rate_limit"`.
- `ClaudeSDKClient` raises nothing on an error result, so the caller reads `ResultMessage.is_error`; `query()` raises `ResultError` after yielding it.
- `RateLimitEvent` wasn't emitted for an API key's 429; how a subscription's spent window surfaces is unverified.
- An interrupt yields `ResultMessage(subtype="error_during_execution", terminal_reason="aborted_streaming")`, and raises nothing.

## Claude Code 2.1.295: what a hook can do to a file tool

From a spike: `claude -p --model haiku` with `PreToolUse` and `PostToolUse` hooks on Write, Edit and Read.
- A `PreToolUse` `allow` with `updatedInput` pointing a Write at another path lands it there; the result reports success and names the new path.
- `PostToolUse`'s `updatedToolOutput` replaced an Edit's result text before the model saw it.
- Claude Code checks an Edit against the path the agent gave, before any hook runs: the file must exist, have been read, and hold `old_string`. Those rejections fire neither `PreToolUse` nor `PostToolUseFailure` (hooks reference), so only the execution can be redirected ("File does not exist.", "String to replace not found in file.").
- A redirected Edit needs no Read of the path it's redirected to; once that file was moved into place, the real file could be edited without a fresh Read.
- A redirected Read shows the redirected file, and counts as reading both paths.
- A hook's `allow` doesn't approve a write into a directory Claude Code protects (`.git`, `.claude`, `.vscode`, `.husky`, `.devcontainer` and others), at any depth of the redirected path; in `-p` the prompt is a refusal ("Claude requested permissions to edit … which is a sensitive file."). Allow rules can't pre-approve one either: "The safety check runs before Claude Code evaluates allow rules from settings". Protected files include `pyrightconfig.json`, `bunfig.toml`, `lefthook.yml` and the Gradle and Maven wrappers' `.properties`.
- Unchecked: whether `PostToolBatch` can explain a refused Edit; whether protected file names match at any depth; whether a `PermissionRequest` hook's `allow` approves a protected-path prompt.

## MCP servers, from the runtimes' docs

- **Claude Code:**
  - a project's server is declared in `.mcp.json` and approved with `enabledMcpjsonServers` in a trusted folder, read when the session starts;
  - a call's time limit is the server's `timeout` (ms), else `MCP_TOOL_TIMEOUT`, else about 28 hours; a stdio call with no response and no progress notification for 30 minutes aborts, and a per-server timeout of at least 1000 ms floors that window (2.1.203 and later);
  - a main conversation's MCP call still running after 2 minutes moves to the background unless `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`; a subagent's calls never move;
  - the server learns only `CLAUDE_PROJECT_DIR`, not the session or the subagent;
  - `PreToolUse` and `PostToolUse` fire for MCP tools (`mcp__<server>__<tool>`), and `updatedInput` replaces the arguments.
- **Codex:** servers go in `[mcp_servers.<name>]` in `.codex/config.toml`, trusted projects only; `tool_timeout_sec` defaults to 60 s per the docs but 300 s in the source (`codex-mcp/src/rmcp_client.rs:104`); `approval_mode` is `auto`, `prompt`, `writes` or `approve`; no idle limit or backgrounding is documented; `PreToolUse` fires for MCP tools, and `updatedInput` replaces the arguments.

## Codex 0.156.1: what a hook can do to a patch

Read from its docs and its source at `rust-v0.156.1`; nothing run.
- `PreToolUse` can rewrite `apply_patch`, shell and MCP calls by answering `allow` with `updatedInput`: for Bash and `apply_patch` it carries `command`, for MCP tools the replacement arguments (`core/src/tools/handlers/apply_patch.rs:466-479`; test `pre_tool_use_rewrites_apply_patch_before_execution`).
- The hook sees only the patch text, not a list of files (`apply_patch.rs:459-463`).
- A patch sent through the shell (`apply_patch <<EOF`) fires `PreToolUse` as `Bash`, not `apply_patch` (`unified_exec/exec_command.rs:378-405`).
- An `*** Update File:` needs its target to exist (`apply-patch/src/file_update.rs:34-45`).
- `PermissionRequest` can't rewrite: its `updatedInput` fails closed (`hooks/src/engine/output_parser.rs:401-414`).
- `PostToolUse` can't undo side effects from a tool that already ran.

## Codex 0.160.1

- its own memories feature, off by default;
- no prompt-cache lifetime setting;
- no way to remove a built-in tool by name;
- the spawn argument is `task_name`;
- `turn/interrupt` responds in about 10 ms;
- `write_stdin` fires no hook;
- `outputSchema` is the shape of the final message, not a tool call.

## The Codex SDK, `openai-codex` 0.162 (bundling codex-cli 0.162)

Read from its source and checked against the bundled binary with a local mock Responses endpoint; no live model run yet.
- Only the low-level `openai_codex.client.CodexClient` takes a server-request handler, and it runs synchronously on the client's one reader thread: a request through the same client from inside it deadlocks.
- Dynamic tools are declared on `thread/start` only, fixed for the thread's life; a call arrives as the server request `item/tool/call` and is answered `{"contentItems": [...], "success": bool}`.
- `thread/start` takes no `effort`; it goes on `turn/start`.
- `environments: []` disables environment access; `agents.enabled=false` in the thread's config removes the subagent tools; web search, skills, the built-in instructions and features are launch `-c` overrides (listed in `docs/library.md`).
- The default model `gpt-6.1-sol` and about ten others are `code_mode_only`: every tool, lup's included, sits behind a JavaScript `exec` tool, with `wait` and `request_user_input_async`; no setting removed them. Other models, such as `gpt-5.4`, carry only the declared tools.
- `exec` reaches nothing beyond the declared tools (probed on 0.162 against a mock endpoint): no `fetch`, `require`, `process`, `Deno`, `WebSocket`, `Worker` or `WebAssembly`; every import refused ("unsupported import in exec"); none of the built-in tools (`exec_command`, `shell`, `apply_patch`, `spawn_agent`, `web_search`, `view_image`). Its nested tools are the declared ones (called as `await tools.submit({...})`), `clock__curr_time`, and MCP resource readers that return nothing without servers. `request_user_input_async` answers `{"accepted": true}` and sends the client nothing. Turning `features.code_mode_host` off makes `exec` answer "code-mode host is disabled", so the declared tools become unreachable.
- With `baseInstructions: ""`, a thread sends no developer message at all; leaving it out sends Codex's 17 KB coding-agent prompt. A project's `AGENTS.md` isn't injected into an app-server thread.
- `thread/tokenUsage/updated` fires per model request and on turns that made none: a turn's usage is the change in `total`. Codex reports no cost.
- `usageLimitExceeded` carries its reset time only in the global notification `account/rateLimits/updated` (`rateLimits.primary.resetsAt`); the message's "try again at" is local-time text.
- `auth.json` is written through a symlink under the `file` credentials store; under `keyring` or `auto`, a refresh deletes it. A keyring login is keyed on the canonical `CODEX_HOME` path, so it isn't visible from another home.
- The SDK's high-level `TurnResult` raises a plain `RuntimeError` for a failed turn, losing `codexErrorInfo`, and reports a thread's usage snapshot.

## Claude Code 2.1.296: launching a session

From the docs (code.claude.com, `cli-reference`, `settings-reference`, `env-vars`, `permission-modes`, `permissions`, `memory`, `mcp`, `hooks`, `authentication`) and the CLI's help; nothing run interactively.
- **Settings outside the repository.**
  - `--settings <file>` sits above the user, project and local files and below managed settings; it can set any key a user settings file can.
  - `--setting-sources user,project,local` chooses which files load. Leaving out `project` drops `.claude/settings.json` and its hooks, `.mcp.json`, the project's skills, commands and agents, and (per the SDK's table) its `CLAUDE.md`.
  - Whether `--settings` still applies with sources left out is undocumented.
  - Hooks and arrays merge across files rather than replacing each other.
- **Guidance.** `--append-system-prompt-file` works interactively and is the documented route for system-level instructions. `CLAUDE.md` arrives as a user message after the system prompt, with "no guarantee of strict compliance"; conflicting layers have no precedence ("Claude may pick one arbitrarily"). `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` stops every `CLAUDE.md`; `claudeMdExcludes` takes absolute-path globs.
- **`CLAUDE_CONFIG_DIR`** holds settings, credentials, transcripts (`projects/<project>/<session>.jsonl`), auto memory, file history, skills and plugins.
  - Folder trust is `projects["<path>"].hasTrustDialogAccepted`.
  - The bypass warning is pre-answered by `skipDangerousModePermissionPrompt`, scoped to user, local or managed settings.
  - `hasCompletedOnboarding` is undocumented but present in the binary.
- **A long-lived login.** `claude setup-token` prints a one-year subscription token, read from `CLAUDE_CODE_OAUTH_TOKEN`. It "can only make model requests": no Remote Control and no claude.ai connectors. It writes no file.
- **No prompts.**
  - `--permission-mode bypassPermissions` refuses to run as root unless "inside a recognized sandbox". In the binary that's `IS_SANDBOX=1` or `CLAUDE_CODE_BUBBLEWRAP`, both undocumented.
  - In bypass mode:
    - deny rules still apply, and so do explicit ask rules;
    - writes to protected directories (`.git`, `.claude`) are allowed;
    - whether a hook's `ask` prompts is undocumented.
- **Tools.** `--tools` restricts the built-in tools, interactively too; `--disallowedTools` and `permissions.deny` with a bare name remove a tool from context.
- **MCP.**
  - `--mcp-config` servers need no approval.
  - A server's `timeout` (ms) is a wall-clock limit per call that progress doesn't extend.
  - `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (30 minutes for stdio) is reset by a progress notification.
  - `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` keeps a main conversation's long call in the foreground; a backgrounded call is lost when the session exits.
- **Hooks.** A command hook's `timeout` is in seconds, default 600, with no documented maximum.
- **PDFs.** Read renders a PDF's pages with poppler's `pdftoppm`; without it: "pdftoppm is not installed. Install poppler-utils … to enable PDF page rendering" (in the binary).
- **The native build** (`~/.local/share/claude/versions/<version>`) links only glibc.
- **Variables:**
  - `CLAUDE_CODE_DISABLE_AUTO_MEMORY`;
  - `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`, which outranks the setting;
  - `DISABLE_AUTOUPDATER`;
  - `DISABLE_TELEMETRY`;
  - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.

## Codex 0.162.1: launching a session

From the source at `rust-v0.162.1` (paths under `codex-rs/`), probed with `codex debug prompt-input` and `app-server`'s `hooks/list` against scratch homes; no model called.
- **`CODEX_HOME`** must exist, and not under a temporary directory: Codex then refuses to make its helper links ("Refusing to create helper binaries under temporary dir"). It holds `config.toml`, `auth.json`, `hooks.json`, `AGENTS.md`, `sessions/`, `session_index.jsonl`, six SQLite databases, logs and caches.
- **`config.toml`.**
  - Codex writes trust, hook trust and first-run counters back into it, following a symbolic link and replacing the target atomically.
  - The interactive CLI always loads `$CODEX_HOME/config.toml`, so only a separate home keeps the operator's file unloaded.
  - `--profile <name>` layers `$CODEX_HOME/<name>.config.toml` over it.
- **`-c` overrides.** `-c` splits a key at every `.` and keeps quotes, so `-c 'projects."<p>".trust_level=…'` does nothing; the inline table `-c 'projects={"<p>"={trust_level="trusted"}}'` works.
- **The login.**
  - Under the `file` store, `auth.json` is rewritten in place (truncated, never renamed), so a symbolic link or a one-file bind mount shares one login.
  - Codex re-reads the file before refreshing and skips a refresh another process made, but no lock spans processes. Two refreshes at once can race, and the loser's token is marked spent (`refresh_token_reused`).
  - `CODEX_ACCESS_TOKEN` and `CODEX_API_KEY` exist.
- **The daemon.** The interactive CLI starts a background app-server per home, which keeps "file settings and defaults" until it restarts. `--no-daemon` turns it off, as do `--profile` and most `-c` keys.
- **Hooks.**
  - Sources:
    - Hooks load from every enabled layer: the home's `hooks.json`, a project's `.codex/hooks.json` (only once the project is trusted, read from the main checkout for a linked worktree), and a `[hooks]` table in any `config.toml`, the `-c` layer included.
    - Turning a project's trust on also turns its `.codex/` back on.
  - Hook trust:
    - A hook runs only once trusted: a `trusted_hash` (sha256 of its event, matcher and handler) recorded in the user or `-c` layer, or `--dangerously-bypass-hook-trust`.
    - Untrusted hooks put a review screen before the session.
  - Managed hooks: those in `/etc/codex/requirements.toml` need no review, and `allow_managed_hooks_only` there drops every other source (read in source, not probed).
  - Events: PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, SessionStart, SessionEnd, UserPromptSubmit, SubagentStart, SubagentStop, Stop and Interrupt.
  - `timeout` has no maximum (99999 s accepted), but SessionEnd and Interrupt are clamped to 1–3 s.
- **MCP.**
  - Approvals:
    - Under `approval_policy = never`, a tool without `readOnlyHint` is refused ("MCP tool call requires approval, but approval policy is never") unless the sandbox is full access or the server sets `default_tools_approval_mode = "approve"`.
    - Only a server declared in a project's own `.codex/config.toml` needs the project trusted.
  - Timeouts:
    - `tool_timeout_sec` has no cap and defaults to 300 s in the source (60 s per the docs).
    - Progress notifications are only logged and don't extend it.
  - Environment: a stdio server gets only a short list of variables (HOME, PATH, LANG, TERM, TZ and a few more), plus those named in `env_vars`.
- **Guidance.**
  - `developer_instructions` opens the first developer message.
  - `model_instructions_file` replaces Codex's own instructions.
  - The project's `AGENTS.md` is read from the root down to the working directory, and silently cut at `project_doc_max_bytes` (32 KiB); `0` turns it off.
- **No prompts.** `--dangerously-bypass-approvals-and-sandbox` is `-s danger-full-access -a never`. The trust screen appears unless the working directory, its project root or its main repository is trusted.
- **Off switches:**
  - subagents: `agents.enabled = false`, with `features.multi_agent_v2` off, since it wins;
  - web search: `web_search = "disabled"`;
  - update checks: `check_for_update_on_startup = false`;
  - analytics and feedback: `analytics.enabled`, `feedback.enabled`;
  - the GitHub sync at start: `features.plugins = false`.
- **Built-in tools** can't be removed by name, only by whole feature groups.

## Rooms

### podman 6.1.3, rootless: the CLIs in a container (measured)

- **The image.**
  - `archlinux` with its mirror set to the Arch Linux Archive's 2026-08-15 snapshot matched the base exactly.
  - `pacman -Sy git` built in 7 s, 137 MB over the 408 MB base; with nodejs, 21 s and 637 MB in all.
  - The snapshot for 2026-08-16 is missing (`core.db` answers 404).
  - After a run with `--userns=keep-id`, `podman image inspect` reports a larger size, likely a remapped copy of the top layer.
- **The bundled CLIs** (`claude_agent_sdk/_bundled/claude`, 2.1.294, linked against glibc only; `codex_cli_bin/bin/codex`, 0.162.0, static) run on the bare base. Claude embeds ripgrep; Codex ships `rg` and `bwrap`.
- **Mounts at their host paths.**
  - A linked worktree works with the shared git directory mounted read-write and its `config` and `hooks/` read-only: `git config` inside fails with "Device or resource busy", objects and refs are writable.
  - A tmpfs hiding the sibling worktrees needs `notmpcopyup`, or podman copies what it hides into it.
- **`--userns=keep-id`.**
  - It sets `HOME` to the working directory, or `/` without one, so `HOME` is set explicitly.
  - Files written inside are the operator's on the host.
  - A mount point podman creates is owned by root: Claude Code refused "Temp directory /tmp/claude-1000 is owned by uid 0", and uv refused a root-owned `~/.cache`.
  - Through `SO_PEERCRED`, a process in the room shows the operator's uid and its host pid.
- **The project's environment.**
  - A uv environment works in the room with uv's interpreter store mounted read-only at its host path. With the interpreter missing, `uv run --frozen` printed "Ignoring existing virtual environment linked to non-existent Python interpreter" and tried to recreate `.venv`; `UV_PYTHON_DOWNLOADS=never` stops it.
  - In sync, `uv run --frozen pytest` wrote nothing to `.venv`.
  - lup's suite passed in the room in 417 s (418 s on the host).
  - The host's `uv` needs `libjemalloc.so.2`, and its `node` can't be mounted at all.
- **A host socket.** A socket mounted as a file stays bound to the old socket when the server restarts ("Connection refused"); its directory mounted follows the new one.
- **The logins.**
  - Claude Code with only `.credentials.json` mounted read-only, and Codex with only `auth.json` mounted read-only, each answered one call. Neither needed a refresh.
  - With the full Claude login, the room connected the account's claude.ai connectors, Google Drive's share and trash tools among them.
- **The SDK on the host, the CLI in the room.** `ClaudeSDKClient(cli_path=…)` with a script running `podman run -i --rm --init … claude "$@"` completed the handshake, and the CLI in the room listed and connected an in-process MCP tool served on the host. This answers `DESIGN.md`'s check: the CLI runs in a container while the SDK and lup's in-process tools stay on the host.
- **Terminals.** `-it` under a real terminal carries its size and `TERM` through.
- A container starts in 0.55 to 0.9 s.

### podman 6.1.3, rootless: the engine's command lines (measured for `lup.rooms`)

- **Mounts.**
  - `--mount` takes one CSV record: a quoted field (`"source=/a,b"`) mounts a path holding a comma.
  - A tmpfs from `--mount type=tmpfs,…,tmpfs-mode=0700,U=true` is owned by the operator under keep-id, and runs programs; `--tmpfs`'s default options are `rw,noexec,nosuid,nodev`.
  - A directory podman makes for a mount inside that tmpfs is owned by root, mode 755: `mkdir ~/.cache/other` failed with "Permission denied" beside a mount at `~/.cache/uv`, and passed once `~/.cache` was a tmpfs of its own with `U=true`.
  - A single file mounted read-write is written in place, through to the host's file, but can't be replaced by a rename ("Device or resource busy"). Claude Code 2.1.294's writer falls back to writing in place when its atomic write fails ("in-place fallback write", in its binary).
- **Builds.** `podman build --file - <empty directory>` reads the Containerfile from its input; `--label` adds a last `LABEL` step. `podman image exists` answers 0 or 1. `podman images --format json` lists each image's `Id`, `Names`, `Created` (epoch seconds), `Size`, `Labels` and `Containers`.
- **Runs.**
  - `podman run` passes the program's exit status through, and answers 125 for its own failures: `--pull=never` with a missing image says "image not known".
  - `--log-driver=none` keeps `-it` and the exit status. On this host the default log driver is journald, which would keep a terminal session's output in the journal.
  - `--detach-keys=` (empty) is accepted with `-it`; its manual says an empty sequence turns off detaching, whose default is Ctrl+P then Ctrl+Q.
  - `--network=private` ran; its manual says it makes a namespace of the container's own, through pasta for rootless podman.

### From the first lup's rooms

Read in its code and history (`lup-legacy`), with each commit there:
- **Its image** was 4.5 GB: a 2 GB package layer (five editors, a virtual display, tooling) and a 1 GB layer of CLIs from npm, re-resolved at every launch and rebuilt whenever one released, most days. 46 tags of 4.5 to 5.5 GB were left on this machine.
  - Its baseline: ca-certificates, curl, git, jq, less, openssh, socat, procps-ng, ripgrep, fd, python, uv, nodejs, bun, util-linux, ttf-liberation;
  - editors for `$EDITOR`: vim, neovim, nano, emacs-nox, helix, with tzdata; a virtual display for the clipboard (xorg-server-xvfb, xorg-xauth, python-xlib);
  - lup's own: github-cli, diffutils, which, tree, lsof, inetutils, go-yq, and poppler in every project's template;
  - adlib's own: ffmpeg, the Noto fonts (CJK and emoji among them), and the libraries headless Chromium links (alsa-lib, at-spi2-core, libglvnd, libx11 and its kin, libxkbcommon).
- **Its environments** were one per project root, outside the checkout (`.venv-contained`), synced at each start: 25 GB across 31 directories. Their scripts went stale when a repository moved, and a uv-managed interpreter was downloaded again at every start.
- **Logins** were copied into a volume per repository and kept in step by a companion every 30 s: a read-only mount at the login's own path broke renewal, and Claude Code 2.1.285 renames over its credentials file, which broke symbolic links.
- **Its sessions' terminals** lost colour, their locale and their time zone until `TERM`, `COLORTERM`, `LANG` and `TZ` were passed. Without `--init`, 4,045 zombies piled up against the pids limit, which counts threads.
- **Concurrent starts** on one config volume left NUL-prefixed `.claude.json` files, and 16 starts ended on `{"autoUpdates": false}`; Codex's `config.toml` raced the same way.
- **The network:** lup's own sessions ran on the host's network, for sign-in callbacks and ssh; the default was an internal network behind a squid proxy, whose DNS and staleness caused failures of their own.
- **Its hooks** ran inside the container on the image's Python, from generated files in the checkout, which a session could rewrite unless they were held read-only.

## Isolation and effects

- An overlay mounts over 300k files in 13 ms and lists its changes in 12 ms, without root, in lup's container (kernel 7.2).
- A git snapshot per command costs about 50 ms at lup's size, 0.4–0.8 s at 100k files, and 1.4–2.8 s at 300k.
- Judging after the fact misses three things:
  - background writers (a process detached with `setsid` escapes);
  - files git ignores;
  - code that runs inside the same call (a planted `core.fsmonitor` ran).

## Package age gates

- uv's `exclude-newer` accepts "3 days" (`UV_EXCLUDE_NEWER`);
- bun 1.3.14 has `minimumReleaseAge`;
- pacman holds to a dated Arch Linux Archive mirror (checked in a room: a snapshot's packages matched its date's base image), though some days are missing (*Rooms*).

## Tools

- ruff 0.16.10 and pyright 1.1.414 resolve an extended base's relative paths from the base's own directory, so a base under `.lup/settings/` writes `../../`;
- in an extending file, ruff's `select` and `per-file-ignores` replace the base's, while `ignore`, `extend-select` and `extend-per-file-ignores` add to it; pyright's settings replace the base's by name, lists included;
- a workspace member with its own `[tool.ruff]` and no `extend` is cut off from the root's settings;
- pyright reads a TOML base's `[tool.pyright]`;
- Node strips TypeScript types by default from 23.6.0 and 22.18.0, never under `node_modules`.

## From the downstream projects

- **aib:**
  - tool names in prompts must be exact (`mcp__x__y`);
  - deferred tool schemas made the agent guess search terms;
  - `allowed_tools` auto-approves but doesn't restrict;
  - plan mode never submits structured output;
  - in its worst misses, the agent's own counterargument often held the right answer and was dismissed;
  - scores never moved attributably after the feedback loop's changes;
  - 21 of its 24 partial forecasts came from a spent usage window.
- **live-translator** needed five things: a provider switch, a timeout, a trace, a guarantee of no tools, and a fake for tests (stubbing one call took about 70 lines).
- **The art studio:**
  - `DISPLAY` set in the container breaks headless Chromium's WebGL;
  - the image had no fonts at all, which makes every CSS `@font-face` fail;
  - uv-managed interpreters weren't kept between containers;
  - pyright's `venv` name didn't match the contained environment's;
  - a pytest test root gave its files no test role;
  - xdist was looked up in the wrong environment.
- **harmon** (a Discord agent that waited inside a tool, woken by events): the waiting held up; timing rules loaded onto the agent through its prompt starved its replies, and a reply took 21–68 s.
