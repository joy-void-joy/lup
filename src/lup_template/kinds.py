"""What this repository records in its ledger, declared once.

Two readers need the list and must not disagree: the console, which turns a
stored record into some class to ask its standing, and the tool group a
session records through. Listed here rather than derived from the adopted
modules, because a union assembled at run time is not one a type checker can
narrow. The library declares none of these — what a node kind is for is a
project's question — so this file is where a project adopting the scaffold
puts its own answer, and where it says which of them are committed with the
code and which stay local to each clone.

This repository's answer is a coordination ledger and nothing else: the
tasks and handoffs that outlive the session which wrote them, and the
sessions and outputs the observability writers index as pointers. What it
knows about itself it writes in `docs/`, not in a corpus; the corpus types
in `lup_template.corpus` are the scaffold's offer to an adopter, declared
nowhere here.
"""

from lup.coordination.handoffs import Handoff, Transfers
from lup.coordination.tasks import Blocks, Task
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.store import InTree, LedgerLayout, SharedStore
from lup.observability.sessions import Output, OutputOf, Session

# lup: template: this repository keeps a coordination ledger only — tasks and
# handoffs committed in `ledger/`, where they travel with commits, are
# reviewed in a diff and merged by union; sessions and outputs local under
# the git directory every worktree shares, never reaching a commit. An
# adopter that wants a corpus declares `lup_template.corpus`'s kinds and
# edges here beside these and chooses their placement; a kind absent from the
# mapping is local, and an edge is committed only where both of its ends are
LAYOUT = LedgerLayout(
    committed=InTree(),
    local=SharedStore(),
    placements={
        Task: "committed",
        Handoff: "committed",
    },
)
"""One log in two journals, and which of this repository's kinds go to which."""

# lup: ignore[constant-declaration] — what this repository records, which is a
# declaration about this project and not a default an adopter tunes
NODE_KINDS: list[type[LedgerNode]] = [
    Task,
    Handoff,
    Session,
    Output,
]

# lup: ignore[constant-declaration] — the relations this repository draws,
# declared beside the node kinds for the same reason
EDGE_KINDS: list[type[LedgerEdge]] = [
    Blocks,
    Transfers,
    OutputOf,
]
