"""Bringing branches together, and settling what the joining breaks.

Two phases need this and they need the same thing. A concern with several
dependencies has to start from a tree that holds all of them, and the run's
final integration has to build one tree from every verified concern — both
are the same problem, differing only in which commits go in.

What makes it one thing rather than a git call is everything that hangs off
a join. Parents are ordered so contested work meets while a merger is on it;
a conflict or a dropped hunk is put to that merger and held to what it
declares; the tree is verified after every parent rather than once at the
end, so a red result names the join that caused it; and every concern is
re-checked against the finished tree. A criterion that stops holding opens
a question rather than failing the run, because later work can legitimately
supersede an earlier one and only a human can say whether this did.

The same re-check can also run after each join, against the concerns that
join touched, which names the merge responsible instead of leaving the
finding to be attributed among every parent. That is what it buys, and it
costs a reviewer turn per overlapping pair, so it is asked for rather than
assumed.
"""

from collections.abc import AsyncIterator
from pathlib import Path

from lup.channels.models import utc_now
from lup.resolver.contracts import ResolverDrained
from lup.resolver.dag import ConcernGraph
from lup.resolver.journal import (
    JoinAuditEvent,
    JoinCompletedEvent,
    JoinPlannedEvent,
    Journal,
    RecheckRepeatedEvent,
)
from lup.resolver.models import (
    ActorRef,
    CarriedParent,
    Concern,
    DropCandidate,
    IntegrationRecord,
    JoinProgress,
    MaterialQuestion,
    MergeReport,
    QuestionAnswer,
    RecheckRuling,
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


def names_parent(declared: str, parent: str) -> bool:
    """Whether a disposition's commit names this candidate's parent.

    Prefix rather than equality, because the merger is shown each candidate
    abbreviated and keyed the full sha against it. Echoing back the twelve
    characters it was given then read as having said nothing, and the refusal
    quoted those same twelve characters at it, so there was no revision that
    could converge: one observed merger dispositioned all three candidates
    with correct rationales, twice, and the run failed on the second.
    """
    return bool(declared) and (
        parent.startswith(declared) or declared.startswith(parent)
    )


def merge_problems(
    merge: MergeReport, conflicted: list[Path], owed: list[DropCandidate]
) -> list[str]:
    """Every obligation this merge report left unmet.

    Two obligations rather than two prohibitions. Every candidate the
    detector raised must be dispositioned — containment, never equality,
    because a legitimate resolution rewrites hunks and requiring the exact
    candidate set back would reject the right answer. That holds for how a
    disposition is keyed as much as for which ones are owed: it is matched
    against the abbreviation the merger was shown rather than the sha it was
    not. And every edit outside
    the conflict set must be declared, because that is where a silent
    override lives: the merger is handed an already-correct tree with
    unrestricted write access, and the canonical joint failure is fixed in a
    file that never conflicted.
    """
    undispositioned = sorted(
        f"{candidate.path.as_posix()} from {candidate.parent[:12]}"
        for candidate in owed
        if not any(
            disposition.path.as_posix() == candidate.path.as_posix()
            and names_parent(disposition.parent, candidate.parent)
            for disposition in merge.dispositions
        )
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


def asked_rulings(
    asked: list[MaterialQuestion], answers: list[QuestionAnswer]
) -> list[RecheckRuling]:
    """Pair each re-check with its recorded answer, dropping the unanswered."""
    recorded = {answer.question_id: answer for answer in answers}
    return [
        RecheckRuling(
            concern_id=question.concern_id,
            criteria=list(question.criteria),
            ruling=recorded[question.id].value,
        )
        for question in asked
        if question.id in recorded
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
        standing_rechecks: bool = False,
    ) -> None:
        self.run = run
        self.runner = runner
        self.questions = questions
        self.verifier = verifier
        self.worktrees = worktrees
        self.journal = journal
        self.standing_rechecks = standing_rechecks

    async def join_commits(
        self,
        lease: WritableRootLease,
        commits: list[str],
        purpose: str,
        title: str,
    ) -> str:
        """Join parents one at a time, spending a turn only where one is owed.

        Every join is pairwise because git cannot merge N branches at once
        when it matters — octopus refuses outright on conflict rather than
        leaving an index to resolve, and 9 of 12 parents measured against one
        run's part-built tree conflicted — so the boundary that moves is the
        session rather than the sequence. One merger sees every parent, and
        by parent six it has genuinely seen one through five.

        Only the parents no other parent contains are merged. The rest are in
        the tree the moment their container lands, so merging them separately
        buys a verification and can buy a turn spent concluding that nothing
        happened.
        """
        if len(commits) < 2:
            raise ValueError("a semantic join requires at least two commits")
        if not lease.root.exists():
            self.worktrees.create(lease, commits[0])
        base = self.worktrees.head(lease)
        current = base
        joined: list[str] = []  # lup: ignore[empty-collection] — audit input
        ordered = self.join_order(lease, base, commits[1:])
        carried = self.carried_parents(lease, ordered)
        riding = {item.commit: item.inside for item in carried}
        tips = [parent for parent in ordered if parent not in riding]
        self.journal.record(JoinPlannedEvent(tips=tips, carried=carried))
        for parent in tips:
            # The loop carries no resumption point, so a resumed join re-enters
            # at the first parent. One already contained in HEAD has nothing to
            # merge, and a merge turn spent on it is not free: the session
            # cannot tell "already joined" from "something upstream is wrong",
            # so it reasonably asks rather than reporting success, and every
            # such round costs a question and a resume. Skip what is already in.
            if self.worktrees.already_joined(lease, parent):
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
                for record in self.verifier.verify(lease.root, base)
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
            if self.standing_rechecks:
                await self.recheck_standing(lease, base, joined[:-1], parent)
            self.record_join_progress(joined, current, len(tips))
            # After the progress file names a tree that exists, for the same
            # reason the worker round checks before its turn: this is where
            # stopping costs nothing. Integration is the longest phase and
            # held no such boundary, so a drain issued during it was never
            # observed and `kill` was the only lever left.
            drain = self.questions.draining()
            if drain is not None:
                raise ResolverDrained(drain.reason, [])
        # A parent that rode inside another was never merged on its own, but
        # its content is in the tree and is exactly as capable of having been
        # dropped there, so the final audit answers for it too.
        await self.audit_join(lease, base, [*joined, *riding], current, purpose)
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
            parent: {path.as_posix() for path in self.authored_by(lease, base, parent)}
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

    def carried_parents(
        self, lease: WritableRootLease, parents: list[str]
    ) -> list[CarriedParent]:
        """Every parent another parent already contains, and which one does.

        Concerns are cut from their dependencies' commits, so the branches
        stack rather than fanning out from the base. A parent inside another
        is in the tree the moment that one lands, and merging it separately
        buys nothing: a verification, and a merger turn where the session
        cannot tell "already joined" from "something upstream is wrong". In
        one measured run, 8 of 21 parents were inside a sibling, and two of
        the three joins spent before it was stopped were on such a parent —
        one of them contained in five different siblings.
        """

        def container_of(parent: str) -> str | None:
            """The first other parent holding this one, of however many do."""
            return next(
                (
                    other
                    for other in parents
                    if other != parent
                    and self.worktrees.contained_in(lease, parent, other)
                ),
                None,
            )

        return [
            CarriedParent(commit=parent, inside=container)
            for parent in parents
            if (container := container_of(parent)) is not None
        ]

    def authored_by(
        self, lease: WritableRootLease, base: str, commit: str
    ) -> list[Path]:
        """Every path one parent wrote, measured from where it forked.

        Measured from the base instead, a parent is credited with every path
        the base moved ahead on since the leases were cut — 124 paths where
        the real answer was 19, in one measured run. That inflation is the
        same for every parent, so every pair appears to overlap and the
        filters built on this stop discriminating: the ordering below ranks
        every parent equally, and the standing re-check examines every pair
        it was written to prune. The fork point is what the drop-candidate
        detector already asks from, for the same reason.
        """
        fork = self.worktrees.merge_base(lease, base, commit)
        return self.worktrees.authored_between(lease, fork, commit)

    def record_join_progress(
        self, joined: list[str], commit: str, planned: int = 0
    ) -> None:
        """Say where the join sequence got to, as each parent lands.

        Written after the parent is committed, so what it names is a tree
        that exists. A resume restores to this commit instead of the run's
        source, which is what stops it discarding joins it already built.
        """
        state = self.run.state
        if state is None:
            return
        before = state.join_progress.completions if state.join_progress else []
        self.run.persist(
            state.model_copy(
                update={
                    "join_progress": JoinProgress(
                        joined=list(joined),
                        commit=commit,
                        planned=planned,
                        completions=[*before, utc_now()],
                    )
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
        enough to read. Off unless asked for: the naming is the whole of what
        it adds, and it costs a reviewer turn for every overlapping pair.

        Only concerns this join could have touched are re-examined. A join
        that changes no file an earlier concern changed cannot have broken its
        criteria in a way the per-join verification above would not already
        have caught, and re-reading every concern after every join would cost
        a reviewer turn per pair.
        """
        state = self.run.state
        if state is None or not standing:
            return
        changed = {path.as_posix() for path in self.authored_by(lease, base, parent)}
        owners = {
            outcome.commit: outcome.concern_id
            for outcome in state.outcomes
            if outcome.commit is not None
        }
        for earlier in standing:
            if earlier not in owners:
                continue
            overlap = changed & {
                path.as_posix() for path in self.authored_by(lease, base, earlier)
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
    ) -> list[MaterialQuestion]:
        """Re-run each concern's reviewer against the tree its siblings built.

        ``review_turn`` runs against a concern's own worktree before
        integration, so nothing re-checked a criterion that stopped holding
        once a sibling landed. This is the only instrument aimed at "concern
        three's criterion two no longer holds now that concern seven merged"
        — the final audit is about content that went missing, which is a
        different failure.

        A failed criterion opens a question rather than failing the run,
        because later work can legitimately supersede an earlier criterion
        and only a human can say whether this did. The questions are returned
        rather than merely queued, so integration waits on the answers it is
        about to act on instead of completing around them.
        """
        integrated = {identifier: True for identifier in integration.concerns}

        async def asked() -> AsyncIterator[MaterialQuestion]:
            """Each concern whose criteria no longer hold in the merged tree."""
            for concern in state.concerns:
                if concern.id not in integrated:
                    continue
                question = await self.recheck_concern(
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
                if question is not None:
                    yield question

        return [question async for question in asked()]

    async def settle_rechecks(
        self, asked: list[MaterialQuestion]
    ) -> list[RecheckRuling]:
        """Wait for these re-checks, and report what each was ruled.

        Queuing publishes a question; it does not wait for one. So the run
        used to reach the end of integration with its re-checks unanswered,
        mark the branch complete, and finish — and a `regression` ruling that
        arrived afterwards was recorded into a run that had already shipped
        it. Waiting parks the run instead, which costs nothing to resume and
        makes the answer arrive before the decision it governs.

        Only the final pass waits. A per-join standing check already has a
        consumer — it is what stops the same finding being re-asked join
        after join — and every concern it examines is examined again here,
        against the finished tree, where the answer can still change what
        happens.
        """
        if not asked:
            return asked_rulings(asked, [])
        answers = await self.questions.await_questions(asked)
        return asked_rulings(asked, answers.answers)

    async def recheck_concern(
        self,
        concern: Concern,
        worktree: Path,
        *,
        situation: str,
        occasion: str,
        lost_because: str,
    ) -> MaterialQuestion | None:
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
            return None
        if self.standing_ruling_exists(concern.id, lost):
            self.journal.record(
                RecheckRepeatedEvent(
                    concern_id=concern.id, occasion=occasion, criteria=sorted(lost)
                )
            )
            return None
        question = MaterialQuestion(
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
        self.questions.queue_questions([question], concern.id)
        return question

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
