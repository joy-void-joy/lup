# The life of a `# lup:` note

A `# lup:` (or `// lup:`) comment is actionable review feedback left in the
code for an agent to address. The guidance states the rule — you cannot delete
one — and this document is the whole lifecycle behind it: the four marker
flavors, why deletion is refused rather than asked, what a resolution claim is
for, and how deferred work stays visible without a tracking file.

## Four flavors, three of them notes

| Marker | Means | Gate on adding | Gate on removing |
|---|---|---|---|
| `# lup: <text>` | open feedback, owed an answer | ask | **deny** |
| `# lup: solved: <text>` | a claim that the feedback was addressed | allow, from a note | **deny** |
| `# lup: defer[<cond>]: <text>` | parked work behind a wake condition | ask | **deny** |
| `# lup: ignore[<rule>]` | an anti-pattern escape hatch, not feedback | ask | allow when the violation is gone |

Only the last is not feedback, which is why it is the only one whose removal
is ordinary tidying. `docs/rules.md` covers it; the rest of this document is
about the three that are.

## Why deletion is denied rather than asked

An ask is answered in the same turn that wanted the deletion, by the agent
that wanted it — and a deleted note is the one artifact nobody can review
afterwards, because its absence is indistinguishable from a note that never
existed. Every other bad edit leaves something to find.

So the gate is structural. `lup.policy.kernel.edit.marker_decision` counts
open notes and claims separately across an edit:

- open count up → **ask** (you are leaving feedback, which is a decision)
- open count down, claims up by the same amount → **allow** (a conversion)
- open count down otherwise → **deny**
- claim count down → **deny** unless the session holds `note-resolution`

The counts skip backtick-quoted examples, so prose *about* the syntax — this
document, the guidance, a docstring explaining the convention — is not
mistaken for feedback.

## Resolving: claim it, keep the words

Resolution means fixing what the note points at, or, for a question, answering
it definitively in the code, the docs, or a recorded user decision. Making a
file parse, tidying up, or editing past a note is not resolution.

Then rewrite the marker, keeping its text **exactly**:

```python
# lup: this cache never invalidates on a schema change
```

becomes

```python
# lup: solved: this cache never invalidates on a schema change
```

Keeping the original words is what makes the claim checkable. A claim that
paraphrases what it answered can only be judged against itself.

## The review pass

`/lup:verify-solved` is the only holder of `note-resolution` and the only
thing that retires a claim. It reads each one against the code as it stands
and answers one question — does the tree now do what the note asked? — with
three outcomes: remove it, restore it to open feedback, or restore it narrowed
to the part still outstanding. It reports the rundown before editing, and it
is expected to restore some; a pass that retires everything it reads is the
first thing to be suspicious of.

`dev check` stays red while any claim is outstanding, so the review is
pressure rather than an optional courtesy.

## A note where comments do not exist

A note in a comment-less format (e.g. JSON) is the trap: you cannot keep it
there, but you still cannot silently drop it to satisfy the parser. Resolve
its concern first, or relocate it to a file that can hold it — the code it
refers to, or a document. If a note raises several concerns, claim it resolved
only once every one is resolved; otherwise keep the unresolved parts open.

## Deferred work

**Never create tracking files.** A `TODO.md`, backlog, or roadmap file parks a
decision where no workflow will surface it again — deferral by tracking file is
delegation to nobody. Deferred work lives in exactly two places:

- **A `# lup: defer[<wake condition>]: <text>` note** at the most relevant
  site: the code or config the work concerns. The bracket names the condition
  under which the work wakes, mirroring `# lup: ignore[rule-id]`. `dev
  comments` lists deferred notes in their own section and `dev check` stays red
  while any exist, so parked work remains visible pressure instead of silent
  debt. Each resolve pass triages them: a note whose wake condition reads as met
  is proposed to the user for waking; an unmet one carries forward untouched,
  never re-litigated as ordinary feedback.
- **Ask instead of filing** — when whether (or how) to defer is itself the open
  question, put it to the user.

A briefing under `tmp/` is the one exception, and it is not a backlog. Its
whole purpose is to start a *fresh* session from scratch on a situation the
current one cannot finish, so it states the situation as it stands now: what is
wrong, what is left to do, and what a reader needs to act. Never append to one,
never patch it, and never let it accumulate a history of what was tried —
rewrite it whole, the way the Code as Documentation convention asks of the
codebase itself. A file that records its own past has become the tracking file
this rule forbids.
