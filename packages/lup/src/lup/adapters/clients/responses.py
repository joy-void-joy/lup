"""The one messages→``LupResponse`` fold shared by every engine.

Both engines produce ordered lup messages — assistant content plus
tool-result user messages; folding them into the response's
``messages``/``blocks``/``tool_results`` shape is one invariant, kept
here. The terminal ``result`` stays engine-stamped: its sources
(Claude's ``ResultMessage``, Codex's ``TurnResult``) are native.
"""

from collections.abc import Sequence

from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupResponse,
    LupUserMessage,
)


def assemble_response(
    messages: Sequence[LupAssistantMessage | LupUserMessage],
    *,
    blocks: Sequence[LupContentBlock] | None = None,
) -> LupResponse:
    """Fold ordered lup messages into a ``LupResponse``.

    Assistant content lands in ``blocks`` and tool-result user content in
    ``tool_results``; every list-content message is kept in order in
    ``messages``. An explicit ``blocks`` sequence overrides the
    assistant-only default — the replay stream reconstructs events from
    ``blocks``, so an engine with no live stream (Codex) passes its full
    inline sequence, tool results included.
    """
    response = LupResponse(blocks=list(blocks) if blocks is not None else [])
    for message in messages:
        match message:
            case LupAssistantMessage():
                response.messages.append(message)
                if blocks is None:
                    response.blocks.extend(message.content)
            case LupUserMessage() if isinstance(message.content, list):
                response.messages.append(message)
                response.tool_results.extend(message.content)
    return response
