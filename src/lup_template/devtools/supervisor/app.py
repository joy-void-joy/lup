"""The supervisor web application: one door onto every persisted run.

The page answers a run by writing offers into that run's mailbox, so it
needs no channel to a resolver process and no run needs to have been started
with a page in mind. A run that is moving, one parked overnight, and one
that finished last week are all reachable through exactly the same routes.

Nothing here takes the resolver's state lock. A run holds that lock for its
entire life, so a door that wanted it could only ever serve dead runs.
"""

# lup: defer[when the human-to-worker channel in resolver/tools.py lands]: a
# concern is a status row here and nothing more — there is no way to open one
# and read what its worker actually did. The data is already persisted and
# merely unserved: `ResolverStateRepository.write_round` writes every worker
# turn to `agents/<concern>-round-<n>.json` and every review to
# `reviews/<...>`, while `ConcernView` carries only `rounds` as a count and no
# route exposes either directory. Serve them, and make a concern row open into
# its rounds. The second half is shape, not plumbing: this page is built around
# a run that parks, asks a batch of questions, and waits. If communication with
# workers becomes continuous — a worker asking mid-flight while others run, a
# human volunteering information or retargeting a worker — a form that submits
# one batch of answers stops fitting, and the page needs a per-worker
# conversation view rather than a questions section.

import asyncio
import webbrowser
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.middleware.base import RequestResponseEndpoint
from urllib.parse import urlsplit

from lup.channels.models import utc_now
from lup.resolver.journal import Journal, JournalEntry
from lup.resolver.mailbox import (
    AnswerDoor,
    AnswerOffer,
    ParkRequest,
    QuestionMailbox,
)
from lup.resolver.models import (
    ACCEPT,
    ACCEPTANCE_QUESTION_ID,
    REJECT,
    QuestionAnswer,
)
from lup.resolver.state import ResolverStateRepository, StateCorruptionError
from lup.workspace.paths import project_root
from lup_template.devtools.supervisor.events import stream
from lup_template.devtools.supervisor.projection import (
    ActorIndex,
    AnswerSubmission,
    DecisionSubmission,
    ParkSubmission,
    RunIndex,
    RunSummary,
    SupervisorState,
    answer_problems,
    supervisor_state,
    unanswered_questions,
)

LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "::1"]
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def allowed_host_values(url: str) -> list[str]:
    """Every Host header this app will answer to.

    A loopback bind stops remote packets but not DNS rebinding, where the
    browser treats this origin as the attacker's and the same-origin policy
    therefore does not apply. The Host header is what still differs.
    """
    port = urlsplit(url).port
    return [
        *LOOPBACK_HOSTS,
        *(f"{host}:{port}" for host in LOOPBACK_HOSTS),
    ]


def run_mailbox(state_root: Path, run_id: str) -> QuestionMailbox:
    """The mailbox for one run, whether or not that run ever existed."""
    return QuestionMailbox(state_root / run_id)


def run_journal(state_root: Path, run_id: str) -> Journal:
    """The record for one run, whether or not that run ever existed."""
    return Journal(state_root / run_id)


def last_seq(header: str) -> int:
    """Where a reconnecting reader got to, or the beginning if it says nothing.

    A malformed id replays everything rather than being rejected. The reader
    is a browser reconnecting on its own, so the recoverable reading of a
    value it cannot explain is that it has seen nothing.
    """
    try:
        return int(header)
    except ValueError:
        return -1


def read_run(state_root: Path, run_id: str, adapter: str) -> SupervisorState:
    """Project one persisted run, reporting absence and corruption distinctly."""
    repository = ResolverStateRepository(state_root, run_id)
    if not repository.exists():
        raise HTTPException(status_code=404, detail=f"no persisted run {run_id!r}")
    try:
        state = repository.load()
    except StateCorruptionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return supervisor_state(state, run_mailbox(state_root, run_id), adapter)


def run_summary(state_root: Path, run_id: str, adapter: str) -> RunSummary:
    """One index row, reporting an unreadable run rather than hiding it."""
    try:
        projected = read_run(state_root, run_id, adapter)
    except (HTTPException, ValueError) as error:
        return RunSummary(
            run_id=run_id,
            phase=None,
            concerns=0,
            pending_questions=0,
            accepted=None,
            unreadable=True,
            detail=str(error),
        )
    return RunSummary(
        run_id=run_id,
        phase=projected.phase,
        concerns=len(projected.concerns),
        pending_questions=len(unanswered_questions(projected.pending)),
        accepted=projected.decision,
        live=projected.live,
    )


def run_index(state_root: Path, adapter: str) -> RunIndex:
    """Every run directory holding persisted state, newest name last."""
    if not state_root.is_dir():
        return RunIndex(runs=[])
    return RunIndex(
        runs=[
            run_summary(state_root, entry.name, adapter)
            for entry in sorted(state_root.iterdir())
            if (entry / "state.json").is_file()
        ]
    )


def offer_answers(
    state_root: Path, run_id: str, answers: list[QuestionAnswer], door: AnswerDoor
) -> None:
    """Write one offer per answer, correctable until a promoter takes it."""
    mailbox = run_mailbox(state_root, run_id)
    for answer in answers:
        mailbox.offer(
            AnswerOffer(
                run_id=run_id,
                question_id=answer.question_id,
                value=answer.value,
                door=door,
                offered_at=utc_now(),
            )
        )


