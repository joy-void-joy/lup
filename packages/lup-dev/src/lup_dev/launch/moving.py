"""A launch walking the operator through moving the repository's sessions from their own runtime directory into its rooms' home, where a room resumes them (`docs/launch.md`, *Moving over*).

Before rooms had homes of their own, every room mounted the operator's own
directory for its runtime, so the sessions launched then are recorded there, and
a room on a home doesn't find them to resume. `lup-dev account migrate` moves
them; a launch, before its room starts, offers that move where it would move
something of the launched runtime's, says what was found in the operator's
directory after it, and how to replace the host login every room could read.

What's said, each line saying what to do (#321):
- where the operator's directory holds records of the repository's directories
  that would move, how many sessions and how much, and, where the launch
  resumes one of them, that it resumes only once they move; then the question,
  once, on a terminal. With no terminal, that a terminal or the command moves
  them. With another launch of the repository running, whose session would write
  on where their record was, each by its name, to end before launching again;
- after a yes, what moved, and what a host session acts on in the operator's
  directory that a room could have written, with how to replace the host login
  the first time a launch says it (`ToldLayout.host_login`), waiting for Enter
  so it's read before the room takes the terminal; one line, and no wait, where
  nothing there needs acting on;
- after a no, that a session left there doesn't resume in a room, its resume
  among them.

Once the repository's records of the runtime are moved, by a launch or the
command, the move is marked (`ToldLayout.migrated`) and no launch offers it
again: what a host session run in the repository writes there after is the
host's, unless the command moves it.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.host.written import counted
from lup_dev.migration import HostRuntime, Migrating

if TYPE_CHECKING:
    from lup_dev.host.protocol import Register
    from lup_dev.host.written import Places


def agreed(said: str) -> bool | None:
    """Read a yes or a no, yes where nothing is said; none where it's neither.

    >>> agreed(""), agreed(" Y"), agreed("no"), agreed("maybe")
    (True, True, False, None)
    """
    match said.strip().lower():
        case "" | "y" | "yes":
            return True
        case "n" | "no":
            return False
        case _:
            return None


class MovingOver(Model, arbitrary_types_allowed=True):
    """One launch's offer to move its runtime's records of the repository from the operator's own directory into its rooms' home, and what it says of them."""

    migrating: Migrating
    """The repository's migration, into the home the launch's profile runs on."""
    runtime: HostRuntime
    """The runtime launched, as the migration takes it."""
    resumed: str | None
    """The session the launch resumes, by their id, where it names one."""
    say: Callable[[str], None]
    """Where the launch tells the operator what it does."""
    ask: Callable[[str], str | None] | None
    """Asks the operator in their terminal, returning the line they answer,
    none at the end of its input; none where there's no terminal."""

    def walked(self) -> None:
        """Offer the move where something would move and no launch marked it done, say what's to know of it, and move on a yes: before the room starts, so a session it resumes is in its home."""
        migrating = self.migrating
        runtime = self.runtime
        if migrating.layout.told.migrated(migrating.repository, runtime.name).exists():
            return
        if not runtime.directory.is_dir():
            return
        under = migrating.under()
        records = migrating.operators(runtime, under)
        if not records:
            return
        dry = migrating.walked(runtime, records, move=False)
        if not dry.moves():
            return
        places = migrating.places(under)
        shown = places.shown(runtime.directory)
        resuming = self.resumed is not None and self.resumed in dry.sessions
        still = f"{shown} still holds {dry.amount()}, which no room resumes there"
        live = migrating.live()
        if live:
            self.say(
                f"{still}. They move with no other launch of it running: "
                f"{self.ending(live)}."
            )
            self.unresumed(resuming=resuming)
            return
        if self.ask is None:
            self.say(
                f"{still}: launch from a terminal to move them, or run "
                f"`{self.command()}`."
            )
            self.unresumed(resuming=resuming)
            return
        self.say(f"{still}. End any {runtime.name} running in it on the host first.")
        if resuming:
            self.say(
                f"The session this launch resumes, `{self.resumed}`, is one of them: "
                "it resumes here once they move."
            )
        if not self.agreed(f"Move them into {self.whose()} now? [Y/n] "):
            self.say(
                f"Left in {shown}, where a session doesn't resume in a room: the "
                f"next launch asks again, and `{self.command()}` moves them."
            )
            self.unresumed(resuming=resuming)
            return
        self.moved(places)

    def moved(self, places: Places) -> None:
        """Move the records, unless a launch of the repository started meanwhile; say what moved, then what of the operator's directory is to check."""
        migrating = self.migrating
        runtime = self.runtime
        shown = places.shown(runtime.directory)
        live = migrating.live()
        if live:
            self.say(f"Nothing moved: {self.ending(live)}.")
            return
        moved = migrating.walked(
            runtime, migrating.operators(runtime, migrating.under()), move=True
        )
        self.say(
            f"Moved {moved.amount()}, into {self.whose()}: they resume in a room "
            "from now on."
        )
        if moved.left:
            self.say(
                f"{counted(len(moved.left), 'thing', 'things')} of them stay in "
                f"{shown}: `lup-dev account migrate` says which, and why."
            )
        self.checked(places)

    def checked(self, places: Places) -> None:
        """Say what a host session acts on in the operator's directory, which rooms could write before, with how to replace the host login the first time a launch says it, and wait for Enter; one line, and no wait, where nothing there needs acting on."""
        runtime = self.runtime
        shown = places.shown(runtime.directory)
        found = self.migrating.found(runtime, places)
        mark = self.migrating.layout.told.host_login(runtime.name)
        login = None if mark.exists() else found.login
        if not found.found and login is None:
            self.say(f"Nothing a host session acts on in {shown} needs checking.")
            return
        self.say(
            f"Every room could write {shown} until now. Check what a host session "
            "acts on there:"
        )
        for each in [*found.found, *([] if login is None else [login])]:
            self.say(f"- {each}")
        if login is not None:
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.touch()
        if self.ask is not None:
            self.ask("Press Enter to go on. ")

    def agreed(self, question: str) -> bool:
        """Ask `question` until it's answered yes or no, Enter answering yes; no where the terminal's input ends."""
        asking = question
        while self.ask is not None and (said := self.ask(asking)) is not None:
            answer = agreed(said)
            if answer is not None:
                return answer
            asking = f"Answer y or n. {question}"
        return False

    def unresumed(self, *, resuming: bool) -> None:
        """Say, where the launch resumes a session left in the operator's directory, that it won't resume in this room."""
        if resuming:
            self.say(
                f"The session this launch resumes, `{self.resumed}`, is one of them, "
                "so it won't resume in this room."
            )

    def ending(self, live: list[Register]) -> str:
        """Say which launches to end, by their names, before launching again."""
        named = ", ".join(f"`{each.name or each.launch}`" for each in live)
        return f"end {named}, then launch again"

    def whose(self) -> str:
        """Say the rooms' home the records move into, as the operator knows it."""
        if self.migrating.shared:
            return "the rooms' home every project shares"
        return "the rooms' home"

    def command(self) -> str:
        """Say the command that moves them by hand."""
        shared = " --shared" if self.migrating.shared else ""
        return f"lup-dev account migrate --move{shared}"
