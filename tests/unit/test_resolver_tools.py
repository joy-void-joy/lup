"""The material-question tools a resolver worker asks through."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lup.mcp import LupMcpTool, ToolError
from lup.resolver.mailbox import (
    AnswerDoor,
    QuestionMailbox,
    RecordedAnswer,
)
from lup.resolver.models import QuestionAnswer
from lup.resolver.tools import (
    AwaitAnswersInput,
    AwaitAnswersOutput,
    AskedQuestion,
    QueueQuestionsInput,
    QueueQuestionsOutput,
    ResolverToolContext,
    create_question_tools,
    read_resolver_tool_context,
)

EPOCH = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def tools_for(
    mailbox: QuestionMailbox, *, wake: asyncio.Event | None = None
) -> dict[str, LupMcpTool]:
    built = create_question_tools(
        mailbox,
        "alpha",
        run_id="run-1",
        wait_seconds=0.05,
        poll_interval_seconds=0.01,
        wake=wake,
    )
    return {tool.name: tool for tool in built}


def asked(identifier: str, choices: list[str] | None = None) -> AskedQuestion:
    return AskedQuestion(
        id=identifier, prompt=f"Decide {identifier}?", choices=choices or []
    )


def promote(mailbox: QuestionMailbox, identifier: str, value: str) -> None:
    mailbox.record(
        RecordedAnswer(
            run_id="run-1",
            answer=QuestionAnswer(question_id=identifier, value=value),
            door=AnswerDoor.PAGE,
            answered_at=EPOCH,
        )
    )


async def test_queueing_returns_composed_ids_without_waiting(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)

    result = await tools["queue_questions"](
        QueueQuestionsInput(questions=[asked("shape"), asked("naming")])
    )

    assert isinstance(result, QueueQuestionsOutput)
    assert result.question_ids == ["alpha-shape", "alpha-naming"]
    assert result.pending == ["alpha-shape", "alpha-naming"]
    assert [item.question.concern_id for item in mailbox.questions()] == [
        "alpha",
        "alpha",
    ]


async def test_a_worker_cannot_post_against_a_sibling_concern(tmp_path: Path) -> None:
    """The concern is bound by the factory, so ids are composed, not trusted."""
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)

    await tools["queue_questions"](QueueQuestionsInput(questions=[asked("beta-x")]))

    assert [item.question.id for item in mailbox.questions()] == ["alpha-beta-x"]


async def test_an_answer_that_landed_first_is_reported_not_awaited(
    tmp_path: Path,
) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)
    promote(mailbox, "alpha-shape", "tuple")

    result = await tools["queue_questions"](
        QueueQuestionsInput(questions=[asked("shape")])
    )

    assert result.already_answered == ["alpha-shape"]
    assert result.pending == []


async def test_waiting_returns_the_promoted_answers(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    wake = asyncio.Event()
    tools = tools_for(mailbox, wake=wake)
    await tools["queue_questions"](QueueQuestionsInput(questions=[asked("shape")]))
    promote(mailbox, "alpha-shape", "a BaseModel")
    wake.set()

    result = await tools["await_answers"](AwaitAnswersInput())

    assert isinstance(result, AwaitAnswersOutput)
    assert result.status == "answered"
    assert [item.value for item in result.answers] == ["a BaseModel"]
    assert result.unanswered == []


async def test_waiting_on_an_unqueued_id_is_refused_rather_than_blocked(
    tmp_path: Path,
) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)

    with pytest.raises(ToolError, match="no question is queued"):
        await tools["await_answers"](AwaitAnswersInput(question_ids=["alpha-ghost"]))


async def test_waiting_before_queuing_anything_is_refused(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)

    with pytest.raises(ToolError, match="queue a question"):
        await tools["await_answers"](AwaitAnswersInput())


async def test_a_partial_answer_keeps_waiting_and_then_parks(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)
    await tools["queue_questions"](
        QueueQuestionsInput(questions=[asked("shape"), asked("naming")])
    )
    promote(mailbox, "alpha-shape", "tuple")

    result = await tools["await_answers"](AwaitAnswersInput())

    assert result.status == "parked"
    assert [item.id for item in result.answers] == ["alpha-shape"]
    assert result.unanswered == ["alpha-naming"]
    assert "submit your report" in result.instruction


async def test_reasking_a_question_differently_is_refused(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)
    await tools["queue_questions"](QueueQuestionsInput(questions=[asked("shape")]))

    with pytest.raises(ToolError, match="already asked differently"):
        await tools["queue_questions"](
            QueueQuestionsInput(questions=[asked("shape", ["a", "b"])])
        )


async def test_a_recommendation_outside_the_choices_is_a_readable_refusal(
    tmp_path: Path,
) -> None:
    mailbox = QuestionMailbox(tmp_path)
    tools = tools_for(mailbox)

    with pytest.raises(ToolError, match="not well formed"):
        await tools["queue_questions"](
            QueueQuestionsInput(
                questions=[
                    AskedQuestion(
                        id="shape",
                        prompt="Decide?",
                        choices=["a", "b"],
                        recommendation="c",
                    )
                ]
            )
        )


async def test_ask_questions_queues_and_waits_in_one_call(tmp_path: Path) -> None:
    mailbox = QuestionMailbox(tmp_path)
    wake = asyncio.Event()
    tools = tools_for(mailbox, wake=wake)

    async def answer_once() -> None:
        await asyncio.sleep(0)
        promote(mailbox, "alpha-shape", "yes")
        wake.set()

    answering = asyncio.create_task(answer_once())
    result = await tools["ask_questions"](
        QueueQuestionsInput(questions=[asked("shape")])
    )
    await answering

    assert result.status == "answered"
    assert [item.value for item in result.answers] == ["yes"]


def test_the_context_round_trips_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = ResolverToolContext(run_dir=tmp_path, concern_id="alpha")
    for name, value in context.to_env().items():
        monkeypatch.setenv(name, value)

    assert read_resolver_tool_context() == context


def test_no_context_outside_a_tool_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUP_RESOLVER_RUN_DIR", raising=False)
    monkeypatch.delenv("LUP_RESOLVER_CONCERN", raising=False)

    assert read_resolver_tool_context() is None
