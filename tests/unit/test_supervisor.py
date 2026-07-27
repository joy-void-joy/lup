"""Web supervision of persisted resolver runs, through the mailbox alone.

There is no session, no hub, and no thread here because the supervisor no
longer needs any: it reads a run's files and writes offers into that run's
mailbox. Every test therefore builds a run on disk and drives the app over
it, exactly as a page drives a run nothing in this process is attached to.
"""

import re  # lup: ignore[import-re] — extracting identifiers from packaged JS
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path

import pytest
import typer
from httpx import ASGITransport, AsyncClient

from lup.harness.models import ResolveSpec, SkillInvocation
from lup.resolver.mailbox import (
    AnswerDoor,
    PendingQuestion,
    QuestionMailbox,
    RecordedAnswer,
    utc_now,
)
from lup.resolver.models import (
    ACCEPTANCE_QUESTION_ID,
    AcceptanceCriterion,
    AnswerBatch,
    Concern,
    ConcernProgress,
    ConcernStatus,
    FinalReview,
    MaterialQuestion,
    QuestionAnswer,
    QuestionBatch,
    ResolvePhase,
    ResolveState,
    SourceSnapshot,
)
from lup.resolver.state import ResolverStateRepository
from lup_template.devtools.supervisor import doors
from lup_template.devtools.supervisor.app import create_supervisor
from lup_template.devtools.supervisor.events import (
    ConcernEvent,
    PhaseEvent,
    QuestionsEvent,
    StatusEvent,
    run_events,
    stream,
)
from lup_template.devtools.supervisor.projection import (
    LIVENESS_WINDOW_SECONDS,
    RunIndex,
    RunStatus,
    SupervisorState,
    run_is_live,
    supervisor_state,
)

BASE_URL = "http://127.0.0.1:8766"


def question(identifier: str, choices: list[str] | None = None) -> MaterialQuestion:
    return MaterialQuestion(
        id=identifier,
        concern_id="alpha",
        prompt=f"Decide {identifier}?",
        choices=choices or [],
        recommendation=(choices or [None])[0],
    )


def concern_of(identifier: str) -> Concern:
    return Concern(
        id=identifier,
        title=identifier.title(),
        spec=f"Resolve {identifier}",
        criteria=[AcceptanceCriterion(id=f"{identifier}-done", description="done")],
    )


def persisted_state(
    phase: ResolvePhase = ResolvePhase.WORKERS,
    questions: QuestionBatch | None = None,
    answers: AnswerBatch | None = None,
    final_review: FinalReview | None = None,
    accepted: bool | None = None,
) -> ResolveState:
    return ResolveState(
        config_digest="config-sha",
        run_id="run-1",
        phase=phase,
        source=SourceSnapshot(branch="dev", commit="source-sha"),
        spec=ResolveSpec(
            id="resolve",
            worker_skill=SkillInvocation(plugin="lup", skill="worker"),
            review_skill=SkillInvocation(plugin="lup", skill="review"),
            merge_skill=SkillInvocation(plugin="lup", skill="merge"),
        ),
        concerns=[concern_of("alpha")],
        progress=[ConcernProgress(concern_id="alpha")],
        questions=questions,
        answers=answers,
        final_review=final_review,
        accepted=accepted,
    )


def build_run(tmp_path: Path, state: ResolveState | None = None) -> QuestionMailbox:
    """Persist one run and hand back the mailbox every door writes into."""
    ResolverStateRepository(tmp_path, "run-1").save(state or persisted_state())
    return QuestionMailbox(tmp_path / "run-1")


def ask(mailbox: QuestionMailbox, identifier: str, choices: list[str] | None) -> None:
    mailbox.queue(
        PendingQuestion(
            run_id="run-1",
            question=question(identifier, choices),
            asked_by="alpha",
            asked_at=utc_now(),
        )
    )


def client_for(state_root: Path) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=create_supervisor(state_root, BASE_URL, "run-1")),
        base_url=BASE_URL,
    )


async def test_supervisor_serves_the_packaged_page(tmp_path: Path) -> None:
    build_run(tmp_path)
    async with client_for(tmp_path) as client:
        response = await client.get("/")  # lup: ignore[dict-get] — HTTP client

    assert response.status_code == 200
    assert "Resolver supervision" in response.text
    assert "Pending questions" in response.text


