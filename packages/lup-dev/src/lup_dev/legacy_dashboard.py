"""Reviews parked in the first lup's dashboard, through its host half.

A bridge: until lup's own dashboard exists, the operator reads reviews in the
first lup's, where the interim review hook shows them an agent's calls. The
reviews an agent submits from a worktree are parked here, through `Host`
(`LegacyQueue`, a `Queue`; `docs/review-flow.md`, *What the operator sees*).

Only `lup_dev.cli` imports this module; it goes, with its setting, when lup's own
dashboard lands.

The first lup's host half (`policy/assets/host.py` in its checkout) uses only the
standard library, so it's loaded by path, and the dashboard reads exactly the
records it writes. What it answers is modelled here, read against the host at
`40c2d28`:
- a review is one `Propose`: each file whole after the change, its text before
  recorded as the review's precondition; the dashboard works out the diff;
- the before side is exported into the worktree (`Export`) and the review's paths
  are there, since the dashboard retires a waiting review whose recorded files
  don't stand on disk as recorded; line comments come back to the worktree's paths;
- the dashboard expires a review an hour after it's parked when its requester
  isn't on the first lup's roster, which nothing parked from here is, so a
  worktree's keeper parks an expired review again under another id, and the
  remarks on each id are read;
- an approval is spent through the host, as an agent's repeated call spends it,
  so the dashboard records the review as carried out;
- a reply is appended to the relay as the first lup's own `review reply` records
  one, and a withdrawal as the transition its own cancel records, each through the
  host half's functions.
"""

import asyncio
import importlib.util
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Literal, override

from filelock import FileLock, Timeout
from pydantic import TypeAdapter

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.git import Git
from lup_dev.inbox.notices import Notices, NotifySend
from lup_dev.layout import CheckoutLayout, Layout, StoreLayout
from lup_dev.policy.importers import BackgroundSpawner, Spawner
from lup_dev.review import (
    Answer,
    Answered,
    Gone,
    LineComment,
    Look,
    Queue,
    Remark,
    ReviewedFile,
    ReviewError,
    ReviewRequest,
    Waiting,
)
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from lup_dev.settings import LupDevSettings


class Parked(Model):
    """What the host half answers when it's asked to park a review."""

    state: Literal["pending", "approved", "rejected", "unavailable"]
    """`pending` while the review waits; `approved` once its approval is spent;
    `rejected` once it's declined; `unavailable` where it can't be parked."""
    id: str
    reason: str


class Entry(Model):
    """A review as the first lup's relay keeps it: the part a wait reads."""

    id: str
    state: str
    """`pending` while it waits; `expired`, `stale` or another state once it left."""
    outcome: str = ""
    """Why it left the queue, where the relay says."""


class HostComment(Model):
    """A line comment as the first lup keeps it, on a file where the page shows it."""

    path: Path
    start: int
    end: int
    side: Literal["before", "after"] = "after"
    note: str

    def comment(self, export: Path) -> LineComment:
        """Return the comment on the file's path in the checkout, out of `export`."""
        path = (
            self.path.relative_to(export)
            if self.path.is_relative_to(export)
            else self.path
        )
        return LineComment(
            path=path, first=self.start, last=self.end, side=self.side, note=self.note
        )


class HostSaid(Model):
    """What the operator wrote on a review, as the first lup keeps it."""

    note: str = ""
    comments: list[HostComment] = []

    def remark(self, export: Path) -> Remark:
        """Return what the operator wrote, its comments on the checkout's paths."""
        return Remark(
            note=self.note,
            comments=[comment.comment(export) for comment in self.comments],
        )


class HostAnswer(HostSaid):
    """The operator's decision on a review, with what they wrote."""

    approved: bool

    def answer(self, export: Path) -> Answer:
        """Return the decision, its comments on the checkout's paths."""
        return Answer(
            approved=self.approved,
            note=self.note,
            comments=[comment.comment(export) for comment in self.comments],
        )


class RecordedAnswer(Model):
    """An answer as the host keeps it, naming the review it settles."""

    question: str
    answer: HostAnswer


