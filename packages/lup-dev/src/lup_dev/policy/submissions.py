"""Submitting drafts for review, waiting on the answers, and carrying them out.

The behaviour behind lup's own tools, `submit`, `wait`, `reviews` and `reply`,
which the operator's command line shares (`docs/review-flow.md`, *lup's own
tools*). A review is numbered in its worktree and parked through a `Queue`, which
never says where it waits. Every submission is recorded in the worktree's store
(`StoreLayout.submissions`), changed only under the store's lock, the lock a
checkpoint holds:
- **submit** judges each draft whole, as a write to its file against the accepted
  content. A finding of lup's rules refuses the whole submission, every file's
  findings listed; what the judge asks is listed on the review. A file landed
  since the session started is shown as context. The versions submitted are kept
  under the review's directory, and naming a file again while its review waits
  supersedes that review;
- **wait** holds until what it waits on is answered or gone, the operator remarks
  on it, or its timeout. It carries out each approval it reads, and tells each
  answer and remark once, never again;
- **an approval is carried out** in one step under the store's lock: every file's
  base checked, every file written or none, the files accepted in the store so no
  checkpoint judges them again, the answer logged, the drafts settled, the
  review's directory removed, and last, the approval spent where it waits;
- **a decline** changes nothing on disk: the drafts stay as they are.
"""

import secrets
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout
from lup_dev.policy.checkpoint import Services, Session, Worktree, decoded
from lup_dev.policy.drafts import Conversation, Draft, Drafts, draft_path, drafted
from lup_dev.policy.judge import Change, Judgement
from lup_dev.policy.report import finding_lines, sections
from lup_dev.policy.store import Store, read_model, write_model
from lup_dev.policy.verdicts import Answer as Logged
from lup_dev.policy.verdicts import Verdict
from lup_dev.policy.worktrees import place
from lup_dev.review import (
    Answer,
    Answered,
    Gone,
    LineComment,
    Look,
    Queue,
    Remark,
    ReviewedFile,
    ReviewRequest,
    Waiting,
)


class SubmissionError(LupDevError):
    """A submission, a wait or a reply can't be made as asked."""


class Caller(Model):
    """Who calls one of lup's tools: the conversation, the call, where it runs."""

    session: str
    agent: str = ""
    """The subagent calling, blank for the session's own conversation."""
    call: str
    """The call's id."""
    cwd: Path
    """The working directory the call runs in, where relative paths start."""

    def conversation(self) -> Conversation:
        """Return the conversation calling."""
        return Conversation(session=self.session, agent=self.agent)


class Offered(Model):
    """One file named in a submission, as the agent names it."""

    path: Path
    """The file, or its draft's path: absolute, or from the caller's working
    directory."""
    context: str
    """What changes in it, and why, in the agent's words."""
    renamed_from: Path | None = None
    """The file's old path, for a rename: the approval removes it."""


class SubmittedFile(Model):
    """One file of a submission, as it was put before the operator."""

    path: Path
    """The file, from the worktree's root."""
    context: str
    """What changes in it and why, as the agent said each time it was submitted."""
    renamed_from: Path | None = None
    base: str | None
    """The object id, in the store, of the content the change applies over; none
    where the change creates the file."""
    version: str | None
    """The object id of the version submitted; none where the change deletes the
    file."""
    asks: list[str] = []
    """Why the judge asks the operator about it; none where the agent asked anyway."""
    landed: bool = False
    """Whether it's landed already, shown as context, with nothing to apply: its
    base is its content when the session started, its version as it's accepted."""


class Open(Model):
    """The review waits for the operator's answer."""

    kind: Literal["waiting"] = "waiting"


class Applied(Model):
    """The operator approved the review, and it was carried out."""

    kind: Literal["applied"] = "applied"
    answer: Answer


class Declined(Model):
    """The operator declined the review: nothing changed, and the drafts stay."""

    kind: Literal["declined"] = "declined"
    answer: Answer


class Stale(Model):
    """The operator approved the review, but files changed under it: nothing applied."""

    kind: Literal["stale"] = "stale"
    answer: Answer
    moved: list[Path]
    """The files that didn't hold, when it was carried out, what the change was
    submitted over."""


class Withdrawn(Model):
    """The review left the queue unanswered: superseded, or gone where it waited."""

    kind: Literal["withdrawn"] = "withdrawn"
    why: str


type Standing = Annotated[
    Open | Applied | Declined | Stale | Withdrawn, Field(discriminator="kind")
]
"""How a submission stands."""


class Submission(Model):
    """One review submitted from a worktree, and how it stands."""

    number: int
    by: Conversation
    why: str
    """What the whole change does, in the agent's words; it heads the review."""
    files: list[SubmittedFile]
    verdicts: list[Verdict] = []
    """The judgements logged on its files when submitted, its answer logged against
    them."""
    standing: Standing = Open()
    remarks: list[Remark] = []
    """What the operator sent on it without deciding, oldest first, as far as read."""
    told: bool = False
    """Whether the conversation was told how it ended; it's never told again."""
    remarks_told: int = 0
    """How many of `remarks` the conversation was told."""

    def untold(self) -> bool:
        """Say whether it waits, or holds an ending or a remark not yet told."""
        ended = self.standing.kind != "waiting"
        return not ended or not self.told or self.remarks_told < len(self.remarks)

    def changes(self) -> list[SubmittedFile]:
        """Return the files it changes: all but those shown as context."""
        return [file for file in self.files if not file.landed]


