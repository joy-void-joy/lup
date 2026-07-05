"""Generated capability matrix — probed from the engines, never declared.

Each cell is derived from the engines' actual behavior: option rows
construct a probe client with exactly one intent knob set and record
whether the engine raises
:class:`~lup.adapters.common.UnsupportedOptionsError`; the streaming row
reads whether the engine's ``stream`` is itself an async generator that
yields as the turn unfolds (live) or a plain method that returns
:func:`~lup.adapters.clients.common.replay_stream`, which emits every
event only after the turn completes (post-hoc); the background row asks
the engine for a tool-using background agent and catches the refusal.
Construction and generator creation never connect, so probing is offline
and cheap — and the table embedded in the top-level ``README.md`` and
printed by ``uv run lup-devtools agent capabilities`` cannot drift from
the code, because it *is* the code.

The harness consumes only the public seam surface, and its only
consumers are this devtools command and the README regression test
(``tests/unit/test_capability_matrix_docs.py``) — which is why it lives
in devtools, not the library. Columns follow the :data:`ENGINES`
insertion order.

Facts that only surface on a live connection (interrupt support, session
resume) have no row here; they are documented in prose and raise
:class:`~lup.adapters.common.UnsupportedOperationError` at the point of
use.
"""

import inspect

from pydantic import BaseModel

from lup.adapters.background.common import create_background_agent
from lup.adapters.common import (
    ENGINES,
    ClientFactory,
    LupAgentOptions,
    UnsupportedOptionsError,
)
from lup.adapters.tools.claude import READ


class CapabilityCell(BaseModel):
    """One probed fact about one engine."""

    capability: str
    value: bool | str


class EngineCapabilities(BaseModel):
    """One engine's probed capability column, labeled for display."""

    name: str
    cells: list[CapabilityCell]


def probe_base_options() -> LupAgentOptions:
    """Minimal options every engine accepts — the probe baseline.

    Call-tier shape (raw prompt, nothing persists), ``raise`` policy so
    unsupported knobs surface, and a dummy compat endpoint so endpoint-
    fronting engines construct.
    """
    return LupAgentOptions(
        model="capability-probe",
        persist_session=False,
        session_defaults=False,
        sdk_sandbox=False,
        on_unsupported="raise",
        base_url="http://probe.invalid",
        api_key="probe",
    )


def option_probes() -> list[tuple[str, LupAgentOptions]]:
    """One probe per intent knob: the baseline plus exactly that knob."""
    base = probe_base_options()
    return [
        ("tools", base.model_copy(update={"tools": [READ]})),
        ("permission_mode", base.model_copy(update={"permission_mode": "plan"})),
        ("max_turns", base.model_copy(update={"max_turns": 3})),
        (
            "max_thinking_tokens",
            base.model_copy(update={"max_thinking_tokens": 1024}),
        ),
        (
            "turn_timeout_seconds",
            base.model_copy(update={"turn_timeout_seconds": 30.0}),
        ),
        ("max_budget_usd", base.model_copy(update={"max_budget_usd": 1.0})),
    ]


def probe_option(factory: ClientFactory, opts: LupAgentOptions) -> bool:
    """Whether the engine constructs a client for *opts* without refusing."""
    try:
        factory(opts)
    except UnsupportedOptionsError:
        return False
    return True


def probe_streaming(factory: ClientFactory) -> str:
    """``live`` when the engine's ``stream`` is its own async generator.

    A live engine yields events as the turn unfolds, so its ``stream`` is
    an async-generator function. A post-hoc engine's ``stream`` is a plain
    method that returns :func:`replay_stream`, which yields only after the
    turn completes.
    """
    client = factory(probe_base_options())
    return "live" if inspect.isasyncgenfunction(type(client).stream) else "post_hoc"


def probe_background_tools(engine_id: str) -> bool:
    """Whether the engine builds a background agent that acts through tools."""
    try:
        create_background_agent(
            engine_id,
            name="capability-probe",
            system_prompt="",
            build_message=lambda: None,
            model="capability-probe",
            builtin_tools=[READ],
        )
    except (ValueError, NotImplementedError):
        return False
    return True


def engine_capabilities(engine_id: str, factory: ClientFactory) -> EngineCapabilities:
    """Probe one engine into its display column."""
    cells = [CapabilityCell(capability="streaming", value=probe_streaming(factory))]
    cells.extend(
        CapabilityCell(capability=name, value=probe_option(factory, opts))
        for name, opts in option_probes()
    )
    cells.append(
        CapabilityCell(
            capability="background_tools", value=probe_background_tools(engine_id)
        )
    )
    return EngineCapabilities(name=engine_id, cells=cells)


def canonical_capability_matrix() -> list[EngineCapabilities]:
    """Probe the shipped engines — the parity table, generated.

    The single source for every rendering: the ``lup-devtools agent
    capabilities`` command, the README table, and the regression test
    that keeps the two identical. Columns follow :data:`ENGINES`.
    """
    return [
        engine_capabilities(engine_id, factory)
        for engine_id, factory in ENGINES.items()
    ]


def capability_matrix_markdown(engines: list[EngineCapabilities]) -> str:
    """Render the probed matrix as a markdown table.

    One row per capability, one column per engine. The README embeds it
    and a regression test regenerates and diffs it, so prose cannot
    drift from behavior.
    """
    lines = [
        "| Capability | " + " | ".join(e.name for e in engines) + " |",
        "|---" * (len(engines) + 1) + "|",
    ]
    for row, cell in enumerate(engines[0].cells):
        cells: list[str] = []
        for engine in engines:
            match engine.cells[row].value:
                case bool() as flag:
                    cells.append("✅" if flag else "—")
                case value:
                    cells.append(str(value))
        lines.append(f"| {cell.capability} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
