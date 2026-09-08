"""Sessions that already exist finding each other.

The subject is not delegation. Orchestration already covers one process
deciding what several agents do; this is the population nobody assembled —
every session working in one repository, in whatever worktree, started by
whoever — and what it needs is an address book, a durable inbox, and a way to
say what it is doing.

Its page carries the actor cohort with it, because a cohort and a repository
roster are the same roster over different directories: separating the prose
would leave a reader learning one delivery path twice and having to notice
they were the same.
"""

from lup.harness.content.docs import coordination
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import COORDINATION
from lup.harness.modules import Module


def module() -> Module:
    """Reaching this repository's other sessions as one value."""
    return Module(
        spec=COORDINATION,
        documents=[
            page("coordination", "coordination.md", lambda _: coordination.DOCUMENT)
        ],
    )