async def test_a_run_reads_back_from_its_mailbox(tmp_path: Path) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    async with client_for(tmp_path) as client:
        listing = await client.get("/api/runs")  # lup: ignore[dict-get] — HTTP client
        read = await client.get("/api/state")  # lup: ignore[dict-get] — HTTP client
    index = RunIndex.model_validate(listing.json())
    state = SupervisorState.model_validate(read.json())

    assert [run.run_id for run in index.runs] == ["run-1"]
    assert index.runs[0].pending_questions == 1
    assert [view.question.id for view in state.pending] == ["q1"]
    assert state.pending[0].answered is None
    assert state.concerns[0].status is ConcernStatus.DISCOVERED
    assert "--answer q1=<value>" in state.rerun_recipe


async def test_browser_answers_become_offers_a_promoter_can_take(
    tmp_path: Path,
) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    async with client_for(tmp_path) as client:
        response = await client.post(
            "/api/runs/run-1/answers",
            json={"answers": [{"question_id": "q1", "value": "no"}]},
        )

    assert response.status_code == 200
    offers = mailbox.offers()
    assert [(offer.question_id, offer.value) for offer in offers] == [("q1", "no")]
    assert offers[0].door is AnswerDoor.PAGE
    assert mailbox.answers() == []


async def test_a_partial_answer_set_is_accepted(tmp_path: Path) -> None:
    """Answering one of two open questions is the point, not an error.

    The single-open-batch invariant is gone: concerns ask concurrently, and
    whoever knows one decision answers it without waiting to know the rest.
    """
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])
    ask(mailbox, "q2", None)

    async with client_for(tmp_path) as client:
        response = await client.post(
            "/api/runs/run-1/answers",
            json={"answers": [{"question_id": "q1", "value": "yes"}]},
        )

    assert response.status_code == 200
    assert [offer.question_id for offer in mailbox.offers()] == ["q1"]


@pytest.mark.parametrize(
    "answers",
    [
        [{"question_id": "q1", "value": "yes"}, {"question_id": "ghost", "value": "y"}],
        [{"question_id": "q1", "value": "maybe"}],
        [{"question_id": "q1", "value": "yes"}, {"question_id": "q1", "value": "no"}],
    ],
    ids=["unknown", "not-a-choice", "duplicate"],
)
async def test_a_bad_answer_set_is_correctable_instead_of_fatal(
    tmp_path: Path,
    answers: list[dict[str, str]],  # lup: ignore[dict-str-payload] — raw JSON body
) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    async with client_for(tmp_path) as client:
        response = await client.post(
            "/api/runs/run-1/answers", json={"answers": answers}
        )

    assert response.status_code == 400
    assert mailbox.offers() == []


async def test_an_offer_stays_correctable_until_it_is_promoted(tmp_path: Path) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    async with client_for(tmp_path) as client:
        await client.post(
            "/api/runs/run-1/answers",
            json={"answers": [{"question_id": "q1", "value": "yes"}]},
        )
        await client.post(
            "/api/runs/run-1/answers",
            json={"answers": [{"question_id": "q1", "value": "no"}]},
        )

    assert [(offer.question_id, offer.value) for offer in mailbox.offers()] == [
        ("q1", "no")
    ]


async def test_an_answered_question_reports_its_promoted_value(tmp_path: Path) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])
    mailbox.record(
        RecordedAnswer(
            run_id="run-1",
            answer=QuestionAnswer(question_id="q1", value="yes"),
            door=AnswerDoor.FLAG,
            answered_at=utc_now(),
        )
    )

    async with client_for(tmp_path) as client:
        read = await client.get("/api/state")  # lup: ignore[dict-get] — HTTP client
    state = SupervisorState.model_validate(read.json())

    assert state.pending[0].answered == "yes"
    assert state.status is RunStatus.RUNNING
    assert "--answer" not in state.rerun_recipe


async def test_parking_from_the_page_writes_the_park_request(tmp_path: Path) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", None)

    async with client_for(tmp_path) as client:
        response = await client.post(
            "/api/runs/run-1/park", json={"reason": "answering tomorrow"}
        )

    assert response.status_code == 200
    request = mailbox.parked()
    assert request is not None
    assert request.reason == "answering tomorrow"


async def test_the_decision_is_offered_as_the_reserved_acceptance_question(
    tmp_path: Path,
) -> None:
    mailbox = build_run(
        tmp_path,
        persisted_state(
            phase=ResolvePhase.ACCEPTANCE,
            final_review=FinalReview(accepted=True, reason="clean"),
        ),
    )

    async with client_for(tmp_path) as client:
        response = await client.post(
            "/api/runs/run-1/decision", json={"accepted": True}
        )

    assert response.status_code == 200
    offers = mailbox.offers()
    assert [(offer.question_id, offer.value) for offer in offers] == [
        (ACCEPTANCE_QUESTION_ID, "accept")
    ]


