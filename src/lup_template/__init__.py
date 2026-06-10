"""Self-improving agent template.

This package provides the scaffolding for building agents that can
review their own traces and improve over time. The reusable library
lives in ``packages/lup`` (the ``lup`` distribution); this package
contains the domain-specific parts.

Structure:
- agent/: Agent code that the feedback loop improves (orchestration,
  config, models, prompts, subagents, tool policy, MCP tools)
- devtools/: Development and analysis CLI (``lup-devtools`` entry point)
- environment/: Domain scaffolding (user interaction, application flow);
  exposes the ``lup`` entry point for running agent sessions
"""
