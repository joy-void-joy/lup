"""Sessions that already exist finding each other, and handing each other work.

The subject is not orchestration. One process deciding what several agents do
is covered elsewhere; this is the population nobody assembled — every session
working in one repository, in whatever worktree, started by whoever — and what
it needs is an address book, a durable inbox, and a way to say what it is
doing.

Delegation belongs here rather than there for the same reason. Handing work to
a peer that already exists is an address-book operation, and what makes it
durable is that the task is a node in the repository's log rather than a
message that expires with the session that sent it — which is why this module
requires `ledger` and its skill is declared beside the roster commands.

Its page carries the actor cohort with it, because a cohort and a repository
roster are the same roster over different directories: separating the prose
would leave a reader learning one delivery path twice and having to notice
they were the same.
"""

from lup.harness.content.docs import coordination
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import COORDINATION
from lup.harness.content.skills.delegate import SKILL as SKILL_DELEGATE
from lup.harness.models import ContentRoster
from lup.harness.modules import Module


def module() -> Module:
    """Reaching this repository's other sessions as one value."""
    return Module(
        spec=COORDINATION,
        content=ContentRoster(skills=[SKILL_DELEGATE]),
        documents=[
            page("coordination", "coordination.md", lambda _: coordination.DOCUMENT)
        ],
    )
