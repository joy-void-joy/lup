"""The Codex engine's translated native configuration shape.

Everything a client run needs, computed once by the translation in
:mod:`lup.adapters.clients.codex.translate`. The client only carries it —
there is nothing left to assemble at run time, which is what lets
``openai-compat`` be a translation (appended provider lines) rather than
a client subclass.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from pydantic import BaseModel, model_validator

from lup.types import JsonObject, UsageCost


class CodexNativeConfig(BaseModel):
    """The Codex engine's translated native configuration.

    The thread-start scalars, the fully rendered ``config_overrides``
    lines and subprocess env, the turn-governance knobs, and the
    session's cleanup guarantee (mirroring the Claude engine's native
    ``ClaudeAgentOptions``).
    """

    # ``usage_cost`` and the ``cleanup`` factory are bare callables —
    # pydantic accepts them only under arbitrary types.
    model_config = {"arbitrary_types_allowed": True}

    model: str
    system_prompt: str = ""
    model_provider: str | None = None
    """Codex model-provider selector for thread start; ``None`` runs on
    the account's default provider."""
    sandbox: str | None = None
    approval_policy: str | None = None
    output_schema: JsonObject | None = None
    effort: str | None = None
    config_overrides: list[str] = []
    env: dict[str, str] = {}
    """Extra env for the Codex subprocess (e.g. a provider's ``env_key``
    credential)."""
    max_budget_usd: float | None = None
    usage_cost: UsageCost | None = None
    turn_timeout_seconds: float | None = None
    cleanup: Callable[[], AbstractContextManager[object]] | None = None

    @model_validator(mode="after")
    def require_priced_budget(self) -> "CodexNativeConfig":
        """A budget with nothing to price it against cannot be enforced."""
        if self.max_budget_usd is not None and self.usage_cost is None:
            raise ValueError(
                "max_budget_usd on the Codex runtime requires a usage_cost "
                "estimator — the SDK reports token counts, not cost. Build "
                "one with per_mtok_usage_cost(...)."
            )
        return self
