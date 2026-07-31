# Migrating to Lup 0.2

This is a clean breaking release. Remove legacy imports rather than wrapping
them; no runtime compatibility facade exists.

| Removed surface | Replacement |
|---|---|
| `Engine.client()` / `Client.session()` | adapter `create_*_session_factory(config)`, then `SessionFactory.open()` |
| `Client.query()` / broad `query(**options)` | `SessionFactory.query(prompt, OutputModel)`, or the free `query(factory, prompt, OutputModel)` alias |
| `Client.stream()` / `ReplayStream` | optional `TurnHandle.events`; completed `TurnResult.blocks` |
| old `Session.send(text)` | `handle = await Session.start(turn_request(text))`; then `await handle.turn.result()` |
| `Session.interrupt()` | optional `TurnHandle.interrupt.interrupt()` |
| `LupResponse.output(Model)` | strict `TurnResult[Model].output` |
| `output_schema` / `output_format` | `TurnRequest(output_type=Model)` and turn-bound `submit_output` |
| template `create_output_tool()` finalization | session-owned per-turn binding and store |
| `Engine.profiles()` / `Profile.select()` | adapter `ProfileResolver.session_factory(base, name)`, or `resolve(name)` plus immutable `ConfigTransform.apply()` |
| `Engine.background()` / `BackgroundDriver` | `runtime.background.BackgroundAgent(factory, state_to_request, ...)` |
| `Engine.builtin_tools()` / provider tables | adapter `NativeEventDecoder` plus semantic events; explicit local native names only where an SDK config requires them |
| `claude-compat` / `openai-compat` engines | `ClaudeCompatibilityTransform` / `CodexCompatibilityTransform` |
| `LupAgentOptions` | component-owned `ClaudeSessionConfig`, `CodexSessionConfig`, wrapper configs, and `TurnRequest` |
| `ConsumeTracker`, `INTENT_KNOBS`, `refuse_unconsumed()` | Pydantic validation on the component that owns each setting |
| global `ENGINES` / mutable `MODEL_ROUTES` | immutable `ModelRoute` values and explicit recipes |
| `Sessions`, `Stream`, `ComposedClient` component slots | narrow contracts and transparent capability handles |
| provider background client reconstruction | one configured factory injected into the neutral scheduler |
| SDK message/response conversion public modules | adapter-private conversion into runtime blocks/events |
| `adapters.tools.names` | semantic policy models; native names remain private to decoders/renderers/config roots |
| `adapters.profiles.*` | `adapters.claude.config` / `adapters.codex.config` transforms and typed registries |
| `lup-devtools claude` | `lup-devtools harness claude` |
| `lup-devtools claude usage` | `lup-devtools usage` |

Before:

```python
client = create_client(model="...", output_type=Summary)
response = await client.query("summarize")
summary = response.output(Summary)
```

After:

```python
factory = create_claude_session_factory(ClaudeSessionConfig(model="..."))
result = await factory.query("summarize", Summary)
summary = result.output
```

Put provider selection in one concrete application composition root. Pass the
resulting `SessionFactory` into neutral orchestration, background agents,
subagent recipes, and resolver entries. Apply timeout, budget, recovery,
correction, persistence, and serialization with `decorated_session_factory()`.

Codex dynamic tools are currently thread-start scoped. Typed resume and schema
changes in one thread fail before input; this is an explicit native capability
gap, not a migration fallback.

Main application sessions retain the previous trace/display pipeline, project
MCP groups, persistent relay tools, reflection gates, budgets, and subagents.
Claude uses native subagent definitions and provider-reported cost; Codex uses
stdio MCP groups and explicit token pricing. Codex rejects subagent specs whose
per-role tool restriction cannot be enforced by the app-server.
