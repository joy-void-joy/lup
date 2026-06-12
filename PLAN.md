# Refactor Plan: True SDK Parity + Repo Stabilization

## Goal

Make the lup inner-agent genuinely runnable on either the Claude Agent SDK or the OpenAI Codex SDK — same feature set, same enforcement, same session artifacts — and bring the repo itself to a healthy baseline: working devtools, CI, truthful docs, and tests that exercise wiring rather than construction.

This plan supersedes the previous SDK-interop status document. That document marked all phases DONE; an end-to-end review showed the pieces exist and pass unit tests, but the Codex path is not wired: `serve-tools` serves 2 of 13 tools, the reflection gate guards a tool that never fires on Codex, generated permission scripts match Claude tool names, and subagents are prompt text with no invocation mechanism.

## Locked Decisions

1. **True parity (Option A)** — both SDKs get the full one-shot feature set. Not "basic mode", not removal.
2. **Output is a lup-owned MCP tool on every backend.** `submit_output` (schema = `AgentOutput`) replaces Claude's native `output_format` and Codex's native `output_schema` as the finalization mechanism.
3. **Enforcement lives in tool handlers first, hooks second.** The reflection gate is checked inside `submit_output` itself (deny via `is_error` until reflected). PreToolUse hooks become optional hardening. This removes the hard dependency on Codex's experimental `features.codex_hooks` flag.
4. **State crosses process boundaries via filesystem + env.** One convention everywhere: session context enters subprocesses through env vars; mutable state (gate flag, output, metrics) relays through files in the session directory.
5. **One MCP server name on all backends: `notes`.** Tool names like `mcp__notes__submit_output` must be identical on every path, or gates and prompts diverge again.
6. **Subagent spec is shared; implementation is per-adapter.** Claude keeps native `AgentDefinition` subagents. Codex gets a served `run_subagent` tool that dispatches `query()` from the same `SubagentSpec` list.
7. **Persistent/realtime mode stays Claude-only in this refactor.** The sleep/wake tools require tool→parent IPC on Codex (different problem class). Deferred with a design sketch — built after Phases 2–5 proved the relay pattern, exactly as the sketch prescribed (Phase 9).
8. **Phase 0 (devtools regressions, CI) ships independently off `dev`** — it is unrelated to interop and unblocks everything else.

## Current State

### Actually working

- [x] `lup/types.py` type layer (blocks, messages, response, hooks, `SubagentSpec`)
- [x] `AgentAdapter` / `Conversation` ABCs; Claude adapter + converters (tested)
- [x] Codex adapter basics: prompt → run → collect, config-override assembly (thread `resume()`/`fork()` shipped here, later removed unused — see Deferred Work)
- [x] OpenAI-compatible adapter (Codex runtime + `model_provider`)
- [x] `core.py` dispatch with zero `claude_agent_sdk` imports
- [x] File-backed `ReflectionGate`; Codex hook **script generation** (generation only)
- [x] Config fields for SDK selection, Codex sandbox/effort/approval

### Wired but dead at planning time (all fixed by the phases below)

- [x] `serve-tools` serves only `EXAMPLE_TOOLS` — reflect/realtime/sandbox tools never reach Codex (`devtools/agent.py: collect_tools_by_server`) — fixed in Phases 2/5/9
- [x] Gate guards `"StructuredOutput"`, which doesn't exist as a tool on Codex; nothing can set the flag file (`core.py: build_codex_adapter`) — fixed in Phase 2
- [x] Generated permission scripts match Claude tool names (`Write`/`Edit`/`Read`/`Glob`/`Grep`) — unverified against real Codex hook events (`adapters/codex_hooks.py`) — resolved in Phase 3 (hooks unusable; native sandbox + in-tool gate)
- [x] Subagents on Codex are a system-prompt section with no invocation mechanism (`core.py: format_subagent_prompt_section`) — fixed in Phase 4
- [x] Sandbox constructed only on the Claude path (`core.py: build_adapter`) — fixed in Phase 5
- [x] `settings.max_turns` / `settings.max_budget_usd` never wired into `build_options`; `query()` silently drops options on non-Claude backends; background factory silently drops `tools` on Codex — fixed in Phases 4/6 (budget on Codex in Phase 9)
- [x] `lup/__init__.py` eagerly imports `adapters.claude_client`; exports retired `ResponseCollector` alongside its replacement — fixed in Phase 6
- [x] `core.py` writes traces to `notes/traces/<session_id>/` bypassing the versioned `lup.paths` layout — fixed in Phase 6
- [x] Devtools: `version` sub-app crashes (`click.get_current_context()`), `usage` hangs in non-TTY, `ruff format` failing on 24 files, no CI — fixed in Phase 0 (CI deferred at user request)
- [x] Docs: README unfinished, CLAUDE.md structure stale, `lup.lib` docstring refs, PATTERNS.md references `lup.client` — addressed in Phase 8 (the only remaining `lup/lib` matches are regenerated `.egg-info` metadata, not code)

