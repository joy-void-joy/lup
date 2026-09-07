<!-- Generated from lup.devtools.harness.content.docs.native_capabilities by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Native capability evidence

This ledger records the native contracts accepted for Lup 0.2. Runtime
versions are evidence boundaries, not branches in shared orchestration. A
capability not proven here is absent from the portable handle or fails before
input; it is never represented by an unsupported-operation stub.

Evidence is refreshed one vendor at a time: Claude Code 2.1.237 on
2026-08-20, Claude Agent SDK 0.2.89 on 2026-08-20, and
Codex CLI/app-server 0.153.4 on 2026-09-07. Those three versions,
their reading dates, and the digests below are read from
`lup.devtools.harness.evidence`, which is also what
`uv run lup-devtools harness doctor all` compares an installed CLI against —
so this page cannot come to name a version nothing was probed on.

| Contract | Version | Evidence | Accepted fact |
|---|---:|---|---|
| Claude plugin package | Claude Code 2.1.237 | `claude plugin validate .claude/plugins/lup` passed, warning only that the manifest declares no author; [Claude plugin documentation](https://docs.anthropic.com/en/docs/claude-code/plugins) | The generated manifest, commands, agents, and bundled hooks are loadable. |
| Claude runtime | Claude Agent SDK 0.2.89 | Lazy option construction plus direct SDK block, usage, cost, hook, partial-event, fork, and subagent fixtures in `packages/lup/tests/unit/test_adapter_runtime.py`; [Claude SDK documentation](https://platform.claude.com/docs/en/agent-sdk/overview) | Live partial events, interruption, and latest-turn transcript forking are exposed. Steering is absent. Turn output uses only Lup's MCP `submit_output` tool. **Resume is offered but not honoured**: re-verified on Claude Code 2.1.237, `claude --session-id <uuid> -p` exits 0 and writes no transcript under `~/.claude/projects`, and `--resume` on that same id answers `No conversation found with session ID`. So a session holds one live connection across every turn that does not change its submission schema, and treats a refused resume as losing that turn's context rather than the run. |
| Codex plugin package | Codex CLI 0.153.4 | Generated manifest/marketplace fixtures and cache-digest tests; [Codex plugin structure](https://developers.openai.com/codex/plugins/build#plugin-structure) | Skills, project agents, hooks, marketplace metadata, and installed-cache separation use documented locations. |
| Codex hooks | Codex CLI 0.153.4 | `codex --enable hooks features list` reported hooks stable; hermetic dispatcher fixtures in `tests/unit/test_harness_compilation.py`; [Codex hooks](https://developers.openai.com/codex/hooks) | Plugin hook commands receive `PLUGIN_ROOT`. Non-allow policy decisions fail closed because the command-hook boundary has no portable ask effect. Hook trust is never *generated*, but a worktree-scoped home seeds it from the account. **A non-interactive `codex exec` reaches the hook**, re-probed on Codex CLI 0.153.4 by `tests/integration/test_codex_exec_governance.py`: in a scoped home carrying the plugin's trust record, an allowed command ran with `hook: PreToolUse Completed` in the transcript, a denied one was blocked with the dispatcher's own diagnostic, and the same denied command under `--dangerously-bypass-hook-trust` behaved identically — so the seeded trust record is what it governs through rather than a stale hash that the flag was papering over. `exec` still reports `approval: never`, so the `PermissionRequest` half never fires there and a non-allow decision reaches the session as the fail-closed denial. One interactive trust grant per plugin hash is still required on a fresh machine, which `install_declared_policy` enforces by refusing an untrusted home. |
| Codex blocked edit | Codex CLI 0.153.4 | Scheduled `test_codex_plugin_blocks_a_forbidden_apply_patch` installs the generated plugin in an isolated home and requests an anti-pattern edit through the real CLI | The `apply_patch` call is rejected, the target file remains unchanged, and the native session stays alive to report the rejection. A CLI version drift makes the nightly doctor fail until this observation is repeated. |
| Codex app-server lifecycle | Codex CLI 0.153.4 | Version-generated JSON Schema plus routed-notification fixtures; [Codex app server](https://developers.openai.com/codex/app-server) | `thread/start`, `thread/resume`, `thread/fork`, `turn/start`, `turn/steer`, and `turn/interrupt` exist; live notifications are distinct from completed replay. |
| Codex turn tool binding | Codex CLI 0.153.4 | Version-generated `ThreadStartParams`, `TurnStartParams`, `ThreadResumeParams`, and dynamic-tool call/response schemas | `dynamicTools` exists only on `thread/start`. A typed resume or schema transition that would need a new handler is rejected before input to preserve conversation identity. Native `outputSchema` is not enabled alongside Lup submission. |
| Codex custom agents | Codex CLI 0.153.4 | Generated TOML fixture parsing; [custom-agent documentation](https://developers.openai.com/codex/agent-configuration/subagents) | Portable agents render as project-scoped `.codex/agents/*.toml`, outside the plugin. |
| Codex project guidance | Codex CLI 0.153.4 | Generated root fixture; [AGENTS.md documentation](https://developers.openai.com/codex/agent-configuration/agents-md) | Portable repository guidance renders to root `AGENTS.md`. |

The accepted Codex 0.153.4 schema hashes are:

| Schema | SHA-256 |
| --- | --- |
| `v2/ThreadStartParams.json` | `25f490368ec6df52a2a3b82a5469d2413307eb93439121b309f415b5648eee7a` |
| `v2/TurnStartParams.json` | `b36fb37326b1cf69f75c8b306f1f886d53a57c4b1b985e08e298e2407ea2ad02` |
| `v2/ThreadResumeParams.json` | `324e96004c49de35935cade3386958431c93a4fd3997a839f9796772ea4c8072` |
| `DynamicToolCallParams.json` | `401bba20cfbd95762bef0467d840430c46be53369093ad9f26425ba757e34efc` |
| `DynamicToolCallResponse.json` | `abb082cad67f11fcc98ba75f2eff75d7d1723af0c657655329b83ff160451a02` |

Regenerate those schemas with:

```bash
codex app-server generate-json-schema --experimental --out <temporary-directory>
```

`uv run lup-devtools harness doctor all` runs exactly that into a temporary
directory and reports any file whose hash has moved, so a schema change is
found by the doctor rather than by a reader comparing this table by eye.
Review any digest change together with the typed app-server models, captured
fixtures, capability matrix, and this ledger. Do not update the user's CLI as
part of probing.

## Explicit release gaps

- Codex 0.153.4 cannot pass the persistent typed-schema transition acceptance
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
  `tests/integration/test_codex_exec_governance.py` settled — and what is missing is the middle verdict, which
  is a Codex surface gap rather than a Lup one.
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
