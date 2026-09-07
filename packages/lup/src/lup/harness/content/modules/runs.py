"""Work that outlives the tool call that started it.

A job launched in the background is a job nobody can see, and the answer is
one directory and a protocol over it: a run launched detached, launched by
somebody else, or launched before this shell existed reads back fully, and
reading it cannot perturb what it is reading.

Its guidance section is the one thing here a session needs *before* it starts
— that long-running work is declared as a pipeline rather than scripted, so it
is resumable and watchable by construction. Nothing enforces that after the
fact; a scripted job is simply a job nobody can resume, discovered later.

That section used to sit with the realtime relay, which shares nothing with it
but the word "running": this is background work with a beginning and an end,
and that is a persistent agent controlling its own attention forever.
"""

import lup.harness.content.conventions as conventions
from lup.harness.content.docs import runs
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import RUNS
from lup.harness.modules import Module


def module() -> Module:
    """Background pipelines as one value."""
    return Module(
        spec=RUNS,
        guidance=[conventions.LONG_RUNNING_WORK],
        documents=[page("runs", "runs.md", lambda _: runs.DOCUMENT)],
    )
