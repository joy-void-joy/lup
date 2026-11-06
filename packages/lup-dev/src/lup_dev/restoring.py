"""`lup-dev restore`: the operator's own way back to a kept copy, which needs no host service and no dashboard.

`docs/trust.md`, *The way back*. The person's `lup-dev` hands this command to the
copy that answered before the one running (`lup_dev.copies.launcher`), so it runs
from code that has worked, whatever's wrong with the copy it replaces, and so
what it reads an older copy may be reading from a newer one's hand: each record
it can't read is passed over (`Copies.history`, `Snapshots.all`).

With no commit it lists the copies and changes nothing. With one it moves the
host service there (`lup_dev/switching.py`), rebuilding the copy from its commit
where it was approved and is gone. Going back never rests on the ledger's
snapshot being taken, and it restores one only where it's asked to, or where the
copy can't read the ledger as it stands, saying first what that loses.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from filelock import FileLock, Timeout

from lup.types import Model
from lup_dev.copies import Copies, Kept
from lup_dev.errors import LupDevError
from lup_dev.host.client import HostClient
from lup_dev.host.protocol import HostError, Listed, ListLaunches
from lup_dev.layout import Layout
from lup_dev.snapshots import Snapshot, Snapshots
from lup_dev.switching import (
    Switch,
    Switcher,
    found,
    host_copies,
    last_switch,
    needs_ledger,
)
from lup_ledger.environment.layout import LedgerLayout


class RestoreError(LupDevError):
    """The operator's way back can't be taken as asked."""


def stamped(at: datetime | None) -> str:
    """Say a moment, to the minute, as the operator's copies are listed by it; `never` for none."""
    return "never" if at is None else at.astimezone().strftime("%Y-%m-%d %H:%M")


