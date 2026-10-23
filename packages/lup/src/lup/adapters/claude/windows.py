"""The context window each of Claude's models runs in under Claude Code: where a conversation's window is read from, by the model its record names.

Models ship faster than this file changes, so this table is where they're added
as they do. It was read on 2026-10-23 from Claude Code's docs
(`code.claude.com/docs/en/model-config`, *1M context window* and *Turn off 1M
context*) and from the model catalog in its 2.1.309 binary. The two agree but
in one place (`docs/field-notes.md`, *A model's context window*):
- "Fable 5.1, Fable 5, Sonnet 5 and later, Haiku 5.5, and Opus 4.7 and later
  run with the 1M window by default, with no `[1m]` suffix needed";
- "Opus 4.6 and Sonnet 4.6 reach 1M only through their `[1m]` variant", and run
  at 200K without it. The binary's catalog gives Sonnet 4.5 and Sonnet 4 the
  same way to 1M, which the docs don't list;
- the rest of the catalog, Opus 4.5, 4.1 and 4 and Haiku 4.5, runs at 200K with
  or without the suffix;
- `CLAUDE_CODE_DISABLE_1M_CONTEXT` keeps every one of them at 200K.

A model this table doesn't name has no window here. The ring then shows the
count alone rather than a guessed window, until the model is added.
"""

from typing import Literal, TypeIs, get_args

type Catalogued = Literal[
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5-5",
    "claude-sonnet-5",
    "claude-haiku-5-5",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-20250514",
    "claude-opus-4-5-20251101",
    "claude-opus-4-1-20250805",
    "claude-opus-4-20250514",
    "claude-haiku-4-5-20251001",
]
"""Claude's models as Claude Code 2.1.309's catalog names them to the API: each
reply's record repeats that name (`message.model`), never with `[1m]` after it."""

type Reach = Literal["long", "chosen", "standard"]
"""Whether a model's context reaches the long window: `long`, it runs in it with
nothing asked; `chosen`, only where its `[1m]` variant was asked for; `standard`,
never."""


def reach(model: Catalogued) -> Reach:
    """Return whether `model`'s context reaches the long window, as Claude Code runs it where nothing turns the long window off."""
    match model:
        case (
            "claude-fable-5-1"
            | "claude-fable-5"
            | "claude-mythos-5"
            | "claude-opus-5-5"
            | "claude-opus-5"
            | "claude-opus-4-8"
            | "claude-opus-4-7"
            | "claude-sonnet-5-5"
            | "claude-sonnet-5"
            | "claude-haiku-5-5"
        ):
            return "long"
        case (
            "claude-opus-4-6"
            | "claude-sonnet-4-6"
            | "claude-sonnet-4-5-20250929"
            | "claude-sonnet-4-20250514"
        ):
            return "chosen"
        case (
            "claude-opus-4-5-20251101"
            | "claude-opus-4-1-20250805"
            | "claude-opus-4-20250514"
            | "claude-haiku-4-5-20251001"
        ):
            return "standard"


def catalogued(model: str) -> TypeIs[Catalogued]:
    """Return whether `model` is a name this table knows.

    >>> catalogued("claude-opus-5-5"), catalogued("claude-opus-5-5[1m]"), catalogued("<synthetic>")
    (True, False, False)
    """
    return model in get_args(Catalogued.__value__)
