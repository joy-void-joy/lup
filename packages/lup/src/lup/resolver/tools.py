"""The tools a resolver worker asks its material questions through.

A worker used to surface questions by ending its turn with them in its
typed report, which cost a whole new session to deliver the answer. These
tools let it ask mid-turn and keep working.

The handlers touch nothing but the mailbox, so one factory serves both
transports: Claude registers the server in-process, Codex spawns it as a
stdio subprocess that rebuilds the same mailbox from the relayed run
directory. Only where the mailbox comes from differs.
"""

# lup: defer[when mid-run-concern-admission lands]: every tool here runs
# worker to human, and nothing runs the other way, so a human can only tell a
# worker something the worker thought to ask. Information discovered after a
# concern's questions are answered cannot reach it: `Mailbox.record` opens with
# "x" so first answer wins by design, and a concern whose questions are all
# answered has no channel left at all. Widen the interface so the orchestrating
# side can act on a live run — spawn a new worker carrying its own concern, and
# reshape the worker/concern mapping itself (split one concern across workers,
# merge several into one, retarget a worker that has not started). Admission of
# a new concern is the narrow case of this; the general case is that run shape
# stays editable while the run is alive. A worked example from the run that
# raised this: `library-application-boundary` was planned as an audit whose
# criterion 6 forbids it from moving any code, with `policy-data-to-template`
# depending on it to act — so the audit wrote a rule, found real violations,
# and was not permitted to fix them. Two concerns that should have been one,
# discovered only once both were leased and unmergeable. The planning half of
# that is its own defect: an audit that deliberately produces no code is the
# human-scarcity reflex the Plan at Agent Speed guidance already rejects, so
# criteria should scope analysis and action together rather than staging them.

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from lup.mcp import LupMcpTool, ToolError, lup_tool
from lup.channels.models import utc_now
from lup.resolver.mailbox import (
    ANSWER_POLL_SECONDS,
    MailboxConflictError,
    PendingQuestion,
    QuestionMailbox,
    wait_for_answers,
)
from lup.resolver.models import MaterialQuestion
from lup.types import EnvVars

RESOLVER_RUN_DIR_ENV = "LUP_RESOLVER_RUN_DIR"
RESOLVER_CONCERN_ENV = "LUP_RESOLVER_CONCERN"
TOOL_WAIT_SECONDS = 300.0

WAIT_CONTRACT = (
    "This call blocks until a human answers. Blocking is expected and correct: "
    "you are not stuck, you are waiting. Do not poll, do not call this again in "
    "a loop, do not sleep and retry, and do not read files under .lup/. Make one "
    "call, wait for it to return, then act on what it gives you."
)


class ResolverToolContext(BaseModel):
    """What a tool-serving subprocess needs to find its run's mailbox."""

    run_dir: Path
    concern_id: str

    def to_env(self) -> EnvVars:
        return {
            RESOLVER_RUN_DIR_ENV: str(self.run_dir),
            RESOLVER_CONCERN_ENV: self.concern_id,
        }


class ResolverToolEnv(BaseSettings):
    """The relay's consumer side, parsed from the environment."""

    run_dir: Path | None = Field(default=None, validation_alias=RESOLVER_RUN_DIR_ENV)
    concern_id: str | None = Field(default=None, validation_alias=RESOLVER_CONCERN_ENV)


def read_resolver_tool_context() -> ResolverToolContext | None:
    """Rebuild the relayed context, or None when this is not a tool subprocess."""
    env = ResolverToolEnv()
    if env.run_dir is None or env.concern_id is None:
        return None
    return ResolverToolContext(run_dir=env.run_dir, concern_id=env.concern_id)


class AskedQuestion(BaseModel):
    """One decision a worker needs a human to make."""

    id: str = Field(
        description="Short id, unique among your questions. Letters, digits, dashes."
    )
    prompt: str = Field(
        description="The decision, stated so a human can answer it cold"
    )
    choices: list[str] = Field(
        default_factory=list,
        description="The allowed answers. Leave empty for free text.",
    )
    recommendation: str | None = Field(
        default=None, description="Your preferred answer, which must be a choice"
    )


class QueueQuestionsInput(BaseModel):
    questions: list[AskedQuestion] = Field(
        min_length=1, description="Every question you want answered"
    )


class QueueQuestionsOutput(BaseModel):
    question_ids: list[str] = Field(description="Pass these verbatim to await_answers")
    already_answered: list[str] = Field(
        description="Questions a human had already answered before you asked"
    )
    pending: list[str] = Field(description="Questions still waiting for a human")


class AwaitAnswersInput(BaseModel):
    question_ids: list[str] = Field(
        default_factory=list,
        description="Ids from queue_questions. Empty waits for every one you queued.",
    )


