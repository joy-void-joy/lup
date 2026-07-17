# Test-suite load-bearing audit

This is the review record answering one question about `tests/unit` and
`tests/integration`: does each test protect behavior an adopter depends on, or
does it assert a fixture back at itself? Every file was read and judged by a
single standard — **would this test catch a realistic regression?** — and
statement coverage was measured over `packages/lup` (the reusable framework)
and `src/lup_template` with `uv run pytest --cov=lup --cov=lup_template
--cov-report=term-missing`.

The headline verdict: the suite is not decorative. Almost every file pins
adopter-visible behavior — security decisions, byte determinism, wire formats,
state persistence — and the canonical/bundled policy parity fixtures are the
strongest asset in the repository. The audit found two decorative artifacts
(both resolved below), one real bug, and a short ranked list of genuinely
uncovered load-bearing code.

## Surface map

| Load-bearing surface | Test files | Verdict |
|---|---|---|
| Permission/policy semantics — canonical and bundled dispatcher | `test_semantic_policy` (shared shell/fetch/edit fixture cases run against the canonical policy objects **and** the assembled kernel under `python3 -I -S`, so the dependency-free runtime cannot drift from the library), `test_policy_chain` (deny precedence, conservative empty chain, observer isolation), `test_tool_policy`, `test_tool_gate`, `test_permission_hooks`, `test_antipatterns` (rule rows single-sourced into the bundle), `test_markers` | Genuinely covered. Kernel 86%, chain/rules/bundle 96–100%. |
| Harness generation determinism, reconciliation, ownership, drift | `test_harness_compilation` (byte-deterministic regeneration, the live repository pinned drift-clean, ownership proofs, reconciler conflict/adoption/deletion semantics, materializer refusal on changed proofs and stale modes, source-patch digests including symlink escape), `test_harness_evidence` (version-drift triggers, CI workflow gates), `test_harness_process` (launcher capture contract) | Genuinely covered. Reconciliation 99%, materialization 100%, models 90%. |
| Resolver state machine and persistence | `test_resolver_core` (DAG ordering, writable-root leases, state round-trip, orchestrator commit authority — a worker changing branch or HEAD is refused), `test_devtools_resolve_branch` | Covered. Core 84%, state 92%; orchestrator 77% (residual: `restore`/`reset`/semantic-join error branches). |
| Adapter native seams — Claude | `test_claude_hook_translation` (portable hook → native SDK hook: path normalization, deny/block/system-message rendering, matcher registration), `test_adapter_runtime`, `test_adapter_transforms`, `test_semantic_policy` decision renderers | Covered. Hooks 100%, runtime 85%, native 76%. |
| Adapter native seams — Codex | `test_app_server_protocol` (JSON-RPC routing: approvals round trip through the installed handler, refusal without one, raising handlers answered so the native side never hangs, disconnect fails all pending futures), `test_capability_runtime` (EOF/malformed-line failure paths, stale-turn protection), `test_native_probes` (CLI probe classification with fake executables; plugin-cache digest install gate: short-circuit, remove-then-add, refusal when the installed digest still differs) | Covered. App-server 72% (residual: process-attached `start`/`close`), runtime 63%, harness_runtime 96%. |
| Realtime relay and scheduler | `test_realtime_relay` (mailbox offset protocol, served tools, wake loop), `test_scheduler` (sleep/wake, debounce windows), `test_background_runtime`, relay no-loss/no-redelivery classes in `test_lib_core_fixes` | Genuinely covered. Relay 93%, scheduler 84%. |
| Sandbox | Unit: `test_sandbox_mounts` (mount topology as single source), `test_sandbox_deadline`, `test_repl_server` (wire protocol), container orphan/liveness decisions in `test_lib_core_fixes`. Integration (Docker, `-m integration`, nightly): `test_sandbox_repl` | Split by design: pure decision logic is unit-pinned; the container lifecycle itself runs only in the nightly integration lane. |
| Workspace, session, account selection | `test_paths`, `test_notes_trace_path`, `test_history`, `test_history_roundtrip`, `test_session_context` (the producer/consumer env relay round-trips exactly), `test_profile_store` (explicit → active → default resolution; unknown names are loud) | Genuinely covered. Context and profile store 100%. |
| Runtime composition and wrappers | `test_capability_runtime`, `test_runtime_wrappers` (whole-turn timeout, recovery, correction, persistence, queue), `test_retry`, `test_throttle`, `test_subagent_tool`, `test_reviewer_backend_agnostic`, `test_lup_tool`, `test_toolsets` | Covered. Wrappers 89%, composition 97%. |
| Codescan (markers, boundaries, capabilities) | `test_markers` (string/comment context rules), `test_boundaries` (adapter imports cannot leak; live tree pinned at zero breaches), `test_capability_ast`, `test_capability_matrix_docs` (README matrix regenerates or fails) | Genuinely covered. |
| Devtools | `test_devtools_cli` (every command's `--help` plus read-only real runs), behavior tests against throwaway git repos (`test_devtools_comments`, `_conflicts`, `_version`, `_trace`, `_feedback`, `_format`, `_fixes`), `test_rule_reference` (docs/rules.md regenerates or fails) | Command wiring and the load-bearing subcommands are covered; deep command bodies (sync 22%, branches 18%, pr 39%) rely on the smoke layer — acceptable for local tooling, listed for honesty. |
| Cross-backend behavior on live services | `test_backend_parity`, `test_native_smokes`, `test_serve_tools` (integration-marked; the nightly workflow ordering is itself pinned by `test_harness_evidence`) | Live lane, deselected by default — by design. |

## Decorative findings

- `tests/unit/test_barrel.py::test_unknown_attribute_raises` asserted that
  Python raises `AttributeError` for an unknown attribute — language behavior,
  not library behavior. **Deleted.**
- `tests/unit/codex_hooks_reference.py` — 491 lines of quarantined Codex
  command-hook codegen imported by nothing and executed by nothing, while its
  docstring claims it is "kept beside its tests". The quarantine itself is a
  recorded decision (the probed runtime does not honor these hooks), so the
  module stays; the missing tests now exist:
  `test_codex_hooks_reference.py` executes the generated permission and
  reflection-gate scripts on a fresh interpreter and pins the tag dispatch and
  TOML override wire format. **Strengthened.**

No other tautological or fixture-echo tests were found. The suite's mocked
seams (e.g. `test_reviewer_backend_agnostic`) each pin an injection contract a
backend swap would break, which passes the regression standard.

## Bug surfaced by this audit

Writing the probe tests exposed that `ClaudeCapabilityProbe.probe` and
`CodexCapabilityProbe.probe` constructed `sh.Command` outside their `try`
block, so a machine without the native CLI crashed the probe with
`CommandNotFound` instead of reporting the capability as unsupported with
`version="missing"` — the exact classification the harness doctor depends on.
Fixed in both adapters; `test_native_probes` holds the pin.

## Ranked remaining gaps

1. **`lup/sandbox/container.py` (33%) and `lup/sandbox/repl.py` (29%)** — the
   Docker lifecycle (create, adopt, orphan-removal execution, REPL client
   transport) runs only in the nightly `-m integration` lane. The pure
   decision logic is unit-pinned, but a lifecycle regression surfaces a day
   late. Next step: route container commands through a fake-`docker`
   executable seam like `test_native_probes` does for `codex`.
2. **`lup/adapters/codex/runtime.py` (63%)** — turn-channel notification
   decoding breadth (item deltas, approval param shapes) beyond the pinned
   failure paths.
3. **`lup/adapters/codex/app_server.py` `start`/`close` (module 72%)** — the
   process-attached handshake and terminate paths run only in native smokes; a
   fake app-server executable speaking the initialize exchange would close
   this offline.
4. **`lup/resolver/orchestrator.py` (77%)** — `restore`, `reset`, and
   `prepare_join`/`commit_join` error branches of the resolver's git
   authority.
5. **`lup/adapters/claude/native.py` (76%) / `codex/native.py` (82%)** —
   decoder/renderer long-tail operation shapes.
6. **`lup/telemetry/display.py` (53%)** — TUI assembly; lowest stakes on this
   list.

Overall `lup` package statement coverage stands at 85% under the default
(non-integration) selection.
