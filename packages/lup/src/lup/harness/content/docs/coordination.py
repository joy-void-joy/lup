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

## What each session is holding

Nobody declares what they are working on. Asking them to is asking for the one
thing an agent reliably forgets, and a declaration nobody keeps current is
worse than none — it reads as current and is not. So it is observed: a hook
watches what each session's calls actually change, and the record of that is
the claim.

A **touch** is an exact file some session changed. A **lock** is a prefix a
session took deliberately, for the case observation cannot reach — an agent
about to rewrite a package has changed none of it yet, and the moment worth
telling anybody about is before the first write rather than after it.

A claim is alive while its holder is on the roster and expires with it. There
is no timeout to tune and no release to forget, which is what makes an observed
claim safe to act on: the failure mode of the whole mechanism is a session that
stopped, and a stopped session's claims go with it.

Editing under somebody else's live claim is an approval question naming the
holder, never a refusal. Two sessions in one file is sometimes exactly right,
and a policy that decided otherwise would refuse ordinary parallel work. What
it must not be is silent — the failure this exists for is finding out at merge
time. Claims are keyed by absolute path, so two sessions in different worktrees
never collide over the same source; the merge is what reconciles those.

**A claim can have more than one holder, and that is honest rather than
broken.** A call that names its file attributes exactly. A shell command names
nothing it will write, so what it changed is read by comparing the tree before
and after — and that comparison sees every change in its window regardless of
who made it. Where two sessions had windows open over one path, both names go
on the record and neither is guessed at: a confident wrong author is worse than
an honest pair, because the next reader is deciding whether it is safe to
write. The next named edit or explicit lock settles it, because both of those
attribute exactly.

**Holdings ride on the roster row, beside the description rather than behind a
second call.** A session listing its peers is asking one question — is it safe
to start here — and the two halves of the answer are what a peer *said* it was
doing and what its calls actually claimed. Splitting them across two surfaces
would put the reliable half behind a call nobody makes at the moment it
matters, so `coordination_peers` carries `holding` on every row, and
`contested` beside it for the claims that already have more than one name on
them. `doing` is self-reported and only as fresh as the last time somebody
wrote it; `holding` is observed. Read the second before writing.

The console splits them the other way, and deliberately. `coordination roster`
carries a count per row, because a count is the decision — whether there is
anything here to ask about — and `coordination holdings` carries the paths,
because a person who wants those wants all of them at once rather than one row
at a time.

## Work that outlives the session that found it

A touch says what a live session is holding and expires with it. A **task**
outlives whoever wrote it and is meant to be picked up by somebody who was not
there — the same distinction the ledger exists for, so a task is a node in the
repository's log rather than a record of coordination's own. That also puts it
in reach of an edge from anywhere: a handoff transferring it, a claim it
verifies.

**A task needs only a title.** Delegating is reached for far more often than
anything else here, so it has to be one line. A gate asking for more would
make it expensive enough to skip, and a task nobody has scoped is still a real
thing to have written down.

**`needs` and `blocks` are different facts and must not be conflated.**
`needs` says what *class of input* a task waits on — judgement, identity,
account, payment, command, review — from a closed vocabulary, which is what
lets a rendering be ordered without anybody writing "most urgent first" at the
top, and what tells a reader whether a row is a decision to make or a command
to paste. A dependency between two tasks is the `blocks` edge, node to node.
Running them together makes both useless: the ordering stops meaning anything
and the dependency stops being checkable.

`ledger delegate` records one and hands it over; a name nobody answers to
parks it rather than refusing it, because work is often scoped before there is
anybody to do it. `ledger mine` renders one holder's outstanding tasks grouped
by what they cost — the person's by default, since they read on a machine that
cannot query the log.

## Handing over a body of work

A task is one piece of work. A **handoff** is the larger thing: a session
stopping, or somebody better placed taking over, where what crosses is the
work *plus* what the sender learned that is not in the diff.

What a receiver needs is a **field, not a gate**. `open_questions` refuses to
be empty at construction — a handoff with nothing open is somebody finishing,
and closing the task is the verb for that. Every established result carries
the **source** it came from and a **grade** saying how well it is supported,
because a result the receiver can neither check nor weigh is one they have to
derive again, which is the cost the handoff exists to remove. The grade is a
string this library does not interpret: what grades exist is a project's
question, the same one the ledger refuses to answer about node types.

`not_again` is the cheapest field here and the one that pays most. A dead end
costs the receiver exactly what it cost the sender, and it is invisible in the
tasks, the locks and the diff.

`watch` names the nodes the work rests on, by id or slug. The brief opens with
which of them have a record newer than the handoff — a premise refuted, a
question answered, a task closed — read off the log's own timestamps rather
than any stored standing, so the receiver meets a moved premise before the
established results that rested on it. A research repository wrote this list
by hand in every direction file and nothing ever read it; here it is read.

**Locks move only where the sender held them.** Only a holder can release a
lock, which is an invariant rather than an accident. A scope naming a path
somebody else holds neither takes it from them nor refuses the handoff: the
contest is recorded with both names, the way an unattributable edit already
is, and the receiver is told. Refusing would make handing work over expensive
enough to skip; taking it would revoke a claim from a session still writing
under it.

**One record, three renderings.** A peer in this repository resolves ids and
keeps them, because an id stays true as the work moves where a copy goes
stale. An agent with no repository access gets everything a peer would look up
written out. A person gets a file. They differ in form and never in substance,
and the inlining one earns its keep by proving the record stands alone: if it
is not enough to work from, something was still living in the sender's head.

## Waking whoever it went to

Mail is written first, always. A wake that cannot be made costs latency and
never the work, which is what makes the asymmetry below tolerable rather than
a gap.

The asymmetry is the runtime's own. One of them serves a command that reaches
a session from any process, so waking finishes the job itself. The other has
no command that speaks to a running session at all — so waking returns an
*instruction* naming the caller's own messaging tool and the address to use,
and a skill running inside a session carries it. A third outcome, that nothing
can reach the peer, is reported rather than silently skipped.

The handle a peer is addressed by is **self-reported on the roster**, because
on one runtime it can only be: the session identifiers in its environment are
not what peers address it by, and the address is discoverable only by asking
the runtime from inside the session.

## Watching the repository

Everything here is an append-only file, and nothing pushes: a session folds
the files again on its own next call, which serves a session and nobody else.
`coordination watch` is the fold run on a clock, saying only what is different
from the last look — who arrived and left, what a session now says it is on,
and what reached whose inbox. It consumes nothing: mail is read the way a peek
reads it, so a person watching a peer's inbox is never the reason the peer did
not see a message. The first look is a baseline rather than a replay, the same
convention a run follower keeps when attaching to work already under way.

The same watcher is a **run** for the case where nobody is at the terminal.
`coordination watch --as-run <dir>` declares it as a pipeline, so it survives
its launcher, is followed with `run monitor <dir> --events`, and reports a
stall as a stall. It nudges — a process nobody reads exists to act — by
whatever path each member declared, and lands when the roster is empty,
because a watcher with nobody to watch is finished. Started against an empty
roster it lands at once, which is the truth rather than a process idling for a
population that may never arrive.

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
