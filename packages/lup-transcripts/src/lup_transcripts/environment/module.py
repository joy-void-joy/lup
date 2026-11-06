"""`Transcripts`, the module: every session's record of the repository kept, mounted read-only in every room, and read with `lup-dev transcripts`."""

from pathlib import Path

from lup_dev.declaration.kinds import Folds, Guidance, Mounted, Section, Serving, Tones
from lup_dev.declaration.module import Module
from lup_transcripts.environment.conversation import FOLD_KINDS, TONES
from lup_transcripts.environment.messages import TONES as MESSAGE_TONES
from lup_transcripts.environment.serving import TranscriptsServing


class Transcripts(Module):
    """Every session's record kept, out of reach of the runtime's cleanup, and readable by later sessions."""

    name = "transcripts"

    serving: Serving = Serving.of(TranscriptsServing)
    """Copying what each runtime added or grew in each of its homes, of the
    project's sessions and each related repository's, when a launch opens, when
    it stops and before a room reads them; reading the copies; and each agent's
    conversation, live: their messages, and their trace."""
    folds: Folds = Folds.of(*FOLD_KINDS)
    """What its conversation folds under: earlier exchanges, messages, the agent's
    and each item's, runs of calls, calls' input and output, and calls' outputs and
    long arguments."""
    tones: Tones = Tones.of(*TONES, *MESSAGE_TONES)
    """What its conversation's lines are drawn in: calls, the items sent and
    received, runs of calls, what another agent said, and a message new to the
    operator."""
    data: Mounted = Mounted(always=True)
    """The copies, read-only in every room, so a session reads why things are
    as they are in the operator's own words (`lup-dev transcripts`); a project
    or a person's layer that keeps them out says
    `Transcripts(data=Mounted(always=False))`, and a launch then lends them
    with `--mount transcripts`."""
    guidance: Guidance = Guidance.of(
        Section(
            name="transcripts",
            package="lup_transcripts.environment",
            path=Path("guidance.md"),
        )
    )
    """Where the copies are, and what they're for."""
