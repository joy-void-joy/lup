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
  - the docs say the server learns only `CLAUDE_PROJECT_DIR`, not the session or the subagent; the 2.1.296 binary sends each call's `claudecode/toolUseId` in its `_meta` too (*MCP in a launched session*);
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

Read from its source and checked against the bundled binary with a local mock Responses endpoint; one typed ask has run live since (*The library's asks*).
- Only the low-level `openai_codex.client.CodexClient` takes a server-request handler, and it runs synchronously on the client's one reader thread: a request through the same client from inside it deadlocks.
- Dynamic tools are declared on `thread/start` only, fixed for the thread's life; a call arrives as the server request `item/tool/call` and is answered `{"contentItems": [...], "success": bool}`.
- `thread/start` takes no `effort`; it goes on `turn/start`.
- `environments: []` disables environment access; `agents.enabled=false` in the thread's config removes the subagent tools; web search, skills, the built-in instructions and features are launch `-c` overrides (listed in `LAUNCH`, `lup/adapters/codex/runtime.py`).
- The default model `gpt-6.1-sol` and about ten others are `code_mode_only`: every tool, lup's included, sits behind a JavaScript `exec` tool, with `wait` and `request_user_input_async`; no setting removed them. Other models, such as `gpt-5.4`, carry only the declared tools.
- `exec` reaches nothing beyond the declared tools (probed on 0.162 against a mock endpoint): no `fetch`, `require`, `process`, `Deno`, `WebSocket`, `Worker` or `WebAssembly`; every import refused ("unsupported import in exec"); none of the built-in tools (`exec_command`, `shell`, `apply_patch`, `spawn_agent`, `web_search`, `view_image`). Its nested tools are the declared ones (called as `await tools.submit({...})`), `clock__curr_time`, and MCP resource readers that return nothing without servers. `request_user_input_async` answers `{"accepted": true}` and sends the client nothing. Turning `features.code_mode_host` off makes `exec` answer "code-mode host is disabled", so the declared tools become unreachable.
- With `baseInstructions: ""`, a thread sends no developer message at all; leaving it out sends Codex's 17 KB coding-agent prompt. A project's `AGENTS.md` isn't injected into an app-server thread.
- `thread/tokenUsage/updated` fires per model request and on turns that made none: a turn's usage is the change in `total`. Codex reports no cost.
- `usageLimitExceeded` carries its reset time only in the global notification `account/rateLimits/updated` (`rateLimits.primary.resetsAt`); the message's "try again at" is local-time text.
- `auth.json` is written through a symlink under the `file` credentials store; under `keyring` or `auto`, a refresh deletes it. A keyring login is keyed on the canonical `CODEX_HOME` path, so it isn't visible from another home.
- The SDK's high-level `TurnResult` raises a plain `RuntimeError` for a failed turn, losing `codexErrorInfo`, and reports a thread's usage snapshot.

## The library's asks (claude-agent-sdk 0.2.165 with Claude Code 2.1.294; openai-codex 0.162.0 with codex-cli 0.162.0)

For `docs/library.md`.
- **Live, with the operator's logins:** one typed ask on each runtime. Claude Code on `haiku`: lup's MCP server through the real CLI, the `init` check passing, the answer through `mcp__lup__submit`, no transcript written. Codex on `gpt-6.1-sol`, in code mode: `exec` calling `submit`, everything written in lup's own Codex home and nothing in the operator's.
- With `--system-prompt ""`, Claude Code still adds one identity line of its own: "You are a Claude agent, built on Anthropic's Claude Agent SDK." (read in the bundled CLI).
- Installed, `claude_agent_sdk` with its bundled CLI is about 240 MB and `codex_cli_bin` about 360 MB (`du`).
- Codex's docs say app-server authentication "has never been permitted for commercial or hosted services".
- Codex reports the rate limits that came with a usage limit before the error, outside any turn's stream (`next_notification`), and the adapter's watcher thread keeps the last; nothing synchronises it with the turn's stream, so a real run could miss the reset. `account/rateLimits/read` after the error would ask for it directly.
- **Not yet seen live:**
  - on Claude Code, the `Stop` guard holding an unanswered turn, and the error classification; how a spent window surfaces under a subscription login (an API key's 429 emitted no `RateLimitEvent`); what a dropped connection reports (taken as an API error with no status);
  - on Codex, a dynamic tool called directly on a model without code mode; that the model's request carries only lup's tools, which no API lists, so it's checked by hand on each pinned version;
  - parallel asks: simultaneous Claude Code starts on the operator's default home (concurrent starts on one config volume corrupted `.claude.json` in the first lup, *From the first lup's rooms*), and parallel Codex app-servers starting on lup's one home.

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
- **Which value wins, for the session settings** (read in the 2.1.296 binary; the `settings` docs agree that "an `env` block inside a settings file is an ordinary key and follows the levels above"):
  - At start, each source's `env` is applied over the process's environment in order: `~/.claude.json`'s, then user, project, local and `--settings`, then managed. So a variable in `--settings`' `env` outranks the same in the user's, which outranks the environment the process started with.
  - The subagents' cache: `FORCE_PROMPT_CACHING_5M`, then `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`, then `subagentPromptCacheTtl`, then an agent's own frontmatter, then `ENABLE_PROMPT_CACHING_1H`.
  - Auto memory: `CLAUDE_CODE_DISABLE_AUTO_MEMORY` (`1` off, `0` forced on) before `autoMemoryEnabled`.
  - Connectors: off where any source's `disableClaudeAiConnectors` is `true` or `ENABLE_CLAUDEAI_MCP_SERVERS` is false; nothing turns them back on.
  - `idleCompaction` ("Setting it to true does not turn idle compaction on"): read from the highest source setting it, `true` where none does. Idle compaction runs only where a server-side flag's mode turns it on, `autoCompactEnabled` is on, and `idleCompaction` isn't `false`.

## Codex 0.162.1: launching a session

From the source at `rust-v0.162.1` (paths under `codex-rs/`), probed with `codex debug prompt-input` and `app-server`'s `hooks/list` against scratch homes; no model called.
- **`CODEX_HOME`** must exist, and not under a temporary directory: Codex then refuses to make its helper links ("Refusing to create helper binaries under temporary dir"). It holds `config.toml`, `auth.json`, `hooks.json`, `AGENTS.md`, `sessions/`, `session_index.jsonl`, six SQLite databases, logs and caches.
- **`config.toml`.**
  - Codex writes trust, hook trust and first-run counters back into it, following a symbolic link and replacing the target atomically.
  - The interactive CLI always loads `$CODEX_HOME/config.toml`, so only a separate home keeps the operator's file unloaded.
  - `--profile <name>` layers `$CODEX_HOME/<name>.config.toml` over it; a `profile` key in `config.toml` is refused ("legacy `profile = …` config is no longer supported", `core/src/config/mod.rs`).
  - `[features]`' switches are a `BTreeMap`, applied in the order of their keys, and an older key switches the same feature as its new one (`features/src/legacy.rs`: `connectors` for `apps`, `memory_tool` for `memories`), so with both set the later key wins: `connectors` over `apps`, `memory_tool` over `memories`.
  - No idle compaction: compaction runs past `model_auto_compact_token_limit` and, when set, at a turn's end past `model_post_turn_compact_threshold_percent` (`config/src/config_toml.rs`); the binary names no other compaction setting.
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

## Codex 0.162.1: its hooks around a call (captured)

From the source at `rust-v0.162.1` (paths under `codex-rs/`), and one `codex exec` on the operator's login in a scratch repository whose `.codex/hooks.json` kept each payload (`--dangerously-bypass-hook-trust --ephemeral`), asked for a patch adding a file, a patch updating it, a shell command, and a patch that can't apply. The nine payloads are kept in `packages/lup-dev/tests/payloads/codex-0.162.1/`, each `cwd` replaced by a neutral path.
- **The hook schemas** (`hooks/schema/generated/`) are 0.156.1's, file for file. Every call's hooks also carry `turn_id`, `model`, `permission_mode` and `transcript_path` (`null` here, under `--ephemeral`). `permission_mode` follows the approval policy alone, `never` reading `bypassPermissions` (`core/src/hook_runtime.rs`, `hook_permission_mode`).
- **A patch:** `tool_name` is `apply_patch`, `tool_input.command` the patch as the model wrote it (`*** Begin Patch\n*** Add File: livecheck.py\n+import subprocess\n*** End Patch`), and `tool_use_id` the call's id, the same at `PreToolUse` and `PostToolUse` (`exec-<uuid>` under `codex exec`). `PostToolUse`'s `tool_response` is text: `Exit code: 0\nWall time: 0 seconds\nOutput:\nSuccess. Updated the following files:\nA livecheck.py\n`. A matcher of `Write` or `Edit` selects a patch's hooks too, the payload still naming `apply_patch` (`core/src/tools/hook_names.rs`).
- **A shell command:** `tool_name` is `Bash` and `tool_input.command` the command line; `test -e livecheck.py` had `""` for its `tool_response`.
- **No `PostToolUse` for a call that didn't succeed** (`core/src/tools/registry.rs`): the patch that couldn't apply ("apply_patch verification failed: Failed to find expected lines") had its `PreToolUse` and nothing after it, the turn's `Stop` coming next. So does a call that's interrupted, or that a `PreToolUse` hook blocks. A shell command succeeds whatever its exit status.
- **`write_stdin`** fires no `PreToolUse`; a command still running when its call returns has no `PostToolUse` then, and gets it, under its own id, from the `write_stdin` poll that sees it end (`core/src/tools/handlers/unified_exec/write_stdin.rs`), as at 0.156.1. The note on 0.160.1 above, "`write_stdin` fires no hook", holds for `PreToolUse`.
- **A call's `cwd`** is the session's local working directory, or the turn's where there's none (`core/src/hook_runtime.rs`, `tool_hook_cwd`); 0.156.1 gave the turn's.
- **`--dangerously-bypass-hook-trust`** runs every enabled layer's hooks for one invocation with no trusted hash, a trusted project's `.codex/hooks.json` among them: enough to capture payloads without recording hook trust. The run still wrote the scratch repository into the operator's `config.toml` as a trusted project (it sat under a trusted directory), `--ephemeral` notwithstanding.

## MCP in a launched session (read 2026-10-13)

Read for `docs/host-tools.md`: Claude Code's docs (code.claude.com, cited by page) and its 2.1.296 binary (a byte search, no model called); Codex's source at `rust-v0.162.1` (paths under `codex-rs/`) and the rmcp crate it pins; `mcp` 2.3.0's source. Nothing here was run against a model; what was seen live is under *Piece 2, live*.

- **Claude Code 2.1.296:**
  - **Servers from the launch:** `--mcp-config` loads servers interactively too; `--strict-mcp-config` is "Only use MCP servers from `--mcp-config`, ignoring all other MCP configurations" (`cli-reference`), managed servers dropped "along with every other configured server" (`managed-mcp`). Managed `allowedMcpServers` and `deniedMcpServers` filter `--mcp-config`'s servers, and `disableSideloadFlags` refuses the flag (`managed-mcp`). Under `bypassPermissions` no MCP tool prompts but one marked `_meta["anthropic/requiresUserInteraction"]` (`mcp`, *Require approval for a specific tool*).
  - **Transports:** stdio, HTTP, SSE and WebSocket; no Unix socket. A stdio entry takes `command`, `args` and `env`; every entry takes `timeout` (ms) and `alwaysLoad` (`mcp`). A stdio server inherits the shell's environment plus `CLAUDE_PROJECT_DIR`; `MCP_TIMEOUT` bounds its start, 30 s by default.
  - **How long a call may run** (the binary): the server's `timeout` where it's at least 1,000 ms, else `MCP_TOOL_TIMEOUT`, else 10⁸ ms (27.8 h), clamped to 1,000 ms to 24.8 days, progress not extending it. A stdio call with no answer and no progress aborts after 30 minutes (5 for the other transports), unless `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` says otherwise; the server's `timeout` raises that idle limit too. A main conversation's call moves to the background after 2 minutes unless `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`.
  - **Restarts:** "stdio servers are never reconnected automatically" (`mcp`, *Automatic reconnection*); `/mcp` reconnects one by hand.
  - **Who's calling:** every call's `_meta` carries `"claudecode/toolUseId"`, the call's id, which the hooks see as `tool_use_id` beside the session's and the subagent's (the binary: `{"claudecode/toolUseId":…}`); `claudecode/agentId` goes to one particular server only. Esc's `notifications/cancelled` is in the binary; whether Esc sends it isn't known.
  - **What the model reads:** a result's `content`; past `MAX_MCP_OUTPUT_TOKENS` (25,000) it's saved to a file and the path given; text past 50,000 characters is saved whatever the tokens, raised per tool by `_meta["anthropic/maxResultSizeChars"]` up to 500,000 (`mcp`, *MCP output limits and warnings*). `structuredContent` isn't documented; the binary has `structuredContentOmitted`.
  - **Tool search** is on by default: every MCP tool is deferred, only names and the server's instructions loaded at start; `alwaysLoad: true` on an entry, or `_meta["anthropic/alwaysLoad"]` on a tool (2.1.287 and later), loads them upfront. Descriptions are cut at 2,048 characters (`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`) (`mcp`, *Scale with MCP tool search*).
  - **The session's messaging socket:** `--messaging-socket-path <path>`, "Cross-session messaging server path: a Unix domain socket on Mac/Linux" (the binary's help, not in `--help`'s list), exported to hooks and Bash as `CLAUDE_CODE_MESSAGING_SOCKET`. "When the receiving session is idle, Claude Code starts a new turn with the message"; a session bypassing permission prompts holds each message for approval unless `crossSessionInbound` is `"accept"`; at most 50 accepted messages wait, repeats are dropped and bursts refused; the auth line is optional on Linux (`cross-session-messaging`). The binary skips the socket in a session it counts as restricted, and where a server-side gate is off ("[uds-messaging] Skipped: restricted session (--messaging-socket-path ignored)"). The frame beyond the auth line is undocumented; the first lup measured `{"type":"user","message":{"role":"user","content":…}}` starting an idle session's turn on 2.1.278 to 2.1.285 (its `coordination/wake.py`, `195ff73f3`), and a frame whose `session_id` named another session dropped (`68eaa2e2e`); neither sent a `priority`. In the 2.1.296 binary (a byte search, 2026-10-14), a `user` frame's `message.content` must be a non-empty string ("Ignoring user message with missing or non-string content"), a `session_id` other than the session's own drops it ("Dropping … message: session_id mismatch"), and `priority` is optional, `next` where it's missing ("Routed user message to queue (priority=…)"). A connection that hasn't sent a complete line within 30 seconds is closed (`cross-session-messaging`). Owed live: the frame starting an idle room's turn.
- **Codex 0.162.1:**
  - **Its docs don't track a version:** developers.openai.com/codex/mcp redirects to learn.chatgpt.com, whose page says 10 s to start and 60 s per call, against the source's 30 s and 300 s. The source at the tag is the authority.
  - **A server's entry** (`config/src/mcp_types.rs`): stdio `command`, `args`, `env`, `env_vars`, `cwd`; HTTP `url` and its headers; both `enabled`, `startup_timeout_sec`, `tool_timeout_sec`, `default_tools_approval_mode`, `enabled_tools`, `disabled_tools`, `omit_tools_from`, `tools.<name>`. Unknown keys are refused, and so is a `url` beside a `command` ("url is not supported for stdio").
  - **`-c` overrides** are one layer: a later override of the same key replaces the earlier (`config/src/overrides.rs`), and the layer merges into the operator's configuration key by key (`config/src/merge.rs`), so an override's server merges into theirs of the same name rather than replacing it.
  - **Transports:** stdio and streamable HTTP. The hidden `codex stdio-to-uds <socket>` relays stdio to a Unix socket (`cli/src/main.rs`, `stdio-to-uds/`). A stdio server's environment is cleared to `HOME`, `LOGNAME`, `PATH`, `SHELL`, `USER`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR` and `TZ`, plus its `env_vars` and `env` (`rmcp-client/src/utils.rs`).
  - **How long a call may run:** `tool_timeout_sec`, 300 s by default (`codex-mcp/src/rmcp_client.rs`), seconds as a float with no cap. Progress is only logged and doesn't extend it (`rmcp-client/src/logging_client_handler.rs`); Codex never sends `notifications/cancelled`, on a timeout or on Esc (rmcp's `service.rs`). In code mode a call from a cell runs the same way, and the cell yields after 30 s.
  - **Restarts:** a stdio server that dies mid-session isn't started again; calls then fail "MCP server 'x' is not connected" (`codex-mcp/src/connection_manager.rs`; read, not probed).
  - **Who's calling:** `tools/call`'s `_meta` carries `callId` (the hook's `tool_use_id`), `threadId`, `sessionId` and `x-codex-turn-metadata` (the turn, and a subagent's parent thread) (`core/src/mcp_tool_call.rs`).
  - **What the model reads:** where a result's `structuredContent` isn't null, that JSON alone, its content blocks dropped (`protocol/src/models.rs`); otherwise its text, image and audio blocks, cut past about 10,000 bytes by default (`utils/output-truncation`) unless the tool's `output_token_limit` is raised.
  - **Nothing a server sends unprompted reaches the model:** notifications are only logged (`rmcp-client/src/logging_client_handler.rs`), and the app-server's `turn/start` runs inside the terminal's own process under `--no-daemon`. Nothing reaches a session idle between turns.
  - **Approval:** a tool's `approval_mode`, else the server's `default_tools_approval_mode`, else `auto` (`codex-mcp/src/server.rs`); the prompt is skipped under `approve`, or under approval `never` with full access (`codex-mcp/src/mcp/mod.rs`).
  - **Tool search:** where the model supports it, MCP tools are left out of the first tool list (`core/src/tools/spec_plan.rs`); `omit_tools_from = ["deferred"]` loads them upfront. Names are `mcp__<server>__<tool>`, any character outside `[A-Za-z0-9_]` turned to `_`.
