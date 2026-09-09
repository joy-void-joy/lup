"""Every cite in every tracked document, held to what its node says now.

The gate's half of the cite check. The reading itself is
:mod:`lup.corpus.cite`, which takes text and a store and knows nothing about
files or git; this is what walks the tracked markdown, hands each file over,
and folds what came back into the one report `dev check` prints. Split that
way so the same reading answers a command over one document and a test over
a string, and so the gate is the only thing that decides which files count.
"""

from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.execution.shell import git
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerNode
from lup.ledger.cite import CiteReading, read_cites
from lup.workspace.paths import project_root


class Located(BaseModel, frozen=True):
    """One cite reading, and the tracked file it was read from."""

    file: str
    reading: CiteReading

    def line(self) -> str:
        return f"  {self.file}:{self.reading.cite.line}  {self.reading.problem()}"


class CiteSweep(BaseModel, frozen=True):
    """What the gate found: how many cites it read, and which do not hold."""

    checked: int
    failing: list[Located]

    def passed(self) -> bool:
        return not self.failing

    def lines(self) -> list[str]:
        """The report as the gate prints it: one summary line, one per failure."""
        if self.failing:
            return [
                f"cites: FAIL ({len(self.failing)} of {self.checked} do not hold)",
                *(found.line() for found in self.failing),
            ]
        if not self.checked:
            return ["cites: none"]
        return [f"cites: ok, {self.checked} hold"]


def sweep_cites(classes: list[type[LedgerNode]]) -> CiteSweep:
    """Read every tracked markdown file's cites against the repository's log."""
    root = project_root()
    store = LedgerStore(root, ActorRef(kind="console", id=mint_member_id()))

    def located() -> Iterator[Located]:
        for rel in git.lines("ls-files", "--", "*.md"):
            try:
                text = Path(rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for reading in read_cites(text, store, classes):
                yield Located(file=rel, reading=reading)

    found = list(located())
    return CiteSweep(
        checked=len(found),
        failing=[item for item in found if not item.reading.holds()],
    )