class Restoring(Model, arbitrary_types_allowed=True):
    """The operator's way back, on this machine."""

    layout: Layout
    host: HostClient
    switcher: Switcher
    confirm: Callable[[str], bool]
    """Asks the operator yes or no, no by default, where going back costs something."""
    built_again: Callable[[Kept, Callable[[Kept], Switch]], Switch]
    """Installs a copy approved and gone from its commit, and hands it to what's
    given while the repository's lock holds it."""
    say: Callable[[str], None]
    patience: timedelta = timedelta(seconds=5)
    """How long to wait on an approval being carried out, holding its lock."""

    def snapshots(self) -> Snapshots:
        """Return the ledger's snapshots, on this machine."""
        return Snapshots(
            home=self.layout.snapshots, ledger=LedgerLayout.of(self.layout)
        )

    def listing(self) -> str:
        """Say whether the service answers, each copy kept, the commits approved whose copies are gone, what came of a last switch that failed, and what to type."""
        service = (
            "The host service answers."
            if self.answering()
            else "No host service answers."
        )
        copies = host_copies(self.layout)
        if copies is None:
            return (
                f"{service}\nNo copy of `lup-dev` is kept yet: the first is from "
                "`lup-dev trust`, on a lup that keeps them."
            )
        kept = copies.kept()
        running = copies.current()
        snapshots = self.snapshots()

        def line(each: Kept) -> str:
            mark = "*" if running is not None and running.name == each.name else " "
            left = snapshots.left_by(each.name)
            ledger = (
                ""
                if left is None
                else f"  left the ledger {stamped(left.taken)}, tables {left.written.tables}"
            )
            return (
                f"{mark} {each.commit}  ran {stamped(each.answered)}  "
                f"{each.subject}{ledger}"
            )

        names = [each.name for each in kept]
        gone = [each for each in copies.history() if each.name not in names]
        gones = [f"  {each.commit}  {each.subject}" for each in gone]
        rebuilt = (
            "Approved, and gone: named, each is built again from its commit, which "
            "takes minutes and needs uv and Node:"
        )
        told = (
            "`lup-dev restore <commit>` goes back to one; `--ledger` also puts the "
            "ledger back as that copy left it, saying first what that loses."
        )
        last = last_switch(self.layout)
        failed = (
            [f"The last switch, {stamped(last.at)}: {last.said}", ""]
            if last is not None and not last.answered
            else []
        )
        said = [
            service,
            "",
            *failed,
            "Copies kept, the last to run first, `*` the one that judges and runs:",
            *map(line, kept),
            *(["", rebuilt, *gones] if gones else []),
            "",
            told,
        ]
        return "\n".join(said)

    def answering(self) -> bool:
        """Say whether the service answers a reading, not just a connection, which a kernel accepts for a process stopped or stuck."""
        try:
            self.host.ask(ListLaunches(), Listed)
        except HostError, OSError:
            return False
        return True

    def restored(self, commit: str, *, ledger: bool) -> Switch:
        """Move to the copy of `commit`, a prefix naming it, with the lock an approval holds, so neither moves what the other is moving.

        Raise `RestoreError` where it can't be taken as asked, an approval being
        carried out among it, or the operator declines what it would lose.
        """
        copies = host_copies(self.layout)
        if copies is None:
            message = "no copy of `lup-dev` is kept yet, so there's none to go back to"
            raise RestoreError(message)
        target = self.chosen(copies, commit)
        lock = self.layout.approved(target.repository)
        held = FileLock(
            lock.with_name(f"{lock.name}.lock"), timeout=self.patience.total_seconds()
        )
        try:
            with held:
                return self.moved(copies, target, ledger=ledger)
        except Timeout as busy:
            message = (
                f"an approval is being carried out, holding {held.lock_file}: wait for "
                "it, or end the `lup-dev` carrying it out, then run this again"
            )
            raise RestoreError(message) from busy

    def tried(self, commit: str) -> str | None:
        """Run the copy of `commit`, a prefix naming it, on a state of its own, moving nothing, whichever copy it is: say why it doesn't answer; none where it does. Raise `RestoreError` where it's not there to run."""
        copies = host_copies(self.layout)
        if copies is None:
            message = "no copy of `lup-dev` is kept yet, so there's none to try"
            raise RestoreError(message)
        target = self.chosen(copies, commit)
        if not copies.there(target):
            message = f"{target.commit}'s copy is gone, so there's none to try"
            raise RestoreError(message)
        return self.switcher.tried(target)

    def chosen(self, copies: Copies, commit: str) -> Kept:
        """Return the copy to go to: among those there, else among those gone."""
        there = [each for each in copies.history() if copies.there(each)]
        matches = [each for each in there if each.commit.startswith(commit)]
        return found(matches or copies.history(), commit)

    def moved(self, copies: Copies, target: Kept, *, ledger: bool) -> Switch:
        """Say what going to `target` loses, where it does, ask, and go."""
        snapshot = self.ledger_to_restore(target, asked=ledger)
        if copies.there(target):
            return self.switcher.to(target, ledger=snapshot, returning=True)
        self.say(f"{target.commit}'s copy is gone: building it again, from its commit.")

        def switched(built: Kept) -> Switch:
            return self.switcher.to(built, ledger=snapshot, returning=True)

        return self.built_again(target, switched)

    def ledger_to_restore(self, target: Kept, *, asked: bool) -> Snapshot | None:
        """Return the snapshot to put back on the way to `target`: what it left, where the operator asked or it can't read what's there, once they've been told what that loses and said yes.

        Raise `RestoreError` where they say no, or where they asked for one and
        the copy left none, since going on would give them less than they asked.
        """
        snapshots = self.snapshots()
        must = needs_ledger(snapshots, target.name)
        left = snapshots.left_by(target.name)
        if asked and left is None:
            message = (
                f"{target.commit} left no snapshot of the ledger, so there's nothing "
                "to put back: without `--ledger`, this goes back and leaves the "
                "ledger as it is"
            )
            raise RestoreError(message)
        snapshot = must or (left if asked else None)
        if snapshot is None:
            return None
        why = (
            (
                f"{target.commit} left the ledger at version {snapshot.written.tables} "
                "of its tables, which it can't read past, so it needs the ledger as it "
                "left it. "
            )
            if must is not None
            else ""
        )
        said = f"{why}{snapshots.lost_to(snapshot).said()}"
        self.say(said)
        if not self.confirm("Go back, and put the ledger back with it?"):
            message = "Nothing moved: the ledger and the copy stay as they were."
            raise RestoreError(message)
        return snapshot