- **`mcp` 2.3.0** (the library's):
  - `Server.run` serves "a single connection over the given streams until the read side closes", in whichever protocol era the client's first request opens: the `initialize` handshake, or 2026-07-28's per-request envelope (`server/lowlevel/server.py`, `server/runner.py`).
  - Its stdio transport is one JSON-RPC message a line, read with `jsonrpc_message_adapter.validate_json(line, by_name=False)` and written with `model_dump_json(by_alias=True, exclude_unset=True)` (`server/stdio.py`). A line that isn't a message reaches the session as an error, which the server logs and passes over.
  - When the read side closes, every call still running is cancelled and answered "Connection closed", a write onto a closed transport, which `mcp` drops with a debug log (`shared/jsonrpc_dispatcher.py`).
  - Importing its server (`mcp.server.lowlevel.server`, `mcp.shared.memory`) took `lup_dev.cli`'s imports from 0.41–0.48 s to 0.87–0.93 s, five runs each (`python -X importtime`), so `lup.tools.serving` imports it only when a server is made.

## Launch, live (2026-10-13)

`lup-dev launch` from `dev` (d0c629a, then 66e5b3a), in lup's own `tree/dev`, a linked worktree of a bare repository, driven through tmux on the operator's machine (podman 6.1.3). The room's image built in 48 s, 2.88 GB.

- **Claude Code 2.1.296:**
  - A first launch reached the prompt with no screen: no onboarding, theme, folder trust or login. The person's model (`opus[1m]`), effort and `editorMode` held, so `--settings` applies beside `--setting-sources user`, and a fresh `~/.claude.json` beside their `~/.claude` opens logged in.
  - A `Write` with a rule finding was refused through the room's hook (socat to the host service, the repository's judge copy), the agent's version saved.
  - A `PreToolUse` `ask` prompts under `bypassPermissions` ("Do you want to make this edit to pyproject.toml?"); declined, the tool result was "The user doesn't want to proceed with this tool use", the file unchanged.
  - The person's own `idleCompaction`, `autoMemoryEnabled` and `subagentPromptCacheTtl` kept those out of the launch's settings (`env` empty); `disableClaudeAiConnectors: true` went in, and `/mcp` answered "No MCP servers configured": none of the account's connectors (Gmail, Drive, Calendar, Docs) reached the room.
  - A server on `127.0.0.1:8765` in the room answered `curl` on the host. Ctrl+G opened vim on `/tmp/claude-prompt-<uuid>.md`, and the edited text came back to the prompt.
  - `/exit` with a background shell running asked "Exit and stop tasks / Move to background and exit / Stay"; exiting removed the container and ended the launch's registration. Claude Code's exit line names `claude --resume <id>`; `lup-dev launch claude --resume <id>` restored the conversation in a new room.
  - Two rooms at once on the shared `~/.claude` each ran a command and answered, with no lock or state errors.
  - `uv run lup-dev check` in the room passed every step but `rules`, which crashed on `CommandNotFound: gh` (a room holds neither `gh` nor a GitHub login); since then, deferrals' issues go unchecked there, and the check says why.
