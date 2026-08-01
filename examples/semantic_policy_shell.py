"""Refuse a denied command inside a live session — the tool-call path.

The tool-call half of the policy pair; ``semantic_policy`` is the fetch
half. The shell policy consults the same declared origin table, so the URL
refused to a fetch is refused to ``curl`` as well and no command reaches a
shell by taking the other route.

The session runs with permissions bypassed, which is the mode where this
hook is the only gate the call meets: what the policy denies is refused,
and nothing else is left to grant it.
"""

import asyncio

from pydantic import AnyHttpUrl

from lup.adapters.claude.hooks import claude_hook_semantic_tool
from lup.adapters.claude.runtime import (
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.hooks import LupHooksConfig
from lup.policy.enforcement import SemanticToolPolicy, create_policy_hooks
from lup.policy.rules import ShellPolicy, UrlScope
from lup.runtime.models import TurnInput, turn_request
from lup.runtime.query import query
from lup_template.devtools.harness.content.shell_vocabulary import SHELL_RULES

from examples.common import Summary

DOCS_ORIGIN = AnyHttpUrl("https://docs.example.com")
DENIED_COMMAND = "curl https://docs.example.com/private/token"


def policy_hooks() -> LupHooksConfig:
    """Enforce the shell lattice, scoped by the same declared origins.

    The vocabulary is this project's own: read-only commands allow,
    destructive ones ask, and anything the lattice cannot judge denies with
    the recipe for reshaping or escalating it.
    """
    policy = ShellPolicy(
        SHELL_RULES,
        allowed_urls=[UrlScope(origin=DOCS_ORIGIN, path_prefix="/api")],
        denied_urls=[UrlScope(origin=DOCS_ORIGIN, path_prefix="/private")],
    )
    return create_policy_hooks(
        SemanticToolPolicy(shell=policy), claude_hook_semantic_tool
    )


def session_config() -> ClaudeSessionConfig:
    """Carry the enforcing hooks into the session the factory will open."""
    return ClaudeSessionConfig(
        model="claude-opus-5",
        system_prompt="Run what you are asked to run and report what happened.",
        hooks=policy_hooks(),
    )


async def main() -> None:
    factory = create_claude_session_factory(session_config())
    result = await query(
        factory,
        turn_request(
            TurnInput(text=f"Run `{DENIED_COMMAND}` and summarize the output."),
            Summary,
        ),
    )
    print(result.output.summary)


if __name__ == "__main__":
    asyncio.run(main())
