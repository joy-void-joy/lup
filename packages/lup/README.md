# lup

Agent development library for the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) and the OpenAI Codex SDK (plus any OpenAI-compatible endpoint). Standalone, domain-neutral utilities for building, running, tracing, and improving SDK agents — configurable through function arguments, with no project-specific code. Importing `lup` pulls in no SDK; install the `claude` and/or `codex` extras for the backend you use.

## Modules

- `lup.adapters` — ALL SDK-specific code, behind one neutral seam. `adapters.Engine` is the contract — one backend, complete: `client()`, `background()`, `profiles()`, `builtin_tools()` — and `adapters.engines` holds the shipped engines as lazy front doors (the compat engines subclass their base). `adapters.options` carries the backend-agnostic `LupAgentOptions`, `adapters.errors` the unsupported-behavior errors, and `adapters.wiring` is the SDK-free door: the `ENGINES` (id → engine) and `MODEL_ROUTES` (model-name regex → engine) routers plus the only doors in — `create_client()` and the one-shot `query()` with structured output. `adapters.clients` holds the purely abstract `Client`/`Session`, the shared machinery (consume-tracking refusal, usage normalization, one-shot/stream fallbacks), and each engine's implementation package (`clients/claude/`, `clients/codex/`, one concern per module) with the compat engines as translations beside them; `adapters.background` holds the background contract and wake/debounce machinery plus each engine's background agent. Backend-committed code can import an engine's door directly (`from lup.adapters.clients.claude.client import create_claude`) instead of routing through `create_client`. The capability table is probed from the engines by devtools, never declared here.
- `lup.types` — the shared vocabulary (blocks, messages, events, `Usage`, `SubagentSpec`, `LupResponse`).
- `lup.mcp` — `@lup_tool` decorator for MCP tools with typed Pydantic input/output, plus a patched `create_mcp_server` that preserves `is_error`.
- `lup.hooks` — composable hook primitives: directory-based permissions, tool allowlists, tool gates (deny until a condition unlocks), nudges, capture hooks.
- `lup.reflect` — reflection gate for reflect-before-output workflows.
- `lup.workspace.output` — `submit_output` finalization and the missing-output guard, shared by every backend.
- `lup.realtime` — persistent-agent machinery, one concern per module: `scheduler` (the `Scheduler` core — sleep/wake, debounce, reminders — with its guard hooks), `models` (shared tool I/O), and `relay` (the file-mailbox relay for subprocess backends, layered on the core).
- `lup.subagents` — `run_subagent` delegation tool built from `SubagentSpec`s.
- `lup.sandbox` — Docker-based persistent REPL (`pip install lup[docker]`).
- `lup.workspace` — the session workspace: `history` (version-aware session storage), `notes` (RO/RW notes layout), `paths` (lazy path configuration), `output` (submit_output finalization), and `context` (`SessionContext` relayed across the subprocess boundary).
- `lup.telemetry.trace` / `lup.telemetry.display` — markdown trace logging and color-coded console display, over the shared block helpers in `telemetry.blocks`.
- `lup.telemetry.metrics` / `lup.resilience.retry` / `lup.resilience.throttle` — tool-call metrics, retry with backoff, rate limiting.
- `lup.codescan` — review-marker scanning (`markers`) and the anti-pattern rule set (`antipatterns`) that development tooling consumes, over a shared scan core (`common`).
- `lup.adapters.profiles` — the profile seam: `ProfileSupport.select(name, client)` returns a client running as the named account; each implementation beside the ABC (`claude`) owns its own storage and resolution.

## Usage

```python
from pydantic import BaseModel, Field

from lup.adapters.wiring import query
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

Paths resolve lazily: importing `lup` never touches the filesystem. Point session storage somewhere explicit with `lup.workspace.paths.configure(root=..., notes_dir=..., version=...)`.
