"""Asking Codex from code: the `Codex` declaration.

    analyst = Codex(model="gpt-6.1-sol", system_prompt=PROMPT, effort="low")
    result = await analyst.ask(question, Forecast)

Each ask runs on Codex's app-server, through the `openai-codex` SDK (`runtime.py`),
in lup's own Codex home with the operator's login (`layout.py`), and serves no
tools but lup's own.
"""

from typing import TYPE_CHECKING, overload, override

from pydantic import BaseModel

from lup.adapters.codex.runtime import CodexAdapter, Effort
from lup.sessions.declaration import Asking, Declaration
from lup.sessions.surface import Agent

if TYPE_CHECKING:
    from lup.sessions.results import TurnResult
    from lup.tools.submit import Submit

__all__ = ["Codex"]


class Codex(Declaration, Agent):
    """An agent on Codex: its model, system prompt, reasoning effort and layers."""

    runtime = "codex"
    effort: Effort | None = None
    """How hard the model reasons; none keeps the model's own default."""

    @overload
    async def ask(self, prompt: str, output: None = None) -> TurnResult[str]: ...

    @overload
    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T]
    ) -> TurnResult[T]: ...

    @override
    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T] | None = None
    ) -> TurnResult[T] | TurnResult[str]:
        """Ask `prompt` on Codex, and return the answer: an `output` model, or text without one."""
        adapter = CodexAdapter(
            model=self.model, system_prompt=self.system_prompt, effort=self.effort
        )
        return await Asking(declaration=self, runtime_adapter=adapter).ask(
            prompt, output
        )
