# Resolver lifecycle and recovery

`ResolverCore` is the single provider-neutral resolver. Concrete entries inject
worker and reviewer factories, a native skill invocation renderer, a question
broker, a process launcher, and an explicit state root. Environment variables
never select a resolver implementation.

State lives at `<state-root>/<run-id>/` as an atomic schema-versioned
`state.json` plus concerns, questions, answers, leases, dependency bases,
agent rounds, reviews, and integration projections. Restart must load only that
explicit run and verify recorded branches, commits, worktrees, and leases.

The lifecycle inventories concerns, brokers material questions, persists
eligibility and integration approval, validates the dependency DAG, leases a
non-overlapping branch/worktree per approved concern, and executes independent
topological nodes concurrently. Root nodes start from the source snapshot,
single-parent nodes start from the verified parent commit, and multi-parent
nodes use an orchestrator-prepared semantic join.

Workers may edit only their leased root and never create branches or commits.
The orchestrator validates the diff and creates the real commit, then an
independent reviewer checks every persisted acceptance criterion. Bounded
revision and question rounds are persisted. Only verified commits reach the
dedicated review-master worktree.

Integration runs configured verification commands, requests an independent
final typed review, records cleanup or retained-worktree instructions, and
stops at human acceptance. It never merges into the user's branch. Failure
records partial evidence and retains actionable cleanup state.
