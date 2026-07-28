"""The identity a launcher declares for the session it is about to start.

Edit autonomy is a property of *how a session was launched*, not of a name
one runtime happens to put in a hook payload. Claude Code fills `agent_type`
only for native subagent dispatch, so a resolver worker — an ordinary
top-level session — could never be recognized by it, and Codex has no such
field at all. Declaring the identity in the session environment lets the
actor that knows the claim to be true be the actor that makes it, on every
runtime.

This mirrors `LUP_SANDBOX_ACTIVE`: set exactly when the launcher verified
what it announces. A hook script is spawned by the runtime CLI with the
CLI's own environment, so an agent exporting this inside a shell tool call
cannot reach the dispatcher that judges it.
"""

from lup.types import EnvVars

AGENT_IDENTITY_ENV = "LUP_AGENT_IDENTITY"
"""Environment variable naming the declared identity of a launched session."""


def agent_identity_environment(identity: str) -> EnvVars:
    """Declare one session's identity, or clear it with an empty name.

    Non-autonomous sessions must set the empty value rather than omit the
    variable: runtimes merge a session's environment over the launching
    process's, so an operator with this exported would otherwise hand their
    own autonomy to a session that was never granted it.
    """
    return {AGENT_IDENTITY_ENV: identity}
