"""Route a model name to one explicit, fully configured agent recipe."""

import asyncio

from pydantic import BaseModel, Field

from lup import Agent, Claude, Codex
from lup.providers.routing import ModelRoute, ModelRouter, PrefixModelMatcher

MODEL = "claude-opus-5"  # lup: ignore[constant-declaration] — a vendor's model id

# One prompt for both routes, which is what a shared argument buys. Codex's own
# configuration calls this `developer_instructions`; the agent translates,
# so a routing table never has to know which provider spells it which way.
# lup: ignore[constant-declaration] — shared by the two recipes below
SYSTEM_PROMPT = "Submit a concise structured summary."


class Summary(BaseModel, frozen=True):
    """A minimal structured result submitted by this example's agent."""

    summary: str = Field(min_length=1)


def claude_agent() -> Agent:
    return Claude(model=MODEL, system_prompt=SYSTEM_PROMPT)


def codex_agent() -> Agent:
    return Codex(model="gpt-5.5", system_prompt=SYSTEM_PROMPT)


async def main() -> None:
    router = ModelRouter(
        [
            ModelRoute(
                name="claude",
                matcher=PrefixModelMatcher("claude-"),
                recipe=claude_agent,
            ),
            ModelRoute(
                name="codex",
                matcher=PrefixModelMatcher("gpt-"),
                recipe=codex_agent,
            ),
        ]
    )
    result = await router.resolve(MODEL).ask("Explain explicit model routing.", Summary)
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
