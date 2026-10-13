"""Submitting drafts, waiting on the answers, and carrying them out.

The queue is a fake that keeps each review in memory and lets a test answer,
remark on or retire it, at once or while the clock sleeps; the engine, ruff, the
clock and the spawner are the judge's fakes. Everything lives under `tmp_path`.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.layout import CheckoutLayout
from lup_dev.policy.checkpoint import (
    CallFinished,
    CallStarted,
    Session,
    SessionStarted,
    Worktree,
)
from lup_dev.policy.drafts import draft_path
from lup_dev.policy.importers import Conversation
from lup_dev.policy.submissions import (
    AllReviews,
    AnyReview,
    Applied,
    Caller,
    Declined,
    Desk,
    FileApplied,
    Offered,
    OneReview,
    Open,
    Stale,
    SubmissionError,
    Withdrawn,
)
from lup_dev.review import (
    Answer,
    Answered,
    Gone,
    LineComment,
    Look,
    Queue,
    Remark,
    ReviewError,
    ReviewRequest,
    Waiting,
)
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from conftest import Kit, Shell

    from lup_dev.policy.checkpoint import Services

CORE = Path("src/pkg/core.py")
NEW = Path("src/pkg/extra.py")
TEST = Path("tests/test_extra.py")
SESSION = "s1"


class FakeQueue(Queue):
    """Reviews parked in memory, answered by the test."""

    def __init__(self) -> None:
        self.parked: dict[int, ReviewRequest] = {}
        self.states: dict[int, Waiting | Answered | Gone] = {}
        self.remarks: dict[int, list[Remark]] = {}
        self.released: list[int] = []
        self.spent: list[int] = []
        self.withdrawn: dict[int, str] = {}
        self.replies: list[str] = []
        self.frozen_on: list[int] = []
        self.refusing = False

    def park(self, review: ReviewRequest) -> None:
        if self.refusing:
            message = "the dashboard isn't there"
            raise ReviewError(message)
        self.parked[review.number] = review
        self.states[review.number] = Waiting()

    def kept(self, number: int) -> None:
        if number not in self.parked or number in self.released:
            message = f"no review {number} is parked"
            raise ReviewError(message)

    def look(self, number: int) -> Look:
        self.kept(number)
        return Look(state=self.states[number], remarks=self.remarks.get(number, []))

    def spend(self, number: int) -> None:
        self.kept(number)
        state = self.states[number]
        assert isinstance(state, Answered)
        assert state.answer.approved
        self.spent.append(number)
        self.released.append(number)

    def withdraw(self, number: int, why: str) -> None:
        self.kept(number)
        self.withdrawn[number] = why
        self.released.append(number)

    def reply(self, number: int, text: str) -> None:
        self.kept(number)
        self.replies.append(f"{number}: {text}")

    def frozen(self, number: int) -> None:
        self.kept(number)
        self.frozen_on.append(number)

    def approve(
        self, number: int, note: str = "", comments: list[LineComment] | None = None
    ) -> None:
        answer = Answer(approved=True, note=note, comments=comments or [])
        self.states[number] = Answered(answer=answer)

    def decline(
        self, number: int, note: str = "", comments: list[LineComment] | None = None
    ) -> None:
        answer = Answer(approved=False, note=note, comments=comments or [])
        self.states[number] = Answered(answer=answer)

    def remark(self, number: int, note: str) -> None:
        self.remarks[number] = [*self.remarks.get(number, []), Remark(note=note)]


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


def common(repo: Path, shell: Shell) -> Path:
    return Path(
        shell.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )


@pytest.fixture
def desk(kit: Kit, repo: Path, shell: Shell, queue: FakeQueue) -> Desk:
    """The repository's reviews, its session started."""
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    services = kit.bench.services
    worktree = Worktree.of(repo, common(repo, shell), services)
    return Desk(worktree=worktree, services=services, queue=queue)


def me(repo: Path, session: str = SESSION, agent: str = "") -> Caller:
    return Caller(session=session, agent=agent, call="c1", cwd=repo)


def draft(
    desk: Desk, file: Path, content: str, *, by: Conversation | None = None
) -> Path:
    """Begin a draft of `file`, as a redirected write would, and write `content` in it."""
    with desk.worktree.lock():
        desk.drafts().begin(file, by or Conversation(session=SESSION))
    written = draft_path(desk.root, file)
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(content)
    return written


