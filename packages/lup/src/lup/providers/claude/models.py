# Generated from packages/lup/src/lup/providers/claude/catalog.json by `uv run lup-devtools harness generate all` — edit the source, not this file.
# See docs/harness.md.
# `uv run lup-devtools dev models` reads that snapshot from the CLI.

"""Every model the Claude CLI accepts, and the efforts each takes.

Compiled from ``catalog.json`` beside this module, which
``uv run lup-devtools dev models`` last read out of ``2.1.282 (Claude Code)``.
A name outside the lineup is still reachable, spelled as
``CustomModel`` so the choice to leave the catalog is written where
it is made.
"""

from typing import Literal

type ClaudeModel = Literal[
    "opus",
    "sonnet",
    "haiku",
    "fable",
    "best",
    "claude-3-5-haiku-20241022",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-7-sonnet-20250219",
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-20250514",
    "claude-opus-4-1-20250805",
    "claude-opus-4-5-20251101",
    "opus[1m]",
    "sonnet[1m]",
    "haiku[1m]",
    "claude-haiku-4-5[1m]",
    "claude-sonnet-4-0[1m]",
    "claude-sonnet-4-5[1m]",
    "claude-sonnet-4-6[1m]",
    "claude-opus-4-0[1m]",
    "claude-opus-4-1[1m]",
    "claude-opus-4-5[1m]",
    "claude-opus-4-6[1m]",
    "claude-opus-4-7[1m]",
    "claude-opus-4-8[1m]",
    "claude-opus-5[1m]",
    "claude-opus-5-5[1m]",
    "claude-3-5-haiku",
    "claude-haiku-4-5",
    "claude-3-5-sonnet",
    "claude-3-7-sonnet",
    "claude-sonnet-4-0",
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-4-0",
    "claude-opus-4-1",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-mythos-5",
    "claude-mythos-5-1",
]
"""A name Claude resolves to a model: an alias, or a model id."""

type ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]
"""Every reasoning effort some Claude model accepts, lowest first."""

# lup: ignore[constant-declaration] — the vendor's own lineup, compiled
# from what its CLI reports rather than chosen here
CLAUDE_MODEL_EFFORTS: dict[ClaudeModel, list[ClaudeEffort]] = {
    "opus": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "sonnet": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "haiku": [],
    "fable": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "best": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-3-5-haiku-20241022": [],
    "claude-haiku-4-5-20251001": [],
    "claude-3-5-sonnet-20241022": [],
    "claude-3-7-sonnet-20250219": [],
    "claude-sonnet-4-20250514": [],
    "claude-sonnet-4-5-20250929": [],
    "claude-opus-4-20250514": [],
    "claude-opus-4-1-20250805": [],
    "claude-opus-4-5-20251101": [],
    "opus[1m]": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "sonnet[1m]": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "haiku[1m]": [],
    "claude-haiku-4-5[1m]": [],
    "claude-sonnet-4-0[1m]": [],
    "claude-sonnet-4-5[1m]": [],
    "claude-sonnet-4-6[1m]": ["low", "medium", "high", "max"],
    "claude-opus-4-0[1m]": [],
    "claude-opus-4-1[1m]": [],
    "claude-opus-4-5[1m]": [],
    "claude-opus-4-6[1m]": ["low", "medium", "high", "max"],
    "claude-opus-4-7[1m]": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-4-8[1m]": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-5[1m]": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-5-5[1m]": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-3-5-haiku": [],
    "claude-haiku-4-5": [],
    "claude-3-5-sonnet": [],
    "claude-3-7-sonnet": [],
    "claude-sonnet-4-0": [],
    "claude-sonnet-4-5": [],
    "claude-sonnet-4-6": ["low", "medium", "high", "max"],
    "claude-sonnet-5": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-4-0": [],
    "claude-opus-4-1": [],
    "claude-opus-4-5": [],
    "claude-opus-4-6": ["low", "medium", "high", "max"],
    "claude-opus-4-7": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-4-8": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-5": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-fable-5": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-fable-5-1": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude-mythos-5": [],
    "claude-mythos-5-1": ["low", "medium", "high", "xhigh", "max", "ultra"],
}
"""The efforts each name accepts, on any route it resolves to.

A declaration naming an effort outside its model's row is refused
where it is made, rather than narrowed to one the model has.
"""
