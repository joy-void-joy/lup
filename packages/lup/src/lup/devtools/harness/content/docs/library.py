"""Guide to ``packages/lup``, the reusable provider-neutral library.

The per-package roster below is authored prose keyed by a walked set. What
each package solves is a judgement no walk can make, so it stays written; but
*which* packages there are to describe is the tree's to answer, and asking it
is what closes the gap this page had — a roster promising "every remaining
top-level entry" while silently omitting six of them, `actors` among them
four commits after it was added.
"""

import ast
from collections.abc import Iterator
from itertools import groupby
from pathlib import Path

from pydantic import BaseModel

import lup.harness.models as models
from lup.devtools.harness.content.application import ApplicationLayout
from lup.devtools.harness.content.tree import top_level_names
from lup.markdown import CodeCell, PlainCell

LIBRARY_PACKAGE = Path(__file__).resolve().parents[4]
"""This library's own package directory, wherever the reader installed it from.

Derived rather than resolved against the reading project's checkout, because
the two answers differ for everyone who is not lup itself. A project that
vendors lup at ``packages/lup`` walks the same tree either way; a project that
takes it as a distribution has no such subtree at all, and a page that looked
for one failed generation rather than describing the library that project
actually runs. Asking the imported package where it lives answers for both,
and answers about the code in use rather than about a directory that may be a
different revision — which is the stronger claim the roster wanted anyway.
"""


class RosterEntry(BaseModel, frozen=True):
    """One top-level entry, and the authored answer to why it is one."""

    package: str
    solves: str


class TieredEntry(BaseModel, frozen=True):
    """One entry a section above the roster already describes, and which one.

    Carried rather than inferred: a package earns a section of its own by
    being load-bearing enough to need one, which is a judgement. Naming the
    section is what lets the roster send a reader *there* rather than leave a
    package it skips unaccounted for — :meth:`Roster.described` renders that
    sentence from this list, so an entry tiered out of the table appears in
    the line saying where it went by being tiered at all.
    """

    package: str
    section: str


