# lup

Agent development library for the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) and the OpenAI Codex SDK (plus any OpenAI-compatible endpoint). Standalone, domain-neutral utilities for building, running, tracing, and improving SDK agents — configurable through function arguments, with no project-specific code. Importing `lup` pulls in no SDK; install the `claude` and/or `codex` extras for the backend you use.

## Modules

- `lup.adapters` — ALL SDK-specific code, one `Engine` per backend: `adapters.common` holds the run-side interface (`Client`/`Session`, the unsupported-behavior errors); `adapters.engine` holds the `Engine` ABC and the only doors in — `create_client()` and the one-shot `query()` with structured output; `adapters.matrix` probes the engines into the capability table; `adapters.claude` and `adapters.codex` are the engines (`claude`, `claude-compat`, `codex`, `openai-compat`).
- `lup.options` / `lup.types` — backend-agnostic `LupAgentOptions` and the shared vocabulary (blocks, messages, events, `Usage`, `SubagentSpec`, `LupResponse`).
- `lup.mcp` — `@lup_tool` decorator for MCP tools with typed Pydantic input/output, plus a patched `create_mcp_server` that preserves `is_error`.
- `lup.hooks` — composable hook primitives: directory-based permissions, tool allowlists, tool gates (deny until a condition unlocks), nudges, capture hooks.
- `lup.reflect` — reflection gate for reflect-before-output workflows.
- `lup.output` — `submit_output` finalization and the missing-output guard, shared by every backend.
- `lup.realtime` / `lup.realtime_relay` — `Scheduler` for persistent agents (sleep/wake, debounce, reminders) with its guard hooks, and the file-mailbox relay for subprocess backends.
- `lup.background` — background-agent base and `create_background_agent` factory for companions that run alongside a main session.
- `lup.subagents` — `run_subagent` delegation tool built from `SubagentSpec`s.
- `lup.sandbox` — Docker-based persistent REPL (`pip install lup[docker]`).
- `lup.history` / `lup.notes` / `lup.paths` — version-aware session storage, RO/RW notes layout, and lazy path configuration.
- `lup.trace` — color-coded console display and markdown trace logging.
- `lup.metrics` / `lup.retry` / `lup.throttle` — tool-call metrics, retry with backoff, rate limiting.
- `lup.antipatterns` / `lup.markers` — the anti-pattern rule set and review-marker scanning that development tooling consumes.
- `lup.profiles` — named Claude config-dir profiles (accounts), shared machine-wide.

## Usage

```python
from pydantic import BaseModel, Field

from lup.adapters.engine import query
from lup.mcp import lup_tool


class SearchInput(BaseModel):
    query: str = Field(description="Search query")


class SearchOutput(BaseModel):
    results: list[str]


@lup_tool("Search the knowledge base for matching documents.")
async def search(params: SearchInput) -> SearchOutput:
    return SearchOutput(results=lookup(params.query))


class Summary(BaseModel):
    title: str
    points: list[str]


response = await query("Summarize the findings", output_type=Summary)
summary = response.output(Summary)
```

Paths resolve lazily: importing `lup` never touches the filesystem. Point session storage somewhere explicit with `lup.paths.configure(root=..., notes_dir=..., version=...)`.
