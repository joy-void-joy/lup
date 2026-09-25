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
    Claude,           # a Claude Code agent, declared whole; it opens its sessions
    Codex,            # a Codex agent, declared whole; it opens its threads
    Agent,            # what either declaration answers, for code naming neither
    Conversation,     # an open session of either
    Turn,             # one turn of either: awaitable, iterable over its blocks
    TurnResult,       # a validated, typed result
    TurnInput,        # portable user input
    TurnMessage,      # one message of a conversation's history
    SessionId,        # the provider's identity for a conversation; resumes it
    SessionSummary,   # one conversation the provider has on record
    TurnId,           # the provider's identity for one turn; a fork is cut at it
    CustomModel,      # a model id outside the runtime's catalog, on purpose
    NativeToolGroup,  # explicit groups of built-in tool authority
)
```

The shortest useful program imports and declares everything it uses:

```python
import asyncio

from pydantic import BaseModel

from lup import Claude


class Summary(BaseModel):
    summary: str


async def main() -> None:
    agent = Claude(model="opus", system_prompt="Be concise.")
    result = await agent.ask("Summarize why typed boundaries help.", Summary)
    print(result.output.summary)


asyncio.run(main())
```

`Claude` and `Codex` are why the root is worth importing. Each is a frozen
Pydantic model declaring one agent whole — model, prompt, tools, permissions,
workspace, and the layers its sessions are wrapped in — and each is also what
opens those sessions: there is no client to build from a declaration.
Everything else here is vocabulary, a name to annotate against, and vocabulary
alone builds nothing: the typed result is a Pydantic model the program
declares itself.

### Asking

`ask` is the only verb. On an agent it is a one-shot: `agent.ask(prompt,
Model)` opens a session, takes one turn, closes the session however the turn
ended, and returns `TurnResult[Model]`; asked without a model it returns
`TurnResult[None]`. For more than one turn, open a session and ask it:

```python
from pydantic import BaseModel

from lup import Claude


class Plan(BaseModel):
    steps: list[str]


async def plan(agent: Claude) -> Plan:
    async with agent.open() as session:
        await session.ask("Draft a plan for the migration.")
        turn = session.ask("Now give that plan as steps.", Plan)
        async for block in turn:
            if (text := block.text_payload) is not None:
                print(text)
        result = await turn
        return result.output
```

A turn starts the first time anything asks for it — an `await`, an iteration,
`events()`, `live()`, `interrupt()`, or on Codex `steer()` — and starts once
however many ask; awaiting it after iterating returns the same result. Its
submission tool is bound to the output model before the provider accepts the
prompt, so no turn runs ahead of the schema it has to answer in.

| Ask the turn | For |
| --- | --- |
| `await turn` | The `TurnResult[T]`: `output`, `blocks`, `messages`, `usage`, `duration`, `identifiers` |
| `async for block in turn` | Each completed block, in the order they finished |
| `turn.events()` | Every durable event: turn and block starts, block and message completions, the turn's end |
| `turn.live()` | The durable events and the deltas between them |
| `await turn.interrupt()` | Stop the turn, returning once it has stopped |
| `await turn.steer(prompt)` | Add input to the running turn without starting another — `CodexTurn` only |

`live()` on a Claude agent declared with `delta_streaming=False` raises
`DeltaStreamingDisabled` rather than yielding a turn that only looks quiet.

A capability a provider lacks is absent from its type, never present and
`None`: `ClaudeTurn` has no `steer`, because Claude takes no input into a
running turn, so the call fails in the type checker rather than at run time.
`ClaudeSession`, `ClaudeTurn`, `CodexSession`, and `CodexTurn` are named from
`lup.providers.claude` and `lup.providers.codex`, each of which holds every
part of its provider a program writes. Code that works over either provider
names the `Agent`, `Conversation`, and `Turn` protocols instead, and asks
only for what both answer.

### Conversations outlive the process

`session.id` is the provider's own identity for a conversation, and it
resumes it. `agent.sessions()` lists what the provider has on record for the
agent's workspace, newest first — conversations a terminal started as well as
the ones this library did:

```python
from lup import Codex


async def last_conversation(agent: Codex) -> None:
    past = await agent.sessions()
    async with agent.open(resume=past[0].id) as session:
        for message in await session.history():
            texts = [text for block in message.blocks if (text := block.text_payload)]
            print(message.role, texts)
