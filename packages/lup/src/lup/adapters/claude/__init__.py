"""`Claude`: an agent asked through Claude Code, the runtime its Agent SDK bundles.

    translator = Claude(model="opus", system_prompt=PROMPT, effort="low")
    result = await translator.ask(segment.model_dump_json(), Translations)

Each ask runs in a Claude Code process of its own, with no tools but lup's own,
none of the operator's settings, and nothing written to their history
(`lup.adapters.claude.runtime`). The login is the operator's own CLI login.

The same declaration compiles for a terminal (`terminal`,
`lup.adapters.claude.terminal`): Claude Code's interactive CLI, with lup's settings
passed as flags and files of the launch's own.
"""

from typing import TYPE_CHECKING, overload, override

from pydantic import BaseModel

from lup.adapters.claude.layout import ClaudeLayout
from lup.adapters.claude.runtime import ClaudeAdapter, Effort
from lup.adapters.claude.settings import ClaudeSettings
from lup.adapters.claude.terminal import compiled
from lup.sessions.declaration import Asking, Declaration

if TYPE_CHECKING:
    from lup.sessions.results import TurnResult
    from lup.sessions.terminal import Terminal, TerminalSettings
    from lup.tools.submit import Submit


class Claude(Declaration):
    """An agent asked through Claude Code."""

    runtime = "claude"
    effort: Effort | None = None
    """How much effort the model puts into an answer; none leaves it to Claude Code."""

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
        """Ask `prompt` in Claude Code, and return the answer: an `output` model, or text without one."""
        adapter = ClaudeAdapter(
            model=self.model, system_prompt=self.system_prompt, effort=self.effort
        )
        return await Asking(declaration=self, runtime_adapter=adapter).ask(
            prompt, output
        )

    @override
    def terminal(self, settings: TerminalSettings) -> Terminal:
        """Compile the declaration for Claude Code's interactive CLI, with lup's settings."""
        return compiled(
            model=self.model,
            system_prompt=self.system_prompt,
            effort=self.effort,
            settings=settings,
            layout=ClaudeLayout.of(ClaudeSettings()),
        )
