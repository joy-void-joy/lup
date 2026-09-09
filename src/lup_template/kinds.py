"""What this repository records in its ledger, declared once.

Two readers need the list and must not disagree: the console, which turns a
stored record into some class to ask its standing, and the tool group a
session records through. Listed here rather than derived from the adopted
modules, because a union assembled at run time is not one a type checker can
narrow. The library declares none of these — what a node kind is for is a
project's question — so this file is where a project adopting the scaffold
puts its own answer.
"""

from lup.coordination.handoffs import Handoff, Transfers
from lup.coordination.tasks import Blocks, Task
from lup.ledger.files import File
from lup.ledger.models import LedgerEdge, LedgerNode
from lup.ledger.store import LedgerPlacement, SharedStore
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

# lup: template: decide where this project keeps its ledger — `SharedStore()`
# under the git directory every worktree shares, or `InTree()` committed with
# the code, reviewed in a diff, merged by union and the same on every machine
PLACEMENT: LedgerPlacement = SharedStore()
"""Where this repository's log lives, read by every surface that opens it."""

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
