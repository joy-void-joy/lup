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
   `lup.formats` is how a compiled artifact has to be spelled to survive being
   one, the do-not-edit banner and the escaping of a derived table's cells;
   `lup.seams` and `lup.execution` are the rest. Burying one of these inside a
   subject is what manufactures a cycle — folding `channels` in with
   `workspace` did exactly that and was undone. Gathering two of them under a
   question they share does not, and cannot: a package holding only leaves has
   no outgoing edge to close a loop with.
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
library never imports the application: a utility left in {{ project_directory }}
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
`lup.formats.banner`, a foundation rather than part of this subject, because the
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

Every remaining top-level entry, and what makes it one. `__init__` is the
front door, and six more are described at length above instead —
{{ library_described }} — so the rest each answer a question no sibling
answers.

Which entries this table has to cover is walked from the installed `lup`
package when the page is generated — {{ subtree }} in this repository,
and wherever a downstream project resolved the dependency to. Generation fails
naming any package that is neither described here nor tiered above, so a
package added to the library cannot be quietly missing from its own roster —
the way six of them once were.