class RecordedRemark(Model):
    """A remark the operator sent without deciding, as the host keeps it."""

    question: str
    remark: HostSaid


class Reply(Model):
    """What the requester says back on its own review, as the first lup keeps it."""

    author: str
    text: str
    at: datetime


class RecordedReply(Model):
    """A reply as the first lup's relay keeps it, naming the review it's on."""

    question: str
    reply: Reply


class ProposedFile(Model):
    """One file of a `Propose`: where it is, and the text it becomes."""

    path: Path
    content: str | None
    """Its text after the change; none where the change deletes it."""
    about: str = ""
    """What the page shows on the file's header, under its path."""


class Proposal(Model):
    """What a `Propose` carries: why, and every file it changes."""

    why: str
    files: list[ProposedFile]


class Call(Model):
    """A review as the host half parks it.

    The same at every park, so the host recognizes it again by its fingerprint: a
    review still waiting is found again rather than parked twice, and an answer
    given to it is read back.
    """

    root: Path
    """The checkout the review is parked from: its relay is kept there."""
    requester: str
    agent: str = ""
    """The subagent that asked, which the host keeps beside the review."""
    rule: str
    """What asks for the review, in the first lup's terms."""
    proposal: Proposal
    preconditions: dict[Path, str | None]
    """Each file's text before the change, by its path in the export."""
    reason: str
    answers: Path
    """The host's file of the operator's answers and remarks on the relay's reviews."""


class ExportedFile(Model):
    """One file of a review, as its export shows it: both sides, and its header."""

    path: Path
    """Its path in the checkout."""
    before: str | None
    after: str | None
    about: str = ""


class Export(Model):
    """A review's before side, written where the first lup's dashboard binds it.

    Each file's text before the change stands at its path below `directory` while
    the review waits, and the review records each file there: the dashboard retires
    a waiting review whose recorded files don't stand on disk as recorded, and the
    page shows each path under this directory.
    """

    directory: Path
    files: list[ExportedFile] = []

    def proposal(self, why: str) -> Proposal:
        """Return the `Propose` showing every file, each at its path in the export."""
        return Proposal(
            why=why,
            files=[
                ProposedFile(
                    path=self.directory / each.path,
                    content=each.after,
                    about=each.about,
                )
                for each in self.files
            ],
        )

    def preconditions(self) -> dict[Path, str | None]:
        """Return each file's text before the change, by its path in the export."""
        return {self.directory / each.path: each.before for each in self.files}

    def write(self) -> None:
        """Write each file's before side, replacing whatever the directory held."""
        self.remove()
        for each in self.files:
            if each.before is None:
                continue
            kept = self.directory / each.path
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes(each.before.encode())

    def remove(self) -> None:
        """Remove the export, where it stands."""
        if self.directory.exists():
            shutil.rmtree(self.directory)


