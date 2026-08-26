# lup

Lup 0.2 is a typed capability-composition library for Claude SDK and Codex
app-server agents. Importing `lup` loads no optional provider SDK.

The package-root API is intentionally small: two constructors —
`create_claude()` and `create_codex()` — plus `Client`, the typed turn
request/result and capability-handle models, and `turn_request()`. Narrow
capabilities live in `lup.sessions.capabilities`; concrete provider config lives in
`lup.providers.claude` and `lup.providers.codex`, which nothing above them needs
to import.

```python
from pydantic import BaseModel

from lup import create_codex


class Summary(BaseModel):
    title: str
    points: list[str]


client = create_codex(model="gpt-5.5")
result = await client.query("Summarize the findings", Summary)
summary = result.output
```

Both constructors take the same common arguments — `model`, `system_prompt`,
`cwd`, `base_url`/`api_key` — and each translates onto whichever field its own
provider declares, so moving between providers is one word. A caller that holds
a whole `ClaudeSessionConfig` or `CodexSessionConfig` passes it positionally
instead.

`create_client("gpt-5.5")` routes a model id to whichever provider serves it,
for a caller who does not want to know which vendor owns which prefix;
`provider=` says it outright where no prefix claims the id. It carries the
common arguments only — dispatch cannot type a provider's own options, so the
named constructors stay the route for those.

They resolve on first access, which is what keeps the promise above: `import
lup` costs roughly 80 ms and pulls neither provider SDK.

`Client` is a concrete class over one typed `SessionOpener` callable,
and what a constructor returns. `query()` is a member of it — one spelling, so
there is no second route to learn — taking a prompt string, a `TurnInput`, or a
prepared `turn_request(...)`, and inferring one exact
`TurnResult[T]`. `turn_request()` builds the request when a caller needs to hold
one — a background agent mapping state to requests, or a session started by
hand. `Client.open()` yields a transparent `SessionHandle`. Await
`handle.session.start(request)` to receive a `TurnHandle`, then await
`turn.turn.result()`. Live events, interruption, steering, and forking are
optional capabilities on those handles; absence is represented by `None`.

Structured results use one portable mechanism: the session binds an exact
Pydantic schema to a fresh `submit_output` store before native input is
accepted. Native structured-output modes are disabled. A successful
`TurnResult[T]` therefore always contains a validated `T`; no submission is a
typed error.

Other modules provide independently composable runtime decorators, semantic
policy, deterministic harness generation/reconciliation, the persisted
resolver, MCP helpers, workspace/history support, scheduling, telemetry, and
sandboxing. See the repository's
[library guide](https://github.com/joy-void-joy/lup/blob/main/docs/library.md)
and
[architecture guide](https://github.com/joy-void-joy/lup/blob/main/docs/architecture.md).
Runnable factory, wrapper, background, profile, endpoint, route, and policy
compositions live in the repository
[examples](https://github.com/joy-void-joy/lup/tree/main/examples).
