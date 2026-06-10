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

- [ ] Fix `version` callback: take `ctx: typer.Context` instead of `click.get_current_context()` (restores `version`, `changelog`, `bump`, and the `/lup:bump`, `/lup:fb-status` workflows)
- [ ] Fix `usage`: one-shot render by default, watch mode behind `--watch`; never block without output on non-TTY
- [ ] `uv run ruff format .` (24 files) and commit
- [ ] Add CI workflow (GitHub Actions): `uv sync` + `lup-devtools dev check` (format, lint, pyright, pytest) on PRs to `dev`/`main`
- [ ] Pin `openai-codex` git dependency to a rev in `[tool.uv.sources]`
- [ ] Standardize the read-only overview verb to `status` across sub-apps (`sync list` → `sync status`)
- [ ] Dedupe `copy_to_clipboard` into `devtools/utils.py`; replace `setup.py` `parents[3]` with `lup.paths.project_root()`; guard rebase-state reads in `dev/conflicts.py`; guard `splitlines()[0]` in `version.py`

**Verify:** `uv run lup-devtools version`, `version changelog`, `usage` all exit cleanly; `dev check` reports 4/4; CI green on a test PR.

## Phase 1 — Output unification (keystone; Claude path first)

- [ ] `lup/output.py`: `create_output_tool(output_model, session_dir, gate)` → `submit_output` LupMcpTool. Handler: validate → if gate not reflected, `is_error` "call review first" → write `session_dir/output.json` → mark complete
- [ ] Completion state file (`output.json`) is the single source `build_result` reads; remove dependence on `ResultMessage.structured_output`
- [ ] Claude path: drop `output_format` from `ClaudeAgentOptions`; register `submit_output` on the `notes` server; add Stop hook (`create_completion_guard` in `lup/hooks.py`) that blocks stop until output exists, with a corrective message
- [ ] Spike first: verify Stop-hook forced-continuation behaves with `max_turns` and doesn't loop unbounded (cap retries, then surface error)
- [ ] Keep the PreToolUse gate hook on Claude as hardening (matcher `mcp__notes__submit_output`)
- [ ] Tests: gate-in-handler denial → reflect → submit succeeds; invalid output → `is_error` retry; stop-guard path

**Verify:** `AGENT_SDK=claude uv run lup run "test task"` produces `output.json` + `AgentSessionResult`; trace shows a denial when submitting before reflecting.

## Phase 2 — Context relay + dynamic serve-tools

- [ ] Env contract constants in `lup/paths.py`; `build_mcp_config_overrides(env=...)` emits `mcp_servers.notes.env.*`
- [ ] `serve-tools` builds tools from env context: example + reflect (file-backed gate from `LUP_GATE_FLAG`) + `submit_output` + sandbox tools; `collect_tools_by_server(context)` replaces the static dict; add `--list` flag for debugging
- [ ] `lup/metrics.py` gains file-backed flush (`session_dir/metrics.json`), mirroring `ReflectionGate`'s dual mode; `build_result` merges subprocess metrics
- [ ] `core.py: build_codex_adapter` passes env; gate matcher becomes `mcp__notes__submit_output`; Codex stops passing native `output_schema`
- [ ] Rename the Codex MCP server key from `lup-tools` to `notes`

**Verify:** integration test (no LLM needed): spawn `serve-tools` with env set, connect an MCP client, list tools (13 expected), call `review` with `skip_reviewer=true` → gate flag file appears → call `submit_output` → `output.json` written.

## Phase 3 — Codex-side enforcement

- [ ] Primary: native config — `sandbox_mode` + `writable_roots` derived from `notes.rw` dirs replaces the generated Write/Edit permission script
- [ ] Spike: probe script logging real Codex hook event payloads (tool names, fields) on a live turn; record findings in this file
- [ ] If hooks usable: regenerate scripts against *actual* Codex tool names; generate them from the same policy source as `lup/hooks.py` (no logic drift — the current scripts diverge on `extract_glob_dir` and path resolution)
- [ ] If hooks unusable: delete the generated-script layer for permissions (in-tool gate + native sandbox already enforce), keep `codex_hooks.py` only for what's verified
- [ ] Wire `Settings.permission_mode` for Claude (currently hardcoded `bypassPermissions`), completing the security-profile normalization

**Verify:** Codex agent cannot write outside `writable_roots`; gate denial observed on Codex in the trace; no hook config referencing unverified tool names remains.

## Phase 4 — Subagents on Codex

- [ ] `run_subagent` LupMcpTool: input (subagent name, task) → look up `SubagentSpec` → dispatch `query()` by `model_backend(spec.model)` → return text or structured result
- [ ] Served via serve-tools on Codex/OpenAI; Claude keeps native `agents=` (same specs, per-adapter interpretation — documented)
- [ ] Specs requiring tools that the chosen backend can't provide fail loudly with a clear message
- [ ] Delete `format_subagent_prompt_section` (capability replaces prose)
- [ ] `query()` honesty: raise `ValueError` for accepted-but-unsupported options per backend (capability table in `adapters/common.py`)

**Verify:** Codex session trace shows `mcp__notes__run_subagent` invocation returning researcher output; `query(model="gpt-…", max_budget_usd=…)` raises.

## Phase 5 — Backgrounds + sandbox lifecycle on Codex

- [ ] Sandbox on Codex: serve-tools constructs `Sandbox` lazily from env (`LUP_SESSION_ID`, shared dir), registers `atexit` cleanup; stale-container sweep on next start (existing label mechanism)
- [ ] `CodexBackgroundAgent` gains MCP tools via per-agent `config_overrides` (its own serve-tools instance); factory stops silently dropping `tools`/`builtin_tools`/`allowed_tools` — pass through or raise
- [ ] Align background model defaults intentionally (document why claude default is opus-class and codex default is mini-class, or make them symmetric)
- [ ] Replace bare `except Exception` supervisors in both background run-loops with specific exceptions + a documented top-level supervisor pattern

**Verify:** `AGENT_SDK=codex` session executes `execute_code` in Docker; `docker ps` clean after exit (including SIGKILL test); background agent on Codex calls one of its tools.

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
