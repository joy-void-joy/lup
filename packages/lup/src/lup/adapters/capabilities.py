"""Versioned evidence-backed runtime capability matrix.

The table describes capabilities supplied in ``SessionHandle`` and
``TurnHandle`` values. Unsupported capabilities are absent; diagnostics never
invoke operations and catch an unsupported-operation exception.

It sits beside the adapters rather than in an application because that is
what it is evidence *about*: each column is one native contract at the
version this library supports, so a release that moves an adapter moves the
row describing it. Held downstream instead, the matrix would keep describing
whichever SDK the adopter first vendored while the code beneath it changed.

Distinct from :mod:`lup.harness.evidence`, which records the CLI versions
installed on one machine to trigger the doctor's drift check. This records
what a contract can do; that records what is currently sitting on disk.
"""

from pydantic import BaseModel, ConfigDict


class CapabilityCell(BaseModel):
    """One supported, absent, or qualified capability fact."""

    model_config = ConfigDict(frozen=True)

    capability: str
    value: bool | str


class AdapterCapabilities(BaseModel):
    """One adapter evidence column at its tested native contract version."""

    model_config = ConfigDict(frozen=True)

    name: str
    cells: list[CapabilityCell]


def cells(**facts: bool | str) -> list[CapabilityCell]:
    """Preserve declaration order while constructing one evidence column."""
    return [
        CapabilityCell(capability=capability, value=value)
        for capability, value in facts.items()
    ]


def canonical_capability_matrix() -> list[AdapterCapabilities]:
    """Return the checked-in evidence for the supported native contracts."""
    return [
        AdapterCapabilities(
            name="claude-sdk-0.2.89",
            cells=cells(
                live_events=True,
                interrupt=True,
                steer=False,
                fork=True,
                resume=True,
                typed_submission="reconnect per turn",
                background=True,
            ),
        ),
        AdapterCapabilities(
            name="codex-app-server-0.144.4",
            cells=cells(
                live_events=True,
                interrupt=True,
                steer=True,
                fork=True,
                resume="without a fresh dynamic tool",
                typed_submission="thread-start schema only",
                background=True,
            ),
        ),
    ]


def capability_matrix_markdown(adapters: list[AdapterCapabilities]) -> str:
    """Render one row per capability and one column per adapter."""
    lines = [
        "| Capability | " + " | ".join(adapter.name for adapter in adapters) + " |",
        "| " + " | ".join(["---"] * (len(adapters) + 1)) + " |",
    ]
    for row, cell in enumerate(adapters[0].cells):
        rendered: list[str] = []
        for adapter in adapters:
            value = adapter.cells[row].value
            rendered.append("✅" if value is True else "—" if value is False else value)
        lines.append(f"| {cell.capability} | " + " | ".join(rendered) + " |")
    return "\n".join(lines)