def create_supervisor(
    state_root: Path,
    url: str,
    run_id: str | None = None,
    adapter: str = "claude",
) -> FastAPI:
    """Build the supervisor app over every run under the state root."""
    supervisor = FastAPI(title="Lup resolver supervisor", docs_url=None, redoc_url=None)
    html = (
        resources.files("lup_template.devtools.supervisor")
        .joinpath("assets/index.html")
        .read_text("utf-8")
    )
    allowed = allowed_host_values(url)

    @supervisor.middleware("http")
    async def guard_host(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        header = request.headers.get("host", "")  # lup: ignore[dict-get] — header map
        if header not in allowed:
            return Response(status_code=421, content="unexpected Host header")
        return await call_next(request)

    def selected_run() -> str:
        if run_id is None:
            raise HTTPException(
                status_code=409,
                detail="no run selected; pass --run-id or use /api/runs",
            )
        return run_id

    @supervisor.get("/", response_class=HTMLResponse)  # lup: ignore[dict-get] — route
    async def supervisor_home() -> HTMLResponse:
        return HTMLResponse(html)

    @supervisor.get("/api/state")  # lup: ignore[dict-get] — route decorator
    async def read_state() -> SupervisorState:
        return read_run(state_root, selected_run(), adapter)

    @supervisor.get("/api/runs")  # lup: ignore[dict-get] — route decorator
    async def list_runs() -> RunIndex:
        return run_index(state_root, adapter)

    @supervisor.get("/api/runs/{selected}")  # lup: ignore[dict-get] — route decorator
    async def read_selected(selected: str) -> SupervisorState:
        return read_run(state_root, selected, adapter)

    @supervisor.get(  # lup: ignore[dict-get] — route decorator
        "/api/runs/{selected}/events"
    )
    async def read_events(selected: str, request: Request) -> StreamingResponse:
        """Follow one run's record, resuming from whatever the reader last saw."""
        resume = request.headers.get("last-event-id", "")  # lup: ignore[dict-get]
        return StreamingResponse(
            stream(run_journal(state_root, selected), last_seq(resume)),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @supervisor.get(  # lup: ignore[dict-get] — route decorator
        "/api/runs/{selected}/actors"
    )
    async def read_actors(selected: str) -> ActorIndex:
        """Every actor that has produced an entry, in first-seen order."""
        return ActorIndex(actors=run_journal(state_root, selected).actors())

    @supervisor.get(  # lup: ignore[dict-get] — route decorator
        "/api/runs/{selected}/journal/{seq}"
    )
    async def read_entry(selected: str, seq: int) -> JournalEntry:
        """One entry whole, for a reader expanding a truncated block."""
        found = run_journal(state_root, selected).entry(seq)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no journal entry {seq}")
        return found

    @supervisor.post("/api/runs/{selected}/answers")
    async def submit_answers(
        selected: str, submission: AnswerSubmission
    ) -> SupervisorState:
        projected = read_run(state_root, selected, adapter)
        problems = answer_problems(
            [view.question for view in projected.pending], submission.answers
        )
        if problems:
            raise HTTPException(status_code=400, detail="; ".join(problems))
        offer_answers(state_root, selected, submission.answers, AnswerDoor.PAGE)
        return read_run(state_root, selected, adapter)

    @supervisor.post("/api/runs/{selected}/park")
    async def park_run(selected: str, submission: ParkSubmission) -> SupervisorState:
        projected = read_run(state_root, selected, adapter)
        run_mailbox(state_root, selected).park(
            ParkRequest(run_id=projected.run_id, reason=submission.reason)
        )
        return read_run(state_root, selected, adapter)

    @supervisor.post("/api/runs/{selected}/resume")
    async def resume_run(selected: str) -> SupervisorState:
        """Start a resolver over a run the page has just supplied answers for.

        Offers only become answers when a promoter takes them, and the
        promoter lives inside a run. A parked run therefore needs something
        to start it again; doing that here means the page that collected
        the decisions is also the thing that spends them.
        """
        projected = read_run(state_root, selected, adapter)
        if projected.live:
            raise HTTPException(status_code=409, detail="this run is already moving")
        await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "lup-devtools",
            "harness",
            "resolve",
            "--adapter",
            adapter,
            "--run-id",
            selected,
        )
        return projected

    @supervisor.post("/api/runs/{selected}/decision")
    async def record_decision(
        selected: str, submission: DecisionSubmission
    ) -> SupervisorState:
        offer_answers(
            state_root,
            selected,
            [
                QuestionAnswer(
                    question_id=ACCEPTANCE_QUESTION_ID,
                    value=ACCEPT if submission.accepted else REJECT,
                )
            ],
            AnswerDoor.PAGE,
        )
        return read_run(state_root, selected, adapter)

    return supervisor


def serve_supervisor(
    run_id: Annotated[
        str | None, typer.Option("--run-id", help="Run to open on load")
    ] = None,
    adapter: Annotated[
        str, typer.Option("--adapter", help="Adapter named in the rerun recipe")
    ] = "claude",
    host: Annotated[str, typer.Option(help="Interface to bind")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="TCP port to bind")] = 8766,
    open_page: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the page in a browser")
    ] = True,
) -> None:
    """Answer any run under ``.lup/resolve``, live or parked."""
    if host not in LOOPBACK_HOSTS:
        raise typer.BadParameter(
            f"the supervisor binds loopback only; {host!r} is not one of: "
            + ", ".join(LOOPBACK_HOSTS)
        )
    url = f"http://{host}:{port}"
    state_root = project_root() / ".lup" / "resolve"
    typer.echo(f"Resolver supervisor: {url}")
    if open_page:
        webbrowser.open(url)
    uvicorn.run(
        create_supervisor(state_root, url, run_id, adapter), host=host, port=port
    )
