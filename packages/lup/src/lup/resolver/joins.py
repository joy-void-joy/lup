"""Bringing branches together, and settling what the joining breaks.

Two phases need this and they need the same thing. A concern with several
dependencies has to start from a tree that holds all of them, and the run's
final integration has to build one tree from every verified concern — both
are the same problem, differing only in which commits go in.

What makes it one thing rather than a git call is everything that hangs off
a join. Parents are ordered so contested work meets while a merger is on it;
a conflict or a dropped hunk is put to that merger and held to what it
declares; the tree is verified after every parent rather than once at the
end, so a red result names the join that caused it; and a criterion an
earlier concern had met is re-checked whenever a later parent touches the
same files. A criterion that stops holding opens a question rather than
failing the run, because later work can legitimately supersede an earlier
one and only a human can say whether this did.
"""

from pathlib import Path

from lup.resolver.dag import ConcernGraph
from lup.resolver.journal import (
    ActorRef,
    JoinAuditEvent,
    JoinCompletedEvent,
    Journal,
    RecheckRepeatedEvent,
)
from lup.resolver.models import (
    Concern,
    DropCandidate,
    IntegrationRecord,
    JoinProgress,
    MaterialQuestion,
    MergeReport,
    ResolveState,
    ReviewReport,
    WritableRootLease,
)
from lup.resolver.orchestrator import WorktreeOrchestrator
from lup.resolver.questions import QuestionBroker
from lup.resolver.run import ResolveRun, ResolverInvariantError
from lup.resolver.turns import TurnRunner
from lup.resolver.verification import Verifier
from lup.runtime.models import TurnInput, turn_request


def merge_problems(
    merge: MergeReport, conflicted: list[Path], owed: list[DropCandidate]
) -> list[str]:
    """Every obligation this merge report left unmet.

    Two obligations rather than two prohibitions. Every candidate the
    detector raised must be dispositioned — containment, never equality,
    because a legitimate resolution rewrites hunks and requiring the exact
    candidate set back would reject the right answer. And every edit outside
    the conflict set must be declared, because that is where a silent
    override lives: the merger is handed an already-correct tree with
    unrestricted write access, and the canonical joint failure is fixed in a
    file that never conflicted.
    """
    dispositioned = {
        (disposition.parent, disposition.path.as_posix())
        for disposition in merge.dispositions
    }
    undispositioned = sorted(
        f"{candidate.path.as_posix()} from {candidate.parent[:12]}"
        for candidate in owed
        if (candidate.parent, candidate.path.as_posix()) not in dispositioned
    )
    unreasoned = sorted(
        disposition.path.as_posix()
        for disposition in merge.dispositions
        if not disposition.rationale.strip()
    )
    declared = {edit.path.as_posix() for edit in merge.out_of_conflict_edits}
    conflicting = {path.as_posix() for path in conflicted}
    undeclared = sorted(
        disposition.path.as_posix()
        for disposition in merge.dispositions
        if disposition.fate in {"rewritten", "superseded", "dropped"}
        and disposition.path.as_posix() not in conflicting
        and disposition.path.as_posix() not in declared
    )
    return [
        *(
            [f"content lost with nothing said about it: {', '.join(undispositioned)}"]
            if undispositioned
            else []
        ),
        *(
            [f"dispositioned without a rationale: {', '.join(unreasoned)}"]
            if unreasoned
            else []
        ),
        *(
            [f"changed outside the conflict set undeclared: {', '.join(undeclared)}"]
            if undeclared
            else []
        ),
    ]


