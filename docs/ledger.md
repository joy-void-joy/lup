<!-- Generated from lup.harness.content.docs.ledger by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Ledger

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

That is the default placement, `SharedStore()`, and a project may declare
the other: `InTree()` keeps the log inside the worktree, at `ledger/` unless
told otherwise, so the journal travels with commits, is reviewed in a diff,
and is the same on every machine. Every worktree then holds a copy — the
failure the shared store answers — and what makes that viable is the shape
already chosen: append-only lines with unique ids, so two branches appending
is exactly what git's own `union` merge resolves losslessly, declared as
`ledger/journal.jsonl merge=union` in `.gitattributes` with no per-clone
registration, and a read folds any duplicate by id. Blobs are
content-addressed and never conflict. `dev check` reports the placement and
refuses an in-tree journal the attribute does not cover. A forge merging on
its server reads no attributes, so there two branches that both appended
show a conflict, resolved by taking both sides. A symlink does not do this
job — git stores a link as its target text — and the placement is a
declaration in the code rather than a per-worktree setting, so two checkouts
of one branch cannot disagree about where the log is.

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

## No epistemics, and one kind

`lup.ledger` declares no grade, no edge type, and one node type. What counts
as verified, what grades exist, and what a claim owes are a project's
questions — the scaffold's corpus (`docs/corpus.md`) is one project's answer,
declared in its `node_classes` beside its tasks, and a project that wants its
own declares its own types the same way.

The one kind is `File`: a path pinned to the digest of its content as it was
recorded, standing `fresh` while the tree still holds those bytes, `stale`
once it does not, `missing` where the path is gone, and `unchecked` without a
tree to read. Files are the substrate standing already rots against —
evidence pins the files it was checked against — so the file itself is
citable, and an edge to one is an ordinary edge: a claim `about`
`src/parser.py`, drawn by the explorer, going stale with the file and nobody
amending anything. A file says nothing about what counts as verified, which
is why it is the library's and the rest is not. A project lists it in
`node_classes` the way it lists `Task`; recorded with an empty title, a file
takes its path for one.

Two more kinds point the same way, declared by the package whose subject a
run is: `lup.observability.sessions` declares `Session` and `Output`, a
session's directory and trace journal under `notes/` and the result document
a run wrote there, each a path, a digest and the checkout it was recorded in —
never the bytes. Both refuse an attachment, in words saying pointers only,
before anything reaches the blob store: a trace runs to hundreds of megabytes
per checkout and the ledger is a log of records. A project lists them beside
`File` and the writers record as sessions open and close; `docs/corpus.md`
says what this repository does with them.

## The shared store is untracked

Under the shared store, nodes accumulate as work happens and nobody reviews a
diff of them. `dev ledger snapshot` commits the tree to a branch of its own,
sharing no history with the code it is about, when somebody wants it
preserved — a deliberate act rather than something that happens on every
write. It is written with git plumbing over a scratch index, so it never
stages uncommitted work. With the log in the tree it is committed with the
code, and `snapshot` says so rather than copying what git already keeps.

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

The same verbs are a session's tools — `ledger_types`, `ledger_record`,
`ledger_relate`, `ledger_amend`, `ledger_show`, `ledger_list`, `ledger_cite`
— served as the `ledger` group beside coordination's, bound to the session's
identity so every record it makes says who made it. An agent that has to
shell out to write down what it learned writes it down less often, and a
corpus nobody records into answers nothing; the tools exist so recording is
one call at the moment something is learned, not a chore at the end.

## The explorer

`ledger explore` opens the log in a browser, on the loopback: every node
listed with its standing read now, narrowed by kind, standing or the moment
it last moved, searched by title, text, slug or id, sorted by any column; one
node in full, the edges pointing at it counted by kind, each end a link; and
the DAG drawn as a graph, a tap opening the node. Every view is a URL, so a
reader hands another one exactly what they were looking at.

`ledger explore --export <path>` writes the same page as one self-contained
file with the whole log embedded — a memo attachment opened without a server,
showing what the log held when it was written and stamped with the moment.
The page is the TypeScript surface Vite built into `lup.web`'s package data;
what it reads is `lup.ledger.views`, the same models the tool group returns,
served as JSON routes under `/api/` or carried whole in the export. Generic
over declared kinds: a project's explorer is this with the project's types,
and the page lists what they are.

## Writeups are declared documents

A document whose figures must never go stale is generated from the log rather
than written by hand: a Python module declares it as parts — the author's
prose, and parts that render from the ledger when the document is generated.
`Prose` fills `{placeholders}` with a node's figure, cited and bold, or struck
through with the reason where the node no longer stands. `Listing` is a table
of nodes chosen by kind, standing, relation, moment, or by name, ordered by
priority. `NeedsPerson` is the person's task list grouped by what each row
costs. `Stamp` says what the document was generated from, naming the newest
record rather than the clock, so one log renders one document.

`ledger writeup` writes every declared document, and `--check` verifies the
file on disk against this machine's log. Under the shared store they are not
drift-checked by `dev check`, deliberately: the log is live state under the
git directory, so the same declaration renders differently where nothing has
been recorded. What keeps a writeup honest everywhere is that every figure in
it is a `lup:` cite, which the cite check holds to its node wherever the log
is. With the log in the tree every machine renders the same document, so the
writeups join the drift-checked generation: `harness generate all` writes
them and `dev check` refuses one that is behind.

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
