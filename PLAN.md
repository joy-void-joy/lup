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
7. **Persistent/realtime mode stays Claude-only in this refactor.** The sleep/wake tools require tool→parent IPC on Codex (different problem class). Deferred with a design sketch — see Deferred Work.
8. **Phase 0 (devtools regressions, CI) ships independently off `dev`** — it is unrelated to interop and unblocks everything else.

## Current State

### Actually working

- [x] `lup/types.py` type layer (blocks, messages, response, hooks, `SubagentSpec`)
- [x] `AgentAdapter` / `Conversation` ABCs; Claude adapter + converters (tested)
- [x] Codex adapter basics: prompt → run → collect, `resume()`, `fork()`, config-override assembly
- [x] OpenAI-compatible adapter (Codex runtime + `model_provider`)
- [x] `core.py` dispatch with zero `claude_agent_sdk` imports
- [x] File-backed `ReflectionGate`; Codex hook **script generation** (generation only)
- [x] Config fields for SDK selection, Codex sandbox/effort/approval

### Wired but dead (what this plan fixes)

- [ ] `serve-tools` serves only `EXAMPLE_TOOLS` — reflect/realtime/sandbox tools never reach Codex (`devtools/agent.py: collect_tools_by_server`)
- [ ] Gate guards `"StructuredOutput"`, which doesn't exist as a tool on Codex; nothing can set the flag file (`core.py: build_codex_adapter`)
- [ ] Generated permission scripts match Claude tool names (`Write`/`Edit`/`Read`/`Glob`/`Grep`) — unverified against real Codex hook events (`adapters/codex_hooks.py`)
- [ ] Subagents on Codex are a system-prompt section with no invocation mechanism (`core.py: format_subagent_prompt_section`)
- [ ] Sandbox constructed only on the Claude path (`core.py: build_adapter`)
- [ ] `settings.max_turns` / `settings.max_budget_usd` never wired into `build_options`; `query()` silently drops options on non-Claude backends; background factory silently drops `tools` on Codex
- [ ] `lup/__init__.py` eagerly imports `adapters.claude_client`; exports retired `ResponseCollector` alongside its replacement
- [ ] `core.py` writes traces to `notes/traces/<session_id>/` bypassing the versioned `lup.paths` layout
- [ ] Devtools: `version` sub-app crashes (`click.get_current_context()`), `usage` hangs in non-TTY, `ruff format` failing on 24 files, no CI
- [ ] Docs: README unfinished, CLAUDE.md structure stale, 11 `lup.lib` docstring refs, PATTERNS.md references `lup.client`

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

- [ ] `lup/__init__.py`: stop eager `claude_client` import; retire `ResponseCollector`, `build_client`, `claude_query` from `__all__` (import from `lup.adapters.claude_client` where genuinely needed); `import lup` must work without `claude_agent_sdk` installed
- [ ] Extras: `lup[claude]`, `lup[codex]`, `lup[docker]`; template depends on `lup[claude,codex,docker]`; update `require_codex_sdk` message accordingly
- [ ] Move `LupEvent` hierarchy into `types.py` as Pydantic models; Claude `run_streamed` `LupDoneEvent` carries blocks (match Codex contract); delete dead `HooksConfig` alias and stale section header in `adapters/claude.py`
- [ ] Move `claude_query` conversion code out of `adapters/common.py` into `claude_client.py` — `common.py` stays SDK-import-free
- [ ] `core.py` traces through `lup.paths.logs_dir()` (versioned layout; fixes session-IDs-as-versions in `trace list`)
- [ ] Wire `settings.max_turns` / `max_budget_usd` into `build_options`; raise on Codex if set (until supported)
- [ ] Convention sweep: bare `except Exception` (cli loop, setup.py, mcp.py, sandbox.py), `_`-prefixed attributes (`_reflected`, `_task`, `_wake`, `_running`), "backward compatibility" comment in `background.py`; audit the 4 file-wide `# claude: ignore` headers down to justified inline ignores
- [ ] Align `requires-python`/pyright `pythonVersion` deliberately (library 3.13, template 3.14 — or unify; document the choice)

**Verify:** fresh venv with `lup` only (no extras) imports; `grep -r "claude_agent_sdk" packages/lup/src/lup --include="*.py" | grep -v adapters/` empty; `trace list` groups new sessions under the agent version.

## Phase 7 — Test program (grows with each phase, plus a coverage push)

- [ ] Devtools smoke suite: Typer `CliRunner` invokes every sub-app and key read-only commands (`--help`, `version`, `trace list`, `feedback status`, `setup status`) — would have caught the `version` crash
- [ ] Wiring tests over unit tests: the Phase 2 serve-tools MCP round-trip; gate flow; output retry loop
- [ ] `realtime.py` Scheduler: sleep/wake/debounce timing tests (flagged as test-worthy by CLAUDE.md, currently zero)
- [ ] `retry.py`, `history.py` round-trip, `metrics.py` (incl. file mode), `paths.py` version resolution
- [ ] Delete construction-only tests (`test_models.py` schema-property checks, happy-path roundtrips in `test_type_conversion.py` that exercise no failure mode)
- [ ] Gated parity integration test: same task via `AGENT_SDK=claude` and `AGENT_SDK=codex`, assert equivalent `AgentSessionResult` shape and artifacts

## Phase 8 — Docs truth pass (last, after interfaces settle)

- [ ] README: finish the cut-off sentences, remove `[[[]]]` placeholders, fill the three empty workflow sections, correct command names (`lup-devtools dev worktree create`, `uv run lup run`), document the `lup` entry point
- [ ] CLAUDE.md: directory tree (add `adapters/`, `types.py`, `output.py`; remove `client.py`), sub-app list (`py` not `api`), getting-started commands
- [ ] PATTERNS.md: replace `lup.client` references; document the submit-output finalization pattern and per-adapter subagent interpretation
- [ ] Fix all 11 `lup.lib` docstring references and the phantom `codex_query` (`subagents.py`); fix `lup.environment.cli` module paths in CLI docstrings
- [ ] Keep this file's checkboxes current as phases land

---

## Deferred Work (explicit, with design notes)

- **Persistent/realtime mode on Codex.** Sketch: parent process keeps `Scheduler` and the wake loop; each cycle is `thread/resume` with a built message; sleep/reply tools are served tools that write a mailbox file (`session_dir/realtime/`) the parent polls/watches between turns. Requires no Codex hooks. Build only after Phases 2–5 prove the relay pattern.
- **Codex `dynamicTools` migration.** When the Python SDK exposes in-process tool handlers over JSON-RPC, swap serve-tools for direct registration behind the same `collect_tools_by_server(context)` seam. The env contract remains the test harness.
- **Budget enforcement on Codex.** Needs per-turn usage accumulation in `CodexConversation`; until then, setting a budget on Codex raises.

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
5. `grep -rn "claude_agent_sdk" src/lup_template/agent/core.py` — empty; `grep -rn "lup\.lib" src/ packages/` — empty
6. Fresh venv: `import lup` succeeds without SDK extras
7. `uv run lup-devtools version && uv run lup-devtools usage` — exit cleanly
