# Generated from packages/lup/src/lup/providers/codex/catalog.json by `uv run lup-devtools harness generate all` — edit the source, not this file.
# See docs/harness.md.
# `uv run lup-devtools dev models` reads that snapshot from the CLI.

"""Every model the Codex CLI accepts, and the efforts each takes.

Compiled from ``catalog.json`` beside this module, which
``uv run lup-devtools dev models`` last read out of ``codex-cli 0.156.1``.
A name outside the lineup is still reachable, spelled as
``CustomModel`` so the choice to leave the catalog is written where
it is made.
"""

from typing import Literal

type CodexModel = Literal[
    "gpt-6-astra",
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-daybreak-blue-latest",
    "gpt-daybreak-red-latest",
    "gpt-5.5",
    "gpt-5.4",
    "codex-auto-review",
]
"""A name Codex resolves to a model: an alias, or a model id."""

type CodexEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]
"""Every reasoning effort some Codex model accepts, lowest first."""

# lup: ignore[constant-declaration] — the vendor's own lineup, compiled
# from what its CLI reports rather than chosen here
CODEX_MODEL_EFFORTS: dict[CodexModel, list[CodexEffort]] = {
    "gpt-6-astra": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "gpt-6-sol": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "gpt-6-luna": ["low", "medium", "high", "xhigh", "max"],
    "gpt-5.6-sol": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "gpt-5.6-terra": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "gpt-5.6-luna": ["low", "medium", "high", "xhigh", "max"],
    "gpt-daybreak-blue-latest": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "gpt-daybreak-red-latest": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "gpt-5.5": ["low", "medium", "high", "xhigh"],
    "gpt-5.4": ["low", "medium", "high", "xhigh"],
    "codex-auto-review": ["low", "medium", "high", "xhigh", "max"],
}
"""The efforts each name accepts, on any route it resolves to.

A declaration naming an effort outside its model's row is refused
where it is made, rather than narrowed to one the model has.
"""
