# SDK Interoperability: Claude + Codex

## Goal

Make the lup inner-agent runnable on either the Claude Agent SDK or the OpenAI Codex SDK, selectable via the `AGENT_SDK` env var. Both paths get the full lup feature set — hooks, MCP tools, reflection, subagents, persistent mode. The implementation differs; the behavior doesn't.

## How Every Feature Maps

The previous plan mapped lup features to SDK primitives and declared anything without a 1:1 match "Claude-only." But every lup feature has a Codex implementation — just through different plumbing.

| Feature | Claude SDK | Codex SDK |
|---|---|---|
| **MCP tools** | In-process via `create_sdk_mcp_server()` | External stdio via `serve-tools` + `config_overrides` (Codex app-server is a Rust subprocess — no in-process tool registration exists) |
| **Permission hooks** | Python functions in `ClaudeAgentOptions.hooks` | config.toml command hooks — Codex supports PreToolUse/PostToolUse/PermissionRequest/Stop with allow/deny |
| **Reflection gate** | PreToolUse hook blocks output tool until reflect is called | config.toml PreToolUse command hook — same gate logic, different transport |
| **Subagents** | `AgentDefinition` — first-class | Thread fork (`thread/fork`) or direct API calls via `query()` |
| **Background agents** | Independent `ClaudeSDKClient` instances | Independent Codex threads (inherently persistent and concurrent) |
| **Persistent agent** | Stop hook prevents exit + Scheduler | Thread resume (`thread/resume`) + Scheduler |
| **Structured output** | `output_format` + `StructuredOutput` tool | `run_pydantic()` / `run_json()` with native schema validation |
| **Sandbox** | lup's Docker `Sandbox` class | Same — lup's Docker `Sandbox` via MCP tools (`execute_code`, `install_package`) |
| **Thinking / effort** | `output_config.effort` (low–max) | `ReasoningEffort` (none–xhigh) |
| **Session persistence** | Session JSONL on disk, `--continue`/`--resume`, `fork_session` | Thread store, `thread/resume`, `thread/fork` |
| **Web search** | `web_search` server tool with domain filtering | Native web search (disabled/cached/live) |
| **Streaming** | `Message` union type, `StreamEvent` wrapper | `ThreadEvent` with type discriminators |
| **Security profiles** | 6 permission modes + allowed/disallowed tools + hooks | `SandboxMode` + `approval_policy` (4 levels) + `writable_roots` |
| **PydanticAI** | `AnthropicModel` provider | `CodexModel` provider (third-party `codex-sdk-python`) |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       Consumer Code                           │
│  core.py, trace.py — import from lup.lib.types only           │
├──────────────────────────────────────────────────────────────┤
│  core.py dispatches: match settings.agent_sdk                 │
├─────────────────────────┬────────────────────────────────────┤
│   lib/adapters/claude   │   lib/adapters/codex               │
│                         │                                    │
│   ClaudeAdapter         │   CodexAdapter                     │
│    build_options()      │    build_config()                  │
│    build_servers()      │    build_mcp_config()              │
│    type converters      │    type converters                 │
│                         │    thread management               │
│                         │                                    │
│   In-process hooks      │   config.toml command hooks        │
│   In-process MCP        │   External MCP (serve-tools)       │
│   AgentDefinition       │   Thread fork / query()            │
│   ClaudeSDKClient       │   AsyncCodex threads               │
├─────────────────────────┴────────────────────────────────────┤
│   lib/adapters/common — AgentAdapter ABC                      │
├──────────────────────────────────────────────────────────────┤
│   lib/types.py — LupContentBlock, LupMessage, LupResponse    │
├──────────────────────────────────────────────────────────────┤
│   Shared (SDK-agnostic)                                       │
│   lib/trace.py    — trace logging (lup types only)            │
│   lib/metrics.py  — tool call tracking                        │
│   lib/history.py  — session storage                           │
│   lib/notes.py    — directory structure                       │
│   lib/realtime.py — scheduler (timing logic is SDK-agnostic)  │
└──────────────────────────────────────────────────────────────┘
```

**Key rule:** Consumer code never imports from `claude_agent_sdk` or `codex_app_server`. All SDK-specific logic lives in `lib/adapters/*`.

## Feature Implementation Details

### 1. MCP Tools on Codex

Codex's app-server is a Rust subprocess communicating via JSON-RPC. There is no in-process tool registration — tools are either built-in or external MCP servers configured via TOML. An experimental `dynamicTools` JSON-RPC protocol exists but the Python SDK doesn't expose it yet.

`lup-devtools agent serve-tools` already launches all `@lup_tool` tools as a stdio MCP server. The Codex adapter passes this via `config_overrides` on `AppServerConfig`:

```python
config = AppServerConfig(
    config_overrides=(
        'mcp_servers.lup-tools.command="uv"',
        'mcp_servers.lup-tools.args=["run", "lup-devtools", "agent", "serve-tools"]',
    ),
)
async with AsyncCodex(config) as codex:
    thread = await codex.thread_start(...)
```

All existing `@lup_tool` decorated tools (reflect, sandbox, realtime, domain) work unchanged — the tool code doesn't know which SDK drives the outer agent.

**Future optimization:** When the Python SDK exposes `dynamicTools`, tool call/result can go through JSON-RPC directly (in-process handlers) instead of spawning a subprocess. This eliminates the MCP server but requires subclassing `AppServerClient` to handle `item/tool/call` requests.

### 2. Permission Hooks on Codex

Codex has a config.toml hook system with PreToolUse, PostToolUse, PermissionRequest, and Stop events — structurally identical to Claude Code's hook scripts, with allow/deny decisions.

Lup's existing hook scripts (`.claude/plugins/lup/hooks/scripts/`) are Python command scripts. The Codex adapter writes equivalent config via `config_overrides`:

```python
config_overrides=(
    'features.codex_hooks=true',
    'hooks.PreToolUse[0].matcher="^Bash$"',
    'hooks.PreToolUse[0].hooks[0].type="command"',
    'hooks.PreToolUse[0].hooks[0].command="python3 hooks/auto_allow_bash.py"',
)
```

The hook scripts need a thin adapter (`lib/adapters/codex_hooks.py`) to translate between output formats — Claude hooks emit `SyncHookJSONOutput`; Codex hooks emit JSON with `allow`/`deny`/`systemMessage` fields. The policy logic itself stays shared.

### 3. Reflection Gate on Codex

The reflection gate is a PreToolUse hook that blocks the output tool (e.g., `StructuredOutput`, `sleep`) until the agent has called the reflect tool. Same mechanism on both SDKs, different transport:

- **Claude:** Python hook function in `ClaudeAgentOptions.hooks` checks `ReflectionGate.reflected` flag
- **Codex:** config.toml PreToolUse command hook runs a Python script that checks a flag file

The gate script tracks state via a temp file (set by the reflect tool's MCP handler, checked by the gate hook). The `ReflectionGate` class gains a `file_path` mode alongside its current in-memory flag for this.

### 4. Subagents on Codex

Three strategies, chosen per-subagent based on needs:

| Strategy | When to Use | How |
|---|---|---|
| **Thread fork** | Subagent needs same tools/context as main agent | `thread/fork` from current turn, run focused prompt, read result |
| **Direct API** | Subagent is a one-shot LLM call (researcher, analyzer) | `query()` — SDK-agnostic, dispatches by model name |
| **PydanticAI** | Subagent needs tool use + structured output + validation | `AnthropicModel` or `CodexModel` as PydanticAI provider |

`agent/subagents.py` evolves from `AgentDefinition` (Claude-specific) to a lup-native `SubagentSpec`:

```python
class SubagentSpec(BaseModel):
    name: str
    description: str
    prompt: str
    tools: list[str]
    model: str  # "haiku", "gpt-4.1-mini", etc.
```

Each adapter interprets `SubagentSpec`:
- Claude adapter → `AgentDefinition`
- Codex adapter → thread fork or `query()` dispatch based on whether tools are needed

`lib/client.py`'s `query()` needs a backend-agnostic mode — dispatch to Anthropic or OpenAI API based on model name prefix (`claude-*` → Anthropic, `gpt-*`/`o*` → OpenAI).

### 5. Background Agents on Codex

On Claude, `BackgroundAgent` spawns independent `ClaudeSDKClient` instances. On Codex, background work uses independent threads — threads are inherently persistent and concurrent:

```python
bg_thread = await codex.thread_start(
    model=model,
    developer_instructions=bg_system_prompt,
)
bg_result = await bg_thread.run(message)
```

`BackgroundAgent` gains an adapter-aware factory:

```python
def create_background_agent(sdk: str, ...) -> BackgroundAgent:
    match sdk:
        case "claude": return ClaudeBackgroundAgent(...)
        case "codex": return CodexBackgroundAgent(...)
```

Shared mutable state for inter-agent communication stays Python-level.

### 6. Persistent Agent on Codex

The persistent agent pattern (sleep/wake loop) maps to Codex's thread model:

| Lup Concept | Claude Implementation | Codex Implementation |
|---|---|---|
| Sleep | `Scheduler.sleep()` blocks, Stop hook prevents exit | Thread turn completes; state persisted by Codex |
| Wake | `Scheduler.wake()` resumes blocked sleep | `thread/resume` with new message |
| Debounce | `Scheduler.start_debounce()` batches events | Same — `Scheduler` logic is SDK-agnostic |
| Stop guard | PreToolUse hook blocks Stop | Not needed — thread turn model has no Stop |

The `Scheduler` class (`lib/realtime.py`) is mostly SDK-agnostic — asyncio timers and state tracking. The SDK-specific parts are hook factories (`create_stop_guard`, etc.) which need Codex equivalents via config.toml hooks.

### 7. Sandbox — Shared

Lup's Docker `Sandbox` class and its MCP tools (`execute_code`, `install_package`) work on both SDK paths unchanged. On Codex, these tools are exposed via `serve-tools` like all other `@lup_tool` tools — the sandbox code doesn't know which SDK drives the outer agent.

Codex has built-in `SandboxMode` but we don't use it. Using lup's own sandbox ensures identical isolation behavior on both paths. The tradeoff is Docker as a dependency on the Codex path.

## Shared Capabilities — Adapter Normalization

Both SDKs support these features with different APIs. The adapter layer normalizes both into lup's internal types.

### Session Persistence & Forking

| | Claude | Codex |
|---|---|---|
| Persistence | JSONL files at `~/.claude/projects/` | Thread store (app-server managed) |
| Resume | `--continue`, `--resume`, `ClaudeAgentOptions.resume` | `thread/resume` by thread ID |
| Fork | `fork_session=True`, `/branch` command | `thread/fork` from any turn |
| Search | `list_sessions()`, `get_session_info()` | `thread/list` with search term |

`LupResponse` gains optional `session_id: str`. Each adapter populates it from its native session/thread ID. `AgentAdapter` gains optional `resume(session_id)` and `fork(session_id)` methods.

### Web Search

Claude has `web_search` server tool with domain filtering and dynamic filtering. Codex has native web search with modes (disabled/cached/live).

Both produce search results that the adapter normalizes into `LupToolUseBlock(name="web_search")` / `LupToolResultBlock` with citations.

### Streaming

Claude has a `Message` union type (`UserMessage | AssistantMessage | StreamEvent | ...`) with `isinstance()` dispatch. Codex has `ThreadEvent` with `.type` string discriminators.

`AgentAdapter` gains optional `run_streamed()` returning `AsyncGenerator[LupEvent]`. Both adapters convert their native event types into a shared `LupEvent` union.

### Effort / Thinking

Both SDKs support named effort levels:

| Level | Claude | Codex |
|---|---|---|
| None/minimal | — | `none`, `minimal` |
| Low | `low` | `low` |
| Medium | `medium` | `medium` |
| High | `high` (default) | `high` |
| Extra | `xhigh`, `max` | `xhigh` |

`Settings` gains `reasoning_effort: str | None`. Each adapter maps to its native enum. Claude uses `output_config.effort`; Codex uses `ReasoningEffort`.

### Security Profiles

Claude has 6 permission modes (`default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`) plus `allowed_tools`/`disallowed_tools` and hooks. Codex has `SandboxMode` × `approval_policy` (4 levels) + `writable_roots`.

`Settings` gains `permission_mode` (maps to Claude's modes) and `sandbox_mode` + `approval_policy` (maps to Codex's config). Each adapter translates to its native primitives.

## Implementation Status

### Phase 1: Type Layer & Basic Dispatch (DONE)

- [x] `src/lup/lib/types.py` — Internal types
- [x] `src/lup/lib/adapters/common.py` — `AgentAdapter` ABC
- [x] `src/lup/lib/adapters/claude.py` — Claude adapter with type converters
- [x] `src/lup/lib/adapters/codex.py` — Codex adapter (basic: prompt → run → collect)
- [x] `src/lup/agent/core.py` — SDK dispatch, zero `claude_agent_sdk` imports
- [x] `src/lup/lib/trace.py` — Migrated to lup types
- [x] `src/lup/lib/client.py` — Claude→lup conversion at print boundary
- [x] `src/lup/agent/config.py` — `agent_sdk` + Codex settings fields
- [x] `tests/unit/test_type_conversion.py` — 14 tests for Claude→lup conversion
- [x] `pyproject.toml` — Codex as optional dependency

### Phase 2: MCP Tools on Codex (DONE)

- [x] `CodexAdapter` passes `serve-tools` as MCP server via `AppServerConfig.config_overrides`
- [x] `build_mcp_config_overrides()` generates TOML config for external MCP server
- [x] `CodexAdapter.build_config_overrides()` assembles all overrides (MCP + hooks)
- [x] Test: config override generation verified

### Phase 3: Permission Hooks on Codex (DONE)

- [x] `lib/adapters/codex_hooks.py` — Adapter translating lup hook output ↔ Codex hook JSON format
- [x] `write_permission_hook_script()` generates standalone permission hook scripts
- [x] `CodexAdapter` accepts `hook_overrides` and passes them via `config_overrides`
- [x] `build_hook_config_overrides()` generates TOML for Codex command hooks
- [x] Test: permission hook script generation and config verified

### Phase 4: Reflection Gate on Codex (DONE)

- [x] `ReflectionGate` gains file-backed mode (`flag_path` parameter)
- [x] `write_reflection_gate_script()` generates PreToolUse gate hook script
- [x] `build_reflection_gate_hook()` wires gate into Codex config
- [x] `core.py` Codex path uses file-backed gate + generated hook scripts
- [x] Test: file-backed gate creation/check/reset verified

### Phase 5: Subagents (DONE)

- [x] `SubagentSpec` model in `lib/types.py` — SDK-agnostic subagent definition
- [x] `agent/subagents.py` migrated from `AgentDefinition` to `SubagentSpec`
- [x] `spec_to_claude()`: `SubagentSpec` → `AgentDefinition`
- [x] `model_backend()`: backend-agnostic dispatch (model name prefix → Anthropic or OpenAI)
- [x] `get_subagent_specs()` returns SDK-agnostic specs
- [x] Test: spec creation, conversion, and backend dispatch verified

### Phase 6: Background Agents & Persistent Mode (DONE)

- [x] `CodexBackgroundAgent` — independent thread per background agent
- [x] `create_background_agent()` factory for SDK-aware creation
- [x] `CodexAdapter.resume()` — thread resume for persistent sleep/wake
- [x] `CodexAdapter.fork()` — thread fork support
- [x] `create_codex_stop_guard_hook()` — no-op (Codex uses thread/resume pattern)

### Phase 7: Streaming & Session Management (DONE)

- [x] `AgentAdapter.run_streamed()` → `AsyncGenerator[LupEvent]`
- [x] `LupEvent` hierarchy: `LupTextEvent`, `LupThinkingEvent`, `LupToolUseEvent`, `LupToolResultEvent`, `LupDoneEvent`
- [x] Claude adapter: `run_streamed()` yields events from `receive_response()`
- [x] `LupResponse.session_id` — populated from native session/thread ID
- [x] `AgentAdapter.resume()` and `fork()` base methods
- [x] `Settings.reasoning_effort` mapped to native effort on each adapter
- [x] `normalize_effort()` utility for cross-SDK effort mapping
- [x] Test: streaming events, session_id, effort normalization verified

### Unchanged (SDK-Agnostic Already)

- `lib/trace.py`, `lib/metrics.py`, `lib/history.py`, `lib/notes.py`
- `lib/cache.py`, `lib/retry.py`, `lib/throttle.py`, `lib/paths.py`
- `agent/models.py`, `agent/prompts.py`, `agent/config.py`
- `agent/tools/example.py` — `@lup_tool` decorated (SDK-agnostic via MCP)
- `devtools/*` — CLI tooling

## Type Mapping

### Content Blocks

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

### Options

| Claude SDK | Config Field | Codex SDK |
|---|---|---|
| `model` | `settings.model` | `thread_start(model=...)` |
| `system_prompt` | `get_system_prompt()` | `thread_start(developer_instructions=...)` |
| `output_format` | `AgentOutput.model_json_schema()` | `run_json(output_schema=...)` / `run_pydantic(output_model=...)` |
| `hooks` | permission + reflection hooks | config.toml `[[hooks.PreToolUse]]` command hooks |
| `mcp_servers` | MCP server dict | `config_overrides` → `mcp_servers.lup-tools` |
| `agents` | subagent dict | thread fork / `query()` |
| `output_config.effort` | `settings.reasoning_effort` | `thread.run(effort=ReasoningEffort.HIGH)` |
| `permission_mode` | `settings.permission_mode` | `thread_start(approval_policy=...)` |
| `resume` / `fork_session` | `settings.session_id` | `thread/resume` / `thread/fork` |

## Verification

1. `uv run pyright` — 0 errors (excluding optional `codex_app_server` imports) ✓
2. `uv run pytest` — all 54 tests pass ✓
3. `grep "claude_agent_sdk" src/lup/agent/core.py` — zero results ✓
4. `AGENT_SDK=claude uv run python -m lup.environment.cli run "test"` — full feature set
5. `AGENT_SDK=codex uv run python -m lup.environment.cli run "test"` — full feature set (requires `codex_app_server`)
6. Both paths produce equivalent `AgentSessionResult` for the same task
7. MCP tools callable from Codex agent via `config_overrides` + `serve-tools`
8. Permission hooks enforce same policies on both paths
9. Reflection gate blocks premature output on both paths