class Host(Model, arbitrary_types_allowed=True):
    """The first lup's host half, loaded from its checkout, which parks reviews."""

    module: ModuleType

    @classmethod
    def source(cls, legacy: Path) -> Path:
        """Say where the host half is, in the first lup's checkout at `legacy`."""
        assets = legacy / "packages" / "lup" / "src" / "lup" / "policy" / "assets"
        return assets / "host.py"

    @classmethod
    def load(cls, source: Path) -> Host:
        """Load the host half from its file at `source`."""
        spec = importlib.util.spec_from_file_location("lup_legacy_host", source)
        if spec is None or spec.loader is None:
            message = f"Python can't load {source} as a module"
            raise ReviewError(message)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return cls(module=module)

    def relay(self, root: Path) -> Path:
        """Say where the reviews parked from `root` are kept, for dashboards to read."""
        return Path(self.module.review_home(root)) / ".lup" / "questions.jsonl"

    def answers(self, relay: Path) -> Path:
        """Say where the operator's answers and remarks on the relay's reviews go."""
        home = self.module.review_answers_home("LUP_REVIEW_ANSWERS")
        return Path(self.module.review_answers(relay, home))

    def park(self, call: Call) -> Parked:
        """Park the review, or read back the review already parked for it.

        An approval read back is spent: the host claims it, once.
        """
        preconditions = TypeAdapter(dict[Path, str | None]).dump_json(
            call.preconditions
        )
        try:
            return Parked.model_validate(
                self.module.review_hook_call(
                    call.root,
                    call.requester,
                    "Propose",
                    call.proposal.model_dump_json(),
                    preconditions.decode(),
                    call.reason,
                    call.rule,
                    "quality_review",
                    "human_only",
                    answers=str(call.answers),
                    agent=call.agent,
                )
            )
        except (OSError, ValueError) as failure:
            message = f"the first lup's host half couldn't park the review: {failure}"
            raise ReviewError(message) from failure

    def spend(self, call: Call, review: str) -> None:
        """Spend the approval of `review`, so the dashboard records it as carried out.

        The host claims an approval when the review is parked again, once.
        """
        spent = self.park(call)
        if spent.state != "approved" or spent.id != review:
            message = (
                f"the approval of review {review} couldn't be spent through the first "
                f"lup's host half: it answered {spent.state} for review {spent.id}"
            )
            raise ReviewError(message)

    def reply(self, relay: Path, recorded: RecordedReply) -> None:
        """Append `recorded` to the relay at `relay`, as the first lup records a reply."""
        try:
            self.module.append_relay_records(
                relay, lambda: [recorded.model_dump(mode="json")]
            )
        except (OSError, ValueError) as failure:
            message = f"the first lup's relay at {relay} took no reply: {failure}"
            raise ReviewError(message) from failure

    def cancel(self, relay: Path, review: str, why: str) -> None:
        """Move `review` out of the relay's queue as cancelled, saying `why`.

        The transition the first lup's own cancel records, appended through the
        host half, so the dashboard shows the review withdrawn.
        """
        try:
            self.module.transition_relay_entry(
                relay, review, {"state": "cancelled", "outcome": why}
            )
        except (OSError, ValueError) as failure:
            message = f"the first lup's relay at {relay} couldn't withdraw {review}: {failure}"
            raise ReviewError(message) from failure

    def entries(self, relay: Path) -> dict[str, Entry]:
        """Return the reviews kept in the relay at `relay`, by id."""
        try:
            return TypeAdapter(dict[str, Entry]).validate_python(
                self.module.native_review_records(relay)
            )
        except ValueError as failure:
            message = f"the first lup's relay at {relay} can't be read: {failure}"
            raise ReviewError(message) from failure

    def records(self, answers: Path) -> list[RecordedAnswer | RecordedRemark]:
        """Return the answers and remarks kept in `answers`, oldest first."""
        try:
            return TypeAdapter(list[RecordedAnswer | RecordedRemark]).validate_python(
                self.module.review_records(answers)
            )
        except ValueError as failure:
            message = f"the first lup's answers at {answers} can't be read: {failure}"
            raise ReviewError(message) from failure

    def decided(self, answers: Path, review: str) -> HostAnswer | None:
        """Return the operator's answer to `review`, or none while it waits."""
        return next(
            (
                record.answer
                for record in self.records(answers)
                if isinstance(record, RecordedAnswer) and record.question == review
            ),
            None,
        )

    def remarks(self, answers: Path, reviews: list[str]) -> list[HostSaid]:
        """Return the remarks the operator sent on any of `reviews`, oldest first."""
        return [
            record.remark
            for record in self.records(answers)
            if isinstance(record, RecordedRemark) and record.question in reviews
        ]


