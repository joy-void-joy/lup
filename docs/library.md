<!-- Generated from lup.devtools.harness.content.docs.library by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# The lup library

`packages/lup` is the reusable half of this repository: a standalone published
package that knows how to run an agent turn, compile a harness, decide a
permission, and resolve reviewed feedback — without knowing which vendor is
behind any of it. It is the larger of the two code components and the one a
downstream project depends on.

The rule that shapes every module: **shared code never names a provider.**
Native config, hook payloads, command spellings, manifests, and wire schemas
live inside `lup/providers/`. Everything above the providers speaks contracts.
A third backend implements those contracts without editing a shared registry,
because there is no registry to edit.

## The front door

`packages/lup/src/lup/__init__.py` re-exports a deliberately small runtime
surface — the one place in the library where a barrel is allowed, because it
declares a public API:

```python
from lup import (
    create_claude,    # open Claude sessions, configured
    create_codex,     # open Codex sessions, configured
    create_client,    # route a model id to whichever serves it
    Client,   # what a constructor returns
    SessionHandle,    # an opened session, plus optional fork capability
    TurnHandle,       # an accepted turn, plus optional events/interrupt/steer
    TurnInput,        # portable user input
    TurnRequest,      # what to run, and the type to come back
    TurnResult,       # a validated, typed result
    turn_request,     # request factory
)
```

The shortest useful program imports everything it uses:

```python
from lup import create_claude

client = create_claude(model="claude-opus-5", system_prompt="Be concise.")
result = await client.query("summarize", Summary)
summary = result.output
```

The constructors are why the root is worth importing. Everything else here is
vocabulary — a name to annotate against — and vocabulary alone builds nothing,
which an earlier edition of this section demonstrated by accident: it listed
eight nouns and then reached for two names it had never imported, so the
shortest useful program did not run.

`client.query(...)` opens a session, takes one turn, and always closes it. For
anything with more than one turn, open a session and start turns on it — the
same contracts, held longer.

`create_client(model=...)` is the third route, for a caller holding a model id
who does not also want to know which vendor owns which prefix:

```python
from lup import create_client

client = create_client("gpt-5.5")           # routed by prefix
client = create_client("house-model", provider="claude")   # said outright
```

It is deliberately narrower than the two named constructors, and that is the
whole reason all three exist. Dispatch cannot carry typed provider options:
`create_claude(options=ClaudeSessionConfig(...))` type-checks, and no annotation
means "whichever config the model turns out to select". So the common arguments
route, the whole declaration does not, and neither pretends to be the other. A
model no prefix claims raises rather than guessing — a guess opens a session
against the wrong vendor and fails later, in that vendor's vocabulary.

All three resolve their adapter on first access, so `import lup` costs roughly
80 ms and pulls neither provider SDK. Naming a constructor imports its adapter;
opening a session is what finally reaches the vendor's own package.

## Layering

Four tiers, and imports only ever point downward.

1. **Foundations** — entries that import nothing else in the library, so
   they sit at the top level rather than inside a subject. `lup.types` is the
   portable content and tool vocabulary every other package speaks
   (`JsonValue`/`JsonObject`, `ToolName`/`ToolGrant`, `LupContentBlock`,
   `LupMessage`, `Usage`, `SubagentSpec`); `lup.channels` is the file-backed
   primitive both durable state and inter-process rendezvous are built on;
   `lup.banner`, `lup.markdown`, `lup.tables` and `lup.execution` are the
   rest. Burying one of these inside a subject is what manufactures a cycle —
   folding `channels` in with `workspace` did exactly that and was undone.
2. **`capabilities` and `events`** — each subject carries both.
   `sessions/events.py` owns the turn vocabulary; `sessions/capabilities.py`
   owns the narrow capability seams, and each other subject carries the same
   pair under its own names. Seams import the foundations only, so a fake
   implementation needs nothing else.
