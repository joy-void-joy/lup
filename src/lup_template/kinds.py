"""What this repository records in its ledger, declared once.

Two readers need the list and must not disagree: the console, which turns a
stored record into some class to ask its standing, and the tool group a
session records through. Listed here rather than derived from the adopted
modules, because a union assembled at run time is not one a type checker can
narrow. The library declares none of these — what a node kind is for is a
project's question — so this file is where a project adopting the scaffold
puts its own answer, and where it says which of them are committed with the
code and which stay local to each clone.
"""

from lup.coordination.handoffs import Handoff, Transfers
from lup.coordination.tasks import Blocks, Task
from lup.ledger.files import File
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.store import InTree, LedgerLayout, SharedStore
from lup.observability.sessions import Output, Session
from lup_template.corpus import (
    About,
    Answers,
    Artifact,
    Certificate,
    Claim,
    Correction,
    Question,
    Refutes,
    RestsOn,
    Source,
    Supersedes,
    Supports,
    Verifies,
)

# lup: template: decide which kinds this project commits with the code and
# which stay local — a committed kind's records sit in `ledger/`, travel with
# commits, are reviewed in a diff and merged by union, so they are the same on
# every machine; a local kind's sit under the git directory every worktree
# shares and never reach a commit. The scaffold commits its corpus, its tasks
# and handoffs, and the files they rest on; a kind absent from the mapping is
# local, and an edge is committed only where both of its ends are
LAYOUT = LedgerLayout(
    committed=InTree(),
    local=SharedStore(),
    placements={
        Task: "committed",
        Handoff: "committed",
        Claim: "committed",
        Question: "committed",
        Artifact: "committed",
        Certificate: "committed",
        Source: "committed",
        Correction: "committed",
        File: "committed",
    },
)
"""One log in two journals, and which of this repository's kinds go to which."""

# lup: ignore[constant-declaration] — what this repository records, which is a
# declaration about this project and not a default an adopter tunes
NODE_KINDS: list[type[LedgerNode]] = [
    Task,
    Handoff,
    File,
    Question,
    Claim,
    Correction,
    Artifact,
    Certificate,
    Source,
    Session,
    Output,
]

# lup: ignore[constant-declaration] — the relations this repository draws,
# declared beside the node kinds for the same reason
EDGE_KINDS: list[type[LedgerEdge]] = [
    Blocks,
    Transfers,
    About,
    Answers,
    RestsOn,
    Supports,
    Refutes,
    Verifies,
    Supersedes,
]
