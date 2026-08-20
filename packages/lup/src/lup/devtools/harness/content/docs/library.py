"""Guide to ``packages/lup``, the reusable provider-neutral library.

The per-package roster below is authored prose keyed by a walked set. What
each package solves is a judgement no walk can make, so it stays written; but
*which* packages there are to describe is the tree's to answer, and asking it
is what closes the gap this page had — a roster promising "every remaining
top-level entry" while silently omitting six of them, `actors` among them
four commits after it was added.
"""

from pathlib import Path

from pydantic import BaseModel

import lup.harness.models as models
from lup.devtools.harness.content.application import ApplicationLayout
from lup.devtools.harness.content.tree import top_level_names
from lup.markdown import CodeCell, PlainCell


class RosterEntry(BaseModel, frozen=True):
    """One top-level entry, and the authored answer to why it is one."""

    package: str
    solves: str


class TieredEntry(BaseModel, frozen=True):
    """One entry a section above the roster already describes, and which one.

    Carried rather than inferred: a package earns a section of its own by
    being load-bearing enough to need one, which is a judgement. Naming the
    section is what lets a roster failure point *there* rather than only say
    "not in the table".
    """

    package: str
    section: str


class Roster(BaseModel, frozen=True):
    """A package roster, and the tree it must agree with.

    Every judgement here is a field default rather than a module constant, so
    a project describing its own library replaces the values instead of
    forking the check that reads them.
    """

    entries: list[RosterEntry]

    subtree: str = "packages/lup/src/lup"
    """Where the package this describes lives, relative to a checkout."""

    tiered: list[TieredEntry] = [
        TieredEntry(package="types", section="tier 1"),
        TieredEntry(package="adapters", section="the adapter tier"),
        TieredEntry(package="harness", section="the harness tier"),
        TieredEntry(package="runtime", section="the runtime tier"),
        TieredEntry(package="policy", section="the policy tier"),
        TieredEntry(package="codescan", section="the policy tier"),
        TieredEntry(package="resolver", section="the target layout"),
    ]
    """Entries a section above the roster describes at length instead."""

    def owed(self, root: Path) -> list[str]:
        """Every entry beneath ``subtree`` that this roster has to describe."""
        elsewhere = {entry.package: entry.section for entry in self.tiered}
        return [
            name
            for name in top_level_names(root, self.subtree)
            if name not in elsewhere
        ]

    def table(self, root: Path) -> models.MarkdownTable:
        """The roster as a table, refusing any disagreement with the tree.

        Raises rather than rendering a partial roster: a page that quietly
        drops a package reads exactly like a complete one, which is the whole
        difficulty. Generation fails loudly instead, naming what to write or
        what to delete.
        """
        owed = self.owed(root)
        described = {entry.package: entry.solves for entry in self.entries}
        if missing := [name for name in owed if name not in described]:
            raise ValueError(
                f"{self.subtree} carries {missing}, which this page neither "
                "tiers nor describes: write a row saying what each solves"
            )
        if vanished := [name for name in described if name not in owed]:
            raise ValueError(
                f"the roster describes {vanished}, which {self.subtree} no "
                "longer carries: delete those rows"
            )
        return models.MarkdownTable(
            headers=["Package", "Solves"],
            rows=[
                [CodeCell(text=entry.package), PlainCell(text=entry.solves)]
                for entry in self.entries
            ],
        )


