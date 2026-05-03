# SDK Interoperability: Claude + Codex

## Goal

Make the lup inner-agent runnable on either the Claude Agent SDK or the OpenAI Codex SDK, selectable via the `AGENT_SDK` env var. Users set `AGENT_SDK=codex` to switch backends; the default remains `claude`.

## SDK Capability Gap

| Feature | Claude Agent SDK | Codex Python SDK |
|---|---|---|
| In-process hooks (allow/deny) | Python functions in `ClaudeAgentOptions` | No — observer-only `ThreadHooks`; permission hooks are CLI-level (TOML) |
| In-process MCP servers | `create_sdk_mcp_server()` | No — MCP servers are external processes via TOML |
| Subagents | `AgentDefinition` — first-class | PydanticAI handoff — different pattern |
| Structured output | `output_format` + `StructuredOutput` tool | `run_json()` / `run_pydantic()` |
| Sandbox | Docker-based (lup's own `Sandbox`) | Built-in (`sandbox_policy`) |
| Thinking tokens | Extended thinking (`max_thinking_tokens`) | No equivalent |

**Impact:** lup's value-add features — reflection gate, custom MCP tools, permission hooks, subagents — are Claude-only. On Codex, lup is: system prompt → `thread.run()` → structured output → trace logging.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Consumer Code                        │
│    core.py, trace.py — import from lup.lib.types          │
├──────────────────────────────────────────────────────────┤
│  core.py creates adapter, calls adapter.run()             │
├───────────────────────┬──────────────────────────────────┤
│  lib/adapters/claude  │  lib/adapters/codex              │
│   setup functions:    │   thin: SDK call +               │
│    build_options()    │   type conversion                │
│    build_servers()    │                                  │
│   adapter class:      │                                  │
│    ClaudeAdapter      │   CodexAdapter                   │
│   type conversion:    │                                  │
│    claude→lup maps    │   codex→lup maps                │
├───────────────────────┴──────────────────────────────────┤
│  lib/adapters/common — AgentAdapter ABC                  │
├──────────────────────────────────────────────────────────┤
│                     lib/types.py                          │
│       LupContentBlock, LupMessage, LupResponse            │
└──────────────────────────────────────────────────────────┘
```

**Key rule:** `core.py` never imports from `claude_agent_sdk` — all SDK-specific logic lives in `lib/adapters/*`.

## Implementation Status

### Created

- [x] `src/lup/lib/types.py` — Internal content block, message, and response types (`LupTextBlock`, `LupToolUseBlock`, `LupContentBlock`, `LupAssistantMessage`, `LupResponse`, etc.)
- [x] `src/lup/lib/adapters/__init__.py` — Package init
- [x] `src/lup/lib/adapters/common.py` — `AgentAdapter` ABC with `run()` method
- [x] `src/lup/lib/adapters/claude.py` — Claude adapter: `ClaudeAdapter`, `build_options()`, `build_agent_servers()`, type converters (`claude_block_to_lup`, `claude_message_to_lup`)
- [x] `src/lup/lib/adapters/codex.py` — Codex adapter: `CodexAdapter` (functional, needs `codex_app_server` package to run)

### Modified

- [x] `src/lup/agent/config.py` — Added `agent_sdk: Literal["claude", "codex"]` field (env var `AGENT_SDK`)
- [x] `src/lup/lib/trace.py` — Migrated from Claude SDK types to lup types (all `match` statements, all function signatures)
- [x] `src/lup/agent/core.py` — Zero `claude_agent_sdk` imports; dispatches via `match settings.agent_sdk` to `run_claude()` / `run_codex()`
- [x] `src/lup/lib/client.py` — `ResponseCollector.collect()` converts Claude messages to lup types before calling `print_message()`
- [x] `src/lup/devtools/agent.py` — Updated `build_agent_servers` import to `lup.lib.adapters.claude`

### Remaining

- [x] Full pyright pass — 0 errors excluding expected `codex_app_server` imports (4 errors, all from uninstalled optional dep)
- [x] `pyproject.toml` — Added `openai-codex-app-server-sdk` as optional dependency (`[project.optional-dependencies] codex`)
- [x] Unit tests for type conversion round-trips (`claude_block_to_lup`, `claude_message_to_lup`) — 14 tests in `tests/unit/test_type_conversion.py`
- [x] Codex adapter refinement: `codex_items_to_lup()` parses `RunResult.items` into typed blocks — handles `AgentMessageThreadItem`, `ReasoningThreadItem`, `CommandExecutionThreadItem`, `McpToolCallThreadItem`, `FileChangeThreadItem`
- [x] Codex adapter: `CodexAdapter` accepts `sandbox`, `effort`, `approval_policy`; wired to `Settings` via `CODEX_SANDBOX`, `CODEX_EFFORT`, `CODEX_APPROVAL_POLICY` env vars
- [ ] Integration test: `AGENT_SDK=codex` runs without crash (requires Codex SDK installed)

### Unchanged (Claude-only, conditionally imported)

These files keep their `claude_agent_sdk` imports — they're only loaded on the Claude path:

- `lib/hooks.py` — hook composition
- `lib/reflect.py` — reflection gate
- `lib/realtime.py` — persistent agent scheduler
- `lib/background.py` — background agents
- `lib/mcp.py` — MCP server factory
- `agent/subagents.py` — subagent definitions
- `agent/tools/reflect.py` — reflection tool (uses `client.query()` internally)
- `agent/tool_policy.py` — tool policy

## Type Mapping

### Content Blocks

| Claude SDK | Lup Internal | Codex SDK |
|---|---|---|
| `TextBlock` | `LupTextBlock` | `RunResult.final_response` |
| `ThinkingBlock` | `LupThinkingBlock` | N/A |
| `ToolUseBlock` | `LupToolUseBlock` | `ThreadItem` (tool call) |
| `ToolResultBlock` | `LupToolResultBlock` | `ThreadItem` (tool result) |

### Messages

| Claude SDK | Lup Internal | Codex SDK |
|---|---|---|
| `AssistantMessage` | `LupAssistantMessage` | `RunResult.items` (assistant) |
| `UserMessage` | `LupUserMessage` | `RunResult.items` (user) |
| `SystemMessage` | `LupSystemMessage` | N/A |
| `ResultMessage` | `LupResultMessage` | `RunResult` (usage, final_response) |

### Options

| Claude SDK | Config Field | Codex SDK |
|---|---|---|
| `ClaudeAgentOptions.model` | `settings.model` | `thread_start(model=...)` |
| `ClaudeAgentOptions.system_prompt` | `get_system_prompt()` | `thread_start(developer_instructions=...)` |
| `ClaudeAgentOptions.output_format` | `AgentOutput.model_json_schema()` | `thread.run(output_schema=...)` |
| `ClaudeAgentOptions.permission_mode` | N/A | `thread_start(approval_policy=...)` |
| `ClaudeAgentOptions.sandbox` | N/A | `thread.run(sandbox_policy=...)` |
| `ClaudeAgentOptions.hooks` | N/A (Claude-only) | N/A |
| `ClaudeAgentOptions.mcp_servers` | N/A (Claude-only) | N/A |
| `ClaudeAgentOptions.agents` | N/A (Claude-only) | N/A |

## Verification

1. `uv run pyright` — 0 errors (excluding `codex_app_server` import)
2. `uv run pytest` — all existing tests pass
3. `grep "claude_agent_sdk" src/lup/agent/core.py` — returns only the docstring
4. `AGENT_SDK=claude uv run python -m lup.environment.cli run "test"` — works as before
5. `AGENT_SDK=codex uv run python -m lup.environment.cli run "test"` — runs on Codex (when installed)
