# lup: ignore[constant-declaration]
# The variable's name is Claude Code's own spelling of its session id, which
# no project could choose differently and still read the value the runtime
# set; it is written here and nowhere outside this adapter.
"""The id Claude Code gives a session, as the tool servers it starts can read it.

A launcher that minted a member id exports it, and that is the strongest
identity a session has. A session nobody launched — a bare ``claude`` in a
worktree, with the plugin — has only what its runtime gives it, and Claude
Code gives the same session id to two of the processes that write this
session's roster row: its hooks read it on stdin as ``session_id``, and its
stdio MCP servers find it in their environment under the name below. Reading
it here is what lets the tool server and the hooks agree on one row without a
launcher.

Measured rather than documented. Claude Code 2.1.272 sets the variable in
the environment of the stdio MCP servers it starts, carrying the session's
id — read off a running coordination server on the machine this was written
on — while https://code.claude.com/docs/en/env-vars and
https://code.claude.com/docs/en/hooks document ``CLAUDE_PROJECT_DIR`` for
MCP servers and neither of these names. A release that stops setting it
costs an unlaunched session its identity and nothing else: the launched
case never reads it.
"""

from pydantic import Field
from pydantic_settings import BaseSettings

CLAUDE_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


class ClaudeSessionEnv(BaseSettings):
    """The runtime's half of an unlaunched session's identity, read from the environment."""

    session_id: str = Field(default="", validation_alias=CLAUDE_SESSION_ENV)


def claude_session_id() -> str:
    """The session id Claude Code set for this process, or blank where it set none."""
    return ClaudeSessionEnv().session_id