## Target Architecture

```
┌────────────────────────────────────────────────────────────────┐
│ Consumer code (core.py) — lup.types only                       │
├────────────────────────────────────────────────────────────────┤
│ Finalization: mcp__notes__submit_output (ALL backends)         │
│   - validates AgentOutput in-handler (is_error retry)          │
│   - checks ReflectionGate in-handler (deny until reflected)    │
│   - writes session_dir/output.json (build_result reads it)     │
├──────────────────────────┬─────────────────────────────────────┤
│ Claude path              │ Codex / OpenAI path                 │
│ in-process MCP "notes"   │ serve-tools subprocess = MCP "notes"│
│ in-process hooks         │ env contract: LUP_SESSION_DIR,      │
│ native AgentDefinition   │   LUP_OUTPUTS_DIR, LUP_GATE_FLAG,   │
│ Stop-guard for unsubmit  │   LUP_TASK_ID, LUP_SESSION_ID       │
│                          │ native sandbox_mode+writable_roots  │
│                          │ run_subagent tool (query dispatch)  │
├──────────────────────────┴─────────────────────────────────────┤
│ State relay: files in session dir (gate flag, output, metrics) │
└────────────────────────────────────────────────────────────────┘
```

### Context relay contract

| Env var | Meaning | Read by |
|---|---|---|
| `LUP_SESSION_DIR` | session notes directory | serve-tools (reflect, output tools) |
| `LUP_OUTPUTS_DIR` | past outputs root | reviewer subagent |
| `LUP_GATE_FLAG` | reflection gate flag file | gate (tool-side and hook-side) |
| `LUP_TASK_ID` / `LUP_SESSION_ID` | identifiers | sandbox naming, metrics |

`build_mcp_config_overrides()` gains an `env` parameter emitted as `mcp_servers.notes.env.*` overrides. Constants live in `lup/paths.py` so both producer (core) and consumer (serve-tools) import one definition.

---

## Phase 0 — Stabilize (independent; worktree off `dev`)

- [x] Fix `version` callback: take `ctx: typer.Context` instead of `click.get_current_context()` (restores `version`, `changelog`, `bump`, and the `/lup:bump`, `/lup:fb-status` workflows)
- [x] Fix `usage`: one-shot render by default, watch mode behind `--watch`; never block without output on non-TTY
- [x] `uv run ruff format .` (24 files) and commit
- [ ] ~~Add CI workflow~~ — deferred at user request (no GitHub workflow for now)
- [x] Pin `openai-codex` git dependency — pinned to release tag `rust-v0.139.0` in `[tool.uv.sources]`
- [x] Standardize the read-only overview verb to `status` across sub-apps (`sync list` → `sync status`)
- [x] Dedupe `copy_to_clipboard` into `devtools/utils.py`; replace `setup.py` `parents[3]` with `lup.paths.project_root()`; guard rebase-state reads in `dev/conflicts.py`; guard `splitlines()[0]` in `version.py`

**Verify:** `uv run lup-devtools version`, `version changelog`, `usage` all exit cleanly; `dev check` reports 4/4; CI green on a test PR.

## Phase 1 — Output unification (keystone; Claude path first)