class Joiner:
    """Join commits into one tree, and resolve whatever the joining breaks."""

    def __init__(
        self,
        run: ResolveRun,
        runner: TurnRunner,
        questions: QuestionBroker,
        verifier: Verifier,
        worktrees: WorktreeOrchestrator,
        journal: Journal,
    ) -> None:
        self.run = run
        self.runner = runner
        self.questions = questions
        self.verifier = verifier
        self.worktrees = worktrees
        self.journal = journal

    async def join_commits(
        self,
        lease: WritableRootLease,
        commits: list[str],
        purpose: str,
        title: str,
    ) -> str:
        """Join parents one at a time, spending a turn only where one is owed.

        Every join is pairwise because git cannot merge N branches at once
        when it matters — octopus refuses on conflict — so the boundary that
        moves is the session rather than the sequence. One merger sees every
        parent, and by parent six it has genuinely seen one through five.
        """
        if len(commits) < 2:
            raise ValueError("a semantic join requires at least two commits")
        if not lease.root.exists():
            self.worktrees.create(lease, commits[0])
        base = self.worktrees.head(lease)
        current = base
        joined: list[str] = []  # lup: ignore[empty-collection] — audit input
        for parent in self.join_order(lease, base, commits[1:]):
            # The loop carries no resumption point, so a resumed join re-enters
            # at the first parent. One already contained in HEAD has nothing to
            # merge, and a merge turn spent on it is not free: the session
            # cannot tell "already joined" from "something upstream is wrong",
            # so it reasonably asks rather than reporting success, and every
            # such round costs a question and a resume. Skip what is already in.
            if self.worktrees.contains(lease, parent):
                joined.append(parent)
                continue
            before = current
            conflicted = self.worktrees.prepare_join(lease, [before, parent])
            if conflicted:
                await self.adjudicate(lease, parent, purpose, [])
            current = self.worktrees.commit_join(lease, title)
            # What this parent added since it forked, and whether the join
            # still holds it. Asking against the fork point rather than the
            # previous head is what keeps a dependency's own content out of
            # the obligation list.
            fork = self.worktrees.merge_base(lease, before, parent)
            owed = self.worktrees.drop_candidates(lease, fork, parent, current)
            if owed:
                await self.adjudicate(lease, parent, purpose, owed)
                current = self.worktrees.commit_join(lease, title)
            joined.append(parent)
            # Verifying after every join is what makes a red result name a
            # join. Running it once over the finished tree gave the same
            # failure with twelve candidates and no way to tell which one
            # introduced it.
            failed = [
                record.name
                for record in self.verifier.verify(lease.root)
                if not record.passed
            ]
            if failed:
                await self.adjudicate(
                    lease,
                    parent,
                    f"{purpose} — joining {parent[:12]} broke: {', '.join(failed)}",
                    [],
                )
                current = self.worktrees.commit_join(lease, title)
            self.journal.record(
                JoinCompletedEvent(
                    parent=parent,
                    commit=current,
                    conflicted=conflicted,
                    broke=failed,
                )
            )
            await self.recheck_standing(lease, base, joined[:-1], parent)
            self.record_join_progress(joined, current)
        await self.audit_join(lease, base, joined, current, purpose)
        return current

    def join_order(
        self, lease: WritableRootLease, base: str, parents: list[str]
    ) -> list[str]:
        """Order the joins so related work meets while the session is on it.

        Completion order is the order concerns happened to finish, which
        scatters related work across the sequence and puts a merger's own
        precedent behind five unrelated joins. Parents that overlap no file
        with anything already placed go first — those are the ones git
        settles alone — and the rest follow in dependency order, so each
        contested join lands next to the work it contests.
        """
        touched = {
            parent: {
                path.as_posix()
                for path in self.worktrees.changed_between(lease, base, parent)
            }
            for parent in parents
        }
        ranked = sorted(
            parents,
            key=lambda parent: (
                sum(
                    1
                    for other in parents
                    if other != parent and touched[parent] & touched[other]
                ),
                self.dependency_depth(parent),
                parent,
            ),
        )
        return ranked

    def record_join_progress(self, joined: list[str], commit: str) -> None:
        """Say where the join sequence got to, as each parent lands.

        Written after the parent is committed, so what it names is a tree
        that exists. A resume restores to this commit instead of the run's
        source, which is what stops it discarding joins it already built.
        """
        state = self.run.state
        if state is None:
            return
        self.run.persist(
            state.model_copy(
                update={
                    "join_progress": JoinProgress(joined=list(joined), commit=commit)
                }
            )
        )

    async def adjudicate(
        self,
        lease: WritableRootLease,
        parent: str,
        purpose: str,
        owed: list[DropCandidate],
    ) -> None:
        """Put one join to the merger and hold its report to what it declared."""
        conflicted = self.worktrees.conflicted_paths(lease)
        merge = await self.runner.merge_turn(lease, parent, purpose, conflicted, owed)
        # An incompletion is the merger's considered answer and spending
        # another turn on it only re-derives it. An accounting gap is
        # different: the tree may be right and the declaration short, which
        # is precisely what a second turn can settle.
        if not merge.completed or merge.unresolved_paths:
            raise ResolverInvariantError(
                f"semantic join failed for {lease.concern_id}: "
                + (merge.blocked or merge.summary)
            )
        problems = merge_problems(merge, conflicted, owed)
        if problems:
            merge = await self.runner.merge_turn(
                lease, parent, purpose, conflicted, owed, problems
            )
            problems = merge_problems(merge, conflicted, owed)
        if problems:
            raise ResolverInvariantError(
                f"semantic join for {lease.concern_id} was not accounted for: "
                + "; ".join(problems)
            )
        self.runner.record_join(parent, merge)

    async def audit_join(
        self,
        lease: WritableRootLease,
        base: str,
        joined: list[str],
        result: str,
        purpose: str,
    ) -> None:
        """Re-check every parent against the finished tree, not just the last.

        A hunk lost at join three and never noticed is invisible to the
        per-join check, which only ever looked at one parent against one
        result. Running the same detector over every parent once the tree is
        final is what catches it.
        """
        owed = [
            candidate
            for parent in joined
            for candidate in self.worktrees.drop_candidates(
                lease, self.worktrees.merge_base(lease, base, parent), parent, result
            )
        ]
        if not owed:
            return
        self.journal.record(
            JoinAuditEvent(parents=joined, outstanding=len(owed), commit=result)
        )
        await self.adjudicate(lease, joined[-1], f"{purpose} — final audit", owed)
        self.worktrees.commit_join(lease, "resolve: settle the final join audit")

    def dependency_depth(self, commit: str) -> int:
        """How deep in the concern graph the concern that produced this sits."""
        state = self.run.state
        if state is None:
            return 0
        owner = next(
            (
                outcome.concern_id
                for outcome in state.outcomes
                if outcome.commit == commit
            ),
            None,
        )
        if owner is None:
            return 0
        return len(ConcernGraph(state.concerns).ancestors(owner))

    async def recheck_standing(
        self,
        lease: WritableRootLease,
        base: str,
        standing: list[str],
        parent: str,
    ) -> None:
        """Ask whether this join stopped an already-joined concern holding.

        A regression is precisely an earlier parent's criterion that no longer
        holds. Checking that only after the last join reports it with every
        parent a candidate and the merger long past the context; asking it
        here names the join that caused it while the tree is still small
        enough to read.

        Only concerns this join could have touched are re-examined. A join
        that changes no file an earlier concern changed cannot have broken its
        criteria in a way the per-join verification above would not already
        have caught, and re-reading every concern after every join would cost
        a reviewer turn per pair.
        """
        state = self.run.state
        if state is None or not standing:
            return
        changed = {
            path.as_posix()
            for path in self.worktrees.changed_between(lease, base, parent)
        }
        owners = {
            outcome.commit: outcome.concern_id
            for outcome in state.outcomes
            if outcome.commit is not None
        }
        for earlier in standing:
            if earlier not in owners:
                continue
            overlap = changed & {
                path.as_posix()
                for path in self.worktrees.changed_between(lease, base, earlier)
            }
            if not overlap:
                continue
            concern = next(
                (item for item in state.concerns if item.id == owners[earlier]), None
            )
            if concern is None:
                continue
            await self.recheck_concern(
                concern,
                lease.root,
                situation=(
                    "A later concern has just been joined into the tree your "
                    "concern is already in, and the two changed the same "
                    "files. Re-check your concern's acceptance criteria "
                    "against this tree. A criterion you passed before may no "
                    "longer hold; say so plainly if it does not.\n\n"
                    "Files both touched:\n"
                    + "\n".join(f"- {path}" for path in sorted(overlap))
                    + f"\n\nJoined commit: {parent[:12]}\nWorktree: {lease.root}"
                ),
                occasion=f"join-{parent[:12]}",
                lost_because=f"once {parent[:12]} was joined into the same tree",
            )

    async def recheck_criteria(
        self, state: ResolveState, integration: IntegrationRecord
    ) -> None:
        """Re-run each concern's reviewer against the tree its siblings built.

        ``review_turn`` runs against a concern's own worktree before
        integration, so nothing re-checked a criterion that stopped holding
        once a sibling landed. This is the only instrument aimed at "concern
        three's criterion two no longer holds now that concern seven merged"
        — the final audit is about content that went missing, which is a
        different failure.

        A failed criterion opens a question rather than failing the run,
        because later work can legitimately supersede an earlier criterion
        and only a human can say whether this did.
        """
        integrated = {identifier: True for identifier in integration.concerns}
        for concern in state.concerns:
            if concern.id not in integrated:
                continue
            await self.recheck_concern(
                concern,
                integration.worktree,
                situation=(
                    "Every concern in this run is now integrated into one "
                    "tree. Re-check your concern's acceptance criteria "
                    "against that tree rather than the worktree you "
                    "reviewed. A criterion you passed before may no "
                    "longer hold now that a sibling has landed; say so "
                    "plainly if it does not.\n\n"
                    f"Integrated concerns: {', '.join(integration.concerns)}\n"
                    f"Worktree: {integration.worktree}"
                ),
                occasion="integrated",
                lost_because="once every sibling is integrated",
            )

    async def recheck_concern(
        self,
        concern: Concern,
        worktree: Path,
        *,
        situation: str,
        occasion: str,
        lost_because: str,
    ) -> None:
        """Ask one concern's reviewer whether its criteria still hold here.

        A failed criterion opens a question rather than failing the run,
        because later work can legitimately supersede an earlier criterion
        and only a human can say whether this did. The question is keyed by
        occasion so the same concern examined after two different joins asks
        twice rather than colliding on one id — the second failure is its own
        fact, and it names a different join.
        """
        reviewer = self.runner.reviewer_session(
            ActorRef(kind="reviewer", id=concern.id), worktree
        )
        declared = {criterion.id: True for criterion in concern.criteria}
        # The reviewer session may be fresh — a resumed run, a parked actor —
        # so the concern record rides with the prompt rather than being
        # assumed remembered. Criteria reconstructed by archaeology produced
        # labels no declared id matched, and every mismatch read as a loss.
        prompt = (
            f"{situation}\n\n"
            "Your concern's persisted record, including the acceptance "
            f"criteria to re-check:\n{concern.model_dump_json(indent=2)}\n\n"
            "Report criteria_met using exactly the declared criterion ids "
            "above — echo an id verbatim when its criterion still holds, and "
            "omit it when it does not."
        )
        result = await reviewer.turn(turn_request(TurnInput(text=prompt), ReviewReport))
        unknown = [
            label for label in result.output.criteria_met if label not in declared
        ]
        if unknown:
            correction = (
                "Your report labelled criteria this concern never declared: "
                + ", ".join(unknown)
                + ". Resubmit with criteria_met drawn only from the declared "
                "ids: " + ", ".join(declared)
            )
            result = await reviewer.turn(
                turn_request(TurnInput(text=correction), ReviewReport)
            )
        met = {identifier: True for identifier in result.output.criteria_met}
        lost = [
            criterion.id for criterion in concern.criteria if criterion.id not in met
        ]
        if not lost:
            return
        if self.standing_ruling_exists(concern.id, lost):
            self.journal.record(
                RecheckRepeatedEvent(
                    concern_id=concern.id, occasion=occasion, criteria=sorted(lost)
                )
            )
            return
        self.questions.queue_questions(
            [
                MaterialQuestion(
                    id=f"{concern.id}-superseded-{occasion}",
                    concern_id=concern.id,
                    prompt=(
                        f"{concern.id} no longer meets {', '.join(lost)} "
                        f"{lost_because}. The reviewer says: "
                        f"{result.output.reason}. Was this criterion "
                        "superseded by later work, or is this a regression?"
                    ),
                    choices=["superseded", "regression"],
                    closed_choices=True,
                    criteria=sorted(lost),
                )
            ],
            concern.id,
        )

    def standing_ruling_exists(self, concern_id: str, lost: list[str]) -> bool:
        """Whether this lost-criteria set was already put to the humans.

        The same standing finding reproduced by join after join asked five
        identical questions in one run. One open question, or one answered
        "superseded", settles the set; only a "regression" ruling — whose
        remediation makes a later identical loss a genuinely new fact —
        lets the question be asked again.
        """
        state = self.run.state
        if state is None or state.questions is None:
            return False
        lost_map = {identifier: True for identifier in lost}
        answered = {
            answer.question_id: answer.value
            for answer in (state.answers.answers if state.answers else [])
        }
        for question in state.questions.questions:
            if question.concern_id != concern_id or not question.criteria:
                continue
            if {identifier: True for identifier in question.criteria} != lost_map:
                continue
            ruling = answered[question.id] if question.id in answered else None
            if ruling != "regression":
                return True
        return False
