# Native capability evidence

This ledger records the native contracts accepted for Lup 0.2. Runtime
versions are evidence boundaries, not branches in shared orchestration. A
capability not proven here is absent from the portable handle or fails before
input; it is never represented by an unsupported-operation stub.

Evidence is refreshed one vendor at a time: Claude Code {{ claude_cli }} on
{{ refreshed }}, Claude Agent SDK {{ claude_sdk }} on {{ refreshed_2 }}, and
Codex CLI/app-server {{ codex_cli }} on {{ refreshed_3 }}. Those three versions,
their reading dates, and the digests below are read from
`lup.harness.evidence`, which is also what
`uv run lup-devtools harness doctor all` compares an installed CLI against —
so this page cannot come to name a version nothing was probed on.

| Contract | Version | Evidence | Accepted fact |
|---|---:|---|---|
| Claude plugin package | Claude Code {{ claude_cli }} | `claude plugin validate .claude/plugins/lup` passed, warning only that the manifest declares no author; [Claude plugin documentation](https://docs.anthropic.com/en/docs/claude-code/plugins) | The generated manifest, commands, agents, and bundled hooks are loadable. |
| Claude runtime | Claude Agent SDK {{ claude_sdk }} | Lazy option construction plus direct SDK block, usage, cost, hook, partial-event, fork, and subagent fixtures in {{ runtime_fixtures }}; [Claude SDK documentation](https://platform.claude.com/docs/en/agent-sdk/overview) | Live partial events, interruption, and latest-turn transcript forking are exposed. Steering is absent. Turn output uses only Lup's MCP `submit_output` tool. **Resume is offered but not honoured**: re-verified on Claude Code {{ claude_cli }}, `claude --session-id <uuid> -p` exits 0 and writes no transcript under `~/.claude/projects`, and `--resume` on that same id answers `No conversation found with session ID`. So a session holds one live connection across every turn that does not change its submission schema, and treats a refused resume as losing that turn's context rather than the run. |
| Codex plugin package | Codex CLI {{ codex_cli }} | Generated manifest/marketplace fixtures and cache-digest tests; [Codex plugin structure](https://developers.openai.com/codex/plugins/build#plugin-structure) | Skills, project agents, hooks, marketplace metadata, and installed-cache separation use documented locations. |
| Codex hooks | Codex CLI {{ codex_cli }} | `codex --enable hooks features list` reported hooks stable; hermetic dispatcher fixtures in {{ dispatcher_fixtures }}; [Codex hooks](https://developers.openai.com/codex/hooks) | Plugin hook commands receive `PLUGIN_ROOT`. Non-allow policy decisions fail closed because the command-hook boundary has no portable ask effect. Hook trust is never *generated*, but a worktree-scoped home seeds it from the account. **A non-interactive `codex exec` reaches the hook**, re-probed on Codex CLI {{ codex_cli }} by {{ exec_fixtures }}: in a scoped home carrying the plugin's trust record, an allowed command ran with `hook: PreToolUse Completed` in the transcript, a denied one was blocked with the dispatcher's own diagnostic, and the same denied command under `--dangerously-bypass-hook-trust` behaved identically — so the seeded trust record is what it governs through rather than a stale hash that the flag was papering over. `exec` still reports `approval: never`, so the `PermissionRequest` half never fires there and a non-allow decision reaches the session as the fail-closed denial. One interactive trust grant per plugin hash is still required on a fresh machine, which `install_declared_policy` enforces by refusing an untrusted home. |
| Codex blocked edit | Codex CLI {{ codex_cli }} | Scheduled `test_codex_plugin_blocks_a_forbidden_apply_patch` installs the generated plugin in an isolated home and requests an anti-pattern edit through the real CLI | The `apply_patch` call is rejected, the target file remains unchanged, and the native session stays alive to report the rejection. A CLI version drift makes the nightly doctor fail until this observation is repeated. |
| Codex app-server lifecycle | Codex CLI {{ codex_cli }} | Version-generated JSON Schema plus routed-notification fixtures; [Codex app server](https://developers.openai.com/codex/app-server) | `thread/start`, `thread/resume`, `thread/fork`, `turn/start`, `turn/steer`, and `turn/interrupt` exist; live notifications are distinct from completed replay. |
| Codex turn tool binding | Codex CLI {{ codex_cli }} | Version-generated `ThreadStartParams`, `TurnStartParams`, `ThreadResumeParams`, and dynamic-tool call/response schemas; inert native resume fixture in `packages/lup/tests/integration/test_native_tool_controls.py` | A thread's effective dynamic-tool binding is established by `thread/start`; resume cannot replace it. Resuming with different application tools or a schema transition that needs another handler is rejected before input. Native `outputSchema` is not enabled alongside Lup submission. |
| Explicit session tool authority | Claude Agent SDK {{ claude_sdk }} and Codex CLI {{ codex_cli }} | Adapter option fixtures in `packages/lup/tests/unit/test_native_tools.py`; native request capture in `packages/lup/tests/integration/test_claude_native_tools.py` and `packages/lup/tests/integration/test_native_tool_controls.py` | `native_tools=None` and `[]` grant no built-in or inherited tool authority. Explicit application tools still execute. The Codex fixture captures both top-level tools and `input.additional_tools`, verifies inherited servers do not start, rejects a fabricated shell call, and proves explicit grants advertise their native facility. Another fixture verifies the declared project hook still blocks a granted native call. `ALL` is an explicit broad built-in opt-in; unsupported exact grants fail before launch. |
| Codex custom agents | Codex CLI {{ codex_cli }} | Generated TOML fixture parsing; [custom-agent documentation](https://developers.openai.com/codex/agent-configuration/subagents) | Portable agents render as project-scoped `.codex/agents/*.toml`, outside the plugin. |
| Codex project guidance | Codex CLI {{ codex_cli }} | Generated root fixture; [AGENTS.md documentation](https://developers.openai.com/codex/agent-configuration/agents-md) | Portable repository guidance renders to root `AGENTS.md`. |

The accepted Codex {{ codex_cli }} schema hashes are:

{{ table }}
Regenerate those schemas with:

```bash
{{ schema_command_spelled_temporary_directory }}
```

`uv run lup-devtools harness doctor all` runs exactly that into a temporary
directory and reports any file whose hash has moved, so a schema change is
found by the doctor rather than by a reader comparing this table by eye.
Review any digest change together with the typed app-server models, captured
fixtures, capability matrix, and this ledger. Do not update the user's CLI as
part of probing.

## Launcher regression evidence

- {{ publication_fixture }} uses the installed native Codex CLI in a credential-free
  home. Installing a second plugin revision must preserve the first revision's
  bytes, retain unrelated configuration, and let native plugin listing find the
  selected revision. A mock that merely copies files does not prove this:
  native installation prunes earlier versions in its target home. Lup confines
  that installation to a staging home and publishes verified output separately.
- {{ authentication_fixture }} covers account refresh, post-login verification,
  redacted failures, explicit unverified continuation, and the same host/container
  command boundary used for the session. These fixtures do not prove a live
  model request or implicit MCP handshake. Named-profile account checks are
  explicitly unavailable, not substituted with checks of the base configuration.

## Explicit release gaps

- Codex {{ codex_cli }} cannot pass the persistent typed-schema transition acceptance
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
- Both generated dispatchers map a session's declared identity to edit
  autonomy, taking it from the launcher's environment and, on Claude, from the
  hook payload as well. Deterministic dispatcher fixtures pin both channels
  against the installed hook; live confirmation that a native payload carries
  the agent identity is owed by the nightly lane. The environment channel needs
  no such confirmation — the launcher writes what it declares.
- Live authenticated provider smoke tests remain locally opt-in through the
  integration marker, run on the credentials-gated nightly lane, and are not
  inferred from unit fixtures.
- A non-allow decision reaches a `codex exec` session as a refusal and never as
  a question. `exec` reports `approval: never`, so the `PermissionRequest` half
  of the boundary cannot fire there whatever the policy classified: an `ask`
  is spent as a denial. The hook itself governs — that is what
  {{ exec_fixtures }} settled — and what is missing is the middle verdict, which
  is a Codex surface gap rather than a Lup one.
- **A session an application opens cannot be asked, only refused — measured on
  Codex CLI {{ codex_cli }}, both halves, by `tests/integration/test_codex_approval_request.py`.**
  `PermissionRequest` does not fire there: a live app-server turn under
  `approval_policy='on-request'` added nothing to the plugin's journal, 48
  completed records before and 48 after, and the 48 it already held came from a
  surface that is not this one. Nor does anything reach the client when the
  dispatcher declines: the shell call was refused by `PreToolUse`,
  `queued_review` parked it, and the turn returned the queue's own recovery
  text with no approval request for the session's hooks to answer.

  Three things follow, and they are the reason this row is worth its length.
  The `exec` finding above is not a property of `exec`: the middle verdict is
  missing from every surface Lup can open, so an `ask` is spent as a denial
  wherever an application is the one asking. The fail-closed denial is
  therefore correct rather than a workaround. And `dev questions` is Codex's
  review surface rather than its fallback, which is what makes that surface's
  diff rendering load-bearing instead of a convenience. Issue #180 is this gap
  met from a real session; queue settlement requires an independent operator.

  **Queue delivery is measured without a model or credentials** by
  `tests/integration/test_codex_review_delivery.py`: an inert loopback Responses
  endpoint requests a copy, the generated hook blocks it, and `hook/completed`
  carries the review id and operator commands as a warning. A recorded operator
  answer permits one exact retry; another retry asks again. The supported
  `PreToolUse` `deny` plus `systemMessage` shape is documented in the
  [official hooks reference](https://learn.chatgpt.com/docs/hooks).
  Exiting 2 drops `systemMessage` on Codex CLI {{ codex_cli }}; successful
  structured denial preserves both the warning and refusal. `codex exec --json`
  omits hook notifications, so its agent-facing refusal remains the delivery
  path on that surface.

  Both arms stay in the suite as `xfail(strict=True)`, so the day a vendor
  grows the channel they pass and the suite says so.
- **Reasoning effort is a per-model vocabulary, and the seeded home holds one
  chosen for a different model.** A scoped home is seeded from the operator's
  own configuration, so it carries their `model_reasoning_effort` beside their
  `model` — and a session naming only the model sends the API a pair nobody
  chose. Measured here: `gpt-5.5` with the home's `max` answers
  `400 unsupported_value`, and the message names the rungs that model takes —
  `'none', 'low', 'medium', 'high', 'xhigh'`. Two readings follow. The ladder
  is per model rather than global: `max` is real for the newer model the home
  was written for, and `minimal` sits in Lup's own accepted vocabulary while
  that list omits it. And a named model must carry an effort, which is what
  `CodexSessionConfig.model_selection` guarantees — the literal is
  deliberately *not* narrowed to one model's answer, because which rungs a
  model accepts is the vendor's to state per model.
- **A Codex home decides whether the policy runs at all, through four gates,
  and `codex doctor` reports on none of them.** The plugin has to be installed
  and enabled; `[features] hooks = true` has to reach *that* home; the project
  has to be trusted in the home's own `config.toml`; and each hook has to be
  trusted per event and per hash. Project trust is a second gate distinct from
  hook trust, with its own failure mode, and
  `--dangerously-bypass-hook-trust` does not lift it — so a session can carry
  a fully trusted plugin and still run ungoverned because the *project* was
  never trusted. Each gate fails the same way: the dispatcher is present, is
  never consulted, and nothing says so.
- **`hooks/list` is a contract Lup depends on.** Trust-record names composed
  from the hook manifest mean keeping a table of events level with what
  generation declares — and a table that is not level makes the one call
  deciding whether an application-opened session carries the policy raise on
  the events it has never heard of. The runtime is asked instead, and each
  hook's `key`, `currentHash`, `trustStatus` and `isManaged` are read off the
  reply. A move in those four field names breaks trust seeding silently, in
  the direction that fails open, so it belongs in the doctor's drift check
  beside the pinned thread schemas rather than being rediscovered.
- Claude Code's **worktree isolation** refuses a command carrying any of
  fifteen shell words as an argv element, in any position, whether or not the
  command is a git command. Read out of the 2.1.237 binary rather than
  inferred: the set is `dNr` minus `qAv`, leaving `eval source . fc coproc
  trap enable mapfile readarray hash bind complete compgen alias let`, and the
  match is `s === "." ? i === 0 : A1p.has(s)` — so `.` alone is gated to
  `argv[0]`. Its two siblings in the same function *are* gated on git
  (`ZLa=/^git(?:\.exe|\.real|-[a-z][\w-]*)?$/i` guards both the
  `xargs`/`parallel` refusal and the `find -execdir/-okdir` one); this third
  check is not. The refusal is byte-identical with a leading `# lup: escalate:`
  line, so no marker reaches it. It arms on the relocation tool, not on the
  working directory: a session launched already rooted in a worktree is not
  isolated, which is what the workflow in `docs/contributing.md` relies on.
  Where it switches is bounded too, and observed rather than read: a path
  outside `.claude/worktrees/` is taken only as a session's first entry from
  its launch directory, and a second switch into a sibling `tree/` worktree
  is refused with `is not under <repo>/.claude/worktrees`.
  Owned by Claude Code; `docs/upstream-reports.md` carries the report to send.