async def test_a_missing_run_is_reported_rather_than_invented(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        response = await client.get(  # lup: ignore[dict-get] — HTTP client
            "/api/runs/ghost"
        )

    assert response.status_code == 404


async def test_no_door_takes_the_run_lock(tmp_path: Path) -> None:
    """A live run holds ``.run.lock`` for its whole life.

    A door that reached for it — even to ask whether a run is live — could
    only ever serve runs that had already finished, and a shared probe can
    make a concurrently starting run fail to take its exclusive lease.
    """
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    def refuse(_self: ResolverStateRepository) -> None:
        raise AssertionError("a supervisor door took the resolver state lock")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ResolverStateRepository, "exclusive", refuse)
        async with client_for(tmp_path) as client:
            await client.get("/api/runs")  # lup: ignore[dict-get] — HTTP client
            await client.get("/api/state")  # lup: ignore[dict-get] — HTTP client
            await client.post(
                "/api/runs/run-1/answers",
                json={"answers": [{"question_id": "q1", "value": "yes"}]},
            )
            await client.post("/api/runs/run-1/park", json={})
            decision = await client.post(
                "/api/runs/run-1/decision", json={"accepted": False}
            )

    assert decision.status_code == 200


async def test_resuming_a_moving_run_is_refused(tmp_path: Path) -> None:
    """Two resolvers over one run would race for its exclusive lease."""
    build_run(tmp_path)

    async with client_for(tmp_path) as client:
        response = await client.post("/api/runs/run-1/resume", json={})

    assert response.status_code == 409


def test_console_doors_read_and_answer_without_the_run_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    def refuse(_self: ResolverStateRepository) -> None:
        raise AssertionError("a console door took the resolver state lock")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ResolverStateRepository, "exclusive", refuse)
        patch.setattr(doors, "resolve_state_root", lambda: tmp_path)
        doors.list_questions(run_id="run-1", pending_only=True)
        listed = capsys.readouterr().out
        doors.answer_questions(pairs=["q1=no"], run_id="run-1")
        doors.park_run(run_id="run-1", reason="answering tomorrow")

    assert "q1 (concern alpha)" in listed
    assert "choices: yes | no" in listed
    assert [(offer.question_id, offer.value) for offer in mailbox.offers()] == [
        ("q1", "no")
    ]
    assert mailbox.offers()[0].door is AnswerDoor.CONSOLE
    parked = mailbox.parked()
    assert parked is not None and parked.reason == "answering tomorrow"


@pytest.mark.parametrize(
    "pairs",
    [["ghost=yes"], ["q1=maybe"], ["q1"]],
    ids=["unknown", "not-a-choice", "malformed"],
)
def test_a_console_answer_is_refused_before_it_reaches_the_mailbox(
    tmp_path: Path, pairs: list[str]
) -> None:
    mailbox = build_run(tmp_path)
    ask(mailbox, "q1", ["yes", "no"])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(doors, "resolve_state_root", lambda: tmp_path)
        with pytest.raises(typer.BadParameter):
            doors.answer_questions(pairs=pairs, run_id="run-1")

    assert mailbox.offers() == []


def test_a_console_door_refuses_a_run_that_was_never_recorded(tmp_path: Path) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(doors, "resolve_state_root", lambda: tmp_path)
        with pytest.raises(typer.BadParameter, match="no resolver run"):
            doors.list_questions(run_id="ghost", pending_only=False)


async def test_an_unexpected_host_header_is_refused(tmp_path: Path) -> None:
    build_run(tmp_path)
    async with AsyncClient(
        transport=ASGITransport(app=create_supervisor(tmp_path, BASE_URL, "run-1")),
        base_url="http://evil.example",
    ) as client:
        response = await client.get("/")  # lup: ignore[dict-get] — HTTP client

    assert response.status_code == 421


def test_a_finished_run_falls_back_to_the_state_file_fold(tmp_path: Path) -> None:
    """A run recorded before the mailbox existed still renders its questions."""
    state = persisted_state(
        phase=ResolvePhase.COMPLETE,
        questions=QuestionBatch(run_id="run-1", questions=[question("q1", ["yes"])]),
        answers=AnswerBatch(
            run_id="run-1", answers=[QuestionAnswer(question_id="q1", value="yes")]
        ),
    )
    projected = supervisor_state(state, QuestionMailbox(tmp_path / "empty"), "claude")

    assert [view.question.id for view in projected.pending] == ["q1"]
    assert projected.pending[0].answered == "yes"
    assert projected.status is RunStatus.COMPLETE