ROSTER = [
    RosterEntry(
        package="devtools",
        solves="The development CLI an adopter inherits rather than forks: worktrees and branches, trace and Python introspection, the resolver supervisor, the sync registry, version bookkeeping. Ships the whole roster — `roster.py` wires every sub-app over one `DevtoolsDeclarations`, and an application declares only what it retires and what only it has, so a sub-app added here reaches it on the next lock refresh instead of waiting to be noticed. Requires the `web` extra for the supervisor.",
    ),
    RosterEntry(
        package="channels",
        solves="File-backed channels — a value that settles, an ordered log, and the atomic publish under both. The widest dependency here: `harness`, `resolver`, `runtime`, `realtime`, `telemetry`, and `adapters` all write through it, which is what makes it a package rather than a helper inside any one of them.",
    ),
    RosterEntry(
        package="journal",
        solves="One ordered record file, sequenced and durably appended, read back from a byte offset or a sequence number and paged backwards from either. Two products ride it — the resolver's typed decision log and the observable transcript's hash-chained provider payloads — and neither collapses into the other. Sharing the mechanism is what lets any reader tail either record the same way, and what stops the next thing needing a record from arriving with a third implementation.",
    ),
    RosterEntry(
        package="codeintel",
        solves="An LSP client and the tools built on it, so a name is resolved rather than grepped. Serves an agent's toolset and the pyright oracle behind `dev check` — two consumers on opposite sides of the library, neither of which owns it.",
    ),
    RosterEntry(
        package="gitlocks",
        solves="Why git cannot take the lock its config writes need. A confinement owning the path and a lock some git left behind when it died both surface as `File exists`, and the remedies are opposite, so telling them apart reads the mount state and the lock's age rather than the message. The same two-consumers shape as `codeintel`: the resolver's orchestrator and `devtools/utils` both diagnose it, and neither owns it.",
    ),
    RosterEntry(
        package="gitguard",
        solves="Catching a suite that wrote into the checkout it was running inside. A test that forgets to bind git to its throwaway repository inherits the process working directory instead, and nothing fails — git finds a repository, commits succeed, and the suite passes green while the developer's branch has moved. Found the slow way, by a `dev pr sync-base` merging a `dev` whose tip had become a fixture's commit deleting the application source. The suite cannot be trusted to notice, because noticing is exactly what it failed at, so the refs are read around it.",
    ),
    RosterEntry(
        package="actors",
        solves="Addressable agents: one held session each, reachable while they work. An agent opened for a single turn and closed cannot be talked to, because there is nothing to talk to between the call and the result. An actor holds its session across turns, takes mail mid-turn through a hook it never chooses to check, and asks questions that settle without stalling the asker. Nothing here knows what the actors are for — the resolver names its own kinds over this mechanism, and a research session names different ones.",
    ),
    RosterEntry(
        package="jobs",
        solves="Durable containerized work that outlives the process that submitted it. A sandbox cell runs inside the caller's process, so the agent waits and a crash takes the work with it; a job is submitted, left running, and asked about later — possibly by a process started after that crash. Everything durable is on the filesystem, and the scheduler's atomically-replaced view is deliberately separate from the terminal result the container writes, so a job cannot forge its own completion.",
    ),
    RosterEntry(
        package="replay",
        solves="A durable journal of executed cells and the divergence check on replaying one: state is reconstructed by re-running the record rather than by serializing objects. What differs between users is the contract attached. An environment claiming determinism says a replay must reproduce its outcomes, so a divergence there is a defect in a claim; an environment claiming nothing still gets the report, and there the divergence *is* the finding — the result depended on something outside the journal. Both are replayable; only the first is certifiable.",
    ),
    RosterEntry(
        package="subagents",
        solves="Spec-driven delegation for engines with no native subagents, dispatching the same `SubagentSpec` roster the native path uses.",
    ),
    RosterEntry(
        package="tool_policy",
        solves="Tool-availability filtering: the mechanism, not the policy. A project subclasses `BaseToolPolicy` and maps its own settings onto it, which is the placement rule in miniature — the machinery is the library's, every exclusion is the adopter's.",
    ),
    RosterEntry(
        package="tool_routes",
        solves="Which tool answers a URL better than fetching it would. Behind a prediction-market URL is a market tool and behind a paper URL is a paper tool, and the rendered page is a poorer answer than either API. This is the table that says so — a URL shape, the tool it stands for, and how to build that tool's arguments from what the shape matched. The same placement split as `tool_policy`: the matching and dispatch are the library's, the table's content belongs to the only thing that knows its own tools.",
    ),
    RosterEntry(
        package="markdown",
        solves="Rendering Markdown that is generated rather than authored, escaping at the leaf where data enters the document. Only `devtools` renders such tables today, but nothing in it is about development tooling.",
    ),
    RosterEntry(
        package="web",
        solves="What a page served on this machine does to stay local-only: the loopback bind refusal, the `Host` check that DNS rebinding would otherwise walk past, and the browser round-trip an installed OAuth client needs. One subject — a local HTTP surface a browser reaches — and the OAuth half is reached by a downstream project rather than by anything here, which is the outward test answering in the affirmative. The two user-facing pages, `devtools/dashboard` and `devtools/supervisor`, sit *on* this; it does not belong beside them.",
    ),
    RosterEntry(
        package="workspace",
        solves="Where a run's data lives: version-aware paths, the `SessionContext` that crosses a process boundary, session history, and the note directories a session may touch.",
    ),
    RosterEntry(
        package="realtime",
        solves="The wake/act/sleep lifecycle for persistent agents. `scheduler.py` stands alone; `relay.py` layers a subprocess mailbox transport on top and is never imported by it.",
    ),
    RosterEntry(
        package="telemetry",
        solves="What a run records about itself: markdown trace plus machine-readable sidecar, console rendering, per-tool metrics with a file-backed flush for subprocess tools.",
    ),
    RosterEntry(
        package="usage",
        solves="One account's metered usage, whichever runtime billed it: the windows a plan meters and when each clears, where the tokens went day by day, and the display that draws both. Ships no roster — each adapter declares the entry that reads its own runtime into this shape, so a runtime joins the display by being read rather than by growing a command beside it.",
    ),
    RosterEntry(
        package="sandbox",
        solves="A Docker-isolated Python REPL — mount topology, container lifecycle, and the exec-multiplexed socket protocol. Requires the `docker` extra.",
    ),
    RosterEntry(
        package="resilience",
        solves="`throttle` bounds concurrency and minimum call interval; `retry` re-runs a coroutine with exponential backoff.",
    ),
    RosterEntry(
        package="hooks",
        solves="SDK-agnostic hook models and factories: permission hooks, tool allowlists, gates, nudges, capture.",
    ),
    RosterEntry(
        package="mcp",
        solves="The `lup_tool` decorator and `create_mcp_server`, with typed input models and error propagation that actually reaches the caller.",
    ),
    RosterEntry(
        package="reflect",
        solves="Reflect-before-output gates: a flag-based `ReflectionGate` and a verdict-aware `ReviewGate`.",
    ),
]
"""What each remaining top-level entry solves, in the order the page reads them.

Authored rather than walked, because "what makes this a package" is a
judgement. Which entries need one is not: :func:`roster_table` walks the tree
and refuses to render a roster that has drifted from it in either direction.
"""


