"""The no-stop-event completion guard (output.ensure_output_submitted).

Backends without a stop event can finish a session without ever calling
submit_output; the guard's job is to push them with corrective turns and
to stop pushing at the right moments — output appearing, retries running
dry, or the budget cutting the session off.
"""

from pathlib import Path

from lup.adapters.clients.Client import Session
from lup.adapters.common import BudgetExceededError
from lup.workspace.output import (
    MISSING_OUTPUT_MESSAGE,
    ensure_output_submitted,
    output_path,
)
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse


class SubmittingConversation(Session):
    """Writes the output file after a configurable number of turns."""

    def __init__(self, path: Path, succeed_on: int | None) -> None:
        self.path = path
        self.succeed_on = succeed_on
        self.prompts: list[str] = []

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        self.prompts.append(prompt)
        if self.succeed_on is not None and len(self.prompts) >= self.succeed_on:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("{}", encoding="utf-8")
        return LupResponse()

    async def interrupt(self) -> None:
        raise NotImplementedError


class BrokeConversation(Session):
    """Every turn is refused: the session crossed its budget."""

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        raise BudgetExceededError("over budget")

    async def interrupt(self) -> None:
        raise NotImplementedError


async def test_no_turn_when_output_already_exists(tmp_path: Path) -> None:
    path = output_path(tmp_path)
    path.write_text("{}", encoding="utf-8")
    conv = SubmittingConversation(path, succeed_on=None)

    result = await ensure_output_submitted(conv, output_exists=path.exists)

    assert result is None
    assert conv.prompts == []


async def test_corrective_turn_produces_output(tmp_path: Path) -> None:
    path = output_path(tmp_path)
    conv = SubmittingConversation(path, succeed_on=1)

    result = await ensure_output_submitted(conv, output_exists=path.exists)

    assert result is not None
    assert conv.prompts == [MISSING_OUTPUT_MESSAGE]
    assert path.exists()


async def test_retries_exhaust_without_output(tmp_path: Path) -> None:
    path = output_path(tmp_path)
    conv = SubmittingConversation(path, succeed_on=None)

    result = await ensure_output_submitted(
        conv, output_exists=path.exists, max_retries=3
    )

    assert result is not None
    assert len(conv.prompts) == 3
    assert not path.exists()


async def test_budget_exhaustion_stops_attempts(tmp_path: Path) -> None:
    path = output_path(tmp_path)

    result = await ensure_output_submitted(
        BrokeConversation(), output_exists=path.exists, max_retries=5
    )

    assert result is None
    assert not path.exists()
