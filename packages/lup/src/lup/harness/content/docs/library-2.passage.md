
### What is left to place

The roster above is where the tree stands, and where the three questions put
it. Thirty-four top-level entries became these by asking, of each one, which
of the four kinds it is: a foundation that imports nothing here, a subject,
the one vendor boundary, or tooling.

`resolver` is the entry the downward question is hardest on, because
everything that drives it is tooling: eight modules across
`devtools/harness/`, `devtools/supervisor/`, `devtools/dev/` and
`devtools/report/` read its journal, its state repository, its question
mailbox and its lease table. What keeps it a sibling of the subjects rather
than a package inside one is what it imports. Twenty-four of its import lines
reach `orchestration.actors` and fifteen reach `harness`, so neither subject
contains it, and what it answers — reviewed concerns driven over a DAG of
branches, each on its own branch in a leased worktree — is a question neither
of them answers.

Five two-way edges between entries survive the sort. Four are placement
questions still open; the fifth is the shape of a guarantee.

| pair | what closes the loop |
|---|---|
| `client` ↔ `providers` | the front door's routing constructor reaches both providers, lazily, inside `create_client` |
| `client` ↔ `sessions` | six session modules hold a `Client`, and the front door reads the turn vocabulary |
| `devtools` ↔ `harness` | three utilities the library needs — `git`, the clipboard probes, a launcher's default environment — live under the tooling half |
| `devtools` ↔ `sandbox` | the same `git`, reached from the container's mount rail |

The last two have one shape: a symbol two subjects share, sitting inside one
of them. Each closes by moving that symbol below both, which is what
`lup.formats.banner` already did for the do-not-edit banner the policy bundle and
harness both write. The first two are the front door deliberately knowing
about what it opens; whether a lazily-imported provider counts as an edge at
all is the question to answer before an acyclicity check is written, and
answering it by choosing a walker that does not look inside a function would
be hiding it rather than settling it.

`harness` ↔ `policy` is the one that stays, because breaking it would break
what `policy` is for. Nine of `codescan`'s modules read `policy.kernel.edit`
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

{{ value }} is the worked example of all three; see
[template.md](template.md).