- [x] `lup/output.py`: `create_output_tool(output_model, session_dir, gate)` → `submit_output` LupMcpTool. Handler: validate → if gate not reflected, `is_error` "call review first" → write `session_dir/output.json` → mark complete
- [x] Completion state file (`output.json`) is the single source `build_result` reads (`result.structured_output` remains the fallback only until the Codex path migrates in Phase 2)
- [x] Claude path: drop `output_format` from `ClaudeAgentOptions`; register `submit_output` on the `notes` server; add Stop hook (`create_completion_guard` in `lup/hooks.py`) that blocks stop until output exists, with a corrective message
- [x] Spike verified live: an agent that ends without submitting is blocked by the Stop hook, reads the corrective message, self-corrects (review → submit); retries bounded at 3
- [x] Keep the PreToolUse gate hook on Claude as hardening (matcher `mcp__notes__submit_output`)
- [x] Tests: gate-in-handler denial → reflect → submit succeeds; invalid output → `is_error` retry; stop-guard path
- [x] (Added during live verification) `Usage` model + injectable per-adapter `usage_normalizer` callbacks: raw vendor usage payloads (nested dicts/strings) crashed result conversion; adapters now normalize to portable token counts via a constructor-supplied callback, with `SerializeAsAny` so custom subclasses survive into session JSON

**Verified:** `AGENT_SDK=claude uv run lup run "test task"` produces `output.json` + `AgentSessionResult` end-to-end ($0.29 smoke session); Stop-guard probe confirmed forced continuation + self-correction.

## Phase 2 — Context relay + dynamic serve-tools

- [x] Env contract (`SessionContext` + constants) in `lup/paths.py`; `build_mcp_config_overrides(env=...)` emits `mcp_servers.notes.env.*`
- [x] `serve-tools` builds tools from env context: example + reflect (file-backed gate from `LUP_GATE_FLAG`) + `submit_output`; `collect_tools_by_server(context)`; `--list` flag (sandbox tools join in Phase 5)
- [x] `lup/metrics.py` gains write-through flush (`session_dir/metrics.json`); `build_result` reads the flushed file when present, in-process collector otherwise (no merge needed — tools run entirely in one process per backend)
- [x] `core.py`: shared `build_codex_session()` scaffolding passes env; gate matcher is `mcp__notes__submit_output`; Codex no longer passes native `output_schema`; `build_result` fallback to `structured_output` removed
- [x] Codex MCP server key renamed `lup-tools` → `notes`

**Verified:** the no-LLM integration test (`tests/integration/test_serve_tools.py`) round-trips the subprocess: 4 tools listed, premature submit denied in-handler, review sets the flag file, submit writes `output.json`, metrics flushed. **Live-verified on the real Codex backend** (`AGENT_SDK=codex AGENT_MODEL=gpt-5.5`): review → submit via the subprocess, `output.json` read by `build_result`, cross-process metrics (2 calls) and normalized `token_usage` in the saved session. Note: ChatGPT-account Codex only accepts its own models — `AGENT_MODEL` must be set accordingly (default account model: gpt-5.5).

## Phase 3 — Codex-side enforcement

- [x] Primary: native config — `build_sandbox_config_overrides()` emits `sandbox_mode="workspace-write"` + `sandbox_workspace_write.writable_roots` from `notes.rw`
- [x] Spike completed live: PreToolUse/PostToolUse command hooks configured with `features.codex_hooks=true` **never fire** on codex-cli 0.128.0 (ChatGPT account) — a full turn ran tools with zero hook invocations. Codex hooks are unusable today.
- [x] Hooks-unusable branch taken: the default Codex path no longer generates permission/gate hook scripts; enforcement is native sandbox (filesystem) + in-tool gate (reflection). `codex_hooks.py` retained as a quarantined library layer for when upstream ships working hooks.
- [x] Wire `Settings.permission_mode` for Claude (`AGENT_PERMISSION_MODE`, default preserves `bypassPermissions`)

**Verified live:** a Codex agent attempting to write `$HOME/lup_escape_test.txt` was blocked by the sandbox (read-only filesystem error), no file created, and the session still completed review → submit normally.

## Phase 4 — Subagents on Codex

- [x] `run_subagent` LupMcpTool (`lup/subagents.py`): look up `SubagentSpec` → dispatch `query()` by `model_backend(spec.model)`; `SubagentSpec` gains optional `max_turns`
- [x] Served via serve-tools on Codex/OpenAI; Claude keeps native `agents=` (same specs, per-adapter interpretation)
- [x] Specs requiring tools on a backend whose one-shot queries can't provide them fail loudly
- [x] `format_subagent_prompt_section` deleted (capability replaces prose)
- [x] `query()` honesty: ValueError for Claude-only options (`max_turns`, `tools`, `permission_mode`, `max_budget_usd`, …) on other backends

