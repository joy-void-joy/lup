"""`Transcripts`, the module: every session's record of the repository kept, mounted read-only in every room, and read with `lup-dev transcripts`."""

from pathlib import Path

from lup.transcripts.serving import TranscriptsServing
from lup_dev.declaration.kinds import Guidance, Mounted, Section, Serving
from lup_dev.declaration.module import Module


class Transcripts(Module):
    """Every session's record kept, out of reach of the runtime's cleanup, and readable by later sessions."""

    name = "transcripts"

    serving: Serving = Serving.of(TranscriptsServing)
    """Copying what the runtime added or grew, when a launch opens and when it stops."""
    data: Mounted = Mounted(always=True)
    """The copies, read-only in every room, so a session reads why things are
    as they are in the operator's own words (`lup-dev transcripts`); a project
    or a person's layer that keeps them out says
    `Transcripts(data=Mounted(always=False))`, and a launch then lends them
    with `--mount transcripts`."""
    guidance: Guidance = Guidance.of(
        Section(name="transcripts", package="lup.transcripts", path=Path("guidance.md"))
    )
    """Where the copies are, and what they're for."""
