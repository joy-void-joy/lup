"""`Transcripts`, the module: every session's record of the repository kept, and mounted read-only in a launch that lends it."""

from pathlib import Path

from lup.transcripts.hooks import TranscriptsHooks
from lup_dev.declaration.kinds import Guidance, Hooks, Mounted, Section
from lup_dev.declaration.module import Module


class Transcripts(Module):
    """Every session's record kept, out of reach of the runtime's cleanup, and readable by later sessions."""

    name = "transcripts"

    hooks: Hooks = Hooks.of(TranscriptsHooks)
    """Copying what the runtime added or grew, when a launch opens and when it stops."""
    data: Mounted = Mounted()
    """The copies, read-only in a room whose launch lends them
    (`lup-dev launch <runtime> --mount transcripts`), or in every room where
    the person's own layer says `Transcripts(data=Mounted(always=True))`: an old
    discussion read there can pass for a decision, and the operator's history
    isn't every session's to read."""
    guidance: Guidance = Guidance.of(
        Section(name="transcripts", package="lup.transcripts", path=Path("guidance.md"))
    )
    """Where the copies are, and what they're for."""
