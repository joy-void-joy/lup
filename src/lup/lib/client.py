"""Centralized Agent SDK client creation.

All Agent SDK client construction goes through this module to ensure
consistent defaults (session persistence disabled for sub-agent calls).

Three exports:
- build_client(**kwargs) — AsyncContextManager[ClaudeSDKClient] with defaults
- run_query(prompt, ...) — query + collect in one call, returns ResponseCollector
- one_shot(prompt, ...) — prompt->result convenience for tool-free LLM calls
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, overload

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from pydantic import BaseModel

from lup.lib.trace import ResponseCollector, TraceLogger

logger = logging.getLogger(__name__)


@asynccontextmanager
async def build_client(
    # **kwargs: Any is intentional — forwarding to the typed ClaudeAgentOptions
    # constructor. Python has no better typing for this pattern.
    *,
    options: ClaudeAgentOptions | None = None,
    **kwargs: Any,
) -> AsyncIterator[ClaudeSDKClient]:
    """Return a configured ClaudeSDKClient with project-wide defaults.

    Pass either ``options`` (pre-built) or keyword arguments for
    ClaudeAgentOptions (not both).

    When using kwargs, always injects (caller wins on conflict):
    - extra_args={"no-session-persistence": None}
    """
    if options is None:
        caller_extra: dict[str, object] = kwargs.pop("extra_args", None) or {}
        merged_extra = {"no-session-persistence": None, **caller_extra}
        options = ClaudeAgentOptions(extra_args=merged_extra, **kwargs)

    async with ClaudeSDKClient(options=options) as client:
        yield client


async def run_query(
    prompt: str,
    *,
    options: ClaudeAgentOptions | None = None,
    prefix: str = "",
    trace_logger: TraceLogger | None = None,
    **kwargs: Any,
) -> ResponseCollector:
    """Query an SDK client and collect the full response.

    Combines build_client + query + ResponseCollector.collect into a
    single call. Pass either ``options`` or keyword arguments for
    ClaudeAgentOptions.

    Returns the ResponseCollector with .result, .blocks, .messages.
    """
    collector = ResponseCollector(prefix=prefix, trace_logger=trace_logger)
    async with build_client(options=options, **kwargs) as client:
        await client.query(prompt)
        await collector.collect(client)
    return collector


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
    """
    extra_kwargs: dict[str, Any] = {}
    if output_type is not None:
        extra_kwargs["output_format"] = {
            "type": "json_schema",
            "schema": output_type.model_json_schema(),
        }

    collector = await run_query(
        prompt,
        prefix=prefix,
        model=model,
        system_prompt=system_prompt,
        allowed_tools=[],
        **extra_kwargs,
    )
    result = collector.result
    if result is None:
        return None

    if output_type is not None and result.structured_output:
        return output_type.model_validate(result.structured_output)
    if output_type is not None:
        return None
    return result.result