class Roster(BaseModel, frozen=True):
    """A package roster, and the tree it must agree with.

    Every judgement here is a field default rather than a module constant, so
    a project describing its own library replaces the values instead of
    forking the check that reads them.
    """

    subtree: str = "packages/lup/src/lup"
    """Where the package this describes lives inside lup's own repository.

    Prose only: what the walk reads is :attr:`source`, which is where the
    reader's own copy actually sits. This is the path a reader opens to find
    the source, which is a fact about lup's repository rather than theirs.
    """

    source: Path = LIBRARY_PACKAGE
    """The package directory this roster is checked against.

    A default rather than a constant, for the reason every default here is
    one: a project that vendors lup somewhere else describes the copy it
    actually has. It is also what lets the drift check be tested at all — a
    walk that could only read its own installation has no way to be shown a
    tree that has drifted.
    """

    tiered: list[TieredEntry] = [
        TieredEntry(package="types", section="Layering"),
        TieredEntry(package="sessions", section="The packages"),
        TieredEntry(package="harness", section="The packages"),
        TieredEntry(package="policy", section="The packages"),
        TieredEntry(package="resolver", section="The packages"),
        TieredEntry(package="providers", section="The packages"),
    ]
    """Entries a section above the roster describes at length instead.

    In the order a reader meets them, because :meth:`described` renders the
    sentence that sends them there from this list and nothing sorts it after.
    """

    def owed(self) -> list[str]:
        """Every entry in the library's own package this roster has to describe."""
        elsewhere = {entry.package: entry.section for entry in self.tiered}
        return [
            name
            for name in top_level_names(self.source.parent, self.source.name)
            if name not in elsewhere
        ]

    def described(self) -> str:
        """Where each entry this roster skips is described at length instead.

        Rendered from :attr:`tiered` rather than restated in the prose beside
        it, which is the whole reason the section is carried: the sentence
        naming what the table omits and the filter that omits it are one list,
        so neither can name a package the other has forgotten. The sentence it
        replaced named `types` and left the other five unaccounted for.

        Grouped by consecutive run rather than by sorted key, so the order is
        the one a reader meets the sections in; two runs of one section read
        as two clauses, which is what interleaving them would deserve.
        """

        def listed(packages: list[str]) -> str:
            """A short run of names, read as a clause rather than as a row."""
            if len(packages) == 1:
                return packages[0]
            return f"{', '.join(packages[:-1])} and {packages[-1]}"

        return "; ".join(
            f"{listed([f'`{entry.package}`' for entry in run])} in **{section}**"
            for section, run in groupby(self.tiered, key=lambda entry: entry.section)
        )

    def entry_source(self, name: str) -> Path:
        """The file whose docstring describes one top-level entry."""
        entry = self.source / name
        return entry / "__init__.py" if entry.is_dir() else entry.with_suffix(".py")

    def solves(self, name: str) -> str:
        """What one entry says it solves, read from its own docstring.

        The summary line and the paragraph beneath it, joined. PEP 257 puts a
        short summary first, which is what a reader of the module wants and is
        too short to be a roster row on its own; the paragraph under it is
        where an entry says why it is an entry at all. Anything further down is
        the module explaining itself to somebody already inside it.

        Read from the code rather than restated here, and that is the point.
        This page used to key an authored string to each name — two
        descriptions of one subject, in two files, with nothing holding them
        together. The hand-written half had already drifted: its `channels` row
        named six consumers where the import graph counts eleven, and a page
        confidently wrong is worse than one that had to be looked up.
        """
        source = self.entry_source(name)
        docstring = ast.get_docstring(ast.parse(source.read_text(encoding="utf-8")))
        if not docstring:
            raise ValueError(
                f"{source} carries no docstring, so this page has nothing to "
                "say about it: open the module with a summary line and a "
                "paragraph saying what it solves"
            )

        def opening() -> Iterator[str]:
            """The summary and the one paragraph under it, line by line.

            Walked rather than split on the blank line, because what is being
            read is prose: there is no parser for "the first two paragraphs",
            and a loop takes them without pretending otherwise.
            """
            blanks = 0
            for line in docstring.splitlines():
                if not line.strip():
                    blanks += 1
                    if blanks == 2:
                        return
                    continue
                yield line.strip()

        return " ".join(" ".join(opening()).split())

    def table(self) -> models.MarkdownTable:
        """The roster as a table, derived from the tree it describes.

        Nothing left to fall behind: every row is the entry's own docstring, so
        an entry added to the library arrives here by existing and one deleted
        leaves by the same route. What used to be a hand-kept list checked
        against a walk is now the walk.

        A missing docstring still fails generation loudly, for the reason the
        authored roster did: a page that quietly drops a package reads exactly
        like a complete one.
        """
        return models.MarkdownTable(
            headers=["Package", "Solves"],
            rows=[
                [CodeCell(text=name), PlainCell(text=self.solves(name))]
                for name in self.owed()
            ],
        )


LIBRARY = Roster()
"""This library's own roster, checked against this library's own tree."""


def document(layout: ApplicationLayout) -> models.PromptDocument:
    """The library guide, naming the application half by its own name.

    Takes no checkout, because the one tree it walks is the library's own and
    :data:`LIBRARY_PACKAGE` already names it. The filesystem is still read at
    call time rather than at import, so composing this module stays possible
    from anywhere.
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
library never imports the application: a utility left in `{layout.directory()}`
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

Every remaining top-level entry, and what makes it one. `__init__` is the
front door, and six more are described at length above instead —
{LIBRARY.described()} — so the rest each answer a question no sibling
answers.

Which entries this table has to cover is walked from the installed `lup`
package when the page is generated — `{LIBRARY.subtree}` in this repository,
and wherever a downstream project resolved the dependency to. Generation fails
naming any package that is neither described here nor tiered above, so a
package added to the library cannot be quietly missing from its own roster —
the way six of them once were.

"""
            ),
            LIBRARY.table(),
            models.TextPart(
                text=rf"""
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
rather than a list kept somewhere else. One module answers it today, and it is
the one that should not: how a project obtains lup, across the published, git,
local, and linked modes, is a question every adopter has and none of it is
about this application, so `devtools/dev/library.py` belongs under
`lup/devtools/dev/`. A single entry with a settled verdict is the shape a
shrinking debt is supposed to have, and the row is read rather than trusted —
a module that reaches the application, as `devtools/setup.py` does for its own
harness composition, leaves the row by doing so rather than by being argued
about here.

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

`{layout.path()}` is the worked example of all three; see
[template.md](template.md).
"""
            ),
        ],
    )