- **Codex 0.162.1:**
  - A first launch reached the prompt with no login, in full access ("YOLO mode"), on the person's own model (GPT-6-Astra), no `--model` passed. The managed hooks from the mounted requirements file ran: the service answered `SessionStart` and each call's `PreToolUse` and `PostToolUse`.
  - A patch with a rule finding first landed unjudged: calls no hook would finish (Claude's writes judged before they land, 1,659 in `tree/dev`) kept every checkpoint there from running. Since a checkpoint waits only on its own session's calls, the patch was put back after its call, the finding told.
  - A patch to a protected path was held. The room's hook (`sh -c 'socat -t 90000 …'`) was still alive and waiting at 1 h 01 min, and the operator's decline reached it.
  - **A hold doesn't hold a code-mode agent.** GPT-6-Astra runs tools in code mode: the patch ran in a cell, and the model read "Script running with cell ID 4", polled it, said the call was still pending, and ended its turn after 7 min 49 s, the hook still waiting. A held call is visible to it as pending, not invisible.
  - Two Claude sessions starting in the worktree while the patch was held accepted it as it stood, so the decline put back nothing (fixed on its own branch: a held file stays out of other sessions' accepted tree).
  - With the host service stopped, a shell call's hooks failed: Codex showed "Hook failed — hook exited with code 1", not what the hook wrote to standard error, and the call went on. Quitting then, the launcher's client started the service again, which served the recorded launch and ended it.
- **Not seen live, as far as these notes record:**
  - Claude Code: the session settings' variables in the `env` of the launch's settings taking effect over the same in the operator's own `env`, as read in the 2.1.296 binary, and `idleCompaction: false` stopping idle compaction. lup's own variables (`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`, `DISABLE_AUTOUPDATER`) are in the room's environment, which a variable of the same name in the operator's own `env` would overwrite at start.
  - Codex: `allow_managed_hooks_only` dropping every hook source but the mounted requirements file; `features.memories` and `features.apps`, overridden with the older key the operator's `config.toml` uses, holding as the source reads; the room's `--no-daemon` beside the host's daemon on the same home.
  - Both: a hook held for hours, past the hour seen.

## Piece 2, live (2026-10-14)

`lup-dev launch` from `dev` (845c7af) in lup's own `tree/dev`, Claude Code 2.1.299 (the latest at launch) and Codex 0.162.1 in rooms, driven through tmux; the operator's answers given with `lup-dev inbox` from another terminal (`docs/host-tools.md`).

- **Claude Code refused a messaging socket in a directory others could reach:** "--messaging-socket-path directory /run/lup is not private (mode 755); the socket directory must be mode 0700 so no other user or group can reach or replace the socket", and didn't start. Each launch's socket directory is 0700 since.
- **lup's tools, on both runtimes:** the guidance listed all ten by name and summary; the agent found each through tool search and called it through the `socat` bridge (Codex's model in code mode too). `note` answered "Your note is with the operator, item 3. Carry on.", the item's sender the calling session, so the hook's stamp reached the server: on Claude Code as `updatedInput` with no decision, on Codex beside `permissionDecision: "allow"`.
- **Told at the next call:** an item sent during a 25-second foreground call didn't interrupt it, and arrived at the next call: on Claude Code as "PreToolUse:Bash hook additional context", on Codex as a developer message; recorded told by `call`.
- **Woken when idle (Claude Code):** an item sent to a session whose turn had ended started a turn, the agent answering it. Claude Code frames whatever arrives on its messaging socket as "Another Claude session sent a message … not typed by your user", with a reminder that a peer can't grant approval: the operator's own messages and answers arriving by wake carry that framing, where told at a call they don't.
- **A turn the operator starts by typing fires no hook,** so the service still took the session for idle and told an item by wake mid-turn; Claude Code read it between tool calls. It arrived once.
- **Held calls:** an `ask` with `wait` held 36 minutes on Claude Code, past its 30-minute idle limit, and returned the operator's answer in the call (the entry's `timeout`); on Codex, 6 minutes 53 seconds, past its 300-second default (`tool_timeout_sec`), as a direct call rather than a pending cell.
- **git through the host:** `git fetch origin` in the room fetched through the helper, the host resolving the remote's URL, an alias in the operator's SSH configuration; a new branch pushed to GitHub; its deletion refused, "deleting `refs/heads/livecheck/push-20261014`: the project's declaration doesn't allow `delete-ref` with the operator's credentials (`Core.credentials`), and allowing it is the operator's call". A push to `main` met git's own fast-forward refusal first. lup's bare repository has no fetch refspec, so a fetch writes `FETCH_HEAD` in the room and no remote-tracking ref.
- **GitHub:** `read_issue` and `find_issues` answered from GitHub; the write tools wait for their first real use.
- **`lup-dev inbox send` in a worktree with two launches** refused, naming both, until one was named by its id.
- **Desktop notices:** `notify-send` failed, "GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name is not activatable": no notification daemon on the operator's session bus. lup logs it and goes on.
- **Not seen live, as far as these notes record:**
  - Claude Code: whether Esc on a held call sends `notifications/cancelled`; `--resume` keeping the session's id, so a resumed session finds what waited for it.
  - Codex: in code mode, what the model sees of a held call answered after its turn ended (the hold above stayed a direct call); resuming keeping the thread's id.
  - Both: lup's MCP bridge carrying a session across a restart of the host service.
  - GitHub's write tools, `file_issue`, `comment` (on a pull request's number too) and `draft_pull_request`, at their first real use from a launched session.
  - A protected ref refused by lup's own check: the push to `main` above met git's own refusal first. lup's rule is tested, and was seen against a stand-in forge in a room.

## Host-side git in a repository the room writes (git 2.56.0, 2026-10-14)

The check `docs/host-tools.md` owes before `remote` is built (*Running git on the host*). On scratch repositories laid out like lup's (a bare `project.git` common dir with a linked worktree under `tree/`, a bare `forge.git` for GitHub, a bare unrelated `secret.git`), acting as a hostile room: each thing the room can write, the host command (`git push <url> <oid>:<dst>`, `git ls-remote <url>`, `git fetch --no-write-fetch-head <url> <name>` in the common dir, url from `git remote get-url --push <name>`), and whether the planned response closes it. Scripts in the session scratchpad.