```

`history()` reads the provider's own record — Claude Code's transcripts,
Codex's thread — normalized into the same `TurnMessage` and block types a turn
yields. `session.fork(at=result.identifiers.turn)` opens an independent
conversation carrying this one's history through that turn, or everything so
far with `at` unset; nothing asked of either reaches the other.

### Models and effort

`model` takes a name from the runtime's own catalog, a `Literal`, so a typo
fails in the type checker; a portable tier — `frontier`, `strongest`,
`balanced`, `fast` — that each adapter spells in its own lineup; or
`CustomModel(id=...)` for an id the catalog does not list, such as a
compatible endpoint's own model. `effort` climbs `low`, `medium`, `high`,
`xhigh`, `max`, `ultra`, and an effort the catalog says the model cannot take
is refused where the agent is declared rather than dropped by the CLI.

A caller holding nothing but a model id asks `catalog_provider(model)`
(`lup.providers.routing`) which runtime's catalog lists it, then declares that
agent: dispatch cannot carry typed provider options, so it answers the
question and leaves the declaration to the caller.

Both declarations resolve on first access, so `import lup` pulls neither
adapter nor either provider SDK. Naming `Claude` or `Codex` imports its
adapter — several hundred modules, the MCP tooling its tools are declared in —
and still no SDK: opening a session is what finally loads Claude's SDK or
starts Codex's app-server.

## Native tools

`native_tools` defaults to `None` on `Claude`, `Codex`, and `SessionRequest`.
`None` and an empty sequence grant no
built-in tools and inherit no ambient tool inventory. A caller opts in with
`NativeToolGroup` values or exact names supported by its provider:

```python
from lup import Claude, Codex, NativeToolGroup

