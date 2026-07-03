"""Backend-agnostic session options and the built-adapter bundle.

These are the only two shapes that cross the template -> adapter boundary for
session construction. The template assembles a :class:`LupAgentOptions` (its
domain work: which tools, which hooks, which subagents, the model knobs), and
``lup.adapters.build_adapter`` hands it to the engine's builder, which
translates it into that engine's native options and returns a
:class:`BuiltAdapter`. No consumer names a backend or touches a native option
type; adding a backend is adding one builder and registering it.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from pydantic import BaseModel, Field

from lup.adapters.common import Client, PermissionMode
from lup.mcp import McpServerEntry
from lup.realtime_relay import RealtimeMailbox
from lup.types import LupHooksConfig, SubagentSpec, UsageCost


class CodexOptions(BaseModel):
    """Codex-runtime construction inputs that have no Claude analogue.

    The Codex app-server is a subprocess: it cannot take in-process tools, so
    tools are served externally (``LupAgentOptions.served_tool_groups`` names
    the groups, and ``mcp_env`` relays the session context the subprocess
    needs), and writes are confined natively to ``writable_roots`` instead of by
    a permission hook. ``session_id``/``shared_dir`` drive the parent-side
    container cleanup. The ``openai_*`` fields are set only for the
    OpenAI-compatible endpoint. A Claude session leaves this at its defaults.
    """

    model_config = {"arbitrary_types_allowed": True}

    sandbox: str | None = None
    approval_policy: str | None = None
    mcp_env: dict[str, str] = Field(default_factory=dict)
    writable_roots: list[Path] = Field(default_factory=list)

    session_id: str | None = None
    shared_dir: Path | None = None
    realtime_dir: Path | None = None

    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model_provider: str | None = None


class LupAgentOptions(BaseModel):
    """Everything an adapter needs to construct a session, in neutral terms.

    Each adapter's builder maps these onto its native option object, honoring
    what it can (see :class:`~lup.adapters.common.AdapterCapabilities`) and
    ignoring or rejecting the rest. Knobs that one backend lacks (thinking
    tokens, permission modes) are carried here regardless — the adapter, not
    the caller, decides what to do with them.
    """

    model_config = {"arbitrary_types_allowed": True}

    model: str
    system_prompt: str = ""

    tool_servers: dict[str, McpServerEntry] = Field(default_factory=dict)
    subagents: list[SubagentSpec] = Field(default_factory=list)
    hooks: LupHooksConfig = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    served_tool_groups: tuple[str, ...] = ()
    add_dirs: list[Path] = Field(default_factory=list)

    permission_mode: PermissionMode | None = None
    max_turns: int | None = None
    max_thinking_tokens: int | None = None
    reasoning_effort: str | None = None
    max_budget_usd: float | None = None
    turn_timeout_seconds: float | None = None
    usage_cost: UsageCost | None = None

    persist_session: bool = True
    realtime: bool = False

    codex: CodexOptions = Field(default_factory=CodexOptions)


class BuiltAdapter(BaseModel):
    """An adapter plus the session-scoped resources the caller must manage.

    ``lifecycle`` is entered around the run (a sandbox or container cleanup;
    ``nullcontext`` when there is nothing to tear down). ``mailbox`` is the
    parent-side endpoint of the realtime file relay, present only for
    subprocess backends running in persistent mode.
    """

    model_config = {"arbitrary_types_allowed": True}

    adapter: Client
    lifecycle: AbstractContextManager[object] = Field(default_factory=nullcontext)
    mailbox: RealtimeMailbox | None = None


type AdapterBuilder = Callable[[LupAgentOptions], BuiltAdapter]
"""An engine's construction entry point: neutral options in, built adapter out."""
