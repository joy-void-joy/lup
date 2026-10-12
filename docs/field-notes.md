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
- pacman needs a dated Arch Linux Archive mirror (not verified).

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
