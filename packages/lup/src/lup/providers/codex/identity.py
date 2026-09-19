"""The id Codex gives a session, as the tool servers it starts could read it.

They cannot, and this is where that is said. Codex hands its hooks a
``session_id`` on stdin (https://learn.chatgpt.com/docs/hooks), and a stdio
MCP server it starts is configured with ``env`` and ``env_vars`` naming the
variables to set or forward (https://learn.chatgpt.com/docs/extend/mcp) —
none of which Codex documents setting to the session's id, and no variable
carrying one is documented anywhere on those pages. So a session nobody
launched has no identity its tool server can join the roster under, and such
a session is not on the roster: its hooks fold the record and beat without
ever joining a row, and its departure writer finds no standing row to end.

The launched case is unaffected: the launcher mints a member id and exports
it, and every session this repository starts is launched. The difference
from Claude Code, whose runtime does set a session id in its servers'
environment, is stated on the parity page rather than papered over here.
"""


def codex_session_id() -> str:
    """Blank: Codex documents no session id reaching a server it starts."""
    return ""