**Verified live:** a gpt-5.5 Codex agent called `mcp__notes__run_subagent(analyzer, …)`; the subprocess dispatched a Claude haiku one-shot and returned its finding, which the codex agent reviewed and submitted — cross-SDK delegation end to end.

## Phase 5 — Backgrounds + sandbox lifecycle on Codex

- [x] Sandbox on Codex: serve-tools constructs `Sandbox` from env, tools lazy-start the container (`ensure_started`), atexit + SIGTERM handler for graceful exit, label-based orphan sweep (creation time and volume stored as container labels — no timestamp parsing), and a parent-side `sandbox_cleanup` context guaranteeing removal even when the subprocess is killed (observed: codex kills serve-tools without graceful exit)
- [x] Per-group serve-tools servers (`--server notes|sandbox`) so tool names match the Claude path exactly (`mcp__sandbox__execute_code`)
- [x] Factory raises for tools with `sdk="codex"` — background tools share in-process state, which cannot cross the subprocess boundary (documented in the factory)
- [x] Background model defaults documented: opus-class on Claude (tool-acting observers) vs small on Codex (prompt-in/text-out summarizers)
- [x] Supervisor `except Exception` blocks annotated as deliberate (`# claude: ignore` with rationale): a background crash logs and dies quietly, never propagates

**Verified live:** `AGENT_SDK=codex` session executed `mcp__sandbox__execute_code` in Docker (lazy container start) and `docker ps -a --filter label=lup.sandbox` is empty after exit — guaranteed cleanup confirmed.

## Phase 6 — Library API + boundary cleanup

- [x] `lup/__init__.py`: no eager SDK imports; `ResponseCollector`/`build_client`/`claude_query` retired from `__all__` (they had zero external users); verified `import lup` loads no SDK modules
- [x] Extras: `lup[claude]`, `lup[codex]`, `lup[docker]` (`mcp` promoted to a hard dep — it is the tool layer); template depends on `lup[claude,codex,docker]`; codex pin stays in `[tool.uv.sources]`
- [x] `LupEvent` hierarchy moved to `types.py` as Pydantic models with a `type` discriminator; Claude `run_streamed` `LupDoneEvent` now carries the collected blocks (matches Codex); dead `HooksConfig` alias and stale header deleted
- [x] `claude_query` moved to `claude_client.py`; `common.py` has no SDK imports and no file-wide ignore; `AgentAdapter.conversation` typed as `AbstractAsyncContextManager[Conversation]` (kills the `# type: ignore`)
- [x] Traces written to `notes.trace_log` (versioned `logs/` layout — session IDs no longer masquerade as versions in `trace list`); `AGENT_NOTES_PATH`/`AGENT_LOGS_PATH` now routed into `lup.paths.configure()` so all consumers honor them
- [x] `settings.max_turns`/`max_budget_usd` wired into `build_options`; Codex/OpenAI builders raise when they are set
- [x] Convention sweep: deliberate supervisor/cleanup `except Exception` annotated with inline `# claude: ignore` + rationale; `memory_flag`/`runner`/`wake_event`/`running` replace `_`-prefixed attributes; dead `BackgroundAgent` alias deleted; `requires-python` unified at 3.14 (the source uses PEP 758 syntax). Remaining file-wide ignores: `codex.py`, `openai_compat.py`, `feedback/analyze.py` (SDK/JSON boundary modules)

**Verified:** `import lup` loads no SDK modules (checked via sys.modules); live Claude session writes its trace to `notes/traces/0.1.0/logs/<session>/`; `dev check` 4/4.

## Phase 7 — Test program (grows with each phase, plus a coverage push)