def legacy_checkout(checkout: Path, settings: LupDevSettings) -> Path:
    """Find the first lup's checkout as the interim review hook does.

    The setting is read from the directory holding the repository's git directory,
    as the hook reads it, so one setting points both at it.
    """
    common = Git(cwd=checkout).text(
        "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    return Path(common).parent / settings.lup_interim_review_legacy_checkout


class Kept(Model):
    """One review parked in the first lup's dashboard, as its queue records it."""

    call: Call
    """What parks it, the same at every park, so the host knows it again."""
    parked: list[str]
    """Each id the dashboard gave it, oldest first: another each time it's parked
    again after expiring. The last is the one it stands under."""
    frozen: bool = False
    """Whether an agent froze on it: the mark is said again under each id."""


class Keeping(Model):
    """The reviews one worktree parked in the first lup's dashboard, by number."""

    reviews: dict[int, Kept] = {}

    def review(self, number: int) -> Kept:
        """Return review `number`'s record, refusing a number not parked."""
        if number not in self.reviews:
            message = f"no review {number} is parked in the first lup's dashboard"
            raise ReviewError(message)
        return self.reviews[number]

    def recorded(self, number: int, kept: Kept) -> Keeping:
        """Return the records with review `number` recorded as `kept`."""
        return Keeping(reviews={**self.reviews, number: kept})

    def without(self, number: int) -> Keeping:
        """Return the records without review `number`."""
        return Keeping(
            reviews={
                each: kept for each, kept in self.reviews.items() if each != number
            }
        )


class LegacyQueue(Queue, Model, arbitrary_types_allowed=True):
    """The reviews an agent submits from one worktree, parked in the first lup's dashboard.

    Each is one `Propose`, its before side exported under the review's directory in
    the worktree (`ReviewLayout.before`; `docs/review-flow.md`, *The first lup's
    dashboard*). The worktree's store records what's parked (`StoreLayout.parked`):
    what parks each review, the ids the dashboard gave it, and whether an agent froze
    on it.

    The operator is told once (*Told once, never re-told*): a desktop notice when a
    review is first parked, and a reply in its thread with a notice when an agent
    first freezes on it. The dashboard expires a review an hour after it's parked,
    so parking starts the worktree's keeper unless one runs, which parks each
    expired review again, silently, until nothing waits (`keep`; both in
    `docs/review-flow.md`, *`LegacyQueue`*).
    """

    worktree: Path
    """The worktree the reviews are submitted from: their relay and exports are there."""
    legacy: Path
    """The first lup's checkout."""
    store: StoreLayout
    """The worktree's store, where what's parked is recorded."""
    clock: Clock
    notices: Notices
    spawner: Spawner
    """What starts the keeper, as its own process."""
    poll: timedelta = timedelta(seconds=15)
    """How often the keeper looks for a review the dashboard expired."""
    mark: str = (
        "An agent is frozen on this review: it waits for your answer before going on."
    )
    """The reply that marks a review an agent is frozen on."""

    @classmethod
    def configured(
        cls, worktree: Path, settings: LupDevSettings, clock: Clock
    ) -> LegacyQueue:
        """Reach the first lup as the interim review hook does, from `worktree`."""
        return cls(
            worktree=worktree,
            legacy=legacy_checkout(worktree, settings),
            store=Layout.of(settings).store(worktree),
            clock=clock,
            notices=NotifySend(),
            spawner=BackgroundSpawner(command=["review", "keep"]),
        )

    def loaded(self) -> Host:
        """Load the first lup's host half, naming the setting where it's missing."""
        source = Host.source(self.legacy)
        if not source.is_file():
            message = (
                f"the first lup's host half isn't at {source}, so its dashboard can't "
                "show the review: set LUP_INTERIM_REVIEW_LEGACY_CHECKOUT to the first "
                "lup's checkout"
            )
            raise ReviewError(message)
        return Host.load(source)

    def export(self, number: int) -> Path:
        """Say where review `number`'s before side is exported."""
        return CheckoutLayout(root=self.worktree).review(number).before

    def guard(self) -> FileLock:
        """Return the lock guarding the record of what's parked."""
        self.store.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.store.parked_lock)

    def runner(self) -> FileLock:
        """Return the lock a running keeper holds, which the system frees."""
        self.store.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.store.keeper, timeout=0)

    def records(self) -> Keeping:
        """Read what's parked, which is replaced whole when it changes."""
        return read_model(self.store.parked, Keeping) or Keeping()

    def running(self) -> bool:
        """Say whether a keeper runs: whether its lock is held."""
        probe = self.runner()
        try:
            probe.acquire()
        except Timeout:
            return True
        probe.release()
        return False

    def said(self, host: Host, kept: Kept, text: str) -> None:
        """Reply `text` as whoever asked, on the id the review stands under."""
        recorded = RecordedReply(
            question=kept.parked[-1],
            reply=Reply(author=kept.call.requester, text=text, at=self.clock.now()),
        )
        host.reply(host.relay(self.worktree), recorded)

    def release(self, keeping: Keeping, number: int) -> None:
        """Remove review `number`'s export and its record; hold the guard."""
        Export(directory=self.export(number)).remove()
        write_model(self.store.parked, keeping.without(number))

    @override
    def park(self, review: ReviewRequest) -> None:
        """Park `review` as one `Propose`, tell the operator, and keep it.

        A number parked already refuses, as does a review the host won't park as
        waiting; its export is removed then.
        """

        def about(file: ReviewedFile) -> str:
            match file:
                case ReviewedFile(landed=True):
                    standing = "Context, already landed: nothing here is applied."
                case ReviewedFile(asks=[]):
                    standing = (
                        "Nothing here asks for review; the agent asked for your view."
                    )
                case ReviewedFile(asks=asks):
                    standing = f"Needs your review: {'; '.join(asks)}."
            return f"{file.context}\n\n{standing}"

        host = self.loaded()
        export = Export(
            directory=self.export(review.number),
            files=[
                ExportedFile(
                    path=file.path,
                    before=file.before,
                    after=file.after,
                    about=about(file),
                )
                for file in review.files
            ],
        )
        shown = export.directory.relative_to(self.worktree)
        why = (
            f"{review.heading}\n\nApproved, the change is applied when the agent next "
            "waits on it or ends its turn; declined, nothing changes. Each file is at "
            f"its path in the worktree under {shown}/, where its text before the "
            "change waits while you review it."
        )
        call = Call(
            root=self.worktree,
            requester=review.requester,
            agent=review.agent,
            rule="lup-dev-submit",
            proposal=export.proposal(why),
            preconditions=export.preconditions(),
            reason=review.heading,
            answers=host.answers(host.relay(self.worktree)),
        )
        with self.guard():
            keeping = self.records()
            if review.number in keeping.reviews:
                message = f"review {review.number} is parked already"
                raise ReviewError(message)
            export.write()
            try:
                parked = host.park(call)
            except ReviewError:
                export.remove()
                raise
            if parked.state != "pending":
                export.remove()
                message = (
                    f"the first lup's host half didn't park review {review.number} as "
                    f"waiting: it answered {parked.state} for review {parked.id} "
                    f"{parked.reason}"
                )
                raise ReviewError(message)
            kept = Kept(call=call, parked=[parked.id])
            write_model(self.store.parked, keeping.recorded(review.number, kept))
            running = self.running()
        asyncio.run(
            self.notices.notify("A change waits for your review", review.heading)
        )
        if not running:
            self.spawner.spawn(self.worktree, self.store.keeper_log)

    @override
    def look(self, number: int) -> Look:
        """Read review `number`'s answer and remarks across every id it was parked under.

        An expired review still waits, since the keeper parks it again.
        """
        kept = self.records().review(number)
        host = self.loaded()
        export = self.export(number)
        current = kept.parked[-1]
        remarks = [
            said.remark(export) for said in host.remarks(kept.call.answers, kept.parked)
        ]
        decided = host.decided(kept.call.answers, current)
        if decided is not None:
            return Look(state=Answered(answer=decided.answer(export)), remarks=remarks)
        relay = host.relay(self.worktree)
        match host.entries(relay).get(current):
            case Entry(state="pending" | "expired"):
                return Look(state=Waiting(), remarks=remarks)
            case Entry(state=state, outcome=outcome):
                why = f"{state}: {outcome}" if outcome else state
                return Look(state=Gone(why=why), remarks=remarks)
            case None:
                why = f"review {current} isn't in the first lup's relay {relay}"
                return Look(state=Gone(why=why), remarks=remarks)

    @override
    def spend(self, number: int) -> None:
        """Spend review `number`'s approval through the host, then let it go.

        The dashboard shows it carried out (`docs/judging-writes.md`, *Where things
        live*).
        A review not approved refuses, and nothing is parked.
        """
        host = self.loaded()
        with self.guard():
            keeping = self.records()
            kept = keeping.review(number)
            current = kept.parked[-1]
            decided = host.decided(kept.call.answers, current)
            if decided is None or not decided.approved:
                message = f"review {number} isn't approved, so no approval is spent"
                raise ReviewError(message)
            host.spend(kept.call, current)
            self.release(keeping, number)

    @override
    def withdraw(self, number: int, why: str) -> None:
        """Cancel review `number` where it waits, remove its export, and let it go.

        A review still waiting in the relay, answered or not, is cancelled with
        `why` as its outcome; one that left already is only let go.
        """
        host = self.loaded()
        with self.guard():
            keeping = self.records()
            kept = keeping.review(number)
            current = kept.parked[-1]
            relay = host.relay(self.worktree)
            entry = host.entries(relay).get(current)
            if entry is not None and entry.state == "pending":
                host.cancel(relay, current, f"withdrawn: {why}")
            self.release(keeping, number)

    @override
    def reply(self, number: int, text: str) -> None:
        """Append `text` to review `number`'s thread, as the first lup's reply."""
        if not text.strip():
            message = (
                f"a reply on review {number} says something, and this one is empty"
            )
            raise ReviewError(message)
        host = self.loaded()
        with self.guard():
            self.said(host, self.records().review(number), text)

    @override
    def frozen(self, number: int) -> None:
        """Mark review `number` with a reply and a desktop notice, the first time only."""
        host = self.loaded()
        with self.guard():
            keeping = self.records()
            kept = keeping.review(number)
            if kept.frozen:
                return
            self.said(host, kept, self.mark)
            write_model(
                self.store.parked,
                keeping.recorded(number, kept.model_copy(update={"frozen": True})),
            )
        asyncio.run(
            self.notices.notify("An agent waits on your review", kept.call.reason)
        )

    def keep(self) -> None:
        """Park each review the dashboard expired again, until none waits.

        Silently: a review parked again raises no notice, and a frozen mark is said
        again under its next id without one. It returns at once where another
        keeper runs. It stops once every review is answered or gone, releasing its
        lock under the guard, so a review parked as it stops finds no keeper and
        starts one.
        """
        runner = self.runner()
        try:
            runner.acquire()
        except Timeout:
            return
        try:
            host = self.loaded()
            while self.kept_again(host, runner):
                self.clock.sleep(self.poll.total_seconds())
        finally:
            if runner.is_locked:
                runner.release()

    def kept_again(self, host: Host, runner: FileLock) -> bool:
        """Park each expired review again; say whether any still waits."""
        with self.guard():
            keeping = self.records()
            relay = host.relay(self.worktree)
            entries = host.entries(relay)

            def state(kept: Kept) -> str:
                current = kept.parked[-1]
                if host.decided(kept.call.answers, current) is not None:
                    return "answered"
                entry = entries.get(current)
                return entry.state if entry is not None else "gone"

            states = {number: state(kept) for number, kept in keeping.reviews.items()}

            def again(kept: Kept) -> Kept:
                parked = host.park(kept.call)
                if parked.state != "pending":
                    message = (
                        f"review {kept.parked[-1]} expired, and parking it again "
                        f"failed: {parked.state} {parked.reason}"
                    )
                    raise ReviewError(message)
                moved = kept.model_copy(update={"parked": [*kept.parked, parked.id]})
                if moved.frozen:
                    self.said(host, moved, self.mark)
                return moved

            parked = Keeping(
                reviews={
                    number: again(kept) if states[number] == "expired" else kept
                    for number, kept in keeping.reviews.items()
                }
            )
            if parked != keeping:
                write_model(self.store.parked, parked)
            if any(each in ["pending", "expired"] for each in states.values()):
                return True
            runner.release()
            return False