class Submissions(Model):
    """Every review submitted from one worktree, as its store keeps them."""

    last: int = 0
    """The number given last, so that no number is given twice."""
    submissions: list[Submission] = []

    def of(self, number: int) -> Submission:
        """Return review `number`, refusing a number no review has."""
        found = next((each for each in self.submissions if each.number == number), None)
        if found is None:
            message = f"no review {number} was submitted from this worktree"
            raise SubmissionError(message)
        return found

    def holding(self, file: Path) -> Submission | None:
        """Return the review submitted last that changes `file`, or none."""
        return max(
            (
                each
                for each in self.submissions
                if any(changed.path == file for changed in each.changes())
            ),
            key=lambda each: each.number,
            default=None,
        )

    def recorded(self, changed: list[Submission]) -> Submissions:
        """Return the record with each of `changed` in place of its number's."""
        numbers = [each.number for each in changed]
        others = [each for each in self.submissions if each.number not in numbers]
        return Submissions(
            last=max([self.last, *numbers]),
            submissions=sorted([*others, *changed], key=lambda each: each.number),
        )


class OneReview(Model):
    """Wait for one review's answer."""

    number: int


class AnyReview(Model):
    """Wait for the first answer among several reviews."""

    numbers: list[int]


class AllReviews(Model):
    """Wait for every answer to the calling conversation's reviews."""


class FileApplied(Model):
    """Wait for a file's change to be answered: the review submitted last holding it."""

    path: Path
    """The file, or its draft's path: absolute, or from the caller's working
    directory."""


type Awaited = OneReview | AnyReview | AllReviews | FileApplied
"""What a wait waits for."""


class Told(Model):
    """One review's ending, or a remark on it, as the conversation was told it once."""

    number: int
    standing: Standing
    """How the review stood when told."""
    remarks: list[Remark] = []
    """The remarks told with it, oldest first."""
    text: str


class Waited(Model):
    """What a wait told, and what still waits."""

    told: list[Told] = []
    waiting: list[int] = []
    """The reviews it waited on still waiting for the operator as it ended."""
    settled: list[int] = []
    """The reviews it was asked to wait on that ended, and were told, before."""

    def text(self) -> str:
        """Say what the wait told, then what still waits."""
        said = [each.number for each in self.told]
        still = [number for number in self.waiting if number not in said]
        waiting = (
            f"Still waiting for the operator on {reviews_named(still)}."
            if still
            else ""
        )
        nothing = (
            (
                f"Nothing to wait on: {reviews_named(self.settled)} ended, and you "
                "were told; `reviews` lists them."
                if self.settled
                else "Nothing to wait on: none of your reviews is waiting."
            )
            if not self.told and not still
            else ""
        )
        return sections([*(each.text for each in self.told), waiting, nothing])


class Submitted(Model):
    """A submission made: its review's number and files, and what it superseded."""

    number: int
    why: str
    files: list[Path]
    """Its files, by their absolute paths."""
    superseded: list[int] = []
    """The reviews it superseded, which held some of its files."""
    waited: Waited | None = None
    """What waiting on it in the same call told; none where it didn't wait."""

    def text(self) -> str:
        """Say what was submitted, and what waiting on it told."""
        named = "\n".join(f"  {file}" for file in self.files)
        superseding = (
            f"It supersedes {reviews_named(self.superseded)}, withdrawn from the "
            "operator's queue."
            if self.superseded
            else ""
        )
        waiting = (
            self.waited.text()
            if self.waited is not None
            else "Its answer comes when you wait on it."
        )
        return sections(
            [
                f"Submitted as review {self.number}, which waits for the operator:\n{named}",
                superseding,
                waiting,
            ]
        )


class Listed(Model):
    """One review as listed: its record, and how it stands where it waits."""

    submission: Submission
    look: Look | None = None
    """How a review still waiting stands in the queue; none for one that ended."""

    def state(self) -> str:
        """Say how the review stands, in a few words."""
        match self.submission.standing:
            case Applied():
                return "applied"
            case Declined(answer=answer):
                return f"declined{noted(answer.note)}"
            case Stale(moved=moved):
                files = ", ".join(str(each) for each in moved)
                return f"stale, nothing applied: {files} changed since it was submitted"
            case Withdrawn(why=why):
                return f"withdrawn: {why}"
            case Open():
                return self.waiting()

    def waiting(self) -> str:
        """Say how a review still waiting stands in the queue."""
        state = self.look.state if self.look is not None else Waiting()
        match state:
            case Answered(answer=Answer(approved=True)):
                return "approved, not yet applied: it applies when it's waited on"
            case Answered(answer=answer):
                return f"declined, not yet told{noted(answer.note)}"
            case Gone(why=why):
                return f"gone from the queue, not yet told: {why}"
            case Waiting():
                return "waiting for the operator"