- **`objects/info/alternates`: exfiltrates without the response.** `objects/info/alternates` = `secret.git/objects` let the common dir read secret objects; `git push <url> <secret-oid>:refs/heads/x` copied the secret blob to the forge. The planned refusal (refuse while alternates name a directory outside the repository) closes it, but must be stronger than a single-line check: a **relative** entry (`../../mid.git/objects`) is resolved, and **nested** alternates are followed (project → mid → secret all read), so the check must resolve relative paths and recurse. `objects/info/http-alternates` is **not** consulted by the local transport (push/fetch), so it is inert for these commands — but refuse it too for safety.
- **A symlink under `objects/` bypasses an alternates-only check (new).** With no alternates file at all, a room-planted symlink `objects/pack/pack-stolen.{pack,idx}` → `secret.git/objects/pack/…` made the common dir read secret objects, and the same push exfiltrated the blob. The alternates refusal does not see it. lup's own bare repo has no alternates and no symlink under `objects/`, so the robust rule measured to cover vector 1, nested/relative/symlinked alternates, and this one at once: **refuse unless the object store is self-contained** — no `objects/info/{,http-}alternates`, and no symlink anywhere under `objects/`. (Caveat: a working exfil also needs the room to know an oid in the outside repo; the defence shouldn't rest on oid secrecy, as alternates don't either.)
- **`refs/replace/`: `git push <oid>` was already immune; `GIT_NO_REPLACE_OBJECTS=1` is sound belt-and-suspenders.** A replace ref changed what `git show`/`rev-list --objects` read (it even dragged a secret parent into `rev-list`), but `git push <oid>:<dst>` transferred the **real** object graph both with and without `GIT_NO_REPLACE_OBJECTS=1`: the forge got the genuine object, no replacement content, no dragged-in secret. Push does not honour replacement in pack generation. The env var changes only the reading commands (which the host doesn't run for a push), so it closes the stated concern and costs nothing.
- **refs and `packed-refs`: closed.** Room-written `refs/heads/evil` and a `packed-refs` entry never reached the forge: `git push <oid>:<dst>` reads no local ref, and `ls-remote <url>` reads the remote's refs. (Observed, consistent with #13: `git push <url>` where the url matches a configured remote still writes `refs/remotes/<name>/<dst>` in the shared common dir — a ref write on push, benign, no new room capability.)
- **A worktree's directory and `config.worktree`: closed by running in the common dir, with a caveat.** The host runs in the common dir, so a room-written `worktrees/*/config.worktree`, `commondir` (redirecting to `secret.git`), `HEAD` or `index` is never consulted; a worktree `config.worktree` is also ignored even for a worktree-scoped command unless `extensions.worktreeConfig=true`, which lives only in the read-only `config`. **But** `config.worktree` is a *different file* from `config`: in the common bare dir it is **room-writable** (the read-only mount is on `config`, not `config.worktree`), and with `extensions.worktreeConfig=true` the common dir reads it (injected `foo.bar`, and by the same path `core.sshCommand`/`core.fsmonitor`/`core.hooksPath`). So if a project's committed `config` sets `extensions.worktreeConfig=true`, the room gains config injection into host git. lup's repo leaves it unset; the launch should refuse/flag a committed `extensions.worktreeConfig=true`, the same family as the includes check below.
- **`info/attributes` and `info/exclude`: closed.** A push and a fetch check nothing out, so `* filter=evil` in `info/attributes` ran no smudge/clean filter, and a filter driver is definable only in the read-only `config`.
- **`shallow`: closed.** A `shallow` cutting history made the forge reject the push (`! [remote rejected] … (shallow update not allowed)`); nothing extra leaked. It can only make the host send less than the forge needs, as the note says.
- **`config` includes: closed by a launch-time check, which must resolve both forms recursively.** `config` is read-only, so the room can't add an include — the risk is a committed `include.path`/`includeIf` already pointing into a room-writable path. Demonstrated: `include.path = info/evil.cfg` (into the room-writable `info/`) made the common dir read room-written `foo.bar` and `core.sshCommand`. The launch refusal must resolve `include.path` **and** `includeIf` (`gitdir:`/`onbranch:`) targets relative to the config's dir, recursively (an included file can include again).
- **Automatic maintenance: closed, and `maintenance.auto=false` is the one that matters on 2.56.** A `git fetch` with `gc.auto=1` spawned `git maintenance run --auto --no-quiet --detach` (git 2.56 runs maintenance, not legacy `gc --auto`; the `--detach` means it outlives the fetch — exactly the concurrent-maintenance risk). `gc.auto=0 maintenance.auto=false` suppressed it; set both (legacy and current paths).
- **`GIT_DIR` discovery and `safe.directory`: run with an explicit git dir.** `safe.directory` is **not** a backstop here: it fires only on cross-UID ownership, and under `--userns=keep-id` the room's files are the operator's, so it never blocks. If the host ran `git` with a cwd inside a worktree and no explicit dir, it discovers the room-writable worktree gitdir; `git -C <common-dir>` (or `GIT_DIR`) resolves to the common dir with no discovery. State this explicitly: the host always names the common git dir. (Named alone, the common dir still follows a `commondir` the room plants at its top: below, git 2.55.0.)
- **A garbage pack in `objects/pack/`: integrity holds, logs flood.** A malformed `pack-*.idx`/`.pack` could not substitute content for a valid oid (the push of a valid oid still delivered the genuine object), but it made host git repeat `error: index file … is too small` dozens of times to stderr, which the service logs per push/fetch — a log-noise/DoS nuisance, not a correctness break. The self-contained-store check doesn't catch a same-prefix garbage pack; left as low priority.
- **`FETCH_HEAD`: inert.** `--no-write-fetch-head` left a room-written `FETCH_HEAD` unwritten, and none of push/`ls-remote`/fetch-by-name reads it.

Responses the note should add: (1) replace the alternates refusal with a **self-contained object store** check — refuse any `objects/info/{,http-}alternates` and any symlink under `objects/` (covers the symlink bypass and the relative/nested cases); (2) extend the launch config check to refuse a committed `extensions.worktreeConfig=true`, since the common dir's `config.worktree` is room-writable; (3) have that config check resolve `include.path` **and** `includeIf` recursively; (4) state that the host runs git with an explicit common git dir and that `safe.directory` is no backstop under keep-id. Unsettled: whether to allow in-tree alternates for general projects (strict refusal fits lup's own repos, which use none) — an operator's call; and the garbage-pack stderr flood (left open, low priority).

