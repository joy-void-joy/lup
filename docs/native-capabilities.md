# Native capability evidence

This ledger records the native contracts accepted for Lup 0.2. Runtime
versions are evidence boundaries, not branches in shared orchestration. A
capability not proven here is absent from the portable handle or fails before
input; it is never represented by an unsupported-operation stub.

Evidence was refreshed on 2026-07-16 against Claude Code 2.1.211, Claude Agent
SDK 0.2.89, and Codex CLI/app-server 0.144.4.

| Contract | Version | Evidence | Accepted fact |
|---|---:|---|---|
| Claude plugin package | Claude Code 2.1.211 | `claude plugin validate .claude/plugins/lup` passed; [Claude plugin documentation](https://docs.anthropic.com/en/docs/claude-code/plugins) | The generated manifest, commands, agents, and bundled hooks are loadable. |
| Claude runtime | Claude Agent SDK 0.2.89 | Lazy option construction plus direct SDK block, usage, cost, hook, partial-event, fork, and subagent fixtures in `tests/unit/test_adapter_runtime.py`; [Claude SDK documentation](https://platform.claude.com/docs/en/agent-sdk/overview) | Resume, live partial events, interruption, and latest-turn transcript forking are exposed. Steering is absent. Turn output uses only Lup's MCP `submit_output` tool. |
| Codex plugin package | Codex CLI 0.144.4 | Generated manifest/marketplace fixtures and cache-digest tests; [Codex plugin structure](https://developers.openai.com/codex/plugins/build#plugin-structure) | Skills, project agents, hooks, marketplace metadata, and installed-cache separation use documented locations. |
| Codex hooks | Codex CLI 0.144.4 | `codex --enable hooks features list` reported hooks stable; hermetic dispatcher fixtures in `tests/unit/test_harness_compilation.py`; [Codex hooks](https://developers.openai.com/codex/hooks) | Plugin hook commands receive `PLUGIN_ROOT`. Non-allow policy decisions fail closed because the command-hook boundary has no portable ask effect. Hook trust remains personal state and is never generated. |
| Codex blocked edit | Codex CLI 0.144.4 | Scheduled `test_codex_plugin_blocks_a_forbidden_apply_patch` installs the generated plugin in an isolated home and requests an anti-pattern edit through the real CLI | The `apply_patch` call is rejected, the target file remains unchanged, and the native session stays alive to report the rejection. A CLI version drift makes the nightly doctor fail until this observation is repeated. |
| Codex app-server lifecycle | Codex CLI 0.144.4 | Version-generated JSON Schema plus routed-notification fixtures; [Codex app server](https://developers.openai.com/codex/app-server) | `thread/start`, `thread/resume`, `thread/fork`, `turn/start`, `turn/steer`, and `turn/interrupt` exist; live notifications are distinct from completed replay. |
| Codex turn tool binding | Codex CLI 0.144.4 | Version-generated `ThreadStartParams`, `TurnStartParams`, `ThreadResumeParams`, and dynamic-tool call/response schemas | `dynamicTools` exists only on `thread/start`. A typed resume or schema transition that would need a new handler is rejected before input to preserve conversation identity. Native `outputSchema` is not enabled alongside Lup submission. |
| Codex custom agents | Codex CLI 0.144.4 | Generated TOML fixture parsing; [custom-agent documentation](https://developers.openai.com/codex/agent-configuration/subagents) | Portable agents render as project-scoped `.codex/agents/*.toml`, outside the plugin. |
| Codex project guidance | Codex CLI 0.144.4 | Generated root fixture; [AGENTS.md documentation](https://developers.openai.com/codex/agent-configuration/agents-md) | Portable repository guidance renders to root `AGENTS.md`. |

The accepted Codex 0.144.4 schema hashes are:

| Schema | SHA-256 |
|---|---|
| `v2/ThreadStartParams.json` | `4f30cb90cae47ff01adba8d863228b2aa198232df895dbfc996d594270326744` |
| `v2/TurnStartParams.json` | `a28f74287e18b8a18c7aa6966ee7552a8ed2ae13c03f4ba12e9af48f7370f19d` |
| `v2/ThreadResumeParams.json` | `f828ee9846f11a68a1d259429ae147ddd49fcbd1cfb860b1a83f41604a5e97b9` |
| `DynamicToolCallParams.json` | `e36242b331ca665c74993e55abbea381b1c8a961b29a42579029cff1ad26b20d` |
| `DynamicToolCallResponse.json` | `50410ccaaefc9871a42fa25ee0c0d4f488a6f0e08c35856842e12d3103410fd1` |

Regenerate those schemas with:

```bash
codex app-server generate-json-schema --experimental --out <temporary-directory>
```

Review any digest change together with the typed app-server models, captured
fixtures, capability matrix, and this ledger. Do not update the user's CLI as
part of probing.

## Explicit release gaps

- Codex 0.144.4 cannot pass the persistent typed-schema transition acceptance
  sequence `None -> A -> A -> B -> None` while preserving one thread: the
  native schema offers no dynamic-tool field on `turn/start` or
  `thread/resume`. One-shot typed turns and repeated same-schema turns are
  supported; incompatible transitions fail before input.
- Claude steering is not claimed by the 0.2 adapter; its handle field is
  `None`. Partial events and latest-turn transcript forking are implemented.
- Codex exposes project tool groups, including `run_subagent`, through MCP.
  A subagent spec with a non-empty native tool allowlist is rejected because
  app-server thread configuration cannot prove that per-subagent restriction;
  the restriction is never silently widened.
- Live authenticated provider smoke tests remain opt-in integration tests and
  are not inferred from unit fixtures.