class Listing(Model):
    """The drafts and reviews of a worktree, or of one of its conversations."""

    root: Path
    drafts: list[Draft] = []
    reviews: list[Listed] = []

    def text(self) -> str:
        """List each draft with its review, then each review with how it stands."""

        def draft(each: Draft) -> str:
            where = draft_path(self.root, each.file)
            submitted = (
                "not submitted"
                if each.submission is None
                else f"last submitted in review {each.submission}"
            )
            return f"  {self.root / each.file}: draft at {where}, {submitted}"

        def review(each: Listed) -> str:
            files = "\n".join(
                f"      {self.root / file.path}" for file in each.submission.files
            )
            return f"  {each.submission.number}  {each.state()}: {each.submission.why}\n{files}"

        drafts = (
            "\n".join(["Drafts:", *(draft(each) for each in self.drafts)])
            if self.drafts
            else "No drafts."
        )
        reviews = (
            "\n".join(["Reviews:", *(review(each) for each in self.reviews)])
            if self.reviews
            else "No reviews."
        )
        return sections([drafts, reviews])


class Named(Model):
    """A file named in a submission, read against the worktree."""

    offered: Offered
    file: Path
    """The file, from the worktree's root."""
    draft: Draft | None
    """Its draft; none for a file landed already, shown as context."""
    renamed_from: Path | None = None


class Progress(Model):
    """Where a wait stands: what it tells if it ends, and what still waits."""

    ending: list[int] = []
    """Reviews it waits on that ended, not yet told."""
    remarked: list[int] = []
    """Reviews it waits on still waiting, with remarks not yet told."""
    waiting: list[int] = []
    settled: list[int] = []
    """Reviews it was asked to wait on that ended, and were told, before."""
    every: bool = False
    """Whether it ends only once every review it waits on has ended."""

    def ends(self) -> bool:
        """Say whether the wait ends here: answered as asked, or remarked on."""
        if self.remarked or not self.waiting:
            return True
        return bool(self.ending) and not self.every


def reviews_named(numbers: list[int]) -> str:
    """Name reviews by their numbers.

    >>> reviews_named([3]), reviews_named([3, 4])
    ('review 3', 'reviews 3, 4')
    """
    listed = ", ".join(str(number) for number in numbers)
    return f"review {listed}" if len(numbers) == 1 else f"reviews {listed}"


def noted(note: str) -> str:
    """Say a note after a state, where there's one.

    >>> noted("too broad"), noted("")
    (': too broad', '')
    """
    return f": {note}" if note else ""


