# Changelog

## Unreleased

Breaking reorganisation of the library's top level. Thirty-four entries became
twenty by asking of each one which of four kinds it is: a foundation that
imports nothing else here, a subject, the one vendor boundary, or tooling.
Every import path an adopter holds is affected, and the migration is derived
rather than written. The surface as it stood before the move is checked in, so
one command reads it against whatever tree is in front of it and prints the
exact `dev relocate` invocation — 106 module pairs — that repoints a checkout:

```sh
uv run lup-devtools dev preserve migration \
    --ledger preservation-ledger-before-hierarchy.json
```

Derived rather than pasted here for the reason the reorganisation itself gives:
a hundred pairs written down go stale the next time one module moves, and a
list confidently wrong is worse than one that had to be looked up.

| Was | Is | Why |
| --- | --- | --- |
| `lup.adapters` | `lup.providers` | the boundary named for what sits behind it, not for the pattern |
| `lup.runtime` | `lup.sessions` | one of four modules called `runtime`; the engine is about a session's turns |
| `lup.runtime.contracts` / `.models` / `.wrappers` | `lup.sessions.capabilities` / `.events` / `.middleware` | each named for what it holds |
| `lup.runtime.profiles`, `.profile_tree`, `.login`, `.session_home`, `.selection`, `.routing`, `.config` | `lup.providers.*` | which runtime answers is the provider's question, not the turn engine's |
| `lup.mcp`, `lup.tool_policy`, `lup.tool_routes`, `lup.codeintel` | `lup.tools.mcp`, `.policy`, `.routing`, `.lsp` | one entry for what an agent acts with; `codeintel` shared eight characters with `codescan` on the opposite side of the system |
| `lup.journal`, `lup.telemetry.*`, `lup.replay.journal`, `lup.usage`, `lup.runtime.usage` | `lup.observability.journal`, `.audit`, `.trace`, `.display`, `.metrics`, `.blocks`, `.native`, `.replay`, `.usage`, `.cost` | four entries answered "what happened", and `journal` named four different things |
| `lup.actors`, `lup.jobs.runtime`, `lup.realtime`, `lup.subagents`, `lup.reflect`, `lup.runtime.background` | `lup.orchestration.*`, with `reflect` → `reflection` and `jobs.runtime` → `jobs` | five entries answered "run work concurrently" |
| `lup.resilience`, `lup.runtime.threads`, `lup.gitlocks` | `lup.execution.resilience`, `.threads`, `.writability` | what carrying work out runs into; `gitlocks` asks a filesystem question that git's `config.lock` is only the first caller of |
| `lup.hooks` | `lup.policy.hooks` | the hook seam is part of the permission subject |
| `lup.codescan` | `lup.harness.codescan` | the rule engine reads the harness declaration models it judges |
| `lup.selection` | `lup.tables` | it is about narrowing a library table, not selecting a runtime |
| `lup.gitguard` | `lup.devtools.gitguard` | catching a test suite writing outside its fixtures is development tooling |
| `lup.harness.banner` | `lup.banner` | a foundation both the harness and the policy bundle write |

`lup.channels`, `lup.types`, `lup.markdown`, `lup.client`, `lup.workspace`,
`lup.web`, `lup.sandbox`, `lup.policy`, `lup.harness`, `lup.resolver` and
`lup.devtools` keep their names. `channels` in particular stays a top-level
foundation: it imports nothing but `lup.types`, and folding it in with
`workspace` manufactured a cycle between storage and observability.

- Modelled the payloads a literal dictionary key was reading by hand: a Codex
  `turn/completed` notification, the two spellings a delegation names its role
  under, what a retrieval call names as its source, Claude's project section,
  and the REPL wire protocol, now declared once in the half that runs in the
  container. `PayloadText` in `lup.types` carries the fact three of them
  share.
- Named the shapes that replace an open string map in the `dict-str-payload`
  and `dict-str-object` diagnostics, so a denial points at a frozen id model,
  a declared route list, or `EnvVars`/`StringMap` rather than at a
  suppression.
- Derived the permissions page's settlement order from the kernel that reads
  it, and the supersession gate now reads its answer from the domain it
  publishes rather than from a constant pair declared beside it.
- Version directory names parse with `semver`, so an experiment arm's
  `+build` suffix orders with the release it came from, and `resolve_version`
  takes the counter and the word for what it counts as overridable defaults.

## 0.2.0 — 2026-07-23

Breaking capability-composition and semantic-policy release. A clean break:
remove legacy imports rather than wrapping them, because no runtime
compatibility facade exists.