LIBRARY = Roster(entries=ROSTER)
"""This library's own roster, checked against this library's own tree."""


def document(layout: ApplicationLayout, root: Path) -> models.PromptDocument:
    """The library guide, naming the application half by its own name.

    Takes the checkout rather than finding one, for the same reason the
    template page does: a document that resolved its own root would read the
    filesystem at import, which makes importing this module — and so every
    CLI command that composes it — fail anywhere but inside a lup project.
    """
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=rf"""# The lup library

`packages/lup` is the reusable half of this repository: a standalone published
package that knows how to run an agent turn, compile a harness, decide a
permission, and resolve reviewed feedback — without knowing which vendor is
behind any of it. It is the larger of the two code components and the one a
downstream project depends on.

The rule that shapes every module: **shared code never names a provider.**
Native config, hook payloads, command spellings, manifests, and wire schemas
live inside `lup/adapters/`. Everything above the adapters speaks contracts.
A third backend implements those contracts without editing a shared registry,
because there is no registry to edit.

## The front door

`packages/lup/src/lup/__init__.py` re-exports a deliberately small runtime
surface — the one place in the library where a barrel is allowed, because it
declares a public API:

```python
from lup import (
    SessionFactory,   # open configured conversations
    SessionHandle,    # an opened session, plus optional fork capability
    TurnHandle,       # an accepted turn, plus optional events/interrupt/steer
    TurnInput,        # portable user input
    TurnRequest,      # what to run, and the type to come back
    TurnResult,       # a validated, typed result
    turn_request,     # request factory
    query,            # one-shot: factory in, typed result out
)
```

The shortest useful program is one call:

```python
factory = create_claude_session_factory(ClaudeSessionConfig(model="..."))
result = await query(factory, turn_request(TurnInput(text="summarize"), Summary))
summary = result.output
```

`query` is the one-shot convenience. For anything with more than one turn, open
a session and start turns on it — the same contracts, held longer.

## Layering

Four tiers, and imports only ever point downward.

1. **`lup.types`** — the portable content and tool vocabulary every other
   package speaks: `JsonValue`/`JsonObject`, `ToolName`/`ToolGrant`,
   `LupContentBlock`, `LupMessage`, `Usage`, `SubagentSpec`.
2. **`contracts` and `models`** — each subpackage carries both. `models` owns
   the vocabulary; `contracts` owns the narrow capability seams. Contracts
   import types only, so a fake implementation needs nothing else.
3. **Implementations** — composition, wrappers, validation, reconciliation,
   rule evaluation. These import their own package's contracts and models, and
   nothing from `adapters`.
4. **`lup.adapters.claude` / `lup.adapters.codex`** — the only packages that
   name a vendor. They implement the contracts above and are imported only by
   named composition roots.

`lup.codescan.boundaries` enforces tier 4 mechanically with the
`seam-boundary` rule: a concrete adapter import outside `lup/adapters/`,
the tests, the examples, or a named application composition root is a
build failure, not a review comment.

## Where a module belongs

Three questions place every module, and they point in different directions.

**Outward — would another project built on lup want this?** If yes it belongs
in `packages/lup/` even when only this application uses it today, because the
library never imports the application: a utility left in `{layout.directory()}`
is unreachable from here and has to move later. The same test applies to
values. The library may declare one only when it could not have chosen
otherwise — a language's file suffixes, a provider's wire spelling, a closed
enum the library itself defines. Everything else is a judgement, and reaches
an adopter as an overridable default they replace rather than a constant they
fork. `library-default` in `lup.codescan.boundaries` is the mechanical half of
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

### `runtime` — how one turn runs

The engine. `contracts.py` declares the lifecycle seams — open a session,
start a turn, await a result — as one-to-three-method capabilities.
`models.py` holds the shared turn vocabulary: opaque `SessionId`/`TurnId`,
the `TurnBlock` union (`TurnTextBlock`, `TurnThinkingBlock`,
`TurnToolCallBlock`, `TurnToolResultBlock`), and the generic
`TurnRequest[T]`/`TurnResult[T]`.

Everything optional is a decorator or an absent capability, never a flag:
`wrappers.py` layers timeouts, budgets, retries, correction, tracing, usage,
and display around a factory; `routing.py` selects a configured recipe from an
immutable `ModelRoute` list and fails closed on an unknown model;
`background.py` coalesces state wakes into turns on a persistent session;
`output.py` binds a fresh `submit_output` tool and store to each typed turn.

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
`generation.py` holds the small deterministic helpers the stages share,
including the do-not-edit banner every commentable generated artifact opens
with. [harness.md](harness.md) walks the whole pipeline.

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
`actors.py` holds one durable session per actor, `turns.py` puts the prompts
to them, `joins.py` brings branches together and settles what that breaks,
`verification.py` runs one tree through the verification set, and
`execution.py` drives one concern's revision loop. `core.py` composes them
and owns only the sequence. [resolver.md](resolver.md) covers the lifecycle.

### `codescan` — the executable conventions

The rule engine behind `lup-devtools dev check` and both generated edit hooks.
`common.py` provides comment-column tokenization, docstring detection, and
ignore-directive parsing; `markers.py` finds `# lup:` review notes;
`antipatterns.py`, `boundaries.py`, `capabilities.py`, and `portable.py` are
the rule families; `registry.py` indexes them all into
[rules.md](rules.md).

### `adapters` — the vendor edge

`adapters/claude/` and `adapters/codex/` each implement the same four seams:
`runtime.py` (open sessions behind the runtime contracts), `harness.py`
(render the declaration into that runtime's tree), `harness_runtime.py`
(probe the installed CLI for evidence), and `native.py` (decode hook payloads
into policy events, render decisions back). `adapters/harness.py` composes the
renderers into whole-tree compilers.

Each also carries what only it needs: Claude a personal account registry that
`runtime/profile_tree.py` answers with the directories a project keeps instead,
Codex a
typed JSON-RPC transport to `codex app-server`. Neither is mirrored for
symmetry's sake. [platform-differentiation.md](platform-differentiation.md)
is the map of every difference.

### The rest

Every remaining top-level entry, and what makes it one. `types` is tier 1
above and `__init__` is the front door; the rest each answer a question no
sibling answers.

Which entries this table has to cover is walked from `{LIBRARY.subtree}` when
the page is generated, and generation fails naming any package that is neither
described here nor tiered above. So a package added to the library cannot be
quietly missing from its own roster — the way six of them once were.

"""
            ),
            LIBRARY.table(root),
            models.TextPart(
                text=rf"""
### The target layout

The roster above is where the tree stands and, with one exception, where the
three questions put it. The exception is `resolver`, whose home is
`lup/harness/resolver/`: its only driver is `lup.devtools.harness.resolve`,
so it is part of the harness subject rather than a sibling of it, and the
downward question stops it at the library edge — following the driver into
`devtools/` would move provider-neutral code into the tooling layer.

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
app sits under `adapters/` and nothing above `devtools/` imports one.

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
pass the resulting `SessionFactory` everywhere else. `seam-boundary` will tell
you when a second site appears.

**Compose capabilities rather than configuring an object.** Timeouts, budgets,
retries, persistence, and tracing are `DecoratingSessionFactory` layers you
add individually, not fields on a client.

**Let typed output be the only output.** Bind a Pydantic type to the turn and
read `TurnResult.output`. A missing submission raises a typed error carrying
the blocks, usage, duration, and validation history — it cannot arrive as an
empty success.

`{layout.path()}` is the worked example of all three; see
[template.md](template.md).
"""
            ),
        ],
    )
