<!-- Generated from lup.harness.content.docs.corpus by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# Corpus

A corpus is a body of claims somebody is prepared to be held to, together with
the evidence that backs each one and the corrections that have since retired
it. `lup.corpus` is the evidence half of the ledger: artifacts pinned to the
files they were checked against, sources kept under their own digest,
corrections that supersede in part, and a check that fails a document citing
what no longer holds. It is not a module with a switch — everything here is a
node kind, an edge kind, or the standing one reads for itself, and the store,
recording, relating and listing are the ledger's. A project turns the corpus
on by declaring these kinds, or its own subclasses of them, in its
`node_classes` and `edge_classes`, exactly as it declares `Task`.

## The failure it answers

The same one, met twice, in two corpora. A research repository kept a status
per claim, and a migration that copied added files and dropped modifications
left thirty-one claims reading as evidenced while their artifacts were missing.
A correction register declared itself authoritative over every other document
and was applied to none of them: the canonical prose carried stale figures
behind a list a reader had to consult first. **A claim kept a label after the
thing supporting it went away, and nothing reported the difference.**

What the first repository got right was the invariant this whole module keeps:
there is no stored status, so a claim cannot outrun its artifact and cannot
keep a label its evidence stopped supporting. Standing is read, never stored,
and may regress.

## Evidence rots against files

An `Artifact` or `Certificate` carries a `Validation`: a schema id naming which
checker's word this is, a digest of what was checked, and the digest of every
file it was checked *against*. That scope is the part that rots. The moment
one of those files changes, the evidence reads as `stale` and says which file,
and every claim it supported reads as `stale` on the next look — with nobody
having gone back to amend anything, because nothing was written that could go
wrong.

The two kinds share the shape and differ in one word: a certificate is a
checker's word about the subject digest, an artifact is a person's or a
script's, and a reader ranks them apart. A `Source` is external bytes under
their own digest, so a claim read from a page cites those bytes and not
whatever the page serves next year.

Read on a machine with no working tree, evidence says `unchecked` rather than
guessing either way.

## A claim refuses to hide contradiction

`Claim.standing()` reads the edges pointing at it, in this order: `superseded`
by a correction; `contradicted`, where a live counterexample and live support
both stand; `refuted`; `stale`, where support exists and none of it stands;
`verified` or `supported`; `unsupported`. Contradiction is reported as itself
rather than resolved, because a reader shown one side and not the other is
shown a lie by omission.

Every reading carries `sound`: the one bit every project's vocabulary shares,
and what the cite check reads. A stale, refuted, contradicted or superseded
claim is not sound; an unsupported one is — it never claimed more than it had.

## Corrections supersede partially

A `Correction` records where the mistake was found, what was wrong, and what
to do differently. What *survives* and what *changes* live on the `supersedes`
edge, because they are facts about the pair — and what changes may not be
empty, since a correction that changes nothing is a note. The superseded node
stays in the log, readable, with the correction pointing at it.

Nothing broadcasts. The one message a correction sends is to the author of
what it corrects, and only while that author is on the roster, because they
are the one party whose next action it changes. Everyone else meets it when
the cite check or a listing puts it in front of them.

## The one rule about who may say what

A `verifies` edge refuses an author verifying their own claim. It is the only
such rule the library keeps, and it lives on the edge because only the edge
sees both ends.

## Grades are the project's

`Claim.grade` is a string this library does not interpret. What grades exist
and what each is worth is a project's vocabulary, and the project's own
`Claim` — a subclass declared in its `node_classes` — validates the word. The
template ships six as a worked example, taken from the mathematics corpus the
design came from, and an adopting project replaces them.

## Citing a node from prose

A document names a node with an ordinary markdown link whose href carries the
`lup:` scheme — `[three of four](lup:9f2a1c)`. Every renderer shows it as a
link; the parser hands the check a token with an href, so a cite inside a
fenced block is not one.

`dev check` reads every tracked markdown file and **fails** a cite whose node
does not exist or is not sound, naming the file, the line, and the standing's
reason. That is the difference from a register nobody applied: prose cannot go
on citing a corrected figure, because the build says so. `ledger cite <doc>`
runs the same reading over one file. There is no command that rewrites a
hand-written document with figures substituted: the parser has no writer and
no inline offsets, and a label carrying markup breaks any reconstruction. A
document whose figures should never go stale is *generated* from the corpus
instead, which is what writeups are.

## Recording it

The ledger's generic commands, over the kinds this project declared:

```sh
uv run lup-devtools ledger types
uv run lup-devtools ledger record corpus:claim "quotes nest to depth two" \
    --text 2 --json '{"grade": "measured"}'
uv run lup-devtools ledger record corpus:artifact run.log --attach run.log \
    --json '{"validation": {"schema_id": "pytest", "subject_digest": "…",
             "scope": [{"path": "src/parser.py", "digest": ""}]}}'
uv run lup-devtools ledger relate corpus:supports <artifact> <claim>
uv run lup-devtools ledger record corpus:correction "depth is three" \
    --json '{"where": "README", "wrong": "said two"}'
uv run lup-devtools ledger relate corpus:supersedes <correction> <claim> \
    --json '{"changes": ["the figure"], "survives": ["the method"]}'
```

A scoped path recorded with an empty digest is pinned by the evidence itself
as it is recorded — the type fills what it derives from the working tree at
the one moment it is true — so a caller names files and never computes a
digest. Every command reads and writes the shared git directory, so any
checkout answers and none owns the answer.