- [x] Devtools smoke suite: `CliRunner` over every sub-app and the key read-only commands — the class of failure that shipped the `version` crash now cannot pass CI silently
- [x] Wiring tests: serve-tools MCP round-trip (Phase 2), gate flow + output retry (Phase 1), config-override generation (Phases 3/5)
- [x] `realtime.py` Scheduler: sleep/wake interruption, pending-wake consumption, debounce quiet-period/empty-window/replacement timing tests
- [x] `retry.py` (transient vs logic errors, exhaustion, extra exceptions), `history.py` round-trip through the versioned layout (caught and fixed a `configure(root, version)` crash), `metrics.py` file mode incl. corrupt-file degradation
- [x] Construction-only tests deleted (`test_models.py`, LupEvent construction class → one dispatch test)
- [x] Parity integration test (integration marker; the extra `LUP_PARITY_TEST=1` gate was later dropped so the nightly `-m integration` lane runs it) — **run live once: passed** (claude-haiku + gpt-5.5, 43s; same artifacts from both backends). Suite: 124 → 171 tests.

## Phase 8 — Docs truth pass (last, after interfaces settle)

- [x] README: cut-off sentences finished, `[[[]]]` placeholders replaced, the three empty workflow sections filled, command names corrected, `uv run lup run` + `AGENT_SDK` documented (edits preserve the original author's structure and voice)
- [x] CLAUDE.md: directory tree reflects `adapters/`, `types.py`, `output.py`, `subagents.py`; sub-app list corrected (`py`, no `api`); getting-started uses `uv run lup run` and the codex backend; Python 3.14 + multi-SDK framing
- [x] PATTERNS.md: `lup.client` → `lup.adapters.common.query` (with backend routing semantics); reflection pattern documents in-handler gating and submit_output finalization
- [x] Dotted `lup.lib` docstring references fixed; path-form `lup/lib/` references corrected (remaining matches live only in regenerated `.egg-info` metadata). Phantom `codex_query` replaced with the real `create_run_subagent_tool` mechanism; CLI docstring module paths corrected
- [x] Checkboxes kept current as phases landed

## Phase 9 — Deferred work follow-through

- [x] Budget enforcement on Codex: `CodexConversation` accumulates per-turn token usage; a caller-supplied `usage_cost` estimator (template builds one from `CODEX_USD_PER_MTOK_INPUT`/`_OUTPUT`/`_CACHED_INPUT`) turns it into USD, stamped into `total_cost_usd` on every turn; the turn after the budget is crossed raises `BudgetExceededError`. A budget without rates fails loudly. Enforcement is between turns — a Codex turn is atomic from the caller's side, so `query()` one-shots still reject `max_budget_usd`.
- [x] Persistent/realtime mode on Codex (`lup/realtime_relay.py`): the parent keeps the `Scheduler` and wake loop (`run_relay_session`); each cycle is one turn on the same thread. Served `session` tools (reply, sleep, context, meta, debounce, remind, schedule_action — same `mcp__session__*` names as the Claude wiring) relay through `session_dir/realtime/`: events JSONL applied mid-turn by a parent-side watcher, sleep request consumed at turn end, state snapshot for context reads, file-backed meta gate. Meta-before-sleep and unread-events guards are enforced in-handler (no hooks); bounded corrective turns replace the Stop hook. `build_codex_realtime_adapter` + `LUP_REALTIME_DIR` wire it per session.
- [x] Codex `dynamicTools` probe: still blocked upstream — the pinned SDK defines `DynamicToolSpec` wire types but no thread/turn param accepts them, and the client routes only responses and notifications (no server→client request channel for tool dispatch). Stays deferred.

**Verified:** budget accounting and refusal pinned by unit tests (fake thread, real SDK usage models); relay round-tripped twice — in-process (mailbox/tools/loop unit suite) and through the real serve-tools subprocess (`tests/integration/test_serve_tools.py::test_serve_tools_realtime_session_group`). **Live on gpt-5.5:** a two-cycle persistent session — agent read context, replied through the relay (delivered mid-turn by the parent), recorded meta, slept; woken by a simulated user message and completed the second cycle the same way.

---

## Deferred Work (explicit, with design notes)

- **CI workflow** — initially deferred at user request; landed with the capabilities pass (`.github/workflows/ci.yml`): a unit lane (ruff/pyright/pytest) on push/PR and a nightly/manual integration lane that runs `-m integration` (incl. the two-backend parity test) under a hard budget cap. `uv run lup-devtools dev check` remains the local gate.
- **Codex pin bump procedure.** The weekly `codex-pin-canary` CI job builds against the latest upstream `rust-v*` tag and runs the unit suite, so staleness is visible instead of silent. When green and a bump is wanted: update the tag in `[tool.uv.sources]`, `uv sync`, run the unit suite, and re-probe the two upstream blockers — config.toml command hooks (`codex_hooks.py` quarantine) and `dynamicTools` (serve-tools replacement) — before merging.
- **Codex `dynamicTools` migration.** When the Python SDK exposes in-process tool handlers over JSON-RPC, swap serve-tools for direct registration behind the same `collect_tools_by_server(context)` seam. The env contract remains the test harness. Probed at the current pin (Phase 9): `DynamicToolSpec` exists in the generated wire types only — no client-side registration parameter, no server→client request routing — so the migration remains blocked upstream.
- **Mid-turn budget interruption on Codex.** Phase 9 enforces budgets between turns. Bounding a single turn would take the notification stream (`ThreadTokenUsageUpdatedNotification`) plus `AsyncTurnHandle.interrupt()`, at the cost of reimplementing the SDK's private turn-result collector; revisit if one-shot budget caps become a real need.
- **Codex thread resume/fork.** Implementations shipped with the adapter but nothing ever called them, and the Claude path runs `no-session-persistence`, so a portable contract was impossible — removed with the capabilities pass. Recover from git history if persistent-session crash recovery becomes real; the relay keeps one thread open, so resume-by-id is the natural recovery point.

## Risks

| Risk | Mitigation |
|---|---|
| Codex hooks are behind an experimental flag and may change/break | Enforcement primary in tool handlers + native sandbox config (Decision 3); hooks optional |
| Stop-guard on Claude may not reliably force `submit_output` | Phase 1 spike before committing; bounded retries with surfaced error |
| Unpinned `openai-codex` git dep + `exclude-newer` floating deps | Pin rev (Phase 0); CI catches drift on every PR |
| Orphaned Docker containers from killed serve-tools | atexit + label-based stale sweep; SIGKILL test in Phase 5 |
| Two-backend test cost grows per feature | Wiring tests run without LLM calls (skip_reviewer, MCP round-trips); LLM parity test stays integration-gated |

## Type Mapping (reference, unchanged)

### Content blocks

| Claude SDK | Lup Internal | Codex SDK |
|---|---|---|
| `TextBlock` | `LupTextBlock` | `AgentMessageThreadItem` (phase=final_answer) |
| `ThinkingBlock` | `LupThinkingBlock` | `ReasoningThreadItem` / `AgentMessageThreadItem` (phase≠final_answer) |
| `ToolUseBlock` | `LupToolUseBlock` | `CommandExecutionThreadItem`, `McpToolCallThreadItem`, `FileChangeThreadItem` |
| `ToolResultBlock` | `LupToolResultBlock` | exit_code/output, result/error, diff |

### Messages

| Claude SDK | Lup Internal | Codex SDK |
|---|---|---|
| `AssistantMessage` | `LupAssistantMessage` | Items with assistant-role semantics |
| `UserMessage` | `LupUserMessage` | Turn input |
| `SystemMessage` | `LupSystemMessage` | `developer_instructions` |
| `ResultMessage` | `LupResultMessage` | `Turn` (usage, final_response) |

## Global Verification

1. `uv run lup-devtools dev check` — 4/4 (format, lint, pyright, pytest)
2. `uv run pytest` — unit suite green; `uv run pytest -m integration` — green with Docker + keys
3. `AGENT_SDK=claude uv run lup run "test task"` — full feature set, `output.json` + versioned trace
4. `AGENT_SDK=codex uv run lup run "test task"` — same artifacts, 13 tools listed, gate enforced
5. `core.py` imports `claude_agent_sdk` only under `TYPE_CHECKING` or inside the Claude-path builder (module loads without any SDK); `grep -rn "lup\.lib" src/ packages/` — empty
6. Fresh venv: `import lup` succeeds without SDK extras
7. `uv run lup-devtools version && uv run lup-devtools usage` — exit cleanly
8. `uv run pytest tests/integration/test_serve_tools.py -m integration` — one-shot and realtime session groups round-trip through the real subprocess
9. Budget: `AGENT_MAX_BUDGET_USD` enforced on every backend (Claude natively; codex/openai between turns via `CODEX_USD_PER_MTOK_*` rates, raising without them)
