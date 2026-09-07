"""What every module lup ships is called, and what it is for.

Separate from the modules themselves, and importing nothing but the type, so
that listing the roster costs nothing. A module file imports its own skills,
its own documents, and whatever optional extra its subject needs; a catalog
that reached into those files to learn a module's name would make the listing
depend on every dependency the listed modules have — which is the cost the
whole arrangement exists to avoid.

So this is the half a reader reaches: ``dev modules`` renders it, generation
resolves requirements against it, and only a module somebody took is ever
built. The other half is :mod:`lup.harness.content.modules.catalog`, which
pairs each of these with a builder that imports its subject when called.

**A default is advice to an adopter, not a description of this repository.**
Four of these are off, and this repository takes all four — it is the
demonstration of its own machinery, so it exercises what it ships. What it
does *not* do is load their prose: adopting a module for its code is a
different question from carrying its paragraph in every session, which is why
``loads_guidance`` is a separate answer. lup builds no realtime app, so it
takes ``realtime`` and declines the section teaching how to write one.
"""

from lup.harness.modules import ModuleSpec

CORE = ModuleSpec(
    id="core",
    title="Core",
    summary=(
        "Reading a codebase, reporting what is left, debugging, and querying "
        "the permission policy, with the reference pages behind them."
    ),
    default_on=True,
)

GIT_WORKFLOW = ModuleSpec(
    id="git-workflow",
    title="Git workflow",
    summary=(
        "Committing, rebasing, merging, and landing a branch, and the page "
        "that says what has to be green before one does."
    ),
    default_on=True,
)

META = ModuleSpec(
    id="meta",
    title="Meta",
    summary=(
        "Changing the machinery rather than the product: the harness a "
        "session runs under, and the walks that move code without losing it."
    ),
    default_on=True,
)

RESOLVER = ModuleSpec(
    id="resolver",
    title="Resolver",
    summary=(
        "Reviewed feedback becoming concerns, worktrees, workers, and an "
        "accepted integration branch, with the supervisor watching it."
    ),
    default_on=True,
    requires=["git-workflow"],
)

VERSION = ModuleSpec(
    id="version",
    title="Version",
    summary=(
        "Deciding and making a version change, with the two agents that "
        "gather the evidence and review the proposal independently."
    ),
    default_on=True,
)

OBSERVABILITY = ModuleSpec(
    id="observability",
    title="Observability",
    summary=(
        "What a session left behind: its trace, what it cost, and the archive "
        "a worktree's records are kept in."
    ),
    default_on=True,
)

SANDBOX = ModuleSpec(
    id="sandbox",
    title="Sandbox",
    summary=(
        "The confined execution a session is offered, and the policy deciding "
        "what may leave it."
    ),
    default_on=True,
)

SETUP = ModuleSpec(
    id="setup",
    title="Setup",
    summary=(
        "Interactive configuration of keys, integrations, and profiles — the "
        "wizard, and the local page that is the same thing in a browser."
    ),
    default_on=True,
)

CONVERSATION = ModuleSpec(
    id="conversation",
    title="Conversation",
    summary="Retaining authenticated AI conversations for later reading.",
    default_on=True,
)

FEEDBACK_LOOP = ModuleSpec(
    id="feedback-loop",
    title="Feedback loop",
    summary=(
        "Turning an observed agent failure into a durable capability change: "
        "the fb- phases, the review pass, and the trace explorer."
    ),
)

RUNS = ModuleSpec(
    id="runs",
    title="Runs",
    summary=(
        "Work that outlives its tool call, declared as a resumable pipeline "
        "rather than scripted, and watchable while it runs."
    ),
)

REALTIME = ModuleSpec(
    id="realtime",
    title="Realtime",
    summary=(
        "Persistent agents that control their own attention: the sleep/wake "
        "loop, and the relay that spells it for subprocess backends."
    ),
)

REFLECTION = ModuleSpec(
    id="reflection",
    title="Reflection",
    summary=(
        "The gate an agent meets on its own output: an independent reviewer "
        "between finishing the work and submitting it."
    ),
)

# lup: ignore[library-default] — the modules this library authors, so the
# roster is what it ships rather than a choice made for an adopter
LIBRARY_SPECS = [
    CORE,
    GIT_WORKFLOW,
    META,
    RESOLVER,
    VERSION,
    OBSERVABILITY,
    SANDBOX,
    SETUP,
    CONVERSATION,
    FEEDBACK_LOOP,
    RUNS,
    REALTIME,
    REFLECTION,
]
"""Every module lup ships, in the order a composition lays them out.

The order is the document's, not an alphabet's: guidance renders as the
chapter spine crossed with this roster, so where a module sits here is where
its prose sits inside whichever chapter its sections named.
"""
