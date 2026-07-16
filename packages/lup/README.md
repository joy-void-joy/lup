# lup

Lup 0.2 is a typed capability-composition library for Claude SDK and Codex
app-server agents. Importing `lup` loads no optional provider SDK.

The package-root API is intentionally small: `SessionFactory`, typed turn
request/result and capability-handle models, `turn_request()`, and `query()`.
Narrow capabilities live in `lup.runtime.contracts`; concrete provider config
and composition roots live in `lup.adapters.claude` and `lup.adapters.codex`.

```python
from pathlib import Path

from pydantic import BaseModel

from lup import TurnInput, query, turn_request
from lup.adapters.codex.runtime import (
    CodexSessionConfig,
    create_codex_session_factory,
)


class Summary(BaseModel):
    title: str
    points: list[str]


factory = create_codex_session_factory(
    CodexSessionConfig(model="gpt-5.5", cwd=Path.cwd())
)
result = await query(
    factory,
    turn_request(TurnInput(text="Summarize the findings"), Summary),
)
summary = result.output
```

`SessionFactory.open()` yields a transparent `SessionHandle`. Await
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
[architecture guide](../../docs/architecture.md) and
[0.2 migration guide](../../docs/migration-0.2.md).
