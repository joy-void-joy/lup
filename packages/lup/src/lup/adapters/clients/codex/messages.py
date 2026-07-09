"""Codex→lup conversion: thread items and the turn-result projection.

The projection layer between the Codex SDK's thread vocabulary and the
backend-neutral ``Lup*`` types. ``LupResponse.blocks`` keeps the
tool-result blocks inline — the shape
:class:`~lup.adapters.clients.streams.replay.ReplayStream` reconstructs
events from — which is why this path projects its own block sequence (a
completed ``TurnResult`` also has no live message stream to drain); the
fold into the response shape is the shared
:func:`~lup.adapters.clients.responses.assemble_response`.
"""

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from lup.adapters.clients.codex.usage import CodexUsageNormalizer, codex_usage_to_lup
from lup.adapters.clients.display import MessageTap
from lup.adapters.clients.responses import assemble_response
from lup.adapters.clients.usage import safe_normalize_usage
from lup.adapters.tools.names import WEB_SEARCH
from lup.adapters.tools.codex import COMMAND_EXECUTION, FILE_CHANGE
from lup.types import (
    JsonObject,
    LupAssistantMessage,
    LupContentBlock,
    LupResponse,
    LupResultMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
)

if TYPE_CHECKING:
    import openai_codex as codex
    import openai_codex.generated.v2_all as codex_items

logger = logging.getLogger(__name__)


def codex_items_to_lup(
    items: "Sequence[codex_items.ThreadItem]",
) -> list[LupContentBlock]:
    """Convert Codex ThreadItem list into lup content blocks.

    Each ThreadItem is a RootModel wrapping a discriminated union.
    We extract ``.root`` to get the typed variant, then map by
    ``type`` field.
    """
    import openai_codex.generated.v2_all as codex_items

    blocks: list[LupContentBlock] = []
    for item in items:
        inner = item.root if hasattr(item, "root") else item

        match inner:
            case codex_items.AgentMessageThreadItem():
                if inner.phase == codex_items.MessagePhase.final_answer:
                    blocks.append(LupTextBlock(text=inner.text))
                else:
                    blocks.append(LupThinkingBlock(thinking=inner.text))

            case codex_items.ReasoningThreadItem():
                summary = "\n".join(inner.summary) if inner.summary else ""
                content = "\n".join(inner.content) if inner.content else ""
                blocks.append(LupThinkingBlock(thinking=content or summary))

            case codex_items.CommandExecutionThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name=COMMAND_EXECUTION,
                        input={"command": inner.command, "cwd": inner.cwd.root},
                    )
                )
                if inner.aggregated_output is not None or inner.exit_code is not None:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=inner.aggregated_output,
                        )
                    )

            case codex_items.McpToolCallThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name=f"mcp__{inner.server}__{inner.tool}",
                        input=inner.arguments
                        if isinstance(inner.arguments, dict)
                        else None,
                    )
                )
                result_text: str | None = None
                if inner.error is not None:
                    result_text = (
                        inner.error.message
                        if hasattr(inner.error, "message")
                        else str(inner.error)
                    )
                elif inner.result is not None:
                    result_text = (
                        json.dumps(inner.result.content)
                        if hasattr(inner.result, "content")
                        else str(inner.result)
                    )
                if result_text is not None:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=result_text,
                        )
                    )

            case codex_items.FileChangeThreadItem():
                changes_desc = "; ".join(f"{c.path} ({c.kind})" for c in inner.changes)
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name=FILE_CHANGE,
                        input={"changes": changes_desc},
                    )
                )
                diff_text = "\n".join(c.diff for c in inner.changes if c.diff)
                if diff_text:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=diff_text,
                        )
                    )

            case codex_items.WebSearchThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name=WEB_SEARCH,
                        input={"query": inner.query},
                    )
                )

            case _:
                item_type = getattr(inner, "type", type(inner).__name__)
                logger.warning(
                    "codex_items_to_lup: unhandled ThreadItem variant %r (%s); "
                    "emitting diagnostic text block",
                    item_type,
                    type(inner).__name__,
                )
                blocks.append(LupTextBlock(text=f"[unhandled codex item: {item_type}]"))

    return blocks


def build_lup_response(
    result: "codex.TurnResult",
    *,
    output_schema: JsonObject | None = None,
    session_id: str | None = None,
    usage_normalizer: CodexUsageNormalizer | None = None,
    tap: MessageTap | None = None,
) -> LupResponse:
    """Convert a Codex TurnResult into a LupResponse.

    The inline block sequence (tool results included) is passed to the
    shared fold explicitly — the replay stream reconstructs events from
    ``blocks``. Each folded message is handed to ``tap`` as it lands.
    """

    blocks = codex_items_to_lup(result.items)
    assistant_blocks: list[LupContentBlock] = [
        b for b in blocks if not isinstance(b, LupToolResultBlock)
    ]
    result_blocks: list[LupContentBlock] = [
        b for b in blocks if isinstance(b, LupToolResultBlock)
    ]
    messages: list[LupAssistantMessage | LupUserMessage] = []
    if assistant_blocks:
        messages.append(LupAssistantMessage(content=assistant_blocks))
    if result_blocks:
        messages.append(LupUserMessage(content=result_blocks))
    response = assemble_response(messages, blocks=blocks)

    if tap:
        for message in messages:
            tap(message)

    structured_output: JsonObject | None = None
    if result.final_response and output_schema:
        try:
            structured_output = json.loads(result.final_response)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Codex structured-output parse failed; final_response was not "
                "JSON matching the schema. Offending text (truncated): %r",
                result.final_response[:500],
            )

    result_usage = safe_normalize_usage(
        usage_normalizer or codex_usage_to_lup, result.usage
    )

    response.result = LupResultMessage(
        structured_output=structured_output,
        result=result.final_response,
        usage=result_usage,
    )
    response.session_id = session_id
    return response
