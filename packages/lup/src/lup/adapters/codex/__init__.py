"""Asking Codex from code: the `Codex` declaration.

    analyst = Codex(model="gpt-6.1-sol", system_prompt=PROMPT, effort="low")
    result = await analyst.ask(question, Forecast)

Each ask runs on Codex's app-server, through the `openai-codex` SDK (`runtime.py`),
in lup's own Codex home with the operator's login (`layout.py`), and serves no
tools but lup's own.

The same declaration compiles for a terminal (`terminal`, `terminal.py`): Codex's
interactive CLI in the operator's own home, with lup's settings passed as flags,
overrides and a requirements file of the launch's own.

The `openai-codex` SDK is imported when an ask first runs, so the declaration,
and its terminal, need no `lup[codex]` extra: a launch runs the CLI it's given.
"""

from typing import TYPE_CHECKING, Literal, overload, override

from pydantic import BaseModel

from lup.adapters.codex.layout import CodexLayout
from lup.adapters.codex.settings import CodexSettings
from lup.adapters.codex.terminal import compiled
from lup.sessions.declaration import Asking, Declaration
from lup.sessions.errors import needs_extra
from lup.sessions.terminal import TerminalError

if TYPE_CHECKING:
    from lup.sessions.results import TurnResult
    from lup.sessions.terminal import Terminal, TerminalSettings
    from lup.tools.submit import Submit

__all__ = ["Codex", "Effort"]

type Effort = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
]
"""How hard Codex's model reasons, in Codex's own words."""


class Codex(Declaration):
    """An agent on Codex: their model, system prompt, reasoning effort and layers."""

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
        """Ask `prompt` on Codex, and return the answer: an `output` model, or text without one.

        Raise `RuntimeMissingError` where the `lup[codex]` extra isn't installed.
        """
        with needs_extra("codex"):
            from lup.adapters.codex.runtime import CodexAdapter
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

    @override
    def held(self, settings: TerminalSettings) -> Terminal:
        """Refuse: Codex has no held session yet.

        Its held session would be `codex app-server --listen unix://…` in the room,
        with lup's launcher a client of its socket, rather than a process held
        over its input and output: over stdio the server ends with its
        controller, and over a socket it outlives every connection, so a terminal
        attaches to the live thread (`codex --remote unix://… resume <id>`)
        rather than ending the process and resuming it, and only stopping the
        container ends it. Its turns start with `turn/start`
        while the thread is idle and `turn/steer` while it's busy, and
        `turn/interrupt` ends the turn but leaves a running shell going. Codex
        itself refuses a second writer on a thread. Measured against a stand-in
        for the Responses API, on no real login (`docs/field-notes.md`, *A
        session held with no terminal*).
        """
        del settings
        message = (
            "Codex has no held session yet: its app-server on a socket in the room "
            "is how it would be held (`lup.adapters.codex`, `Codex.held`)"
        )
        raise TerminalError(message)