class Desk(Model, arbitrary_types_allowed=True):
    """One worktree's reviews: drafts submitted, waited on, answered, carried out."""

    worktree: Worktree
    services: Services
    queue: Queue
    """Where the worktree's reviews are parked for the operator."""
    poll: timedelta = timedelta(seconds=2)
    """How often a wait looks for the operator's answer."""
    patience: timedelta = timedelta(hours=23, minutes=55)
    """The longest a wait holds: a little under the day a runtime gives the call."""

    @property
    def root(self) -> Path:
        """The worktree's root."""
        return self.worktree.root

    @property
    def store(self) -> Store:
        """The worktree's store."""
        return self.worktree.store

    def drafts(self) -> Drafts:
        """Return the worktree's drafts; hold the store's lock to use them."""
        return Drafts(store=self.store)

    def record(self) -> Submissions:
        """Read every submission; hold the store's lock."""
        found = read_model(self.store.layout.submissions, Submissions)
        return found or Submissions()

    def keep(self, record: Submissions) -> Submissions:
        """Store every submission, and return them; hold the store's lock."""
        write_model(self.store.layout.submissions, record)
        return record

    def accepted(self) -> str:
        """Return the accepted tree; hold the store's lock.

        A worktree no session has reached has none, and is accepted as it stands,
        as a session's start accepts the work done while none ran there.
        """
        found = self.store.accepted()
        if found is not None:
            return found
        taken = self.store.snapshot()
        self.store.accept(taken)
        head = self.store.head()
        state = self.store.state()
        state.tips = self.store.tips(head)
        self.store.remember(state)
        self.worktree.record(self.services.layout, head)
        return taken

    def stored(self, blob: str) -> bytes:
        """Return the content of object `blob`, refusing one the store doesn't hold."""
        content = self.store.object(blob)
        if content is None:
            message = f"the store of {self.root} doesn't hold object {blob}"
            raise SubmissionError(message)
        return content

    def content(self, blob: str | None) -> bytes | None:
        """Return the content of object `blob`; none for none."""
        return None if blob is None else self.stored(blob)

    def session(self, key: str) -> Session | None:
        """Return what the store remembers of session `key` here, or none."""
        return read_model(self.store.layout.session(key), Session)

    def since(self, session: str, path: Path) -> str | None:
        """Return the object id of `path` as `session` started here.

        Where no start is recorded for it (the operator's command line), as the
        worktree's `HEAD` commit has it. None where it wasn't there.
        """
        started = self.store.started(session)
        if started is not None:
            return self.store.blob(started, path)
        return self.store.entry(self.store.head(), path).blob

    def located(self, caller: Caller, path: Path) -> Path:
        """Return `path` from the worktree's root, read from the caller's directory."""
        full = path if path.is_absolute() else caller.cwd / path
        found = place(full)
        if found is None or found.worktree != self.root:
            message = f"{full} isn't in the worktree at {self.root}"
            raise SubmissionError(message)
        return found.path

    def submit(
        self,
        caller: Caller,
        files: list[Offered],
        why: str = "",
        *,
        wait: bool = False,
        timeout: timedelta | None = None,
    ) -> Submitted:
        """Submit drafts, and files landed as context, as one review.

        With `wait`, wait for its answer in the same call, as `wait` on it does.
        """
        if not files:
            message = "a submission names at least one file"
            raise SubmissionError(message)
        empty = [str(each.path) for each in files if not each.context.strip()]
        if empty:
            message = (
                "each file's context says what changes in it and why, and it's "
                f"empty for {', '.join(empty)}"
            )
            raise SubmissionError(message)
        if len(files) > 1 and not why.strip():
            message = (
                "a submission of several files says what the whole change does in "
                "`why`, which heads the review"
            )
            raise SubmissionError(message)
        with self.worktree.lock():
            submitted = self.submitted(caller, files, why.strip())
        if not wait:
            return submitted
        waited = self.wait(caller, OneReview(number=submitted.number), timeout)
        return submitted.model_copy(update={"waited": waited})

    def named(self, caller: Caller, offered: Offered, accepted: str) -> Named:
        """Read one file named in a submission; hold the store's lock.

        A draft written at its path with no record is begun here, its base the
        file's accepted content: the agent asked for the operator's view anyway.
        """
        given = self.located(caller, offered.path)
        file = drafted(self.root, given)
        drafts = self.drafts()
        written = draft_path(self.root, file)
        found = drafts.of(file)
        draft = (
            drafts.begin(file, caller.conversation())
            if found is None and written.is_file()
            else found
        )
        if draft is None:
            if given != file:
                message = f"no draft is written at {written}"
                raise SubmissionError(message)
            since = self.since(caller.session, file)
            if self.store.blob(accepted, file) == since:
                message = (
                    f"{self.root / file} is neither a draft nor a change landed since "
                    "the session started: write the change at its draft's path, "
                    f"{written}, to submit it"
                )
                raise SubmissionError(message)
            if offered.renamed_from is not None:
                message = (
                    f"{self.root / file} is landed already, and only a draft is "
                    "submitted as a rename"
                )
                raise SubmissionError(message)
            return Named(offered=offered, file=file, draft=None)
        if draft.base != self.store.blob(accepted, file):
            message = (
                f"{self.root / file} changed since its draft began, so the draft at "
                f"{written} would undo that change: bring the draft up to date with "
                "the file, then submit it"
            )
            raise SubmissionError(message)
        old = (
            self.located(caller, offered.renamed_from)
            if offered.renamed_from is not None
            else draft.renamed_from
        )
        if old is not None and self.store.blob(accepted, old) is None:
            message = f"{self.root / old}, named as the file renamed, isn't a file here"
            raise SubmissionError(message)
        if old is not None and drafts.of(old) is not None:
            message = (
                f"{self.root / old}, named as the file renamed, has a draft of its "
                "own: a rename leaves the old file as it is"
            )
            raise SubmissionError(message)
        return Named(offered=offered, file=file, draft=draft, renamed_from=old)

    def judged(
        self, caller: Caller, names: list[Named], accepted: str
    ) -> list[Judgement]:
        """Judge each draft whole against the accepted content, and each renamed file.

        Refuse the submission where lup's rules find anything on the lines a draft
        changes, every file's findings listed. Hold the store's lock.
        """
        drafts = self.drafts()

        def change(file: Path, after: bytes | None) -> Change:
            return Change(
                path=file,
                before=decoded(self.store.content(accepted, file)),
                after=decoded(after),
                baseline=decoded(self.content(self.since(caller.session, file))),
            )

        changes = [
            *(
                change(name.file, drafts.path(name.draft).read_bytes())
                for name in names
                if name.draft is not None
            ),
            *(
                change(name.renamed_from, None)
                for name in names
                if name.renamed_from is not None
            ),
        ]
        if not changes:
            return []
        session = self.session(caller.session)
        approved = session.approved if session is not None else []
        judge = self.worktree.judge(self.services, approved)
        judgements = judge.judge(changes, inform=False)
        refused = [each for each in judgements if each.outcome == "refuse"]
        if refused:
            raise SubmissionError(self.refusal(refused))
        return judgements

    def refusal(self, refused: list[Judgement]) -> str:
        """Say why the submission is refused: lup's findings in each draft."""

        def block(judgement: Judgement) -> str:
            draft = draft_path(self.root, judgement.path)
            placed = [
                found.model_copy(update={"path": draft}) for found in judgement.refusing
            ]
            lines = [line for found in placed for line in finding_lines(found)]
            return "\n".join([str(draft), *lines])

        return sections(
            [
                (
                    "lup refused the submission: lup's rules find these on lines the "
                    "drafts change. Nothing was submitted; fix them in the drafts, "
                    "then submit again."
                ),
                *(block(each) for each in refused),
                (
                    "To keep a finding, add on its line or the line above (the "
                    'operator is asked):\n  # lup: ignore("<rule>", why="<reason>")'
                ),
            ]
        )

    def submitted(self, caller: Caller, files: list[Offered], why: str) -> Submitted:
        """Judge, record and park one submission; hold the store's lock."""
        accepted = self.accepted()
        names = [self.named(caller, offered, accepted) for offered in files]
        paths = [
            path
            for name in names
            for path in [name.file, *([name.renamed_from] if name.renamed_from else [])]
        ]
        twice = [path for path in dict.fromkeys(paths) if paths.count(path) > 1]
        if twice:
            message = (
                "a file is named once in a submission, and these are named more "
                f"than once: {', '.join(str(self.root / path) for path in twice)}"
            )
            raise SubmissionError(message)
        judgements = self.judged(caller, names, accepted)
        judged = {judgement.path: judgement for judgement in judgements}
        record = self.record()
        superseded = [
            each
            for each in record.submissions
            if each.standing.kind == "waiting"
            and any(file.path in paths for file in each.files)
        ]
        earlier = {
            file.path: file.context for each in superseded for file in each.files
        }
        drafts = self.drafts()

        def context(path: Path, said: str) -> str:
            return f"{earlier[path]}\n\n{said}" if path in earlier else said

        def asked(path: Path) -> list[str]:
            return [ask.reason for ask in judged[path].asks]

        def entries(name: Named) -> list[SubmittedFile]:
            said = context(name.file, name.offered.context)
            if name.draft is None:
                return [
                    SubmittedFile(
                        path=name.file,
                        context=said,
                        base=self.since(caller.session, name.file),
                        version=self.store.blob(accepted, name.file),
                        landed=True,
                    )
                ]
            version = self.store.keep(drafts.path(name.draft).read_bytes())
            changed = SubmittedFile(
                path=name.file,
                context=said,
                renamed_from=name.renamed_from,
                base=name.draft.base,
                version=version,
                asks=asked(name.file),
            )
            if name.renamed_from is None:
                return [changed]
            removed = SubmittedFile(
                path=name.renamed_from,
                context=context(name.renamed_from, name.offered.context),
                base=self.store.blob(accepted, name.renamed_from),
                version=None,
                asks=asked(name.renamed_from),
            )
            return [changed, removed]

        fresh = [entry for name in names for entry in entries(name)]
        carried = [
            file for each in superseded for file in each.files if file.path not in paths
        ]
        heading = (
            why
            or next((each.why for each in superseded if each.why), "")
            or names[0].offered.context.strip()
        )
        number = record.last + 1
        logged = [self.verdict(caller, judgement) for judgement in judgements]
        submission = Submission(
            number=number,
            by=caller.conversation(),
            why=heading,
            files=[*fresh, *carried],
            verdicts=[
                *(
                    verdict
                    for each in superseded
                    for verdict in each.verdicts
                    if verdict.path not in paths
                ),
                *logged,
            ],
        )
        self.park(caller, submission)
        withdrawn = f"superseded by review {number}, which holds its files"
        ended = [
            each.model_copy(
                update={
                    "standing": Withdrawn(why=withdrawn),
                    "told": each.by == caller.conversation(),
                }
            )
            for each in superseded
        ]
        self.keep(record.recorded([*ended, submission]))
        for name in names:
            if name.draft is not None:
                drafts.keep(
                    name.draft.model_copy(
                        update={"submission": number, "renamed_from": name.renamed_from}
                    )
                )
        self.worktree.verdicts(self.services.layout).append(logged)
        for each in ended:
            self.queue.withdraw(each.number, withdrawn)
            self.cleared(each.number)
        return Submitted(
            number=number,
            why=heading,
            files=[self.root / file.path for file in submission.files],
            superseded=[each.number for each in ended],
        )

    def verdict(self, caller: Caller, judgement: Judgement) -> Verdict:
        """Log a draft's judgement as submitted: the operator is asked about it.

        Its reasons are the kinds of ask, or `asked-anyway` where the judge asks
        nothing and the agent asked for the operator's view.
        """
        session = self.session(caller.session)
        return Verdict(
            key=secrets.token_hex(8),
            time=self.services.clock.now(),
            session=caller.session,
            runtime=session.runtime if session is not None else "",
            tool="submit",
            worktree=self.root,
            path=judgement.path,
            role=judgement.role,
            outcome="ask",
            reasons=[ask.kind for ask in judgement.asks] or ["asked-anyway"],
        )

    def park(self, caller: Caller, submission: Submission) -> None:
        """Keep each version submitted under the review's directory, and park it.

        Where it can't be parked, the review's directory is removed again.
        """
        kept = CheckoutLayout(root=self.root).review(submission.number)
        for file in submission.changes():
            if file.version is None:
                continue
            copy = kept.submitted / file.path
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(self.stored(file.version))
        request = ReviewRequest(
            number=submission.number,
            requester=caller.session,
            agent=caller.agent,
            heading=submission.why,
            files=[self.reviewed(file, submission.files) for file in submission.files],
        )
        try:
            self.queue.park(request)
        except LupDevError:
            self.cleared(submission.number)
            raise

    def reviewed(self, file: SubmittedFile, files: list[SubmittedFile]) -> ReviewedFile:
        """Return one file of a submission as the operator reviews it.

        Each side of a rename names the other in its context.
        """
        moved_to = next(
            (each.path for each in files if each.renamed_from == file.path), None
        )
        moved = (
            f"Renamed from `{file.renamed_from}`. "
            if file.renamed_from is not None
            else (f"Renamed to `{moved_to}`. " if moved_to is not None else "")
        )
        return ReviewedFile(
            path=file.path,
            before=decoded(self.content(file.base)),
            after=decoded(self.content(file.version)),
            context=f"{moved}{file.context}",
            asks=file.asks,
            landed=file.landed,
        )

    def cleared(self, number: int) -> None:
        """Remove review `number`'s directory in the worktree, where it stands."""
        home = CheckoutLayout(root=self.root).review(number).home
        if home.exists():
            shutil.rmtree(home)

    def wait(
        self, caller: Caller, awaited: Awaited, timeout: timedelta | None = None
    ) -> Waited:
        """Wait on reviews, carrying out each approval read, telling each ending once.

        It ends once what it waits on is answered, or gone: one review, the first
        of several, every one of the conversation's, or the review submitted last
        holding a file. It ends too where the operator remarks on one, telling the
        remark, and at `timeout`, or the desk's patience, saying what still waits.
        Each review still waiting is marked as one an agent is frozen on, once.
        """
        clock = self.services.clock
        limit = self.patience if timeout is None else min(timeout, self.patience)
        deadline = clock.now() + limit
        marked = False
        while True:
            with self.worktree.lock():
                progress = self.progress(caller, awaited)
                if progress.ends() or clock.now() >= deadline:
                    return self.told(progress)
            if not marked:
                for number in progress.waiting:
                    self.queue.frozen(number)
                marked = True
            clock.sleep(min(self.poll, deadline - clock.now()).total_seconds())

    def targets(
        self, caller: Caller, awaited: Awaited, record: Submissions
    ) -> list[int]:
        """Return the reviews a wait waits on, by number; hold the store's lock."""
        match awaited:
            case OneReview(number=number):
                return [record.of(number).number]
            case AnyReview(numbers=numbers):
                if not numbers:
                    message = "a wait for the first of several reviews names them"
                    raise SubmissionError(message)
                return [record.of(number).number for number in numbers]
            case AllReviews():
                return [
                    each.number
                    for each in record.submissions
                    if each.by == caller.conversation() and each.untold()
                ]
            case FileApplied(path=path):
                file = drafted(self.root, self.located(caller, path))
                holding = record.holding(file)
                if holding is None:
                    message = (
                        f"no review holds {self.root / file}: submit its draft first"
                    )
                    raise SubmissionError(message)
                return [holding.number]

    def progress(self, caller: Caller, awaited: Awaited) -> Progress:
        """Read the answers to the reviews a wait waits on, and act on them.

        Each approval read is carried out. Hold the store's lock.
        """
        record = self.record()
        numbers = self.targets(caller, awaited, record)
        for number in numbers:
            if record.of(number).standing.kind == "waiting":
                record = self.settled(record, number)
        reviews = [record.of(number) for number in dict.fromkeys(numbers)]
        return Progress(
            ending=[
                each.number
                for each in reviews
                if each.standing.kind != "waiting" and not each.told
            ],
            remarked=[
                each.number
                for each in reviews
                if each.standing.kind == "waiting"
                and each.remarks_told < len(each.remarks)
            ],
            waiting=[
                each.number for each in reviews if each.standing.kind == "waiting"
            ],
            settled=[
                each.number
                for each in reviews
                if each.standing.kind != "waiting" and each.told
            ],
            every=isinstance(awaited, AllReviews),
        )

    def settled(self, record: Submissions, number: int) -> Submissions:
        """Read review `number`'s answer and remarks, and act on the answer.

        An approval is carried out, a decline recorded, a review gone from the
        queue recorded as withdrawn; each answered review is let go from the queue.
        Return the record as kept; hold the store's lock.
        """
        submission = record.of(number)
        look = self.queue.look(number)
        seen = submission.model_copy(update={"remarks": look.remarks})
        match look.state:
            case Waiting():
                return self.keep(record.recorded([seen]))
            case Answered(answer=Answer(approved=True) as answer):
                return self.carried(record, seen, answer)
            case Answered(answer=answer):
                kept = self.ended(record, seen, Declined(answer=answer), "declined")
                self.queue.withdraw(number, "declined, and the answer read")
                return kept
            case Gone(why=why):
                kept = self.ended(record, seen, Withdrawn(why=why), "unanswered")
                self.queue.withdraw(number, why)
                return kept

    def ended(
        self,
        record: Submissions,
        submission: Submission,
        standing: Standing,
        answer: Logged,
    ) -> Submissions:
        """Record how `submission` ended, and log its answer; hold the store's lock."""
        kept = self.keep(
            record.recorded([submission.model_copy(update={"standing": standing})])
        )
        self.worktree.verdicts(self.services.layout).append(
            [
                verdict.model_copy(update={"answer": answer})
                for verdict in submission.verdicts
            ]
        )
        return kept

    def carried(
        self, record: Submissions, submission: Submission, answer: Answer
    ) -> Submissions:
        """Carry out an approval, in one step; hold the store's lock.

        Each file must still hold what the change was submitted over, or nothing
        is applied: the review is stale. Then every file's version is written and
        each file the change deletes removed, all or none; the files are accepted
        in the store, so no checkpoint judges them again, and the approval covers
        their design asks for the session that submitted them; the answer is
        logged; each draft still equal to its version is removed, and one edited
        since stays, its base the version applied; the review's directory goes;
        and the approval is spent where the review waits.
        """
        number = submission.number
        changes = submission.changes()

        def standing(file: SubmittedFile) -> bytes | None:
            disk = self.root / file.path
            return disk.read_bytes() if disk.is_file() else None

        moved = [
            file.path for file in changes if standing(file) != self.content(file.base)
        ]
        if moved:
            stale = Stale(answer=answer, moved=moved)
            kept = self.ended(record, submission, stale, "approved")
            files = ", ".join(str(self.root / path) for path in moved)
            self.queue.withdraw(
                number, f"stale: {files} changed since it was submitted"
            )
            return kept
        try:
            self.put(submission)
        except OSError as failure:
            message = (
                f"review {number} couldn't be applied, and nothing changed: {failure}"
            )
            raise SubmissionError(message) from failure
        paths = [file.path for file in changes]
        self.accept(paths)
        session = self.session(submission.by.session)
        if session is not None:
            session.approved = list(dict.fromkeys([*session.approved, *paths]))
            session.touched = list(dict.fromkeys([*session.touched, *paths]))
            self.worktree.keep(session)
        kept = self.ended(record, submission, Applied(answer=answer), "approved")
        drafts = self.drafts()
        for file in changes:
            if file.version is None:
                continue
            draft = drafts.of(file.path)
            if draft is None or drafts.path(draft).read_bytes() == self.stored(
                file.version
            ):
                drafts.forget(file.path)
                continue
            drafts.keep(
                draft.model_copy(
                    update={
                        "base": file.version,
                        "submission": None,
                        "renamed_from": None,
                    }
                )
            )
        self.cleared(number)
        python = [path for path in paths if self.worktree.roles.checked(path)]
        self.worktree.importers().request(python, self.services.spawner)
        self.queue.spend(number)
        return kept

    def put(self, submission: Submission) -> None:
        """Write each version submitted, and delete what the change deletes: all or none.

        Each version is written under the review's directory first, then moved
        into place; where a move fails, the files moved already are put back.
        """
        changes = submission.changes()
        staged = CheckoutLayout(root=self.root).review(submission.number).submitted
        for file in changes:
            if file.version is None:
                continue
            copy = staged / file.path
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(self.stored(file.version))
        done = 0
        try:
            for file in changes:
                target = self.root / file.path
                if file.version is None:
                    target.unlink(missing_ok=True)
                    done += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file():
                    shutil.copymode(target, staged / file.path)
                (staged / file.path).replace(target)
                done += 1
        except OSError:
            self.restore(changes[: done + 1])
            raise

    def restore(self, files: list[SubmittedFile]) -> None:
        """Put each file back as the change was submitted over."""
        for file in files:
            target = self.root / file.path
            if file.base is None:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.stored(file.base))

    def accept(self, paths: list[Path]) -> None:
        """Accept `paths` as they stand on disk, and nothing else; hold the store's lock.

        The worktree is snapshot, and every other path that differs from the
        accepted tree is left out, for the next checkpoint to judge.
        """
        accepted = self.accepted()
        taken = self.store.snapshot()
        others = [
            change.path
            for change in self.store.changed(accepted, taken)
            if change.path not in paths
        ]
        self.store.accept(self.store.unstage(accepted, others, []) if others else taken)

    def told(self, progress: Progress) -> Waited:
        """Tell each ending and remark a wait read, once, and record it told.

        Hold the store's lock.
        """
        record = self.record()
        telling = list(dict.fromkeys([*progress.ending, *progress.remarked]))
        reviews = [record.of(number) for number in telling]
        told = [
            Told(
                number=each.number,
                standing=each.standing,
                remarks=each.remarks[each.remarks_told :],
                text=self.said(each, each.remarks[each.remarks_told :]),
            )
            for each in reviews
        ]
        marked = [
            each.model_copy(
                update={
                    "told": each.told or each.standing.kind != "waiting",
                    "remarks_told": len(each.remarks),
                }
            )
            for each in reviews
        ]
        self.keep(record.recorded(marked))
        return Waited(told=told, waiting=progress.waiting, settled=progress.settled)

    def said(self, submission: Submission, remarks: list[Remark]) -> str:
        """Say how a review ended, or that it waits, with what the operator wrote."""
        number = submission.number
        drafts = self.drafts()
        found = [drafts.of(file.path) for file in submission.changes()]
        standing = [draft for draft in found if draft is not None]
        match submission.standing:
            case Applied(answer=answer):
                written = [
                    str(self.root / file.path)
                    for file in submission.changes()
                    if file.version is not None
                ]
                removed = [
                    str(self.root / file.path)
                    for file in submission.changes()
                    if file.version is None
                ]
                listed = "; ".join(
                    [
                        *([f"written {', '.join(written)}"] if written else []),
                        *([f"removed {', '.join(removed)}"] if removed else []),
                    ]
                )
                stayed = [
                    f"Your draft of {self.root / draft.file} changed since you "
                    f"submitted it, so it stays at {drafts.path(draft)}, holding only "
                    "the later edits: submit it when it's ready."
                    for draft in standing
                ]
                lines = [
                    f"The operator approved review {number}, and it's applied: {listed}.",
                    *self.answer(submission, answer),
                    *stayed,
                ]
            case Declined(answer=answer):
                where = ", ".join(str(drafts.path(draft)) for draft in standing)
                kept = (
                    f"your drafts stand as they were: {where}. Revise them and submit "
                    "them again, or answer the operator with `reply`."
                    if standing
                    else "none of its drafts stands. Answer the operator with `reply`."
                )
                lines = [
                    f"The operator declined review {number}. Nothing changed, and {kept}",
                    *self.answer(submission, answer),
                ]
            case Stale(answer=answer, moved=moved):
                files = ", ".join(str(self.root / path) for path in moved)
                lines = [
                    (
                        f"The operator approved review {number}, but nothing was "
                        f"applied: {files} changed since you submitted it. Bring your "
                        "drafts up to date with the files, then submit them again."
                    ),
                    *self.answer(submission, answer),
                ]
            case Withdrawn(why=why):
                lines = [f"Review {number} was withdrawn: {why}."]
            case Open():
                lines = [
                    (
                        f"The operator remarked on review {number}, which still "
                        "waits for their answer; you may answer with `reply`."
                    )
                ]
        remarked = [
            line
            for remark in remarks
            for line in self.written(submission, remark, "The operator remarked")
        ]
        return "\n".join([*lines, *remarked])

    def answer(self, submission: Submission, answer: Answer) -> list[str]:
        """Say what the operator wrote with their answer."""
        return self.written(submission, answer, "With it")

    def written(self, submission: Submission, remark: Remark, lead: str) -> list[str]:
        """Say a note and line comments the operator wrote on a review.

        A comment on the after side counts lines in the version submitted: where
        the draft moved on since, it says where that version is kept.
        """
        note = (
            [
                f"{lead}, the operator's note:",
                *(f"    {line}" for line in remark.note.splitlines()),
            ]
            if remark.note
            else []
        )
        comments = (
            [
                f"{lead}, the operator's line comments:",
                *(f"  {self.comment(submission, each)}" for each in remark.comments),
            ]
            if remark.comments
            else []
        )
        return [*note, *comments]

    def comment(self, submission: Submission, comment: LineComment) -> str:
        """Say one line comment, naming its file in full.

        An after-side comment counts lines in the version submitted: where the
        file's draft moved on since, it says where that version stands, the file
        itself once applied.
        """
        placed = comment.model_copy(update={"path": self.root / comment.path})
        said = placed.text(None)
        version = next(
            (
                file.version
                for file in submission.changes()
                if file.path == comment.path
            ),
            None,
        )
        drafts = self.drafts()
        draft = drafts.of(comment.path)
        moved_on = (
            comment.side == "after"
            and version is not None
            and draft is not None
            and drafts.path(draft).read_bytes() != self.stored(version)
        )
        if not moved_on:
            return said
        kept = (
            self.root / comment.path
            if submission.standing.kind == "applied"
            else CheckoutLayout(root=self.root).review(submission.number).submitted
            / comment.path
        )
        return (
            f"{said}\n    (its lines count in the version submitted, at {kept}: "
            "your draft moved on since)"
        )

    def reviews(self, conversation: Conversation | None = None) -> Listing:
        """List the drafts and reviews of `conversation`, or of the whole worktree.

        A review still waiting is looked at where it waits, and nothing is told
        or carried out.
        """
        with self.worktree.lock():
            record = self.record()
            drafts = self.drafts().all()
        mine = [
            each
            for each in record.submissions
            if conversation is None or each.by == conversation
        ]
        return Listing(
            root=self.root,
            drafts=[
                draft
                for draft in drafts
                if conversation is None or draft.began == conversation
            ],
            reviews=[
                Listed(
                    submission=each,
                    look=self.queue.look(each.number)
                    if each.standing.kind == "waiting"
                    else None,
                )
                for each in mine
            ],
        )

    def reply(self, caller: Caller, number: int, text: str) -> str:
        """Answer the operator on one of the caller's session's reviews still waiting.

        It settles nothing: the review waits as it did.
        """
        with self.worktree.lock():
            submission = self.record().of(number)
        if submission.by.session != caller.session:
            message = f"review {number} is another session's, so its thread isn't yours to answer in"
            raise SubmissionError(message)
        if submission.standing.kind != "waiting":
            message = f"review {number} is {submission.standing.kind}, so its thread is closed"
            raise SubmissionError(message)
        self.queue.reply(number, text)
        return f"Replied on review {number}, which waits as it did."

    def apply(self, number: int) -> Submission:
        """Carry out review `number`'s approval, read where it waits, and return it.

        What a conversation's end does with an approval it heard of; telling it
        is the caller's. A review not waiting, or not approved, refuses.
        """
        with self.worktree.lock():
            record = self.record()
            submission = record.of(number)
            if submission.standing.kind != "waiting":
                message = f"review {number} is {submission.standing.kind}, so there's nothing to carry out"
                raise SubmissionError(message)
            look = self.queue.look(number)
            match look.state:
                case Answered(answer=Answer(approved=True) as answer):
                    seen = submission.model_copy(update={"remarks": look.remarks})
                    return self.carried(record, seen, answer).of(number)
                case _:
                    message = f"review {number} isn't approved, so there's nothing to carry out"
                    raise SubmissionError(message)