class AnsweredQuestion(BaseModel):
    id: str
    prompt: str
    value: str


class AwaitAnswersOutput(BaseModel):
    status: Literal["answered", "parked"]
    answers: list[AnsweredQuestion]
    unanswered: list[str]
    instruction: str


def create_question_tools(
    mailbox: QuestionMailbox,
    concern_id: str,
    *,
    run_id: str,
    poll_interval_seconds: float = ANSWER_POLL_SECONDS,
    wait_seconds: float = TOOL_WAIT_SECONDS,
    wake: asyncio.Event | None = None,
) -> list[LupMcpTool]:
    """Build the ask tools bound to one concern's mailbox.

    ``concern_id`` is bound here rather than taken as an argument, so a
    worker structurally cannot post a question against a sibling concern,
    and ids are composed rather than trusted — two workers inventing the
    same short id must not collide in one flat namespace.
    """
    queued: list[str] = []

    def compose(identifier: str) -> str:
        return f"{concern_id}-{identifier}"

    def prompts() -> dict[str, str]:  # lup: ignore[dict-str-payload] — open id map
        return {item.question.id: item.question.prompt for item in mailbox.questions()}

    @lup_tool(
        "Ask the human one or more material questions about this concern and "
        "return immediately. Use this the moment you know a decision is not "
        "yours to make — queue every question you have at once so a human can "
        "answer them in one pass, keep working on whatever does not depend on "
        "them, then call await_answers. Returns the ids to wait on.",
        name="queue_questions",
    )
    async def queue_questions(params: QueueQuestionsInput) -> QueueQuestionsOutput:
        answered = mailbox.answered_ids()
        composed: list[str] = []
        for asked in params.questions:
            identifier = compose(asked.id)
            try:
                question = MaterialQuestion(
                    id=identifier,
                    concern_id=concern_id,
                    prompt=asked.prompt,
                    choices=asked.choices,
                    recommendation=asked.recommendation,
                )
            except ValueError as error:
                raise ToolError(
                    f"question {asked.id!r} is not well formed: {error}"
                ) from error
            try:
                mailbox.queue(
                    PendingQuestion(
                        run_id=run_id,
                        question=question,
                        asked_by=concern_id,
                        asked_at=utc_now(),
                    )
                )
            except MailboxConflictError as error:
                raise ToolError(str(error)) from error
            composed.append(identifier)
            if identifier not in queued:
                queued.append(identifier)
        return QueueQuestionsOutput(
            question_ids=composed,
            already_answered=[name for name in composed if name in answered],
            pending=[name for name in composed if name not in answered],
        )

    @lup_tool(
        "Wait for the human's answers to questions you queued, then return them. "
        + WAIT_CONTRACT
        + " If nobody answers in time the run parks: you will get status "
        "'parked', and you should stop work on this concern and submit your "
        "report so the orchestrator can resume once an answer arrives.",
        name="await_answers",
    )
    async def await_answers(params: AwaitAnswersInput) -> AwaitAnswersOutput:
        wanted = params.question_ids or list(queued)
        if not wanted:
            raise ToolError("queue a question before waiting for an answer")
        known = prompts()
        unknown = [name for name in wanted if name not in known]
        if unknown:
            raise ToolError(
                "no question is queued under "
                + ", ".join(repr(name) for name in unknown)
                + "; call queue_questions first and pass the ids it returns"
            )
        result = await wait_for_answers(
            mailbox,
            wanted,
            wait_seconds=wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
            wake=wake,
        )
        answers = [
            AnsweredQuestion(
                id=record.answer.question_id,
                prompt=known[record.answer.question_id],
                value=record.answer.value,
            )
            for record in result.answered
        ]
        if not result.unanswered:
            return AwaitAnswersOutput(
                status="answered",
                answers=answers,
                unanswered=[],
                instruction="Act on these answers and finish the concern.",
            )
        return AwaitAnswersOutput(
            status="parked",
            answers=answers,
            unanswered=result.unanswered,
            instruction=(
                f"No answer arrived ({result.reason}). Stop working on this "
                "concern and submit your report now — the orchestrator parks the "
                "run and resumes it once a human answers."
            ),
        )

    @lup_tool(
        "Ask the human one or more material questions and wait for the answers. "
        "This is queue_questions followed by await_answers. " + WAIT_CONTRACT,
        name="ask_questions",
    )
    async def ask_questions(params: QueueQuestionsInput) -> AwaitAnswersOutput:
        posted = await queue_questions(params)
        return await await_answers(AwaitAnswersInput(question_ids=posted.question_ids))

    return [queue_questions, await_answers, ask_questions]
