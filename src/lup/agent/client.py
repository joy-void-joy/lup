"""Centralized Agent SDK client creation.

All Agent SDK client construction goes through this module to ensure
consistent defaults (session persistence disabled for sub-agent calls).

Two exports:
- build_client(**kwargs) — AsyncContextManager[ClaudeSDKClient] with defaults
- one_shot(prompt, ...) — prompt->result convenience for tool-free LLM calls
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, overload

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from pydantic import BaseModel

from lup.lib import ResponseCollector

logger = logging.getLogger(__name__)


@asynccontextmanager
async def build_client(
    # **kwargs: Any is intentional — forwarding to the typed ClaudeAgentOptions
    # constructor. Python has no better typing for this pattern.
    **kwargs: Any,
) -> AsyncIterator[ClaudeSDKClient]:
    """Return a configured ClaudeSDKClient with project-wide defaults.

    Always injects (merged with caller values, caller wins on conflict):
    - extra_args={"no-session-persistence": None}

    All keyword arguments are forwarded to ClaudeAgentOptions.
    """
    caller_extra: dict[str, object] = kwargs.pop("extra_args", None) or {}
    merged_extra = {"no-session-persistence": None, **caller_extra}

    options = ClaudeAgentOptions(
        extra_args=merged_extra,
        **kwargs,
    )
    async with ClaudeSDKClient(options=options) as client:
        yield client


@overload
async def one_shot(
    prompt: str,
    *,
    model: str = ...,
    system_prompt: str = ...,
    prefix: str = ...,
) -> str | None: ...


@overload
async def one_shot[T: BaseModel](
    prompt: str,
    *,
    model: str = ...,
    system_prompt: str = ...,
    output_type: type[T],
    prefix: str = ...,
) -> T | None: ...


async def one_shot(
    prompt: str,
    *,
    model: str = "sonnet",
    system_prompt: str = "",
    output_type: type[BaseModel] | None = None,
    prefix: str = "",
) -> BaseModel | str | None:
    """One-shot prompt->result convenience wrapper.

    Without output_type: returns the text result (str).
    With output_type: returns a validated Pydantic model from structured output.

    Uses ResponseCollector for consistent message handling.
    """
    # Build kwargs for build_client, conditionally adding output_format
    build_kwargs: dict[str, Any] = {
        "model": model,
        "system_prompt": system_prompt,
        "allowed_tools": [],
    }
    if output_type is not None:
        build_kwargs["output_format"] = {
            "type": "json_schema",
            "schema": output_type.model_json_schema(),
        }

    collector = ResponseCollector(prefix=prefix)
    async with build_client(**build_kwargs) as client:
        await client.query(prompt)
        result = await collector.collect(client)

    if output_type is not None and result.structured_output:
        return output_type.model_validate(result.structured_output)
    if output_type is not None:
        return None
    return result.result