3. **Implementations** — composition, middleware, validation, reconciliation,
   rule evaluation. These import their own subject's seams and vocabulary, and
   nothing from `providers`.
4. **`lup.providers.claude` / `lup.providers.codex`** — the only packages that
   name a vendor. They implement the contracts above and are imported only by
   named composition roots.

`lup.harness.codescan.boundaries` enforces tier 4 mechanically with the
`seam-boundary` rule: a concrete adapter import outside `lup/providers/`,
the tests, the examples, or a named application composition root is a
build failure, not a review comment.

## Where a module belongs

Three questions place every module, and they point in different directions.

**Outward — would another project built on lup want this?** If yes it belongs
in `packages/lup/` even when only this application uses it today, because the
library never imports the application: a utility left in `src/lup_template/`
is unreachable from here and has to move later. The same test applies to
values. The library may declare one only when it could not have chosen
otherwise — a language's file suffixes, a provider's wire spelling, a closed
enum the library itself defines. Everything else is a judgement, and reaches
an adopter as an overridable default they replace rather than a constant they
fork. `library-default` in `lup.harness.codescan.boundaries` is the mechanical half of
that; canonicity it cannot judge, so a canonical table says so with
`# lup: ignore[library-default]` and a reason.

**Inward — is this the tooling layer, or what the tooling layer is built on?**
`lup/devtools/` is the development CLI an adopter inherits. Provider-neutral
code a program would want with no CLI in front of it sits above `devtools/`,
and `devtools/` imports it; the reverse never holds. A value follows the same
rule at module scale: a page's default port belongs to the module serving that
page, not to a module about checkout directories that happens to be imported
by both.

**Downward — is this a subject of its own, or part of one?** A top-level
package answers a question no sibling answers. One that exists to serve a
single subject nests under it — and library code follows its driver only as
far as the library edge, so a package driven from `lup/devtools/harness/`
nests under `lup/harness/` rather than moving into `devtools/`, which would
pull provider-neutral code into the tooling layer.

## The packages

### `sessions` — how one turn runs

The engine. `capabilities.py` declares the lifecycle seams — open a session,
start a turn, await a result — as one-to-three-method capabilities.
`events.py` holds the shared turn vocabulary: opaque `SessionId`/`TurnId`,
the `TurnBlock` union (`TurnTextBlock`, `TurnThinkingBlock`,
`TurnToolCallBlock`, `TurnToolResultBlock`), and the generic
`TurnRequest[T]`/`TurnResult[T]`.

Everything optional is a decorator or an absent capability, never a flag:
`middleware.py` layers timeouts, budgets, retries, correction, tracing, usage,
and display around a factory; `output.py` binds a fresh `submit_output` tool
and store to each typed turn; `budget.py` and `quota.py` are the two opposite
kinds of "no more work" it applies.

Everything about *which* runtime answers moved out to `providers`, and
everything about running work *over* a session moved out to
`orchestration` — a turn engine that also held routing, profile trees and a
background agent was three subjects sharing one name.

Unsupported behavior is *absent* from the handle rather than present and
raising. If `TurnHandle.steer` is `None`, that backend cannot steer.

### `harness` — declaration to disk

Compiles one provider-neutral declaration into native plugin trees, with a
proof of what it owns. `models.py` holds the declaration graph
(`Harness` → `Plugin` → `Skill`/`Agent`/`HookSet`) and the rendered
`Artifact`/`ArtifactTree`. Prompt bodies are ordered typed parts —
`TextPart` for prose, `SkillInvocation`/`NativePath`/`ArgumentsRef` and their
siblings for anything a runtime spells its own way.

The pipeline is `validation` → `ownership` → `reconciliation` →
`materialization`, plus `proposals` for the reviewed patch transport back to
canonical source and `process`/`environment` for launching a native CLI.
`generation.py` holds the small deterministic helpers the stages share. The
do-not-edit banner every commentable generated artifact opens with is
`lup.banner`, a foundation rather than part of this subject, because the
policy bundle writes one too and a banner reached through the harness made
the two entries import each other.

