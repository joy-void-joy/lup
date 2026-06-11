"""Self-improving agent template.

This package provides the domain-specific scaffolding for building agents
that can review their own traces and improve over time. It depends on the
``lup`` library (``packages/lup/``) for all SDK-agnostic infrastructure.

Structure:
- lup_template/agent/: Agent code (feedback loop improves this)
  - core.py: Main agent orchestration (dispatches to the SDK adapter)
  - config.py: Configuration via pydantic-settings
  - models.py: Output models (AgentOutput, Factor, AgentSessionResult)
  - prompts.py: System prompt sections and composition
  - subagents.py: Subagent definitions (SDK-agnostic SubagentSpec)
  - tool_policy.py: Conditional tool availability
  - tools/: Domain MCP tools
    - example.py: Template MCP tools to customize
    - reflect.py: Forced self-review tool (reviewer sub-agent)
    - realtime.py: Real-time tools template (sleep, context, reply)

- lup_template/environment/: Domain scaffolding (user interaction, app flow)
  - cli/__main__.py: Typer CLI entry point (run + loop with auto-commit)

- lup_template/devtools/: Development CLI (lup-devtools entry point)

Reusable, SDK-agnostic infrastructure (history, hooks, metrics, notes,
paths, realtime scheduling, reflection gate, retry, sandbox, trace) lives
in the ``lup`` library — import it directly (e.g. ``from lup.history import
save_session``).
"""
