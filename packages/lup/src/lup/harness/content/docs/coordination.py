"""How sessions that already exist find each other, and reach each other."""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.TextPart(
            text=r"""# Coordination

Orchestration is one process deciding what several agents do. Coordination is
several agents that already exist finding each other: a roster somebody joins
rather than is spawned into, mail that outlives the process that sent it, a
person who is addressed the way an agent is. Everything here folds shared
state off disk instead of remembering it, which is what lets a peer answer to
a process that did not create it.

## Two populations, one mechanism

A **cohort** is what one process assembled — a resolver run's workers, the
agents a session spawned as it went. Its directory is wherever that process
put it, and it ends when the work does.

A **repository roster** is the population nobody assembled: every session
working in this clone, in whatever worktree, started by whoever. It lives at
`<repo>.git/lup/coordination/`, which every worktree resolves to the same path
and none of them owns, so a branch cannot change what a peer reads and
removing a worktree does not take the roster with it.

Both are the same roster, mail and journal over different directories. That is
the whole of the reuse and it is the point: a message to a peer and a message
to a spawned worker travel one stream, fold through one set of records, and
are read by one inbox — so there is one delivery path to get right rather than
two that agree until they do not.

Different repositories are structurally disjoint. There is no global registry
to collide in, no daemon to elect, and no way for a session in one project to
appear on another project's roster.

## What a directory says about itself

A roster, a message stream and a journal in one directory were a cohort by
convention, which every reader had to know and a stranger could not read at
all. `cohort.json` states it — which run, since when, and what for — and
`cohorts_under` is what a peer that created nothing walks to find one. Nothing
else moved into it: who is present is still the roster's fold and what is
queued is still the mail's, because those move and this does not.

## The person is a member

The user joins as `user`, with an inbox and no session, addressed by the verbs
that address an agent. A report is a message to `user`; a question is a
message to `user` carrying a slot id, and the reply settles the slot. Messages
park nobody; questions park, because the slot parks.

That is what makes the human channel one mechanism rather than two. A person
resolved ahead of the roster by a branch of their own leaves every other
reader half-right: a listing does not show them, a console cannot find them,
and whether an address reaches anybody depends on which of two paths the
caller is on. `live()` is the one place they are left out, because nobody
started them and a listing of spawns should not claim otherwise.

## Identity

Two facts, deliberately separate. The **id** is minted once and never moves:
mail is addressed to it, and a restart reattaches by it. The **name** is what
a person types, and a session renames itself whenever what it is doing
changes. Renames are journaled rather than overwritten, so a name somebody
wrote down an hour ago still reaches the session it named until something else
claims it — there is no error a sender could be shown, because the name they
used was correct when they read it.

A launcher exports the id as `LUP_COORDINATION_MEMBER` and can prove it, the
way `LUP_AGENT_IDENTITY` is proven: a hook is spawned by the runtime CLI with
the CLI's own environment, so an agent exporting this inside a shell call
cannot reach the hook that reads it. A bare session in a worktree has the
plugin and no launcher, so it falls back to the identity its own runtime gave
it and registers under a name derived from its worktree. It is a full peer
that cannot prove who started it.

## Delivery is a property of the member

What carries a message differs by what the recipient is, so the roster carries
it and a sender is told which mode it got:

| Mode | What it means |
| --- | --- |
| `inbox` | Its own hook puts the message in front of its next tool call, so a working recipient cannot fail to read it |
| `mailbox` | The message waits in the file until the recipient next looks, and nothing wakes it |

File mail is the durable record either way; every other mode is a wake *on top
of* it rather than an alternative. A sender told only that the mail accepted a
message cannot tell a hook from a file nobody is watching, which is why
`spawn_say` reports the mode rather than asserting delivery.

## The other address book

A runtime that can already address another session offers a second way to
reach one, and the two acts are not the same. A message on this stream is a
durable record every worktree folds and every later session can read; a native
send is a call whose text exists only inside whichever process received it. So
where both would reach the same member the native send is stopped and told
where the durable one is, and where it reaches somebody the roster has never
heard of nothing happens at all — a subagent this session started is on no
repository roster, so continuing one goes through untouched.

A native *listing* of who can be reached is the different case, and refusing it
would be wrong rather than merely strict. Measured against a live account, most
of what such a listing returns is sessions in other repositories: a population
this roster is structurally incapable of holding, since different repositories
are disjoint by construction. A redirect to the roster would answer a question
the reader did not ask and be escalated past every time. So the listing goes
ahead untouched and this repository's roster rides beside it, labelled — the
failure worth stopping is a reader taking the wider list for this repository's
address book, not the reader having the wider list.

That asymmetry is the whole rule. Refuse the act that would leave no record;
never refuse the answer to a question the record cannot give.

## Actor cohorts

The three delegation patterns in [orchestration.md](orchestration.md) all end
the same way: the delegated agent runs, and whatever anyone learns while it
runs has nowhere to go. A subagent's task is fixed at dispatch, a nested agent
is unreachable inside its tool call, and a background agent takes state on a
wake rather than a sentence mid-turn. When several agents work at once and the
facts move under them, that is the whole problem — an agent verifying a
statement you have since disproved keeps going because nothing can tell it.

An **actor cohort** (`lup.coordination.cohort.ActorCohort`) is a population of
agents that stay in contact while they work. Each holds one session across
every turn it takes; anything addressed to one lands in front of its next tool
call through a hook it never chooses to check; and the person watching is
itself an address, `user`, so an agent can say something back.

| Aspect | Actor Cohort |
| --- | --- |
| Lifetime | As long as the population is held; each member across many turns |
| Runtime | One held session per member, from a recipe the cohort configures |
| Initiation | `ask` (awaited), `start` (detached), or `work_all` (a whole wave) |
| Communication | Mail both ways, mid-turn; questions through a `QuestionMailbox` |
| Use case | Several agents at once, over work whose facts move under them |

**`ask` versus `start` is the load-bearing distinction.** A caller blocked
inside an awaited call cannot make another, so a cohort whose members are all
`ask`ed has steering tools that can never fire. `start` returns immediately
and the caller keeps its turn — which is what makes saying anything possible
at all.

**Fan out with `work_all`, not with a gather of your own.** How many agents
run at once, which of them are running, and what a close reaches are three
facts about the population; a caller that assembles its own wave from
`start_work` and `asyncio.gather` gets the cap right and the other two wrong.
`work_all` runs one piece of work per address and hands back each answer
positionally — a result or the exception it raised, faithfully, so a caller
that classifies failures can still tell a park from a host fault from a
cancellation.

**A raise does not always finish an agent.** A raise usually settles the agent
it came out of, but work can stop because it was suspended — parked on a
question, drained at a boundary, stopped by a failing host — and every one of
those expects the same agent to carry on. `settles` is how a consumer says
which of its own failures suspend; recorded finished instead, the resume opens
a fresh conversation rather than reattaching to the one holding the context,
and every door reads a waiting agent as a stopped one.

It belongs to the cohort, passed once at construction, rather than to each
wave. A suspension is raised in both places a raise can happen — a drain
checked between rounds comes out of the work, a host fault out of the turn
itself — so a judgement held by the wave answers for one and not the other,
and the turn's own failure path finishes the agent before the wave is ever
consulted. Which failures suspend is a fact about the consumer's vocabulary,
and a consumer has one.

**The cohort owns the wiring.** Delivery works only if the inbox hook is in
the options the session opened with, so callers pass an `ActorRecipe`
(`(ActorRef, LupHooksConfig) -> Client`) and the cohort hands it the hooks. A
recipe that had to fetch them could be written once without them, producing an
agent that looks spawned and reads nothing anyone sends it.

**Addresses are supplied or minted.** `cohort.actor(kind, id)` with an id
derived from durable state is stable across a restart, which is what lets a
resumed run reattach to conversations rather than open new ones;
`cohort.actor(kind)` mints one for a spawn nobody declared. That is the only
difference between the two cases.

**The population is a record, not a dict.** `live()`, `members()` and
`reaching()` fold `roster.jsonl`, so a console in another process resolves the
same address the cohort's own tools do, and a restart rebuilds the roster.

## What a session reaches this through

`lup.coordination.tools.create_cohort_tools` serves the verbs an agent needs —
list what I spawned, read what one of them has found so far, say something to
one of them, say something to the person watching. Reading is what makes
steering more than a guess: a spawn's turn events reach the journal as they
happen, so `spawn_read` folds its own words, its calls and its refusals out of
that record while it is still working, and a redirect can be aimed at what the
agent is doing rather than at what it was asked.
`lup.coordination.mailbox.QuestionMailbox` adds decisions that park a run, on
the same storage; messages ride a stream and never park anything, which is why
"a message stalled the run" is not expressible rather than merely avoided.

A person reaches the same roster through `coordination roster`, `send`,
`inbox`, `describe` and `rename`. They drive the same files, so what a console
says is here is what a session addressing it will reach.
"""
        )
    ],
)