| Removed surface | Replacement |
|---|---|
| `Engine.client()` / `Client.session()` | adapter `create_*_session_factory(config)`, then `SessionFactory.open()` |
| `Client.query()` / broad `query(**options)` | `SessionFactory.query(prompt, OutputModel)`, or the free `query(factory, prompt, OutputModel)` alias |
| `Client.stream()` / `ReplayStream` | optional `TurnHandle.events`; completed `TurnResult.blocks` |
| old `Session.send(text)` | `handle = await Session.start(turn_request(text))`, then `await handle.turn.result()` |
| `Session.interrupt()` | optional `TurnHandle.interrupt.interrupt()` |
| `LupResponse.output(Model)` | strict `TurnResult[Model].output` |
| `output_schema` / `output_format` | `TurnRequest(output_type=Model)` and turn-bound `submit_output` |
| `Engine.profiles()` / `Profile.select()` | adapter `ProfileSelector.session_factory(base, name)`, or `transform(name)` plus immutable `ConfigTransform.apply()` |
| `Engine.background()` / `BackgroundDriver` | `runtime.background.BackgroundAgent(factory, state_to_request, …)` |
| `Engine.builtin_tools()` / provider tables | adapter `NativeEventDecoder` plus semantic events |
| `claude-compat` / `openai-compat` engines | `ClaudeCompatibilityTransform` / `CodexCompatibilityTransform` |
| `LupAgentOptions` | component-owned `ClaudeSessionConfig`, `CodexSessionConfig`, wrapper configs, `TurnRequest` |
| `ConsumeTracker`, `INTENT_KNOBS`, `refuse_unconsumed()` | Pydantic validation on the component owning each setting |
| global `ENGINES` / mutable `MODEL_ROUTES` | immutable `ModelRoute` values and explicit recipes |
| `adapters.tools.names` | semantic policy models; native names stay private to decoders and renderers |
| `lup-devtools claude` | `lup-devtools harness claude` |
| `lup-devtools claude usage` | `lup-devtools usage` |

- Replaced engine/client/options service locators with narrow `SessionFactory`,
  `Session`, `Turn`, event, interrupt, steer, fork, binding, render, launch, and
  policy capabilities.
- Added strict typed turn-bound `submit_output`, whole-logical-turn wrappers,
  debounced background scheduling, immutable routing, profile transforms, and
  Claude/Codex concrete factories.
- Added `SessionRequest.effort`, so reasoning effort is asked for in portable
  words and rendered by `CLAUDE_EFFORT`/`CODEX_EFFORT` the way autonomy already
  was. Both adapters already carried an effort field and passed it to their
  provider, but no request could reach either, so an application that set one
  silently ran at whatever the runtime's own configuration file said. The two
  ladders meet on `low`–`xhigh`; `minimal` opens at Claude's floor and `max` at
  Codex's ceiling, and Codex's `none` is withheld because Claude would render
  it as `low`.
- Moved Codex execution to typed live app-server JSON-RPC and records the
  current dynamic-tool rebinding limitation explicitly.
- Added a single Pydantic harness catalog, deterministic Claude/Codex artifact
  compilation, validation, safe reconciliation, ownership manifests, hermetic
  semantic policy dispatchers, Codex cache verification, and named launchers.
- Added the persisted DAG resolver with question brokering, isolated leases and
  worktrees, semantic multi-parent joins, bounded review, integration,
  verification, final review, and cleanup records. Native entries scan and
  organize inline notes through the shared Python core without modifying the
  user's checkout.
- Added the project-wide `abc-capability` AST rule and typed suppression audit.
- Added the semantic shell decision lattice: erased rule tables judge every
  command, subcommand, and flag tier; unjudged work denies with a
  `# lup: escalate:` recipe; loops, conditionals, case arms, subshells, brace
  groups, and `$(...)` substitutions classify recursively over frozen variable
  bindings; `find -exec` payloads, `timeout`/`nice` wrappers, read-only
  `sed`/`awk`/`curl` screens, and quoted heredocs are judged in place; segments
  join deny > ask > defer > allow.
- Added launcher-verified OS-sandbox awareness: a `HookSet` sandbox declaration
  compiles into settings, launch, and doctor; unjudged work defers to the
  active sandbox boundary, a `dangerouslyDisableSandbox` escape re-enters the
  deny lattice, and Codex launches establish the interactive sandbox envelope.
- Added the Codex guidance flavor: shared template sections render both
  `TEMPLATE_CLAUDE.md` and a native `TEMPLATE_AGENTS.md`, with intentional
  differences recorded in docs/platform-differentiation.md.
- Added `# lup: defer[<wake condition>]:` parked-work notes with wake-gated
  clearing; tracking files are retired and `dev check` stays red while any
  deferred note exists.
- Renamed the downstream registry to `sync.json` with a documented contract
  (docs/template.md) and a legacy fallback.
- Added human-owned file protection compiled from the hook catalog: README.md
  edits always ask and never auto-allow.
- Added generated-artifact provenance banners with ownership documentation
  (docs/harness.md), and extracted the resolver entry and hook
  dispatchers into real source assets.
- Retyped the harness catalog around annotated domain types, decomposed the
  harness CLI into composition, drift, reconcile, doctor, resolve, and launch
  modules, and gave anti-pattern rules token-masked syntactic contexts shared
  by the auditor and the hook kernel.
- Hardened the resolver entry's argument normalization and pinned
  worker-crash, revision-exhaustion, and join-conflict recovery legs.
- Added the pre-commit generation gate and the native-nightly workflow
  (deterministic evidence checks plus secrets-gated live smokes), and audited
  the test suite for load-bearing coverage.
- Removed all legacy engine, client, broad options, profile, background-driver,
  replay-stream, and provider-wide tool-registry modules. There is no legacy
  facade.
- Fixed `LocalProcessLauncher` to capture through pipes so git output stays
  plain regardless of the host pager configuration, and made resolver resume
  treat the persisted phase as a monotonic high-water mark so hard-killed runs
  recover from every mid-phase kill window.
- Fixed a Claude launch to name every plugin directory the checkout carries
  rather than only the compiled one, so a project's hand-written plugin loads
  from its own tree instead of through a marketplace name — one global
  namespace whose winner is whichever checkout registered it last.

This was a clean breaking release with no compatibility facade: every removed
surface above has a replacement in the current API, which
[docs/library.md](docs/library.md) describes directly.
