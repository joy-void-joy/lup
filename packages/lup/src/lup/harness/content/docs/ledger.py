"""One log per repository, separate types in it, and standing read not stored."""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.TextPart(
            text=r"""# Ledger

Work that outlives the session which did it has to live somewhere a later
session finds. `lup.ledger` is that somewhere: one append-only log per
repository, kept outside every worktree, holding typed nodes whose standing is
computed when somebody reads rather than stored when somebody claims.

## One log, separate types

**The log is one file. The types in it are unrelated.** Those are two
different facts and running them together is the mistake this shape avoids.

A `Task` has a holder and what it is waiting for. A `Claim` has a grade. A
`Correction` has what survives and what changes. They share `id`, `kind`,
`title`, `author` and `at` from `LedgerNode` and nothing else — no common
payload, no field bag, no shared vocabulary. Reads are per type:

```python
tasks  = store.read(Task)     # -> list[Task],  task.holder is typed
claims = store.read(Claim)    # -> list[Claim], claim.grade  is typed
```

so nothing outside deserialization ever sees `Task | Claim | Correction`, and
a record of the wrong type is simply not in the answer.

**What requires one log** is that standing is computed by asking *what points
at this node*: corrections superseding it, evidence supporting it,
verifications checking it. Split the log by subject and that question spans
several files which can change between reads, needs a resolver that knows
every one of them, and has to be snapshotted consistently across all of them.
Git keeps commits, trees and blobs in one object store for the same reason,
and those are no more alike than these.

So an edge crosses types freely, which is the point: a handoff points at the
tasks it transfers, a task verifies a claim, a correction supersedes one. An
id is an id.

## Where it lives

```
<repo>.git/lup/ledger/
  journal.jsonl       every node and edge, append-only, oldest first
  blobs/<sha256>      bytes a node attached, under the digest of what they are
```

Outside every worktree, which is the whole answer to a record that forks. A
store inside a checkout is a store per branch: worktrees diverge for days, and
reconciling them afterwards is a script somebody writes once, races against
live sessions, and never re-runs. There is no merge to get wrong when there is
one log.

Nothing is rewritten in place, so two sessions appending at once produce a
longer file rather than a lost record, and a malformed line is skipped rather
than fatal.

## Standing is read, never stored

A stored status is a label that outlives whatever justified it. The evidence
is withdrawn, the file it was checked against changes, and the label sits
there reading as current while nothing anywhere reports the difference.

So each node type answers `standing(incoming)` for itself, over the edges
pointing at it, **and is allowed to answer something weaker than it did
yesterday**. A claim cannot outrun its support, because nothing records that
it ever had any.

`LedgerNode`'s own answer is `recorded` — it was written down — so a type with
no epistemics is one class and no overrides.

## What a type must carry is a field, not a gate

There is no gate concept. A requirement a type can state, it states:

```python
class Handoff(LedgerNode, frozen=True):
    open_questions: list[str] = Field(min_length=1)
```

That refuses an empty handoff at construction, in the type. What is left is
only what a node cannot see about itself, and it lives on the edge, which is
the only thing that sees both ends:

```python
class Verifies(LedgerEdge, frozen=True):
    def refusal(self, source: LedgerNode, target: LedgerNode) -> str:
        if target.author == self.author:
            return "a verification of your own work is not one"
        return ""
```

That is the one rule this library keeps about who may say what, and it is a
property of the relation rather than of any project's epistemics.

## No epistemics

`lup.ledger` declares no node type, no edge type and no grade. What counts as
verified, what grades exist, and what a claim owes are a project's questions —
the scaffold's corpus (`docs/corpus.md`) is one project's answer, declared in
its `node_classes` beside its tasks, and a project that wants its own declares
its own types the same way.

## The store is untracked

Nodes accumulate as work happens and nobody reviews a diff of them. `dev
ledger snapshot` commits the tree to a branch of its own, sharing no history
with the code it is about, when somebody wants it preserved — a deliberate act
rather than something that happens on every write. It is written with git
plumbing over a scratch index, so it never stages uncommitted work.

## Reading it

`dev ledger list` shows every node with its standing read now; `--kind`
narrows it. `dev ledger show <id>` prints one node with its edges and
attachments. `dev ledger types` says what node and edge types this project
declares, with the fields each accepts — which is what `ledger record <kind>
"<title>" --json '{…}'` and `ledger relate <kind> <source> <target>` take.
Recording is generic: the kind is looked up in what the project declared and
the type validates the fields, so there is one `record` rather than a command
per kind, and a kind the project adds tomorrow is recordable today. `ledger
cite <doc>` holds one hand-written document to the nodes it names.

`ledger list --since <moment>` is how a reader opens on what moved: the nodes
with a record newer than the moment they last looked — theirs, or an edge
touching them — read off the log's own timestamps, since standing is never
stored. A node may carry a `slug`, unique once taken, and every command that
takes an id takes a slug. `ledger show` counts the edges pointing at a node by
kind before listing them, because the count is what a reader weighs a node by.

## Standing reaches through the log

A type's `standing()` reads its neighbourhood, and the neighbourhood carries
`standing_of`: a reader the store supplies that answers for *any* node, as
deep as the log goes, remembering each answer and reporting a cycle rather
than following it. A type that only needs one hop — a task reading whether
its blockers finished — never calls it; a type whose standing depends on a
neighbour's standing calls `standing_at(id)` and gets the whole chain. That is
the mechanism; what a chain means is the project's, declared in its kinds.

The console is the one reader whose subject is the log rather than any one
type, so it is the one place a list of node classes is needed: a record names
its kind, not the class that reads it, so something has to try. A record no
declared class accepts reads as the base and says its kind — which is what a
node written by an older or differently-configured build looks like, and it
stays visible rather than being refused or silently dropped.
"""
        )
    ],
)