def test_liveness_is_derived_from_activity_not_from_a_lock() -> None:
    moving = persisted_state(phase=ResolvePhase.WORKERS)
    finished = persisted_state(phase=ResolvePhase.COMPLETE)

    assert run_is_live(moving, activity=100.0, now=100.0)
    assert not run_is_live(moving, activity=0.0, now=LIVENESS_WINDOW_SECONDS + 1.0)
    assert not run_is_live(finished, activity=100.0, now=100.0)


def test_an_unanswered_question_parks_a_run_that_stopped_moving() -> None:
    state = persisted_state(
        phase=ResolvePhase.WORKERS,
        questions=QuestionBatch(run_id="run-1", questions=[question("q1", None)]),
    )
    quiet = supervisor_state(
        state, QuestionMailbox(Path("/nonexistent")), "claude", now=1e12
    )

    assert not quiet.live
    assert quiet.status is RunStatus.PARKED


def projection(
    phase: ResolvePhase = ResolvePhase.WORKERS, status: ConcernStatus | None = None
) -> SupervisorState:
    state = persisted_state(phase=phase)
    if status is not None:
        state = state.model_copy(
            update={"progress": [ConcernProgress(concern_id="alpha", status=status)]}
        )
    return supervisor_state(state, QuestionMailbox(Path("/nonexistent")), "claude")


def test_the_first_observation_emits_nothing() -> None:
    """A page hydrates before it connects, so replaying the run restates it."""
    assert run_events(None, projection()) == []


def test_only_observed_differences_become_events() -> None:
    before = projection()
    after = projection(phase=ResolvePhase.REVIEW, status=ConcernStatus.VERIFIED)

    events = run_events(before, after)

    assert PhaseEvent(phase=ResolvePhase.REVIEW) in events
    assert any(isinstance(event, ConcernEvent) for event in events)
    assert run_events(before, projection()) == []


def test_a_new_question_becomes_a_questions_event(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path / "run-1")
    before = supervisor_state(persisted_state(), mailbox, "claude")
    ask(mailbox, "q1", None)
    after = supervisor_state(persisted_state(), mailbox, "claude")

    events = run_events(before, after)

    assert any(isinstance(event, QuestionsEvent) for event in events)
    assert any(isinstance(event, StatusEvent) for event in events)


async def test_the_stream_frames_events_and_keeps_the_connection_alive() -> None:
    states = [projection(), projection(phase=ResolvePhase.REVIEW), projection()]

    def read() -> SupervisorState | None:
        return states.pop(0) if states else None

    body = stream(read, interval=0.0, heartbeat=0.0)
    frames = [await anext(body) for _ in range(3)]
    await body.aclose()

    assert frames[0].startswith("retry:")
    assert frames[1] == ": keep-alive\n\n"
    assert '"phase":"review"' in frames[2]


class ElementIds(HTMLParser):
    """Collect every id the packaged page declares."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],  # lup: ignore[tuple-shape] — stdlib API
    ) -> None:
        del tag
        self.ids.extend(
            value for name, value in attrs if name == "id" and value is not None
        )


def test_every_element_the_script_reaches_for_exists_in_the_markup() -> None:
    """The zero-build page has no compiler, so a typo is a silent null.

    Nothing else in the suite would notice a renamed id: the routes keep
    passing and the page simply stops updating that region.
    """
    page = (
        resources.files("lup_template.devtools.supervisor")
        .joinpath("assets/index.html")
        .read_text("utf-8")
    )
    parser = ElementIds()
    parser.feed(page)
    referenced = re.findall(  # lup: ignore[re-call] — identifiers in packaged JS
        r"""element\(["']([\w-]+)["']\)""", page
    )

    assert referenced
    assert [name for name in referenced if name not in parser.ids] == []


def test_the_page_posts_only_routes_the_app_serves() -> None:
    """The page and the app share no schema, so a renamed route is silent."""
    page = (
        resources.files("lup_template.devtools.supervisor")
        .joinpath("assets/index.html")
        .read_text("utf-8")
    )
    posted = re.findall(  # lup: ignore[re-call] — fetch targets in packaged JS
        r"""/api/runs/\$\{state\.run_id\}/(\w+)""", page
    )

    assert sorted(dict.fromkeys(posted)) == [
        "answers",
        "decision",
        "events",
        "park",
        "resume",
    ]
