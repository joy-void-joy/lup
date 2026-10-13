"""The output tool: how a typed answer is submitted, and reviewed before it's accepted.

A typed ask gives the session one tool, `submit`, whose input is the output model.
It's an ordinary lup tool: validation and its `before` hooks refuse an answer with
the reason, and the agent corrects it within the same turn. `ask(prompt, Forecast)`
builds `Submit(Forecast)`; to review an answer, build it with hooks:

    ask(question, Submit(Forecast, before=[cites_sources]))
"""

from pydantic import BaseModel

from lup.tools.tool import Hook, Tool
from lup.types import Model


class Receipt(Model):
    """What the agent reads when its answer is accepted."""

    accepted: bool = True
    message: str = "Your answer is accepted. End your turn."


async def receipt(answer: BaseModel) -> Receipt:
    """Accept an answer that passed validation and every hook."""
    del answer
    return Receipt()


class Submit[T: BaseModel](Tool[T, Receipt]):
    """The output tool for one output model, with the hooks that review an answer."""

    def __init__(self, output: type[T], *, before: list[Hook[T]] | None = None) -> None:
        """Build the tool for `output`, reviewed by `before` in order."""
        super().__init__(
            name="submit",
            description=(
                "Submit your final answer once it's complete.\n\n"
                "If it's refused, the reply says what to fix: fix it and submit again. "
                "Your turn can't end until an answer is accepted."
            ),
            input=output,
            function=receipt,
            before=before or [],
        )
