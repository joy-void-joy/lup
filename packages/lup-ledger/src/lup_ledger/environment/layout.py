"""Where the ledger keeps what it stores: one SQLite database, and the files its records attach, in lup's state on the host.

The host service is its only writer, and no room mounts it, as with the inbox
(`docs/inbox.md`, *Parties and items*).
"""

from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model

if TYPE_CHECKING:
    from lup_dev.layout import Layout


# lup: defer(issue=344, why="a kind kept committed in the repository has its half there, in the worktree, beside this one in lup's state")
class LedgerLayout(Model):
    """Where the ledger's database lives: one per user, every repository's records in it."""

    home: Path

    @classmethod
    def of(cls, layout: Layout) -> LedgerLayout:
        """Place the ledger in lup's state, as `layout` places it: `$XDG_STATE_HOME/lup/ledger/`."""
        return cls(home=layout.state / "ledger")

    @property
    def database(self) -> Path:
        """The database itself; SQLite keeps its write-ahead log and its index of it beside it."""
        return self.home / "ledger.sqlite3"

    @property
    def attachments(self) -> Path:
        """What records attach, too large to hold in a row, such as an item's diff: a file each, named by its content's digest."""
        return self.home / "attachments"

    def attachment(self, digest: str) -> Path:
        """Say where the attachment whose content's SHA-256 is `digest`, in hex, is kept."""
        return self.attachments / digest