reader = Claude(native_tools=[NativeToolGroup.READ])
executor = Codex(native_tools=[NativeToolGroup.SHELL])
```

The groups are `READ`, `WEB`, `WRITE`, `SHELL`, and `ALL`. `ALL` explicitly
grants the runtime's broad built-in inventory; it does not promise every
experimental facility or grant ambient application integrations. Groups
compose, and unknown or unenforceable grants fail before a session starts.
Permission patterns such as `Bash(*)` are not native tool identities.

| Grant | Claude | Codex |
|---|---|---|
| `NativeToolGroup.READ` | `Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch` | Rejected: reading through a shell would grant execution |
| `NativeToolGroup.WEB` | `WebFetch`, `WebSearch` | Native web search |
| `NativeToolGroup.WRITE` | `Write`, `Edit`, `NotebookEdit` | Patch application |
| `NativeToolGroup.SHELL` | `Bash`, `TaskOutput`, `TaskStop` | Shell execution |
| Exact names | Includes `Read`, `WebFetch`, `Write`, `Bash` | `Bash`, `WebSearch`, `apply_patch`; `Read`, `Write`, and `WebFetch` are rejected |

The declaration's `tools=[...]` field supplies application `@lup_tool`
handlers independently. Those handlers still work with `native_tools=None`:
Claude hosts them through MCP, and Codex dispatches them through its in-process
dynamic-tool handlers. `tool_servers` on `Claude` and `mcp_servers` on `Codex`
remain the explicit MCP-server declarations. Typed output remains available
with no native tools. On `Claude`, `allowed_tools` controls automatic approval
within the declared authority and `disallowed_tools` narrows it; neither adds
an undeclared tool.

Explicit session hooks remain attached when native tools are granted. Codex
enables the verified declared project policy plugin for an explicit native grant while keeping
unrelated inherited plugins disabled. Provider settings and extra arguments
that could widen the requested authority are rejected, including altered
copies of validated configurations.

Codex requires the selected model to appear in its native model catalog so
the adapter can bound the tool metadata attached to model requests. An unknown
explicit or inherited model is rejected before input.

A Codex thread's application tools are fixed at thread creation. Resume
requires the same set; native grants may narrow on resume. Start a fresh
session when application tools require another dynamic binding. The adapter
rejects an incompatible resume before sending user input. Typed output does
not ride that channel — each turn carries its own `outputSchema` — so the
model a turn is asked for may change from one turn to the next.

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

The engine. `surface.py` declares what a program holds over either provider:
the `Agent`, `Conversation`, and `Turn` protocols. `capabilities.py` declares
the seams beneath them — start a turn, resolve it, stream its events,
interrupt, steer, fork, read the provider's record — as one-to-three-method
capabilities, and `turns.py` holds the turn that starts itself through them
the first time anything asks. `events.py` holds the shared turn vocabulary:
opaque `SessionId`/`TurnId`, the `TurnBlock` union (`TurnTextBlock`,
`TurnThinkingBlock`, `TurnToolCallBlock`, `TurnToolResultBlock`,
`TurnNativeActivityBlock`), `TurnMessage`, `SessionSummary`, and the generic
`TurnResult[T]`.

Everything optional is a layer or an absent capability, never a flag:
`middleware.py` holds the turn decorators — timeouts, budgets, retries,
correction, tracing, usage, and display — and `layers.py` the `SessionLayers`
an agent declares them in, beside the session wrappers that go around them;
`output.py` binds a fresh `submit_output` tool and store to each typed turn;
`budget.py` and `quota.py` are the two opposite kinds of "no more work" it
applies.

Everything about *which* runtime answers moved out to `providers`, and
everything about running work *over* a session moved out to
`orchestration` — a turn engine that also held routing, profile trees and a
background agent was three subjects sharing one name.

Unsupported behavior is *absent* from a provider's type rather than present
and raising: `CodexTurn` has `steer`, and `ClaudeTurn` has no such method.

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
`mailbox.py` binds `lup.coordination.mailbox`, which carries questions and
answers as files so any door can write while the run holds its lease, to the
resolver's own question type. Each phase is a collaborator over those rather
than a method on one class: `questions.py` publishes and promotes; the
population is `lup.coordination.cohort`, holding one durable session per
member through `lup.coordination.sessions`; `turns.py` puts the prompts
to them, `joins.py` brings branches together and settles what that breaks,
`verification.py` runs one tree through the verification set, and
`execution.py` drives one concern's revision loop. `core.py` composes them
and owns only the sequence. [resolver.md](resolver.md) covers the lifecycle.

### `providers` — the vendor edge

`providers/claude/` and `providers/codex/` each hold, in the package itself,
everything a program writes with that provider — the `Claude` or `Codex`
declaration, its session and turn classes, and the vocabulary they take — so
a program names nothing deeper. Behind that each implements the same four seams:
`runtime.py` (open sessions behind the runtime contracts), `harness.py`
(render the declaration into that runtime's tree), `harness_runtime.py`
(probe the installed CLI for evidence), and `native.py` (decode hook payloads
into policy events, render decisions back). `providers/harness.py` composes the
renderers into whole-tree compilers.

Each also carries what only it needs: Claude a personal account registry that
`providers/profile_tree.py` answers with the directories a project keeps instead,
and a reader of the transcripts Claude Code keeps, which `history()` and
`sessions()` answer from; Codex a typed JSON-RPC transport to
`codex app-server`, which answers both itself. Neither is mirrored for
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


<!-- passage: what-is-left-to-place -->

### What is left to place

The roster above is where the tree stands, and where the three questions put
it. Thirty-four top-level entries became these by asking, of each one, which
of the four kinds it is: a foundation that imports nothing here, a subject,
the one vendor boundary, or tooling.

`resolver` is the entry the downward question is hardest on, because
everything that drives it is tooling: {{ resolver_readers }} modules under
`devtools/` read its journal, its state repository, its question mailbox and
its lease table. What keeps it a sibling of the subjects rather than a package
inside one is what it imports. Of its import lines, {{ coordination_reach }}
reach `coordination`, where its actors, their durable sessions and the shared
question mailbox live, and {{ harness_reach }} reach `harness`, so neither
subject contains it, and what it answers — reviewed concerns driven over a DAG
of branches, each on its own branch in a leased worktree — is a question
neither of them answers.

Ten two-way edges between entries survive the sort. Nine are placement
questions still open; the tenth is the shape of a guarantee.

| pair | what closes the loop |
|---|---|
| `tools` ↔ `coordination` | `tools/toolsets.py`, the registry every tool group is assembled from, reaches coordination's wake path and its peer and relay tools, which coordination declares in `tools.mcp`'s vocabulary |
| `tools` ↔ `ledger` | the same registry reaches the ledger's models, store and tools, which the ledger declares in `tools.mcp` |
| `tools` ↔ `orchestration` | the same registry reaches the review gate and the realtime relay, which declare their tools in `tools.mcp` |
| `tools` ↔ `sandbox` | the same registry reaches the container, which declares its tools in `tools.mcp` |
| `tools` ↔ `devtools` | the same registry reaches the Pyright oracle's language-server lookup under the tooling half, lazily, inside the code-intelligence group; the oracle and the resolver's command glue read `tools.lsp`, `tools.mcp` and `tools.native` back |
| `devtools` ↔ `harness` | utilities the library needs live under the tooling half — the clipboard probes, a launcher's default environment, `gh`, the sub-app roster, and the report and upstream-report models two pages render |
| `coordination` ↔ `ledger` | the ledger names who acted by coordination's `ActorRef` and member identity and renders its tasks, while coordination's hand-offs, delegations and tasks are ledger records written through `LedgerStore` |
| `coordination` ↔ `observability` | the cohort and its durable sessions write `observability`'s journal, whose session record names its actor by coordination's `ActorRef` |
| `observability` ↔ `workspace` | the sweep walks `workspace`'s run history and parses its timestamps, and that history and the notes are built from `observability`'s session recorder and metrics |

The first five have one shape: a registry sitting in the package that
everything it registers already imports. Every tool group is declared in
`tools.mcp`'s vocabulary, and `tools/toolsets.py` assembles them all, so the
edge closes by moving the assembly above what it assembles. The last four have
the shape the do-not-edit banner had: vocabulary both sides speak — an actor
reference, a journal record, a history reader, a clipboard probe — sitting
inside one of them, which closes by moving it below both, as
`lup.formats.banner` already did for the banner the policy bundle and harness
both write. `tools` ↔ `devtools` also carries the question the rest of the
table assumes an answer to: its one import back is deferred inside a function,
and whether a deferred import counts as an edge at all is the question to
answer before an acyclicity check is written — answering it by choosing a
walker that does not look inside a function would be hiding it rather than
settling it.

`harness` ↔ `policy` is the one that stays, because breaking it would break
what `policy` is for. Of `codescan`'s modules, {{ edit_readers }} read `policy.kernel.edit`
— the tokenizer, the AST walkers, and the match-site finders that the
compiled hook script carries — and `policy` reads `codescan`'s anti-pattern
table back. That is not an accident of where the utilities happened to be
written. This package exists to decide identically in two homes, the compiled
hook and `dev check`, and one shared reading of the source is how the two are
held to the same answer. Cutting the edge would mean two implementations of
that reading, drifting apart on exactly the cases nobody thought to test —
which is the failure the package was built to prevent, reintroduced for the
sake of a tidier graph.

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
rather than a list kept somewhere else. It names nothing today, which is the
shape this debt is meant to reach: how a project obtains lup is a question
every adopter has and no part of which is about any one application, so it
lives at `lup/devtools/dev/library.py` where `dev update` reads the pin it
writes. The row is read rather than trusted — a module that reaches the
application, as `devtools/setup.py` does for its own harness composition,
leaves it by doing so rather than by being argued about here.

## Building on it

The library is the dependency; your application is the composition root. That
inversion is the whole design, and it has three practical consequences.

**Name the provider exactly once.** Declare the agent — `Claude(...)` or
`Codex(...)` — in one function, and hand it everywhere else as an `Agent`, so
the code that asks it works unchanged when the declaration changes provider.
`seam-boundary` refuses an import of `lup.providers.claude` or
`lup.providers.codex` outside a composition root, which keeps a provider's
own parts where it is named.

**Declare layers rather than wrapping by hand.** Timeouts, budgets, retries,
correction, persistence, and tracing are whole-turn decorators, each taking
its own config; an agent lists them in its `layers`, and every session it
opens is wrapped in them in the library's one stated order:

```python
from lup import Claude
from lup.sessions.layers import SessionLayers
from lup.sessions.middleware import RecoveryConfig, TimeoutConfig

agent = Claude(
    model="strongest",
    layers=SessionLayers(
        timeout=TimeoutConfig(seconds=600), recovery=RecoveryConfig(retries=2)
    ),
)
```

Code holding an agent it did not declare lays more on with
`agent.layered(SessionLayers(...))`, the fields it sets winning, without
knowing which provider it holds.

**Let typed output be the only output.** Pass a Pydantic model to `ask` and
read `TurnResult.output`. A missing submission raises a typed error carrying
the blocks, usage, duration, and validation history — it cannot arrive as an
empty success.

{{ value }} is the worked example of all three; see
[template.md](template.md).