`codescan/` nests here: the rule engine behind `lup-devtools dev check` and
both generated edit hooks, and it reads this package's declaration models to
judge a portable artifact. `common.py` provides comment-column tokenization,
docstring detection, and ignore-directive parsing; `markers.py` finds
`# lup:` review notes; `antipatterns.py`, `boundaries.py`, `capabilities.py`
and `portable.py` are the rule families; `registry.py` indexes them all into
[rules.md](rules.md). [harness.md](harness.md) walks the whole pipeline.

### `policy` — one decision, two homes

The permission core, split so the same verdict can be reached inside this
library and inside a generated plugin that cannot import it.

`policy/kernel/` is hermetic: stdlib-only, statically audited imports,
primitive rows in and a decision out. It is copied *verbatim* into every
generated tree, which is why a traceback from a hook still points at real
canonical line numbers. Above it, `rules.py` validates application inputs as
Pydantic surfaces and erases them into kernel rows, `chain.py` composes
policies deny-before-ask, and `bundle.py` assembles the kernel source plus
rendered data rows for generation. [permissions.md](permissions.md) is the
full lattice.

### `resolver` — reviewed feedback to an integration branch

A persisted state machine over concerns. `models.py` holds schema-versioned
records; `dag.py` validates and orders the concern graph; `state.py` persists
it atomically under a file lock; `run.py` names the one live state a run
holds, with the lock and the observer that guard it; `orchestrator.py` owns
every git side effect (leases, worktrees, commits, dependency bases);
`mailbox.py` carries questions and answers as files so any door can write
while the run holds its lease. Each phase is a collaborator over those rather
than a method on one class: `questions.py` publishes and promotes,
the `actors` package holds the population and one durable session per member,
`turns.py` puts the prompts
to them, `joins.py` brings branches together and settles what that breaks,
`verification.py` runs one tree through the verification set, and
`execution.py` drives one concern's revision loop. `core.py` composes them
and owns only the sequence. [resolver.md](resolver.md) covers the lifecycle.

### `providers` — the vendor edge

