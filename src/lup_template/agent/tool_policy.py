"""Decide which tools the agent is allowed to use this session.

This is a TEMPLATE. Customize for your domain.

A tool may be unavailable because its dependency is unmet — an API key the
settings don't carry, a mode that forbids it. :class:`ToolPolicy` is the one
place that decision lives, so a tool that needs a key you haven't configured
simply never reaches the agent (it can't call a tool that would only fail).

The machinery (tag filtering, group predicates, server assembly, the
hook-enforced allowlist) lives in :class:`lup.tool_policy.BaseToolPolicy`;
this subclass only maps the application's settings onto exclusions. See
the base class for the tag-vs-name rule of thumb.

Usage:
    from lup.hooks import create_tool_allowlist_hook
    from lup_template.agent.config import settings
    from lup_template.agent.tool_policy import ToolPolicy

    policy = ToolPolicy(settings)
    mcp_servers = policy.get_mcp_servers(*lup_servers)
    hooks = create_tool_allowlist_hook(policy.get_allowed_tools(mcp_servers))
"""

from typing import TYPE_CHECKING

from lup.tool_policy import BaseToolPolicy

if TYPE_CHECKING:
    from lup_template.agent.config import Settings


class ToolPolicy(BaseToolPolicy):
    """Map application settings to tool exclusions.

    Determines which tools are available based on:
    - API key availability (from settings)
    - Mode configuration (e.g., restricted mode)
    - Session context (e.g., allow certain tools only in some contexts)
    - Code-execution sandbox: pass ``code_execution=True`` when the session
      has one, and raw shell (Bash) is dropped unless ``AGENT_SANDBOX_ALLOW_SHELL``
      opts back in — the sandbox's ``execute_code`` is the sanctioned code path.

    TEMPLATE: customize ``__init__`` to define your exclusion logic; override
    ``group_enabled`` to gate groups on your domain's conditions (e.g. a
    ``live_data`` group only outside restricted mode) and ``get_mcp_servers``
    to register your domain's servers, e.g.::

        def get_mcp_servers(self, *additional_servers):
            servers = super().get_mcp_servers(*additional_servers)
            servers["search"] = search_server
            if not self.restricted_mode:
                servers["live_data"] = live_data_server
            return servers
    """

    def __init__(
        self,
        settings: "Settings",
        *,
        restricted_mode: bool = False,
        excluded_tools: set[str] | None = None,
        excluded_tags: set[str] | None = None,
        code_execution: bool = False,
    ) -> None:
        tags: set[str] = set(excluded_tags or ())
        names: set[str] = set(excluded_tools or ())

        # TEMPLATE: map each unmet requirement to its tag — replace the
        # example-api check with your domain's keys, one tag per service
        if not settings.example_api_key:
            tags.add("requires:example-api")

        # A code-execution sandbox provides isolated execute_code; drop raw
        # host shell (Bash, the Claude backend's shell builtin) unless
        # explicitly re-allowed, so the agent cannot bypass the sandbox.
        if code_execution and not settings.sandbox_allow_shell:
            names.add("Bash")

        # TEMPLATE: add more name-set exclusions for tools you don't own here

        super().__init__(
            restricted_mode=restricted_mode,
            excluded_tools=names,
            excluded_tags=tags,
        )
        self.settings = settings
