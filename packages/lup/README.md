# lup

Agent development library for the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview). Standalone, domain-neutral utilities for building, running, tracing, and improving SDK agents — configurable through function arguments, with no project-specific code.

## Modules

- `lup.client` — SDK client construction (`build_client`), one-shot `query()` with structured output, and `ResponseCollector` for streaming.
- `lup.mcp` — `@lup_tool` decorator for MCP tools with typed Pydantic input/output, plus a patched `create_mcp_server` that preserves `is_error`.
- `lup.hooks` — composable hook primitives: directory-based permissions, tool allowlists, tool gates (deny until a condition unlocks), nudges, capture hooks.
- `lup.reflect` — reflection gate for reflect-before-output workflows.
- `lup.realtime` — `Scheduler` for persistent agents (sleep/wake, debounce, reminders) and its guard hooks.
- `lup.background` — `BackgroundAgent` companions that run alongside a main session.
- `lup.sandbox` — Docker-based persistent REPL (`pip install lup[docker]`).
- `lup.history` / `lup.notes` / `lup.paths` — version-aware session storage, RO/RW notes layout, and lazy path configuration.
- `lup.trace` — color-coded console display and markdown trace logging.
- `lup.metrics` / `lup.retry` / `lup.throttle` — tool-call metrics, retry with backoff, rate limiting.

## Usage

```python
from pydantic import BaseModel, Field

from lup.client import query
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


summary = await query("Summarize the findings", output_type=Summary)
```

Paths resolve lazily: importing `lup` never touches the filesystem. Point session storage somewhere explicit with `lup.paths.configure(root=..., notes_dir=..., version=...)`.