`providers/claude/` and `providers/codex/` each implement the same four seams:
`runtime.py` (open sessions behind the runtime contracts), `harness.py`
(render the declaration into that runtime's tree), `harness_runtime.py`
(probe the installed CLI for evidence), and `native.py` (decode hook payloads
into policy events, render decisions back). `providers/harness.py` composes the
renderers into whole-tree compilers.

Each also carries what only it needs: Claude a personal account registry that
`providers/profile_tree.py` answers with the directories a project keeps instead,
Codex a
typed JSON-RPC transport to `codex app-server`. Neither is mirrored for
symmetry's sake. [platform-differentiation.md](platform-differentiation.md)
is the map of every difference.

### The rest

Every remaining top-level entry, and what makes it one. `types` is tier 1
above and `__init__` is the front door; the rest each answer a question no
sibling answers.

Which entries this table has to cover is walked from the installed `lup`
package when the page is generated — `packages/lup/src/lup` in this repository,
and wherever a downstream project resolved the dependency to. Generation fails
naming any package that is neither described here nor tiered above, so a
package added to the library cannot be quietly missing from its own roster —
the way six of them once were.

| Package | Solves |
| --- | --- |
| `banner` | The one generated-from banner, spelled however a target format admits. Every generated artifact whose format can hold a comment opens with the same sentence: what produced it, the command that rebuilds it, and where the provenance record lives. Only the source, the command, any target-specific notes, and the comment syntax differ, so the wording is written once here and each generator supplies its parameters. A format with no comment syntax, and the two families that deliberately carry no banner, are named by :class:`BannerExemption` so the absence is declared rather than noticed. |
| `channels` | File-backed channels: a value that settles, and an ordered log. The widest dependency in the library: most of its top-level entries write through this one, which is what makes it a package rather than a helper inside any of them. Counted rather than listed, because the list is the thing that falls behind — the roster this paragraph came from named six consumers where the import graph held eleven, and nobody notices a sentence going stale. |
| `client` | The concrete session surface every consumer holds. Top-level rather than under `runtime` because it is what the package root exports and what a reader meets first — a front door reached through a subpackage named for the machinery behind it is the shape that made every example open a session by importing an adapter instead. |
| `devtools` | The development CLI a project built on lup inherits rather than forks. Worktrees and branches, trace and Python introspection, the resolver supervisor, the sync registry, version bookkeeping. Ships the whole roster — `roster.py` wires every sub-app over one `DevtoolsDeclarations`, and an application declares only what it retires and what only it has, so a sub-app added here reaches it on the next lock refresh instead of waiting to be noticed. Requires the `web` extra for the supervisor. |
| `execution` | What carrying work out runs into, and what to do about each of it. The retry and the throttle a flaky or rate-limited service is met with, the executor a blocking call is handed to so work in flight outlives any one loop&#x27;s teardown, and whether a path can be written at all — or whether a boundary owns it and something merely died holding a lock. |
| `markdown` | The cells a generated Markdown table is laid out from. Rendering Markdown that is generated rather than authored, escaping at the leaf where data enters the document. Only `devtools` renders such tables today, but nothing in it is about development tooling. |
| `observability` | What happened, recorded so that a later reader can answer for it. One subject that used to be four top-level entries answering the same reader question. The ordered record file every durable log appends to; the lossless hash-chained audit stream a session writes as it runs; the compact markdown trace and its sidecar a later reader skims to find a session worth opening; the console display; the per-tool metrics; the replay divergence check; the per-turn cost arithmetic; and the account-level metered usage. What separates them is what each is kept *for* — evidence, navigation, or a bill — and never the mechanism, which they share. |
| `orchestration` | Running more than one piece of work, and staying able to speak to it. A cohort of addressable held sessions with mail that lands in front of each one&#x27;s next tool call; a background agent that coalesces wakes into turns; a scheduler and relay for work that sleeps; durable out-of-process jobs; the review gates a turn passes through; and spec-driven delegation for runtimes whose own subagents will not do. |
| `sandbox` | Docker-based Python sandbox, split by concern. A Docker-isolated Python REPL — mount topology, container lifecycle, and the exec-multiplexed socket protocol. Requires the `docker` extra. |
| `tables` | Taking a library table as offered, and saying only what differs from it. Three tables reach a project as a starting point rather than a fixture — the anti-patterns it holds its code to, the shell vocabulary it runs, the edit gates it judges its own changes by — and in all three the only way to disagree with one entry was to restate the table around it, where a restatement fallen behind the library looks exactly like a decision. A project names what it drops and adds what the library lacks, keyed on the same id a directive, a denial and the generated reference already use, so an override replaces its namesake in place rather than sitting beside it. |
| `tools` | What an agent is given to act with, and what decides which of it it gets. The tool decorator and server surface, the conditional availability policy, the URL routing that sends a fetch to the tool that may serve it, and the LSP-backed code intelligence the agent tools are built on. One subject: the instruments, not the work done with them. |
| `web` | Local web surfaces: the boundaries a page served on this machine keeps. What a page served on this machine does to stay local-only: the loopback bind refusal, the `Host` check that DNS rebinding would otherwise walk past, and the browser round-trip an installed OAuth client needs. One subject — a local HTTP surface a browser reaches — and the OAuth half is reached by a downstream project rather than by anything here, which is the outward test answering in the affirmative. The two user-facing pages, `devtools/dashboard` and `devtools/supervisor`, sit *on* this; it does not belong beside them. |
| `workspace` | Session workspace: where a run&#x27;s data lives and how it is addressed. Where a run&#x27;s data lives: version-aware paths, the `SessionContext` that crosses a process boundary, session history, and the note directories a session may touch. |

### What is left to place

The roster above is where the tree stands and, with one exception, where the
three questions put it. The exception is `resolver`, whose home is
`lup/harness/resolver/`: its only driver is `lup.devtools.harness.resolve`,
so it is part of the harness subject rather than a sibling of it, and the
downward question stops it at the library edge — following the driver into
`devtools/` would move provider-neutral code into the tooling layer.

Thirty-four top-level entries became these by asking, of each one, which of
the four kinds it is: a foundation that imports nothing here, a subject, the
one vendor boundary, or tooling. Five two-way edges between entries survive
that, and each is a placement question still open rather than an accident:

| pair | what closes the loop |
|---|---|
| `client` ↔ `providers` | the front door's routing constructor reaches both providers, lazily, inside `create_client` |
| `client` ↔ `sessions` | six session modules hold a `Client`, and the front door reads the turn vocabulary |
| `devtools` ↔ `harness` | three utilities the library needs — `git`, the clipboard probes, a launcher's default environment — live under the tooling half |
| `devtools` ↔ `sandbox` | the same `git`, reached from the container's mount rail |
| `harness` ↔ `policy` | the edit gate reads the anti-pattern table, which reads this package's declaration models |

The last three all have one shape: a symbol two subjects share, sitting inside
one of them. Each closes by moving that symbol below both, which is what
`lup.banner` already did for the do-not-edit banner the policy bundle and the
harness both write. The first two are the front door deliberately knowing
about what it opens; whether a lazily-imported provider counts as an edge at
all is the question to answer before an acyclicity check is written, and
answering it by choosing a walker that does not look inside a function would
be hiding it rather than settling it.

Acting on one of these answers is a command rather than an afternoon.
`uv run lup-devtools dev relocate old.module=new.module` repoints every import
of what moved, locating each module path by Python's own grammar rather than
by pattern, and reports the mentions it deliberately did not touch — a log
line, a docstring naming the old home — for a human to read. That the
mechanical half is cheap is what keeps the placement question answerable
instead of perpetually deferred.

`usage/` and the `usage/` beside each adapter are worth naming next to it as
the placement rule worked all the way through. What an account publishes is
the only thing that differs between runtimes — which windows it meters,
whether it splits a day's tokens by model — so that is what stays at the
vendor edge, and the report shape, the pacing bars and the rendering are
decided once above it. Neither reader carries a command of its own: each
declares an entry, and an application composes the ones it wants, so no Typer
app sits under `providers/` and nothing above `devtools/` imports one.

The outward question also runs the other way, and `dev check` asks it on every
run: the `application placement` row names each module under the application's
`devtools/` that imports nothing from the application. It reports rather than
fails, because the template is copied and frozen the moment an adopter takes
it while `packages/lup` reaches them through an ordinary dependency bump — so
the row is a debt that shrinks, and this is where its verdicts are settled
rather than a list kept somewhere else. Two modules answer it today.
`devtools/setup.py` is where it belongs: this project's own integrations
written as data, which is exactly what importing nothing looks like when a
module is this project's judgement. `devtools/dev/library.py` is not — how a
project obtains lup, across the published, git, local, and linked modes, is a
question every adopter has and none of it is about this application, so its
home is `lup/devtools/dev/`.

## Building on it

The library is the dependency; your application is the composition root. That
inversion is the whole design, and it has three practical consequences.

**Name the provider exactly once.** Choose an adapter factory in one function,
pass the resulting `Client` everywhere else. `seam-boundary` will tell
you when a second site appears.

**Compose capabilities rather than configuring an object.** Timeouts, budgets,
retries, persistence, and tracing are `DecoratingSessionFactory` layers you
add individually, not fields on a client.

**Let typed output be the only output.** Bind a Pydantic type to the turn and
read `TurnResult.output`. A missing submission raises a typed error carrying
the blocks, usage, duration, and validation history — it cannot arrive as an
empty success.

`src/lup_template` is the worked example of all three; see
[template.md](template.md).