Found while building `remote` (git 2.56.0 on the host, podman 6.1.3 and the room's image with git 2.55.0), beyond the review above:
- **A remote the room defines in a file git still reads.** A room-written `remotes/<name>` (`URL: …`) or `branches/<name>` in the common dir is a remote to host git: `git --git-dir=<common> remote get-url --push planted` printed the planted URL, with a deprecation warning. Taking the URL "from the repository's `config` by name" through `get-url` alone would let a room name any URL the operator's credentials reach, a fetch from another of their private repositories into the shared store among them. A remote the `config` names isn't read from those files (a planted `remotes/origin` beside a configured `origin` was ignored), so the host first asks `git config --local --get-all remote.<name>.url`, and refuses a name `config` doesn't hold.
- **A clone's `.git` can be moved aside.** Under the tree's mount, with `config` and `hooks/` mounted read-only inside it, `mv .git .git-real` succeeded in the room, and a `.git` of the room's own, its `config` among it, then stood where the host's git (the operator's, the judge's, the service's) reads. Mounting the git directory on its own made the move fail with "Device or resource busy". A bare repository's git directory is the tree's mount already.
- **A short destination is a protected ref by another name.** `git push <url> <oid>:main` updated `refs/heads/main` on the forge, the short name matched against the remote's refs, so a destination is held to a full name (`refs/…`, then `git check-ref-format`) before it's matched against the protected patterns.
- **What git hands a helper:** `git push --force` gives each refspec its `+` and sends no `option force`; `--force-with-lease` sends `option cas <ref>:<oid>`, its expected object resolved, and only after git's own check against `list for-push`, which refuses a stale lease before the helper hears it; a deletion of a ref the remote doesn't list never reaches the helper; a batch lists the refs the remote listed first, in its order, then the new ones; `fetch <oid> <name>` lines may repeat; `option followtags true` came after the `list` of a fetch of `refs/tags/*`.
- **`git push -u` with `config` unwritable** (a `config.lock` standing in for the read-only mount) pushed, printed "error: could not lock config file" and "unable to write upstream branch configuration", and ended with status 0.
- **`git config --file`** reads that file alone, its includes not followed; but any git command run with its working directory inside a repository reads that repository's `config` with its includes first, and fails on a circular one.

Found since, on the room's git 2.55.0 (2026-10-16), on scratch repositories laid out the same way, `<git dir>` the bare common directory and `<theirs>` a bare git directory of the room's, its `config` setting `lup.probe` and naming `origin` at another URL (#54, its second comment):
- **A `commondir` at the top of the common git directory redirects git that names it.** A bare common directory never has a `commondir` (a linked worktree's `worktrees/<name>/` does); a room can write one beside `config`, since only `config` and `hooks/` are mounted read-only. With `<git dir>/commondir` reading `<theirs>`, git read `<theirs>/config` however `<git dir>` was named: `git --git-dir=<git dir> config lup.probe`, `git -C <git dir> config lup.probe`, `GIT_DIR=<git dir> git config lup.probe` and the same run inside `<git dir>` all printed the planted value, and `git --git-dir=<git dir> remote get-url origin` the planted URL. With `GIT_DIR` and `GIT_COMMON_DIR` both set to `<git dir>`, each printed the repository's own, `config --local --get-all remote.origin.url` included. Seen in three separate checks, each with a harmless value.
- **What it reaches unpinned:** a push the host made for the room, `Remotes.git` run with `--git-dir=<git dir>` alone, listed and pushed to the planted `origin`'s URL (it failed only for want of the objects, which git then read from `<theirs>`'s store too); and `git config --file <git dir>/config` run inside `<git dir>`, as the launch reads `config` for the room's git, read `<theirs>/config` first, so a circular include there failed it. A planted `core.sshCommand` or `url.*.insteadOf` sits in the same `config`, so it would be read the same way; none was planted to run.
- **A `gitdir` file there alone** (`<git dir>/gitdir` reading `<theirs>`) redirected neither `--git-dir` nor git run inside `<git dir>`.
- Not checked: the host's git 2.56.0.

## A hook the judge doesn't read (measured, 2026-10-14)

What `docs/host-tools.md` owes before Claude Code hooks every call (*How an agent is told*): the cost of a hook the host service answers itself, without starting the judge. On the operator's machine (32 cores, Linux 7.2.6, Python 3.14.0, socat 1.8.1.3), `feat-room-sockets`' `lup-dev host` ran in the background with its XDG directories in a scratch directory, one launch registered for Claude Code, its judge the branch's own `lup-dev`. Each hook was the room's exact command (`launch/session.py`, `piped`: `sh -c 'socat -t 90000 - UNIX-CONNECT:<hook.sock> || …'`), its payload on standard input, timed from spawning `sh` to its exit, 300 runs each from a Python loop on the host. Script in the session's scratchpad.

| Hook | Median | p90 | Min | Max |
|---|---|---|---|---|
| A `Bash` call, unjudged: no decision | 4.54 ms | 5.81 ms | 3.78 ms | 7.95 ms |
| A call to `mcp__lup__report`, unjudged, stamped with its `caller` | 4.68 ms | 6.09 ms | 3.86 ms | 7.36 ms |
| `Stop`, unjudged | 4.65 ms | 6.01 ms | 3.74 ms | 9.50 ms |
| `SessionStart`, the judge's process started for it (30 runs) | 665 ms | 722 ms | 620 ms | 782 ms |
| The same `sh` and `socat` against a bare asyncio server that reads to the end and closes | 3.75 ms | 4.86 ms | 3.07 ms | |

- **The service's own part is under a millisecond** (4.54 against 3.75 ms): reading the payload, the courier's parse, minting or finding the conversation's id, and its answer. Most of a hook is spawning `sh` and `socat`, which a room pays for every hook already.
- **A hook the judge reads costs about 150 times as much,** almost all of it the judge's process starting (Python and `lup-dev`'s imports), so hooking every call on Claude Code adds about 5 ms a call, where judging every call would add two-thirds of a second. The first lup's guard in the same place took 7.85 ms against its dispatcher's 107 ms (its `17321798b`).
- Not measured: what Claude Code itself spends around a hook (spawning it, and parsing its answer), the same for a judged hook and an unjudged one; and the room's own overhead, the hook running inside a container whose `sh` and `socat` are the image's.

## GitHub through `gh` on the host (gh 2.102.0, 2026-10-14)

Read-only, on the operator's machine, logged in as the operator, for `forge/` (`docs/host-tools.md`, *GitHub through `gh`*). Nothing was created, commented or filed: the one `gh pr create` ran with `--dry-run`. `GH_DEBUG=1` shows the git commands `gh` runs and its API requests; a logging `ssh` on the `PATH` showed what it ran of ssh.

- **Naming a bare repository behind an SSH alias, the check `docs/host-tools.md` owed:** `gh repo view --json owner,name` run in lup's bare git directory (`/home/op/lup.git`, its one remote `origin` at `<alias>:joy-void-joy/lup`, `<alias>` an SSH alias in the operator's SSH configuration) answered `{"name":"lup","owner":{"id":"MDQ6VXNlcjU2MjU3NDA1","login":"joy-void-joy"}}` in 0.42 s. It ran `git remote -v` and `git config --get-regexp ^remote\..*\.gh-resolved$` there, resolved the alias with `ssh -G <alias>` (hostname `github.com`), and made one GraphQL request (0.31 s). From a directory outside any repository it failed: "failed to run git: fatal: not a git repository". lup's repository has no `gh repo set-default` recorded (`remote.*.gh-resolved` unset).
- **Exit codes:** "If a command requires authentication, the exit code will be 4" (`gh help exit-codes`); with an empty `GH_CONFIG_DIR`, `gh issue view` ended with status 4 ("To get started with GitHub CLI, please run: gh auth login"), and `gh auth status` with status 1. A missing number, or `gh pr view` on an issue's number, ends with status 1 and GitHub's GraphQL error ("Could not resolve to a PullRequest with the number of 66.").
- **An issue's number or a pull request's:** `gh issue view` on a pull request's number answers its issue fields (no checks, no branches); `gh pr view` on an issue's number fails. `gh issue view --json` has no field telling them apart; `gh search issues --json` has `isPullRequest`.
- **A pull request's checks** (`gh pr view --json statusCheckRollup`) are of two GraphQL types, told apart by `__typename`: `CheckRun` (`name`, `workflowName`, `status`, `conclusion`, empty before completion, `detailsUrl`, `startedAt`, `completedAt`) and `StatusContext` (`context`, `state`, `targetUrl`, `startedAt`), the second from a service outside GitHub Actions (nodejs/node's Jenkins, cpython's CLA bot). lup's own pull requests have none.
- **Searching:** `gh search issues` sends `( <terms> ) repo:<owner>/<repo>` with `advanced_search=true`, so a `repo:` qualifier in the query is ANDed with `--repo` rather than widening it (`repo:cli/cli refresh token` with `--repo joy-void-joy/lup` found nothing); a closing parenthesis in the query could still break out, so lup leaves out a match from another repository, read from the result's `repository.nameWithOwner`. An argument holding a space is searched as a phrase (`"refresh token"`), so a query's words and qualifiers go as separate arguments; a query starting with `-` needs `--` before it. A search's `state` is lowercase (`open`), a view's uppercase (`OPEN`).
- **Commands that need no checkout:** `gh issue view --repo` runs no git; `gh pr create --repo <r> --head <b> --dry-run` ran from a directory outside any repository and printed the pull request it would make, and run in the bare git directory it ran `git remote -v` and read `branch.<head>.*`. `--head` takes `<owner>:<branch>` for a fork's branch, so a branch's name is checked on GitHub before a pull request opens: GraphQL's `repository(owner:, name:) { ref(qualifiedName: "refs/heads/<b>") }` answers null for a branch that isn't there, `a:b` and `../x` included, its name a variable rather than a URL's path.
- **Read, not run:** `gh issue comment <n>` on a pull request's number, which lup's `comment` relies on, since `gh issue view` reads either and GitHub's `addComment` takes either's id. Owed live with the first comment a launched session makes.

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
  - A mount point podman creates is owned by root: Claude Code refused "Temp directory /tmp/claude-<uid> is owned by uid 0" (`<uid>` the operator's), and uv refused a root-owned `~/.cache`.
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

### The CLIs' release channels (2026-10-13)

Read in each vendor's installer and docs, then fetched once each through `launch/clis.py` into a scratch cache: Claude Code 2.1.296 and Codex 0.162.1, each checked against its published checksum, each answering `--version` on the host. Fetching both took 6 s here; with both current, a launch makes one request each.
- **Claude Code,** as its native installer (`https://claude.ai/install.sh`) and its setup docs (code.claude.com/docs/en/setup, *Configure release channel*, *Binary integrity and code signing*) have it:
  - `https://downloads.claude.ai/claude-code-releases/latest` answers the newest version as text, 7 bytes (`2.1.296`). `…/stable` answers the stable channel's (`2.1.287`), "typically about one week old, skipping releases with major regressions"; `latest` is the default channel.
  - `<version>/manifest.json` lists each platform (`linux-x64`, `linux-x64-musl`, `linux-arm64`, …) with its binary's SHA-256 and size; `<version>/manifest.zst.json`, the same binary compressed with zstd. The files are `<version>/<platform>/claude` (257 MB for `linux-x64`) and `claude.zst` (90 MB).
  - The installer reads `latest` and the manifest. With `zstd` installed, it downloads `claude.zst`, checks it against `manifest.zst.json`, decompresses it and checks the binary against `manifest.json`; without, it downloads the binary and checks that. Then it runs the binary's `install`.
  - `manifest.json` has a detached GPG signature, `manifest.json.sig`, by "Anthropic Claude Code Release Signing <security@anthropic.com>", whose key is at `https://downloads.claude.ai/keys/claude-code.asc` (fingerprint `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`): "verifying the signature on the manifest transitively verifies every binary it lists". The manifest also carries `"manifestSignatureEnforcement": "flag"`, and `sdkCompat`, the SDK versions it was tested with.
- **Codex,** as its standalone installer (`https://chatgpt.com/codex/install.sh`, which its README gives beside npm and Homebrew) has it:
  - `https://releases.openai.com/codex/channels/latest` describes the newest release as GitHub's releases API does, 52 KB of JSON: `tag_name` (`rust-v0.162.1`), and `assets`, each with its `name`, `browser_download_url` and `digest` (`sha256:<hex>`). A given version is `releases/<version>/release.json`, its files under `releases/<version>/`.
  - Where releases.openai.com fails, the installer falls back to GitHub Releases (`https://api.github.com/repos/openai/codex/releases/latest`, files under `https://github.com/openai/codex/releases/download/rust-v<version>/`); `CODEX_INSTALLER_USE_RELEASES_OPENAI_COM=false` goes there first.
  - For Linux on x86-64 it installs `codex-package-x86_64-unknown-linux-musl.tar.gz` (163 MB; a `.tar.zst` of 117 MB is published beside it). It checks `codex-package_SHA256SUMS` against that file's `digest`, then the package against its line there, which is the package's own `digest`. A release without packages falls back to `codex-npm-linux-x64-<version>.tgz`.
  - The package is the layout the SDK's `codex_cli_bin` bundles: `codex-package.json` (`version`, `target`, `entrypoint` `bin/codex`, `resourcesDir`, `pathDir`), `bin/codex`, `bin/codex-code-mode-host`, `codex-path/rg`, `codex-resources/bwrap` and `zsh`, and `codex-resources/voice` (a 65 MB voice host and GStreamer's libraries): 432 MB unpacked. The binary finds them beside itself ("no bundled codex-resources/bwrap binary was found next to the Codex executable", in its binary).
  - Every package and binary also has a Sigstore bundle (`<file>.sigstore`).

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

### Waking a session (Claude Code, from the first lup, 2.1.285)

- **A message to a busy session is queued, not lost.** Measured by the first lup in an interactive session (its `04f4d1594`, `482768107`): a frame written to the messaging socket while a tool call runs is taken right after the call; while the model generates, a frame without a `priority` (taken as `next`) lets the turn finish and is taken then, and a `now` frame ends the generating turn within milliseconds and is taken at once. An idle session starts a turn with it. The 2.1.296 binary still names the queue ("Routed user message to queue (priority=…)"). So lup writes the operator's items at once, unless a call is running, without tracking idleness (`inbox/delivery.py`, `wake`).
- **Sockets that collide.** The first lup's sessions met each other's sockets: the runtime's default `/tmp/cc-socks/<pid>.sock` names a live socket of another container's session wherever both are pid 7, and paths keyed by display names met an earlier session's stale socket; Claude Code refuses `--messaging-socket-path` at a live socket (its `06b544585`). lup's sockets are per launch, under a fresh id.

### The clipboard (Claude Code 2.1.302, read from its binary, 2026-10-18)

- **Copying:** on Linux, Claude Code picks its tool once: `wl-copy` where `WAYLAND_DISPLAY` is set and the program is found, else `xclip`, then `xsel`, where `DISPLAY` is set, else a native addon (`clipboard-napi`). `wl-copy` gets the text on its input, then again with `--primary`; `xclip -selection clipboard` and `-selection primary` likewise.
- **Pasting an image:** shell commands, each falling back to the next: `xclip -selection clipboard -t TARGETS -o | grep -E "image/(png|jpeg|jpg|gif|webp|bmp)" || wl-paste -l | grep …` to find one, then `xclip -selection clipboard -t image/png -o > <file> || wl-paste --type image/png > <file>`, and the same for `image/bmp`.
- **Reading text:** `wl-paste --no-newline` (`--primary` for the selection), then `xclip -selection clipboard -o`, then `xsel --clipboard --output`.
- So a room needs `WAYLAND_DISPLAY` set and `wl-copy` and `wl-paste` on its `PATH`; `xclip` missing there only makes its half of each fallback fail.
- The first lup's clipboard (its `harness/clipboard.py`) served these through command shims for Claude Code and through a private Xvfb display with a selection bridge for Codex, whose installed CLI calls no program.

### Lending to a running room (podman 6.1.3, util-linux 2.42.4, kernel 7.2.6, measured 2026-10-17)

Probed on the operator's host with throwaway containers from the room's base image, run as lup runs a room (`--userns=keep-id`):
- **A mount reaches a running container only under a mount that was shared when it started.** A directory bound to itself and made shared in podman's namespace (`podman unshare mount --bind D D`, `mount --make-shared D`), then mounted into the container with `bind-propagation=rslave` (or `rshared`): a directory mounted under it afterwards (`podman unshare mount --bind SRC D/data`) was visible in the running container, and unmounting it on the host removed it there. Without propagation, as rooms were mounted before, nothing mounted later reached the container.
- **Read-only has to be set before the mount spreads.** Bound, then remounted read-only (`mount -o remount,bind,ro`), the mount was read-only on the host's side and writable in the container: a remount's flags don't propagate to a slave's copy. Two ways gave a read-only mount there: `mount --bind -o ro` in one step (util-linux 2.42 applies the flag before attaching the mount; older versions remount after, which would spread it writable), and binding into a private directory, remounting read-only there, then binding that into the shared one. lup uses the second (`lup.rooms.engine.Podman.lend`), whatever the host's util-linux.

## Isolation and effects

- An overlay mounts over 300k files in 13 ms and lists its changes in 12 ms, without root, in lup's container (kernel 7.2).
- A git snapshot per command costs about 50 ms at lup's size, 0.4–0.8 s at 100k files, and 1.4–2.8 s at 300k.
- Judging after the fact misses three things:
  - background writers (a process detached with `setsid` escapes);
  - files git ignores;
  - code that runs inside the same call (a planted `core.fsmonitor` ran).

## Judging writes

What the judge (`docs/judging-writes.md`) rests on, measured on the operator's machine; the spikes' evidence is under `tmp/spikes/` in the `main` checkout.
- **A checkpoint's cost,** through the store's own code, for each worktree a session holds: 70 to 100 ms where nothing changed, about nine git processes, of which the snapshot is 5 ms at lup's size and 10 to 15 ms at nori's 4,000 files; a worktree's first snapshot 40 to 50 ms at lup's size and 2.5 to 3.6 s at nori's. The downstream projects have 161 to 3,721 tracked files. With the tests' stub engine on a 97-file clone of lup, a call's start and finish where nothing changed took 52 ms and 8 git processes holding one worktree, 148 ms and 20 holding three; a checkpoint alone, 37 to 43 ms. Judging every worktree of a repository rather than those a session holds would cost about 80 ms each: 0.25 s for 3 worktrees, about 3.5 s for nori's 36. The target is under 300 ms per checkpoint, type check included, for a session holding one or two worktrees.
- **Reading a commit's declaration:** exporting lup's tip (141 Python modules, from git's objects) took about 100 ms, then 1 ms to load it.
- **Calls no hook finishes:** a configuration hooking only `PreToolUse` counts each call it lets through and finishes none. While a checkpoint waited on every session's calls in its worktree, lup's own Claude Code sessions and a launched Claude Code room left 9,858 calls counted across 48 of lup's worktrees by 2026-10-13, and a Codex session launched in `dev` had no write judged (its patch adding `import subprocess` stayed), which is why a checkpoint waits only on its own session's calls.
- **The engine's spike** (pyright 1.1.414, about 970 lines of TypeScript, `tmp/spikes/pyright-rules/`):
  - the same answers as pyright: on the first lup's library, 32 of 32 type errors matched the CLI's exactly;
  - the rules cost under 1% of the check, at most 8 ms a file;
  - warm re-checks of one changed file took 65–270 ms median (10–620 ms range), of ten files 0.5–2.7 s, nearly all of it pyright's own re-check, on a heavily loaded machine;
  - the typed `string-split` leaves out `shlex.split` and `re.split`, which a syntax-only rule flags; `tuple-shape` caught every alias form tried;
  - the rule code compiled unchanged against pyright releases 17 months apart, and about 40 lines of project setup broke;
  - a 3.5 MB bundle plus 28 MB of standard-library stubs, and 1.5–2.7 GB of memory on a 700-file project, for each worktree's engine.
- **Loading lup's project** in the engine takes 1.4 s, which an engine per hook would pay at every hook. The importers pass run whole, rather than a file at a time, would hold a check behind 27 s of re-checking on the first lup's library.
- **Rules in Python over `ast`,** asking the warm engine by position (`tmp/spikes/rule-shape/`): the same findings as the table on 739 files, but their checks cost 10 to 20 times more, and they miss types pyright reads in strings outside annotations (`cast("tuple[int, str]", value)`) unless the engine lists them.
- **uv in the judge's path:** `uv run` adds about 12 ms to a ruff call (26 ms against 14 ms for one file's check), and `--no-sync` saves about 3 ms of it; asking uv for the interpreter costs about 28 ms a program, against 1.4 s for the program; making lup's environment from uv's cache took 0.7 s. Plain `uv run` relocks a stale or missing lock: a `pyproject.toml` holding only `[tool.pyright]` got a `.venv` and a `uv.lock`.
- **The gate on lup,** with pytest on one worker: pytest was 75 of the gate's 85 s, lup's rules 8 s warm. Over 66 files, the rules step took 1.3 s warm and 5.6 s with the engine cold.
- **Reading lup's host zone for an approval** (2026-10-18, in a room, the engine and ruff run as `Trust.read` runs them, lup's defaults judging): the zone whole at `dev`'s tip, as a first approval, 212 files and 54,465 lines, took 10.8 to 10.9 s, the engine cold or warm; the 40 commits before the tip, 70 files, 5.8 s. What it folds is little, lup's zone being nearly all production code, which opens wherever a line changed: every production file of a first approval is new and asks `new-file`, so 204 of the 212 stay open, 51,304 lines shown of 54,465; over the 40 commits, 15,293 lines shown against 16,379 with every file open; over the last 10, 3,107 against 3,114. A first approval's new files ask `public-api` too, once for each class they define: 932 such asks.
- **An approval's reading, from the parse alone and whole** (2026-10-18, on the operator's machine, lup's own declaration judging): over the 40 commits before `dev`'s tip, 60 files, 33 of them Python, 64 versions of those read, the whole judgement took 8.3 s with the engine warm (checking the versions after the change 3.3 s, those before it 3.0 s, ruff 1.3 s, a process a file), 11.5 s cold. The same versions read from their parse alone took 0.35 s through the engine's one-shot `parse` command, 0.15 s of it Node's start, whatever the worktree's engine was doing; 0.21 s asked of a warm engine on its socket, 0.94 s of a cold one, whose start loads a project the parse never reads; and through the program, each file bound and each annotation's type printed but nothing checked, 1.0 to 3.2 s. Over the whole zone, 212 files and 1.46 MB of Python, the whole judgement took 5.7 s warm, 5.1 s of it ruff, and 13.2 s cold, the parse 0.35 s. Judged from the parse, the asks were the whole judgement's exactly, over the last 10 and 40 commits and the whole zone (938 public-API asks, 196 new files, 24 `ignore`s added, 15 protected paths): what types add to an approval's reading is lup's findings.
- **What the judge relies on from Claude Code's hooks reference:** `PreToolUse` "runs before a tool call executes", `PostToolUse` "after a tool call succeeds", `PostToolUseFailure` "after a tool call fails", each with the call's `tool_use_id`, and matching hooks "run in parallel"; a call the operator declines at its prompt reports neither. `cwd` "follows Claude: the `cwd` field in the hook's input JSON is the worktree root after Claude enters a worktree, and the new directory after Claude runs `cd`." `SubagentStop` "Runs when a Claude Code subagent has finished responding" and takes "the same decision control format as Stop hooks"; a `Stop` hook's `additionalContext`, like a block's `reason`, means "The conversation continues so Claude can act on it". From its environment-variable reference, `CLAUDE_CODE_CHILD_SESSION` is "set to `1` in subprocesses Claude Code spawns via the Bash, PowerShell, and Monitor tools, hook commands, and status line commands", and unlike `CLAUDECODE` is "only set by Claude Code itself when it launches a subprocess and not by IDE extensions" (observed in a session's commands). Its own record of a command's edits (`bashEditDiff`) misses files, a protected one among them.
- **What the judge relies on from Codex** (its docs, and its source at `rust-v0.156.1`): its `PermissionRequest` for `apply_patch` carries the patch and no file list (`core/src/tools/approvals.rs`), and fires only for a patch needing approval: under `on-request`, one writing outside the writable roots or retried after a sandbox denial; under `never`, never. Its `PreToolUse` can't ask: "`permissionDecision: "ask"` … [is] parsed but not supported yet". Its hooks' `cwd` is the "Working directory for the session", and "`Bash` and `apply_patch` use `tool_input.command`". A hook's `timeout` defaults to 600 s with no maximum (`timeout_sec.unwrap_or(600).max(1)`, `hooks/src/engine/discovery.rs`), and a hook that times out fails open. Codex sets `CODEX_THREAD_ID` in every command its agent runs, after the shell environment policy so a profile can't strip it, with `CODEX_CI=1` (`core/src/unified_exec/process_manager.rs`); its hooks run without them. A `PostToolUse` hook's `additionalContext` "is added as extra developer context", where `decision: block` would replace the call's result; `Stop` takes no `additionalContext`, and a block's `reason` becomes "a new continuation prompt". A subagent's tool hooks carry its `agent_id`, and each of its turns ends with `SubagentStop` (`core/src/hook_runtime.rs`), whose input carries `stop_hook_active` (`subagent-stop.command.input`).
- **Unchecked:** whether a `PreToolUse` hook's `allow` skips auto mode's classifier (Claude Code's permission docs say a mod's approval does, and nothing of a hook's); whether Claude Code's `cwd` follows a `cd` in a subagent's calls, whose shell starts each call in the project's directory; and whether either runtime reports `SubagentStop` for a subagent the operator stops, or one that fails. Claude Code's `Stop` input lists the session's `background_tasks`, subagents among them, "present when the task registry is reachable", which would tell there.

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

## The declaration

For `docs/declaration.md`: what its code and its next pieces (a project's own rule tables, lup's settings for ruff and pyright, the command line) rest on.
- **Node for rule tables in TypeScript** (Node's `api/typescript.html` and `api/module.html`):
  - type stripping runs without its experimental warning from 24.3.0 and 22.18.0, and is marked stable from 25.2.0 and 24.12.0;
  - `module.registerHooks` arrived in 23.5.0 and 22.15.0;
  - so 22.18 is the oldest Node that runs both without a flag, the version `CodeRules`' requirement takes;
  - stripping refuses enums, namespaces holding values and parameter properties.
- **A table loaded through the engine's bundle:**
  - an esbuild 0.28.2 CommonJS bundle, built as `build.py` builds the engine (`--platform=node --target=node20`), kept `import()` as written;
  - through that bundle, Node 26.10 loaded a `.ts` table holding an interface and a typed constant, with no flag;
  - a `registerHooks` resolve hook registered from the bundle resolved a fixed bare name, `lup-engine`, for the stripped table.
- **TypeScript's compiler:** pyright 1.1.414 pins `typescript ~6.0.3`, whose `lib/typescript.js` is 8.8 MB unminified.
- **Probes print bare versions:** `node -p process.versions.node` printed `26.10.0`, `uv self version --short` printed `0.12.23`, and `podman version --format '{{.Client.Version}}'` printed `6.1.3`.
- **ruff's target version** (0.16.10):
  - it's inferred from `requires-python` in the `pyproject.toml` holding `extend` (3.12 from `>=3.12`);
  - in a uv workspace whose root `pyproject.toml` has no `[project]`, as lup's, a member without its own `[tool.ruff]` gets none (`linter.unresolved_target_version = none`), and the formatter falls back to 3.10.
- **ruff in a workspace:**
  - a member without a `[tool.ruff]` gets the root's settings;
  - a member's `extend = "../../pyproject.toml"` chains through the root to the base the root extends, with the member's own `ignore` on top and its own `requires-python` as its target version.
- **pyright's configuration** (1.1.414):
  - it's parsed as JSON with comments (`JSONC.parse`, `analyzer/service.ts`);
  - an `extends` target ending in `.toml` is read as a `pyproject.toml`'s `[tool.pyright]` (`_getExtendedConfigurations`), with its comments.
- **`.gitignore`** (git 2.56): `.lup/` followed by `!.lup/settings/` leaves `settings/` ignored, since git never looks inside an ignored directory; un-ignoring it takes `/.lup/*`.
- **`uv sync --managed-python`** moved a `.venv` on `/usr/bin/python3.14` onto uv's own 3.14. That's the remedy `Uv` gives when a room can't reach the interpreter.
- **`uv init --lib --build-backend uv --vcs git`** writes:
  - `pyproject.toml`, `src/<name>/__init__.py` and `py.typed`;
  - `.python-version`, `.gitignore` and a README;
  - a git repository.

  Its `hello()` has no docstring, which ruff refuses.
- **grimp 3.17,** which import-linter 2.15 brings, answered `chain_exists(importer=…, imported="lup_dev", as_packages=True)` and `find_shortest_chain` on lup's packages.
- **click's help listing** calls `get_command` for every entry (`click/core.py`, `format_commands`), so a lazy group has to list from its own data.

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

## Where each runtime keeps its sessions' records (2026-10-17)

Read on the operator's machine for the `Transcripts` module (`lup/transcripts/`), and from the first lup's own reading of Codex's rollouts (its `test_native_transcripts.py`); Codex's was not read on a live home, since this machine has none.
- **Claude Code** (its directory, `~/.claude` or `CLAUDE_CONFIG_DIR`): `projects/<folder>/<session>.jsonl` per session, the folder one per directory sessions ran in; beside a session's record, `projects/<folder>/<session>/subagents/` and `tool-results/`; and `file-history/<session>/`. A record's lines carry `cwd`, the first ones (`mode`, `permission-mode`, `file-history-snapshot`) without it, so the directory a folder's sessions ran in is read off its first line naming one. A launched room writes into the operator's own directory, mounted read-write at its path.
- **Codex** (`~/.codex` or `CODEX_HOME`): `sessions/YYYY/MM/DD/rollout-*.jsonl`, whose first line is `{"type": "session_meta", "payload": {"cwd": …}}`.

### A session's record (Claude Code 2.1.302, measured 2026-10-18 on this repository's sessions)

What `lup-dev transcripts` reads of `projects/<folder>/<session>.jsonl` (`adapters/claude.py`, `ClaudeTranscripts`). Counted over 20 sessions: most lines are `assistant` (9,190), `attachment` (7,643) and `user` (5,254), beside bookkeeping lines (`api-request`, `last-prompt`, `mode`, `ai-title`, `permission-mode`, `queue-operation`, `custom-title`, `agent-name`, …).
- **The operator's typed words** are `user` lines with `origin: {"kind": "human"}` (and `promptSource: "typed"`), their `message.content` a string. Other `user` lines: a tool's result (`content` in parts with a `tool_result`, 4,884 of them), a task's notice (`origin.kind: "task-notification"`), a message from another conversation (`"peer"`), and Claude Code's own (`isMeta`, `isCompactSummary`, `<command-name>`, `<local-command-stdout>`). An older line with no `origin` is the operator's where it's text that isn't such a tag; text in parts with no `origin` is Claude Code's (`[Request interrupted by user]`).
- **Words sent while the agent works** are `attachment` lines of `type: "queued_command"`, `commandMode: "prompt"`, `origin.kind: "human"`, the words in `prompt`.
- **The agent's words** are `assistant` lines' `text` parts; its calls their `tool_use` parts, by `name`; `thinking` parts are its own.
- **The session's name:** the last `custom-title` line's `customTitle` (the operator's `/rename`, or lup's `sessionTitle`), else `agent-name`'s `agentName`, else `ai-title`'s `aiTitle`. Its directory is a `user` line's `cwd`.
- Reading a 6 MB record this way took 0.03 s.

### A thread's rollout (Codex, read from its source at `rust-v0.163.0`, 2026-10-18; not measured on a live rollout)

What `lup-dev transcripts` reads of `sessions/YYYY/MM/DD/rollout-*.jsonl` (`adapters/codex.py`, `CodexTranscripts`). Each line is `{timestamp, ordinal?, type, payload}` (`history/src/lib.rs`, `RolloutLine`), `timestamp` UTC to the millisecond; `type` one of `session_meta`, `response_item`, `event_msg`, `turn_context`, `compacted`, and others (`history/src/rollout_payload.rs`).
- **Two history modes:** `session_meta.payload.history_mode`, `legacy` where absent. From 0.163 the TUI and `codex exec` start threads `paginated` (`tui/src/app_server_session.rs`, `exec/src/lib.rs`).
- **The operator's words and the agent's** are events: `user_message` and `agent_message` in the legacy mode (`protocol.rs`, `UserMessageEvent`), `item_completed` with a `UserMessage` or `AgentMessage` item in the paginated one (`protocol/src/items.rs`). Both modes also write `response_item` messages (`role: "user"` with `input_text`, `role: "assistant"` with `output_text`), which repeat them and carry injected context as `user` messages too (AGENTS.md, `<environment_context>`); so the events are read, and the messages passed over.
- **Tools called** are `response_item`s: `function_call` and `custom_tool_call` by `name`, after their `namespace` but for `functions` (`protocol/src/tool_name.rs`); `local_shell_call`, with no name.
- **The thread's name** isn't in a 0.163 rollout: it's appended to `session_index.jsonl` in Codex's home, the last line for an id winning (`rollout/src/session_index.rs`), which lup doesn't copy. Rollouts before 0.163 carry `thread_name_updated` events.
- **A subagent's thread** has a rollout of its own, its `session_meta` naming `parent_thread_id`; it isn't listed as a session.

### Subagents' records (Claude Code 2.1.301 and 2.1.302 measured, 2026-10-17; Codex read at `rust-v0.163.0`)

What each runtime records of a subagent's spawn, which lup reads to name it and place it under its parent (`docs/launch.md`, *Names*):
- **Claude Code** writes `<session>/subagents/agent-<agent_id>.meta.json` beside the session's transcript, one flat folder for every depth. Read in this session's own folder: `{"agentType": "general-purpose", "launchedWithDefaults": true, "description": …, "name": "meta-probe", "toolUseId": "toolu_…", "spawnDepth": 1, "requestShape": "background", "requestNonInteractive": true, "finished": true}`; `name` only where the spawn gave one. A subagent spawned by a subagent adds `"parentAgentId": "<its parent's agent_id>"` with `"spawnDepth": 2`.
  - **A session's `Agent` takes `name` though its schema doesn't list it** (2.1.302, 2026-10-18): a session whose tool schema showed no `name` spawned with `name: "name-probe"`, and the spawn's record read `"name": "name-probe"`. An agent reading the schema concludes it can't name a spawn.
  - **A subagent's own `Agent`:** asked to spawn one named, a subagent reported that its `Agent` tool has no `name` parameter, and its spawn's record had none. That came from reading the schema, which hides the parameter from a session too, so whether a subagent's spawn takes a `name` it isn't shown is unmeasured; lup tells only a session's own conversation to name what it spawns.
  - **Found from a subagent's hooks:** each carries `agent_id` and `agent_type`, and the first lup found the record beside the hook's `transcript_path`, the session's transcript (its `caller_payload.py`, measured on 2.1.283), where the record's `name` was there from the subagent's first tool call and absent at `SubagentStart`; lup's hooks don't include `SubagentStart` on Claude Code.
- **Codex** heads each subagent's own rollout with a `session_meta` (`protocol/src/protocol.rs`, `SessionMeta`): its `id` (the hooks' `agent_id`), `session_id` (the root thread's, shared by the tree, and the hooks' `session_id`), `parent_thread_id`, `agent_role` and `agent_path`, `/root/<name>/…`, each ancestor's name before its own. The first lup measured on 0.158.0 that every event fired inside a subagent names that rollout as `transcript_path`, and `SubagentStop` names the root's and adds `agent_transcript_path`; so a rollout whose `id` isn't the subagent's says nothing of it.
  - **Naming a spawn:** the first `spawn_agent` takes no name (`create_spawn_agent_tool_v1`, `core/src/tools/handlers/multi_agents_spec.rs`: `message`, `items`, `agent_type`, `fork_context`, `model`, `reasoning_effort`), and spawns with no `agent_path` (`tools/handlers/multi_agents/spawn.rs` passes `task_name` as `None`). The second requires `task_name`, `[a-z0-9_]`, and joins it onto the parent's path.
  - **Its tool's name in hooks:** `spawn_agent` for the first, or for the second without a namespace (`core/src/tools/registry.rs`, `function_hook_tool_name`, with `Agent` as a matcher alias); the second is namespaced `collaboration` by default (`DEFAULT_MULTI_AGENT_V2_TOOL_NAMESPACE`), and a namespaced tool's hook name is the namespace and the name joined with nothing between, `collaborationspawn_agent` (`core/src/tools/mod.rs`, `flat_tool_name`).
- **What a subagent reads of the guidance, and whether it has lup's tools** (2026-10-19):
  - **Claude Code** (its `sub-agents` docs; this session's records, 2.1.303): a non-fork subagent's system prompt is "the agent's own prompt plus environment details", so lup's guidance, appended to the session's, never reaches it; a fork "sees the same system prompt, tools, model, and message history as the main session", and its record says `"agentType": "fork"`. A subagent inherits the session's MCP tools unless its definition's `tools` or `disallowedTools` drop them, and a user or project agent named like a built-in replaces it, so a type's name doesn't fix its tools. Hooks carry `agent_type`, never a tool list. The subagent's own record opens with a `deferred_tools_delta` attachment naming the deferred tools it was given (`mcp__lup__…` for a general-purpose subagent, none for `claude-code-guide`): undocumented, and absent where tool search is off. `--append-subagent-system-prompt` reaches every non-fork subagent, in non-interactive mode only. `SubagentStart`, which lup doesn't hook, can add context before a subagent's first request.
  - **Codex** (read at `rust-v0.163.0`, not measured live): a spawned thread's configuration is its parent's, the requirements among it (`core/src/agent/child_config.rs`, `build_agent_shared_config`), which a role keeps (`core/src/agent/role.rs`, `build_config_layer_stack`), and every thread but a reviewer's of Codex's own is given the managed developer instructions (`core/src/session/world_state.rs`), so every subagent reads lup's guidance. A role can't change `mcp_servers` (`apply_role_to_config_inner`; `role_tests.rs` asserts them equal to the parent's), and each thread opens its own MCP connections, so every subagent has lup's tools. A spawned thread fires `SubagentStart`, never `SessionStart` (`core/src/hook_runtime.rs`, `run_pending_session_start_hooks`), and no hook lists tools.

## A turn's end told through `additionalContext` (Claude Code 2.1.303, measured 2026-10-19)

`claude -p` on Haiku with `--setting-sources ""`, `--strict-mcp-config` and `--settings` holding only a spike's hooks, a script printing JSON; what the model reads checked in the transcript and in the binary's renderers.
- **`Stop` answering `hookSpecificOutput.additionalContext` continues the turn.** The transcript keeps a `hook_additional_context` attachment, which the model reads as a system reminder, `Stop hook additional context: <text>` (several hooks' texts joined by newlines). A block's reason reaches it twice: a meta user message, `Stop hook feedback:\n<reason>`, and a `hook_blocking_error` attachment, `Stop hook blocking error from command: "<command>": <reason>`. Given both, the model reads all three.
- **The next end carries `stop_hook_active: true`** after an `additionalContext` continue, as after a block: after a tool call in the continued turn too, and after each of two continues in a row.
- **`SubagentStop` is the same:** the subagent goes on (`SubagentStop hook additional context: <text>` in its record), and its next `SubagentStop` carries `stop_hook_active: true`.

## A session's title, and a subagent's name on screen (Claude Code 2.1.303, measured 2026-10-19)

- **`sessionTitle` does what `/rename` does.** `SessionStart`'s at startup, and `UserPromptSubmit`'s, each wrote a `custom-title` and an `agent-name` line with it, the two lines `/rename` writes. The next `UserPromptSubmit`, and a resume's `SessionStart`, carry it as `session_title`, so after lup's first start every resume brings lup's own earlier title; `sessionTitle` at a resume sets it again. Each resume writes the current title's two lines again.
- **A subagent on screen** (interactive): the panel below the prompt shows the `Agent` call's `name`, else the subagent's type, then the call's `description`; the call's line and its end show the description (`Agent (quote test)`, `Agent "quote test" finished`), and what it sends comes `from @<name or type>`. No hook sets it: `SubagentStart` takes context alone (*hooks*).

## A conversation resumed in a later launch (read 2026-10-16)

For `docs/resume-guidance.md`: Claude Code's docs (code.claude.com/docs/en: *hooks*, *cli-reference*, *sessions*) and its 2.1.301 binary's help; Codex's docs (developers.openai.com/codex: *hooks*, *config-reference*) and its source at `rust-v0.163.0` (paths under `codex-rs/`), the same at `rust-v0.162.1` where checked.
- **Claude Code records the system prompt.** It builds it once, at a conversation's first request, with the system prompt flags' text, records it in the session, and until the conversation is compacted every later request uses the record, after `--resume` or `--continue` too (*cli-reference*, *System prompt flags in resumed conversations*). `--system-prompt-snapshot off` (2.1.257 and later): "never record; the prompt is rendered fresh every request". At a resume whose prompt cache has likely expired it says so (`prompt_cache_likely_expired`).
- **Codex sends a resumed thread later `developer_instructions` only once it's compacted.** They're part of the initial context (`core/src/session/mod.rs`, `build_initial_context_with_world_state`), written only to a thread with no recorded turn context, and again at a compaction (`core/src/compact.rs`); a resumed thread has one from its rollout, and after it only changes to the world state are written (`record_context_updates_and_set_reference_context_item`; the test `record_initial_history_restores_world_state_baseline` writes nothing on resume). `additional_developer_instructions`, a managed requirement, are in the world state (`core/src/context/world_state/managed_developer_instructions.rs`): kept by their hash, and where they changed, sent again whole, opening "These managed developer instructions replace all previously provided managed developer instructions." The markers and that notice add 169 bytes to the text (`validate_managed_developer_instructions`).
- **Both keep the conversation's id on resume, and say it's one.** Claude Code's `SessionStart` `source` is `resume` for "`--resume`, `--continue`, or `/resume`" (*hooks*), and `--fork-session` makes "a new session ID instead of reusing the original" (*cli-reference*). Codex's is `resume` too, run at the thread's first turn after it (`core/src/hook_runtime.rs`), its id the rollout's (`core/src/session/session.rs`). Each also has `startup`, `clear`, `compact` and `fork`; a fork's hook names no parent on either.
- **What a `SessionStart` hook tells reaches the model, and stays.** Claude Code puts `additionalContext` in a system reminder "at the point where the hook fired", and `/resume` "waits for the hooks to finish"; it saves the text in the transcript and replays it (*hooks*, *Add context for Claude*). Codex adds it "as extra developer context", and its rollout keeps it. So what's told at one resume is still there, perhaps stale, at the next. Each hook's cap on what it tells whole: `docs/host-tools.md`, *Told once*.
- **Sizes:** on 2026-10-17 lup's own guidance's section files came to about 23 KB (`AGENTS.md` 10.9 KB, `Core`'s 8.6 KB), before lup's tools and other repositories are listed: past either hook's cap whole, and over half of Codex's 40,000 bytes of managed instructions.
