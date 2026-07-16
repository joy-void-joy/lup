# Resolver lifecycle and recovery

`ResolverCore` is the single provider-neutral resolver. Concrete entries inject
worker and reviewer factories, a native skill invocation renderer, a question
broker, a process launcher, and an explicit state root. Environment variables
never select a resolver implementation.

Run the native composition directly with one of:

```text
uv run lup-devtools harness resolve --adapter claude
uv run lup-devtools harness resolve --adapter codex
```

`--run-id` selects a stable run for explicit recovery. Without it, the command
uses the current source commit. The generated Claude workflow and Codex skill
only launch these composition roots; they contain no resolver phases.

State lives at `<state-root>/<run-id>/` as an atomic schema-versioned
`state.json` plus concerns, questions, answers, leases, dependency bases,
agent rounds, reviews, and integration projections. Restart must load only that
explicit run and verify recorded branches, commits, worktrees, and leases.

For a new run, the composition root scans tracked files for actionable review
notes and passes their source context to a read-only structured planning turn.
The planner must assign every note exactly once to a generalized concern. If a
note-bearing file differs from `HEAD`, an unattached Git commit captures those
files through a temporary index. The user's branch, `HEAD`, index, and working
tree are unchanged.

The lifecycle inventories concerns, brokers material questions, persists
eligibility and integration approval, validates the dependency DAG, leases a
non-overlapping branch/worktree per approved concern, and executes independent
topological nodes concurrently. Root nodes start from the source snapshot,
single-parent nodes start from the verified parent commit, and multi-parent
nodes use an orchestrator-prepared semantic join.

The initial question batch includes an approve/defer decision for each planned
concern. A directly approved concern is still ineligible when any dependency is
deferred. These answers, rather than planner guesses, control the work DAG.

Workers may edit only their leased root and never create branches or commits.
The orchestrator validates the diff and creates the real commit, then an
independent reviewer checks every persisted acceptance criterion. Bounded
revision and question rounds are persisted. A worker removes only the markers
belonging to criteria it resolved, so deferred notes remain visible. Only
verified commits reach the dedicated review-master worktree.

Integration runs configured verification commands, requests an independent
final typed review, records cleanup or retained-worktree instructions, and
stops at human acceptance. It never merges into the user's branch. Failure
records partial evidence and retains actionable cleanup state.
