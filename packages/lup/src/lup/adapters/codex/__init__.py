"""Asking Codex from code: the `Codex` declaration.

    analyst = Codex(model="gpt-6.1-sol", system_prompt=PROMPT, effort="low")
    result = await analyst.ask(question, Forecast)

Each ask runs on Codex's app-server, through the `openai-codex` SDK (`runtime.py`),
in lup's own Codex home with the operator's login (`layout.py`), and serves no
tools but lup's own.

The same declaration compiles for a terminal (`terminal`, `terminal.py`): Codex's
interactive CLI in the operator's own home, with lup's settings passed as flags,
overrides and a requirements file of the launch's own.
"""

from typing import TYPE_CHECKING, overload, override

from pydantic import BaseModel

from lup.adapters.codex.layout import CodexLayout
from lup.adapters.codex.runtime import CodexAdapter, Effort
from lup.adapters.codex.settings import CodexSettings
from lup.adapters.codex.terminal import compiled
from lup.sessions.declaration import Asking, Declaration

if TYPE_CHECKING:
    from lup.sessions.results import TurnResult
    from lup.sessions.terminal import Terminal, TerminalSettings
    from lup.tools.submit import Submit

__all__ = ["Codex"]


class Codex(Declaration):
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

    @override
    def terminal(self, settings: TerminalSettings) -> Terminal:
        """Compile the declaration for Codex's interactive CLI, with lup's settings."""
        return compiled(
            model=self.model,
            system_prompt=self.system_prompt,
            effort=self.effort,
            settings=settings,
            layout=CodexLayout.of(CodexSettings()),
        )
