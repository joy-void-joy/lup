"""Route a model name to one explicit, fully configured client recipe."""

import asyncio

from lup import Client, create_claude, create_codex
from lup.runtime.routing import ModelRoute, ModelRouter, PrefixModelMatcher

from examples.common import Summary

MODEL = "claude-opus-5"  # lup: ignore[constant-declaration] — a vendor's model id

# One prompt for both routes, which is what a shared argument buys. Codex's own
# configuration calls this `developer_instructions`; the constructor translates,
# so a routing table never has to know which provider spells it which way.
# lup: ignore[constant-declaration] — shared by the two recipes below
SYSTEM_PROMPT = "Submit a concise structured summary."


def claude_client() -> Client:
    return create_claude(model=MODEL, system_prompt=SYSTEM_PROMPT)


def codex_client() -> Client:
    return create_codex(model="gpt-5.5", system_prompt=SYSTEM_PROMPT)


async def main() -> None:
    router = ModelRouter(
        [
            ModelRoute(
                name="claude",
                matcher=PrefixModelMatcher("claude-"),
                recipe=claude_client,
            ),
            ModelRoute(
                name="codex",
                matcher=PrefixModelMatcher("gpt-"),
                recipe=codex_client,
            ),
        ]
    )
    result = await router.resolve(MODEL).query(
        "Explain explicit model routing.", Summary
    )
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
