# Changelog

## Unreleased

Breaking reorganisation of the library's top level. Thirty-four entries became
twenty by asking of each one which of four kinds it is: a foundation that
imports nothing else here, a subject, the one vendor boundary, or tooling.
Every import path an adopter holds is affected, and the migration is derived
rather than written. Both ends of the range are read out of git, so one command
prints the exact `dev relocate` invocation that repoints a checkout from
whichever commit it stands at:

```sh
uv run lup-devtools dev migrate map c564bc01a..
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
| `lup.client` | `lup.sessions.client`, `lup.providers.routing`, `lup` | one module was the type every consumer holds *and* the router that reaches both vendors |
| `lup.gitlocks` → `lup.execution.writability`, and `lup.devtools.utils.git` | `lup.execution.shell` | a configured `git` the mount rail and the harness both reach, moved below both |

`lup.channels`, `lup.types`, `lup.markdown`, `lup.workspace`, `lup.web`,
`lup.sandbox`, `lup.policy`, `lup.harness`, `lup.resolver` and `lup.devtools`
keep their names. `channels` in particular stays a top-level foundation: it
imports nothing but `lup.types`, and folding it in with `workspace`
manufactured a cycle between storage and observability.

`from lup import Client, create_client, Provider` is unchanged — the package
root still exports the whole front door, and `create_client` is declared there
now rather than one module down. What moved is where a consumer that bypassed
the root has to look: `Client` is `lup.sessions.client`, and the model-id
routing is `lup.providers.routing`, which is the vendor edge that was already
keeping a matcher vocabulary of its own.

**One capability is gone rather than moved.** `PROVIDER_PREFIXES`, a
`dict[str, Provider]` matched longest-prefix-first, is replaced by
`PROVIDER_ROUTES`, a `list[ProviderRoute]` matched in declaration order and
carrying a `ModelMatcher` rather than a bare prefix — so an adopter can name a
model exactly, or write a matcher of its own, where a prefix says the wrong
thing. A caller passing `prefixes=` passes `routes=` instead, and writes the
narrower entry above the broader one rather than relying on a sort nothing on
the page mentioned. Every other export in the ledger resolved to its new home.

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

### The coordination store is state

Four append-only logs folded whole by every reader on every call became one
file per member, written by that member's own processes under its own lock,
with every relation between members derived at the read: presence is the
file's modification time, a claim carries the modification time of the path it
was taken over and is settled by a stat, and a contest is two live members'
files meeting on one path. Mail is one file per message in one inbox, consumed
by deletion, so no reader keeps a position.

Broadcast splits into the two acts it always was. A message has one recipient,
so a sender that means everyone resolves it against the roster; a standing
fact is state — read at the head of a turn for as long as it holds, retracted
by deleting it, and reaching a session that starts tomorrow.

Eight migrations are declared over the hundred and fifty-three names this
moves; `uv run lup-devtools dev migrate map` prints what to call instead.

### A module's prose is one file

Prose a content module composes is authored as Markdown beside it. A module
composing several passages marks them off inside that one file with
`<!-- passage: name -->` and names which it is placing, so a subject is one
file rather than eleven and a passage is named for what it holds rather than
for its position in a list.

`passage_path` takes the module alone — which passage is `Passage.name`, read
off the section markers rather than off a second filename. How many newlines a
rendered document ends on moved from `sectioned` to the renderer, which is the
one reader that sees a whole document whatever kinds of part composed it.

### A peer that is idle can be woken

`wake()` finishes the job itself on both runtimes rather than handing the
caller an instruction on one of them. Every Claude session runs a private
inbox socket, and lup passes `--messaging-socket-path` for every session it
launches, so a member declares the handle that wakes it when it joins and a
sender writes a frame there carrying that member's session id. A session lup
did not launch is still reached through the runtime's own default paths.

The handle is declared by the adapter for the runtime that would use it,
because what a handle *is* differs by runtime: on Codex it is the thread
`codex queue` takes, which nothing hands a server Codex starts, so that
adapter declares nothing and the outcome is reported rather than skipped.

A wake is always *on top of* the mail and never instead of it, so the record
is identical on both and only the latency differs. The agent never touches the
channel: `coordination_send` remains the one habit.

### The rest

- `ledger migrate` copies a kind's journal lines and blobs into the placement
  its mapping now declares, for a kind moved after records already exist. The
  source lines stay: the committed journal is merged by git's union driver, so
  a deletion there would not even be durable, and the fold already reads each
  record once.
- `ledger index-notes` records a closed session per directory under an
  existing `notes/` tree, and one output per result, through the same writers
  a live run uses — so a backfilled record is the same two records a live run
  leaves. Idempotent by `(checkout, path)`.
- Every parsed command carries the directory it runs in, and a segment's path
  words resolve by position rather than by value, so a relative operand after
  a `cd` is judged against the file it would reach.
- An in-place rewrite nothing produced says which reading stopped it: a path
  naming no file, a target that is not a regular file, a script `sed` would
  not run, and text that could not be read each carry their own recovery.
- A global in front of a subcommand is consumed before the subcommand is read.
- A contained session reads the clock in the operator's zone, filled from the
  file the machine keeps it in rather than from a `TZ` a Linux host exports
  for nobody.
- Every workflow job names the pinned runner image, held to it by a sweep over
  `.github/workflows` rather than by whoever remembers.

### What this release carries no migration for

A repository declares which of its subtrees it publishes nothing out of, in
`DevProject.internal_modules`, and the preservation gate walks what is left.
Two are declared here, and what went from them is not a break an adopter can
meet:

- **`lup_template`**, the scaffold. `dev init` copies this half into the
  adopting repository and renames it, so its names arrive there as that
  project's own source rather than as an import. Thirteen went, among them
  `build_session_toolset`, the five `*_GROUP` toolsets, and the `library_*`
  commands.
- **`lup.policy.kernel`**, compiled into the hermetic dispatcher each
  generated plugin runs and reached there as bare `kernel.*`. Forty-seven
  went, nearly all of them the hand-rolled shell tokenizer — `ShellToken`,
  `Lexeme`, `Scan`, `tokenize_shell`, `read_heredoc_bodies` — and the
  control-flow readers beside it, replaced in place.

A project that imported either subtree was reaching past what this repository
publishes. The declaration sits in the catalog with its reasoning, so the
judgement can be read and argued with rather than inferred from a gate that
quietly stopped firing.

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