def edited(desk: Desk) -> str:
    """Draft an edit to `core.py`'s body, which asks nothing."""
    content = (desk.root / CORE).read_text().replace("return x", "return x + 1")
    draft(desk, CORE, content)
    return content


def submit_both(desk: Desk, repo: Path) -> str:
    """Draft a module being created and an edit to `core.py`; submit them as review 1."""
    draft(desk, NEW, '"""Extra."""\n')
    content = edited(desk)
    desk.submit(
        me(repo),
        [
            Offered(path=NEW, context="An extra module, for the tests."),
            Offered(path=CORE, context="`helper` adds one."),
        ],
        "Extra behaviour.",
    )
    return content


def stored(desk: Desk, path: Path) -> bytes | None:
    store = desk.worktree.store
    return store.content(store.accepted(), path)


def session(desk: Desk) -> Session:
    found = read_model(desk.worktree.store.layout.session(SESSION), Session)
    assert found is not None
    return found


def test_a_submission_is_parked_as_one_review_of_its_drafts_with_their_asks(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    content = submit_both(desk, repo)
    review = queue.parked[1]
    assert review.heading == "Extra behaviour."
    assert review.requester == SESSION
    module, core = review.files
    assert (module.path, module.kind(), module.before, module.after) == (
        NEW,
        "created",
        None,
        '"""Extra."""\n',
    )
    assert module.asks == [f"{repo}/src/pkg/extra.py is a new production file"]
    assert (core.kind(), core.asks, core.after) == ("overwritten", [], content)
    assert core.context == "`helper` adds one."
    assert not (repo / NEW).exists()
    assert (repo / CORE).read_text() != content
    submitted = CheckoutLayout(root=repo).review(1).submitted
    assert (submitted / CORE).read_text() == content
    with desk.worktree.lock():
        assert [each.submission for each in desk.drafts().all()] == [1, 1]


def test_a_submission_logs_each_draft_as_asked(desk: Desk, repo: Path) -> None:
    submit_both(desk, repo)
    logged = desk.worktree.verdicts(desk.services.layout).read()
    assert [(each.tool, each.outcome, each.reasons) for each in logged] == [
        ("submit", "ask", ["new-file"]),
        ("submit", "ask", ["asked-anyway"]),
    ]


def test_a_file_landed_since_the_session_started_is_shown_as_context(
    desk: Desk, repo: Path, kit: Kit, queue: FakeQueue
) -> None:
    CallStarted(session=SESSION, cwd=repo, call="t", tool="Bash").apply(kit.bench)
    (repo / TEST).write_text("def test_extra(): ...\n")
    assert (
        CallFinished(session=SESSION, cwd=repo, call="t").apply(kit.bench).context == ""
    )
    draft(desk, NEW, '"""Extra."""\n')
    desk.submit(
        me(repo),
        [
            Offered(path=NEW, context="An extra module."),
            Offered(path=TEST, context="Its tests, landed already."),
        ],
        "Extra, with its tests.",
    )
    shown = queue.parked[1].files[1]
    assert (shown.path, shown.landed, shown.before, shown.after) == (
        TEST,
        True,
        None,
        "def test_extra(): ...\n",
    )


def test_a_finding_refuses_the_whole_submission_listing_every_file(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    draft(desk, NEW, '"""Extra."""\nimport re  # BAD regex\n')
    content = (repo / CORE).read_text() + "y = (1, 2)  # BAD tuple-shape\n"
    draft(desk, CORE, content)
    with pytest.raises(SubmissionError) as refused:
        desk.submit(
            me(repo),
            [
                Offered(path=NEW, context="An extra module."),
                Offered(path=CORE, context="A pair."),
            ],
            "Both.",
        )
    said = str(refused.value)
    assert said.startswith("lup refused the submission")
    drafted_new = draft_path(repo, NEW)
    assert f"{drafted_new}:2:12 - regex: regex fires here" in said
    assert f"{draft_path(repo, CORE)}:11:13 - tuple-shape" in said
    assert queue.parked == {}
    with desk.worktree.lock():
        assert desk.record().submissions == []


def test_submit_refuses_what_it_cant_put_before_the_operator(
    desk: Desk, repo: Path
) -> None:
    draft(desk, NEW, '"""Extra."""\n')
    with pytest.raises(SubmissionError, match="context says what changes"):
        desk.submit(me(repo), [Offered(path=NEW, context="  ")])
    with pytest.raises(SubmissionError, match="several files says what the whole"):
        desk.submit(
            me(repo),
            [Offered(path=NEW, context="a"), Offered(path=CORE, context="b")],
        )
    with pytest.raises(SubmissionError, match="neither a draft nor a change landed"):
        desk.submit(me(repo), [Offered(path=CORE, context="Nothing here.")])
    with pytest.raises(SubmissionError, match="no draft is written"):
        desk.submit(
            me(repo),
            [Offered(path=draft_path(repo, CORE), context="Nothing here.")],
        )
    with pytest.raises(SubmissionError, match="isn't a file here"):
        desk.submit(
            me(repo),
            [Offered(path=NEW, context="Moved.", renamed_from=Path("src/gone.py"))],
        )


def test_a_draft_written_at_its_path_asks_anyway_and_is_begun_at_submit(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    written = draft_path(repo, CORE)
    written.parent.mkdir(parents=True)
    written.write_text((repo / CORE).read_text() + "\n# a note on the helper\n")
    desk.submit(
        me(repo), [Offered(path=written, context="A note I'd like your view on.")]
    )
    [shown] = queue.parked[1].files
    assert (shown.path, shown.asks, shown.landed) == (CORE, [], False)
    assert queue.parked[1].heading == "A note I'd like your view on."
    with desk.worktree.lock():
        begun = desk.drafts().of(CORE)
    assert begun is not None
    assert desk.worktree.store.object(begun.base or "") == (repo / CORE).read_bytes()


def test_a_draft_whose_file_changed_since_it_began_refuses(
    desk: Desk, repo: Path, kit: Kit
) -> None:
    edited(desk)
    CallStarted(session=SESSION, cwd=repo, call="b", tool="Bash").apply(kit.bench)
    (repo / CORE).write_text((repo / CORE).read_text() + "z = 3\n")
    CallFinished(session=SESSION, cwd=repo, call="b").apply(kit.bench)
    with pytest.raises(SubmissionError, match="changed since its draft began"):
        desk.submit(me(repo), [Offered(path=CORE, context="`helper` adds one.")])


def test_submitting_a_file_again_supersedes_its_review(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    before = submit_both(desk, repo)
    draft_path(repo, NEW).write_text('"""Extra, better."""\n')
    submitted = desk.submit(
        me(repo), [Offered(path=NEW, context="Its docstring says more.")]
    )
    assert (submitted.number, submitted.superseded) == (2, [1])
    assert queue.withdrawn == {1: "superseded by review 2, which holds its files"}
    module, core = queue.parked[2].files
    assert module.after == '"""Extra, better."""\n'
    assert module.context == (
        "An extra module, for the tests.\n\nIts docstring says more."
    )
    assert (core.path, core.after) == (CORE, before)
    assert queue.parked[2].heading == "Extra behaviour."
    assert not CheckoutLayout(root=repo).review(1).home.exists()
    with desk.worktree.lock():
        first = desk.record().of(1)
    assert isinstance(first.standing, Withdrawn)
    assert first.told, "the conversation that superseded it was told at submit"


def test_another_conversation_hears_its_review_superseded_once(
    desk: Desk, repo: Path
) -> None:
    submit_both(desk, repo)
    draft_path(repo, NEW).write_text('"""Extra, better."""\n')
    desk.submit(
        me(repo, agent="worker"), [Offered(path=NEW, context="A better docstring.")]
    )
    waited = desk.wait(me(repo), AllReviews(), timeout=timedelta(0))
    [told] = waited.told
    assert told.number == 1
    assert told.text == (
        "Review 1 was withdrawn: superseded by review 2, which holds its files."
    )
    assert desk.wait(me(repo), AllReviews(), timeout=timedelta(0)).told == []


def test_an_approval_is_applied_whole_and_accepted_by_the_judges_store(
    desk: Desk, repo: Path, queue: FakeQueue, kit: Kit
) -> None:
    content = submit_both(desk, repo)
    queue.approve(1, note="Fine.")
    waited = desk.wait(me(repo), OneReview(number=1))
    [told] = waited.told
    assert isinstance(told.standing, Applied)
    assert told.text.startswith(
        f"The operator approved review 1, and it's applied: written {repo / NEW}, "
        f"{repo / CORE}."
    )
    assert "With it, the operator's note:\n    Fine." in told.text
    assert (repo / NEW).read_text() == '"""Extra."""\n'
    assert (repo / CORE).read_text() == content
    assert stored(desk, NEW) == b'"""Extra."""\n'
    assert stored(desk, CORE) == content.encode()
    assert queue.spent == [1]
    assert not CheckoutLayout(root=repo).review(1).home.exists()
    assert not draft_path(repo, NEW).exists()
    with desk.worktree.lock():
        assert desk.drafts().recorded() == []
    assert set(session(desk).approved) >= {NEW, CORE}
    logged = desk.worktree.verdicts(desk.services.layout).read()
    assert [each.answer for each in logged] == ["approved", "approved"]
    CallStarted(session=SESSION, cwd=repo, call="n", tool="Bash").apply(kit.bench)
    assert (
        CallFinished(session=SESSION, cwd=repo, call="n").apply(kit.bench).context == ""
    )
    assert (repo / NEW).exists(), "the checkpoint accepted what was applied"


def test_an_approval_applies_every_file_or_none(
    desk: Desk, repo: Path, queue: FakeQueue, shell: Shell
) -> None:
    blocked = Path("src/pkg/blocked/inner.py")
    (repo / "src/pkg/blocked").write_text("a file where a directory is wanted\n")
    shell.commit(repo, "a file in the way")
    original = (repo / CORE).read_text()
    edited(desk)
    draft(desk, blocked, '"""Blocked."""\n')
    desk.submit(
        me(repo),
        [
            Offered(path=CORE, context="`helper` adds one."),
            Offered(path=blocked, context="A module that can't be written."),
        ],
        "Two files.",
    )
    queue.approve(1)
    with pytest.raises(
        SubmissionError, match="couldn't be applied, and nothing changed"
    ):
        desk.wait(me(repo), OneReview(number=1))
    assert (repo / CORE).read_text() == original
    with desk.worktree.lock():
        assert isinstance(desk.record().of(1).standing, Open)
        assert len(desk.drafts().all()) == 2
    assert queue.spent == []


def test_a_stale_base_applies_nothing_and_is_told_once(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    submit_both(desk, repo)
    moved = (repo / CORE).read_text() + "# pulled from elsewhere\n"
    (repo / CORE).write_text(moved)
    queue.approve(1)
    [told] = desk.wait(me(repo), OneReview(number=1)).told
    assert isinstance(told.standing, Stale)
    assert told.standing.moved == [CORE]
    assert f"nothing was applied: {repo / CORE} changed since" in told.text
    assert (repo / CORE).read_text() == moved
    assert not (repo / NEW).exists()
    assert queue.withdrawn[1].startswith("stale: ")
    assert draft_path(repo, NEW).exists()
    assert desk.wait(me(repo), OneReview(number=1)).told == []


def test_a_decline_leaves_the_drafts_where_they_are(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    content = submit_both(desk, repo)
    comment = LineComment(path=CORE, first=10, last=10, side="after", note="Why one?")
    queue.decline(1, note="Not this way.", comments=[comment])
    [told] = desk.wait(me(repo), OneReview(number=1)).told
    assert isinstance(told.standing, Declined)
    assert told.text.startswith(
        "The operator declined review 1. Nothing changed, and your drafts stand as "
        f"they were: {draft_path(repo, NEW)}, {draft_path(repo, CORE)}."
    )
    assert "With it, the operator's note:\n    Not this way." in told.text
    assert f"  {repo / CORE}:10 (after): Why one?" in told.text
    assert draft_path(repo, CORE).read_text() == content
    assert not (repo / NEW).exists()
    assert queue.withdrawn == {1: "declined, and the answer read"}
    assert CheckoutLayout(root=repo).review(1).submitted.is_dir()
    listing = desk.reviews(Conversation(session=SESSION))
    assert "1  declined: Not this way.: Extra behaviour." in listing.text()


def test_an_after_comment_names_the_submitted_copy_once_the_draft_moved_on(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    submit_both(desk, repo)
    draft_path(repo, CORE).write_text("x = 1\n")
    comment = LineComment(path=CORE, first=2, last=3, side="after", note="Hm.")
    queue.decline(1, comments=[comment])
    [told] = desk.wait(me(repo), OneReview(number=1)).told
    kept = CheckoutLayout(root=repo).review(1).submitted / CORE
    assert f"(its lines count in the version submitted, at {kept}" in told.text


def test_wait_for_the_first_of_several_tells_only_what_ended(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    draft(desk, NEW, '"""Extra."""\n')
    desk.submit(me(repo), [Offered(path=NEW, context="A module.")])
    edited(desk)
    desk.submit(me(repo), [Offered(path=CORE, context="`helper` adds one.")])
    queue.decline(2, note="No.")
    waited = desk.wait(me(repo), AnyReview(numbers=[1, 2]))
    assert [each.number for each in waited.told] == [2]
    assert waited.waiting == [1]
    assert "Still waiting for the operator on review 1." in waited.text()


def test_wait_for_all_holds_until_every_review_ends(
    desk: Desk, repo: Path, queue: FakeQueue, kit: Kit
) -> None:
    draft(desk, NEW, '"""Extra."""\n')
    desk.submit(me(repo), [Offered(path=NEW, context="A module.")])
    edited(desk)
    desk.submit(me(repo), [Offered(path=CORE, context="`helper` adds one.")])
    queue.approve(1)
    kit.clock.on_sleep.append(lambda: queue.decline(2, note="Not yet."))
    waited = desk.wait(me(repo), AllReviews())
    assert [each.number for each in waited.told] == [1, 2]
    assert waited.waiting == []
    assert kit.clock.slept == desk.poll.total_seconds()
    assert (repo / NEW).exists()
    assert queue.frozen_on == [2]


def test_wait_for_a_file_follows_the_review_holding_it(
    desk: Desk, repo: Path, queue: FakeQueue, kit: Kit
) -> None:
    submit_both(desk, repo)
    kit.clock.on_sleep.append(lambda: queue.approve(1))
    [told] = desk.wait(me(repo), FileApplied(path=draft_path(repo, NEW))).told
    assert (told.number, told.standing.kind) == (1, "applied")
    with pytest.raises(SubmissionError, match="no review holds"):
        desk.wait(me(repo), FileApplied(path=Path("README.md")))


def test_a_wait_says_what_still_waits_at_its_timeout(
    desk: Desk, repo: Path, queue: FakeQueue, kit: Kit
) -> None:
    submit_both(desk, repo)
    waited = desk.wait(me(repo), OneReview(number=1), timeout=timedelta(minutes=5))
    assert (waited.told, waited.waiting) == ([], [1])
    assert waited.text() == "Still waiting for the operator on review 1."
    assert kit.clock.slept == timedelta(minutes=5).total_seconds()
    assert queue.frozen_on == [1]
    assert desk.wait(me(repo), OneReview(number=1), timeout=timedelta(0)).waiting == [1]
    assert queue.frozen_on == [1], "a wait that doesn't hold marks nothing"


def test_a_wait_holds_no_longer_than_its_patience(
    desk: Desk, repo: Path, kit: Kit
) -> None:
    submit_both(desk, repo)
    patient = desk.model_copy(update={"patience": timedelta(minutes=1)})
    patient.wait(me(repo), OneReview(number=1), timeout=timedelta(hours=2))
    assert kit.clock.slept == 60


def test_each_answer_is_told_once(desk: Desk, repo: Path, queue: FakeQueue) -> None:
    submit_both(desk, repo)
    queue.approve(1)
    assert len(desk.wait(me(repo), OneReview(number=1)).told) == 1
    again = desk.wait(me(repo), OneReview(number=1))
    assert (again.told, again.settled) == ([], [1])
    assert again.text().startswith("Nothing to wait on: review 1 ended")
    assert desk.wait(me(repo), AllReviews()).told == []


def test_a_remark_ends_a_wait_and_is_told_once(
    desk: Desk, repo: Path, queue: FakeQueue, kit: Kit
) -> None:
    submit_both(desk, repo)
    kit.clock.on_sleep.append(lambda: queue.remark(1, "Is `helper` used?"))
    waited = desk.wait(me(repo), OneReview(number=1))
    [told] = waited.told
    assert isinstance(told.standing, Open)
    assert told.remarks == [Remark(note="Is `helper` used?")]
    assert "The operator remarked, the operator's note:" in told.text
    assert waited.waiting == [1]
    queue.approve(1)
    [answered] = desk.wait(me(repo), OneReview(number=1)).told
    assert answered.remarks == []
    assert "Is `helper` used?" not in answered.text


def test_a_rename_is_reviewed_as_both_sides_and_applied_together(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    kernel = Path("src/pkg/kernel.py")
    content = (repo / CORE).read_text()
    draft(desk, kernel, content)
    desk.submit(
        me(repo),
        [Offered(path=kernel, context="The core, renamed.", renamed_from=CORE)],
    )
    created, deleted = queue.parked[1].files
    assert (created.path, created.kind()) == (kernel, "created")
    assert created.context == "Renamed from `src/pkg/core.py`. The core, renamed."
    assert (deleted.path, deleted.kind()) == (CORE, "deleted")
    assert deleted.context == "Renamed to `src/pkg/kernel.py`. The core, renamed."
    queue.approve(1)
    [told] = desk.wait(me(repo), OneReview(number=1)).told
    assert f"written {repo / kernel}; removed {repo / CORE}." in told.text
    assert (repo / kernel).read_text() == content
    assert not (repo / CORE).exists()
    assert stored(desk, CORE) is None
    assert stored(desk, kernel) == content.encode()


def test_a_draft_edited_since_its_submission_stays_with_only_the_later_edits(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    applied = submit_both(desk, repo)
    later = applied + "z = 3\n"
    draft_path(repo, CORE).write_text(later)
    queue.approve(1)
    [told] = desk.wait(me(repo), OneReview(number=1)).told
    assert (repo / CORE).read_text() == applied
    assert f"Your draft of {repo / CORE} changed since you submitted it" in told.text
    with desk.worktree.lock():
        stayed = desk.drafts().of(CORE)
    assert stayed is not None
    assert stayed.submission is None
    assert desk.worktree.store.object(stayed.base or "") == applied.encode()
    assert draft_path(repo, CORE).read_text() == later


def test_a_dropped_draft_is_neither_listed_nor_submitted(
    desk: Desk, repo: Path
) -> None:
    edited(desk)
    draft_path(repo, CORE).unlink()
    assert desk.reviews().drafts == []
    with pytest.raises(SubmissionError, match="neither a draft nor a change landed"):
        desk.submit(me(repo), [Offered(path=CORE, context="`helper` adds one.")])


def test_reviews_lists_drafts_and_reviews_with_how_each_stands(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    submit_both(desk, repo)
    draft(desk, TEST, "def test_extra(): ...\n", by=Conversation(session="s2"))
    queue.approve(1)
    mine = desk.reviews(Conversation(session=SESSION))
    assert [each.file for each in mine.drafts] == [NEW, CORE]
    assert [each.state() for each in mine.reviews] == [
        "approved, not yet applied: it applies when it's waited on"
    ]
    assert [each.file for each in desk.reviews().drafts] == [NEW, CORE, TEST]
    assert "last submitted in review 1" in mine.text()
    assert queue.spent == [], "listing carries nothing out"


def test_reply_speaks_in_the_thread_of_a_review_still_waiting(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    submit_both(desk, repo)
    said = desk.reply(me(repo, agent="worker"), 1, "`helper` is used by the CLI.")
    assert said == "Replied on review 1, which waits as it did."
    assert queue.replies == ["1: `helper` is used by the CLI."]
    with pytest.raises(SubmissionError, match="another session's"):
        desk.reply(me(repo, session="s2"), 1, "Me too.")
    queue.decline(1)
    desk.wait(me(repo), OneReview(number=1))
    with pytest.raises(SubmissionError, match="its thread is closed"):
        desk.reply(me(repo), 1, "But…")


def test_apply_carries_out_an_approval_without_telling_it(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    submit_both(desk, repo)
    with pytest.raises(SubmissionError, match="isn't approved"):
        desk.apply(1)
    queue.approve(1)
    applied = desk.apply(1)
    assert isinstance(applied.standing, Applied)
    assert not applied.told
    assert (repo / NEW).exists()
    with pytest.raises(SubmissionError, match="is applied"):
        desk.apply(1)


def test_a_review_gone_from_the_queue_is_told_withdrawn(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    submit_both(desk, repo)
    queue.states[1] = Gone(why="cancelled: the operator retired it")
    [told] = desk.wait(me(repo), OneReview(number=1)).told
    assert told.text == "Review 1 was withdrawn: cancelled: the operator retired it."
    assert draft_path(repo, NEW).exists()


def test_a_review_that_cant_be_parked_leaves_nothing_behind(
    desk: Desk, repo: Path, queue: FakeQueue
) -> None:
    draft(desk, NEW, '"""Extra."""\n')
    queue.refusing = True
    with pytest.raises(ReviewError):
        desk.submit(me(repo), [Offered(path=NEW, context="A module.")])
    assert not CheckoutLayout(root=repo).review(1).home.exists()
    with desk.worktree.lock():
        assert desk.record().submissions == []


def test_a_worktree_no_session_reached_is_accepted_as_it_stands(
    kit: Kit, repo: Path, shell: Shell, queue: FakeQueue
) -> None:
    services = kit.bench.services
    desk = Desk(
        worktree=Worktree.of(repo, common(repo, shell), services),
        services=services,
        queue=queue,
    )
    (repo / TEST).write_text("def test_extra(): ...\n")
    written = draft_path(repo, NEW)
    written.parent.mkdir(parents=True)
    written.write_text('"""Extra."""\n')
    desk.submit(
        me(repo, session="operator"),
        [
            Offered(path=written, context="A module."),
            Offered(path=TEST, context="Its tests."),
        ],
        "A module and its tests.",
    )
    module, tests = queue.parked[1].files
    assert module.asks == [f"{repo}/src/pkg/extra.py is a new production file"]
    assert (tests.landed, tests.before) == (True, None)


runner = CliRunner()


@pytest.fixture
def command_line(
    desk: Desk, queue: FakeQueue, monkeypatch: pytest.MonkeyPatch
) -> FakeQueue:
    """The command line, on the test's services and queue, from the repository."""

    def configured() -> Services:
        return desk.services

    def parked(worktree: Path) -> Queue:
        return queue

    monkeypatch.setattr(cli, "services", configured)
    monkeypatch.setattr(cli, "queue", parked)
    monkeypatch.chdir(desk.root)
    return queue


def test_the_command_line_submits_waits_lists_and_replies(
    desk: Desk, repo: Path, command_line: FakeQueue
) -> None:
    written = draft_path(repo, NEW)
    written.parent.mkdir(parents=True)
    written.write_text('"""Extra."""\n')
    files = json.dumps([{"path": str(written), "context": "An extra module."}])
    submitted = runner.invoke(cli.app, ["submit"], input=files)
    assert submitted.exit_code == 0, submitted.output
    assert submitted.output.startswith("Submitted as review 1")
    assert command_line.parked[1].requester == "operator"
    replied = runner.invoke(cli.app, ["reply", "1", "It's small."])
    assert replied.exit_code == 0, replied.output
    assert command_line.replies == ["1: It's small."]
    waiting = runner.invoke(cli.app, ["wait", "1", "--timeout", "PT0S"])
    assert waiting.output.strip() == "Still waiting for the operator on review 1."
    command_line.approve(1)
    applied = runner.invoke(cli.app, ["wait", "--all"])
    assert applied.exit_code == 0, applied.output
    assert applied.output.startswith("The operator approved review 1")
    listed = runner.invoke(cli.app, ["reviews"])
    assert "1  applied: An extra module." in listed.output


def test_the_command_lines_wait_takes_one_form(command_line: FakeQueue) -> None:
    assert runner.invoke(cli.app, ["wait", "1", "2"]).exit_code != 0
    assert runner.invoke(cli.app, ["wait", "1", "--all"]).exit_code != 0
    assert runner.invoke(cli.app, ["wait", "--timeout", "soon", "--all"]).exit_code != 0


def test_the_command_lines_submit_refuses_input_that_isnt_files(
    command_line: FakeQueue,
) -> None:
    result = runner.invoke(cli.app, ["submit"], input='{"path": "a"}')
    assert result.exit_code != 0
    assert "isn't a list of files to submit" in result.output
