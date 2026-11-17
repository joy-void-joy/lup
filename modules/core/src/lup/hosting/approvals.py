"""`Approvals`: the machine's part keeping which commit of each project the operator approved to run, and what to ask them before another does.

Nothing of a project runs that the operator hasn't approved: each of its parts
runs the commit they approved last, from its files as `Trees` writes them out.
An approval comes from the review of a landing, whose yes approves the commit
it lands (`landed`, the machine's), or from the operator answering the
question asked when a project's running branch moved with no review of
theirs: a pull, a push of their own, a first run (`approve`, theirs). The
question says what changed since the commit approved before, read from each
object's own bytes, the files of a part holding something and the
dependencies called out, as a review highlights what's held; the whole diff
comes from both commits written out, so what's shown is what would run
(`README.md` here, *Approvals*).
"""

from pathlib import PurePosixPath
from typing import Literal
lazy from pathlib import Path

from pydantic import TypeAdapter

import lup
from lup.doors.parties import Machine, Operator
from lup.doors.parts import Data, Part
from lup.hosting.trees import Change, Commit, Comparing, Trees
from lup.running.plan import Name, Plan
from lup.types import Model


class Approving(Model):
    """A commit of a project to approve to run."""

    project: Name
    commit: Commit


class Approval(Model):
    """A commit of a project the operator approved, and how."""

    commit: Commit
    how: Literal["landing", "asked"]
    """As a landing's review said yes, or as the operator answered the
    question asked before it ran."""


APPROVALS = TypeAdapter(list[Approval])


class Asking(Model):
    """A project, asked about by its name."""

    project: Name


class Approved(Model):
    """The commit of a project the operator approved last; none before their first approval."""

    commit: Commit | None = None


class Questioning(Model):
    """What to ask the operator before a project's commit runs: the project, its common git directory, the commit, and its plan, where it's known, which says what each part holds."""

    project: Name
    common: Path
    tip: Commit
    plan: Plan | None = None


class Question(Model):
    """What the operator is asked before a commit runs: what changed since the commit approved before, what of it a part holding something runs, and whether the dependencies changed."""

    project: Name
    before: Commit | None
    """The commit approved before; none for a first approval, which shows
    every file."""
    tip: Commit
    changes: list[Change] = []
    holding: list[Change] = []
    """The changes in a directory holding a part that holds something, which
    the question shows first, as a review shows what's held."""
    dependencies: bool = False
    """Whether a lockfile or a project's `pyproject.toml` changed: every
    part's dependencies, which the question shows first too."""


def holding_of(changes: list[Change], plan: Plan | None) -> list[Change]:
    """Return the changes in a directory holding a part that holds something, as `plan` says where each part's class is defined; none where there's no plan.

    >>> from lup.doors.parts import Holds
    >>> from lup.running.plan import PartPlan
    >>> plan = Plan(parts=[PartPlan(module="chat", part="Bot", holds=Holds(secrets=["token"]), source="src/chat/bot.py")])
    >>> [str(each.path) for each in holding_of([Change(path=PurePosixPath("src/chat/api.py"), how="changed"), Change(path=PurePosixPath("README.md"), how="changed")], plan)]
    ['src/chat/api.py']
    """
    if plan is None:
        return []
    directories = [
        PurePosixPath(each.source).parent
        for each in plan.apart()
        if each.source is not None
    ]
    return [
        change
        for change in changes
        if any(change.path.is_relative_to(each) for each in directories)
    ]


class Approvals(Part, machine=True, shared=True):
    """The machine's part keeping which commit of each project the operator approved to run, and what to ask them before another does."""

    records: Data
    """Each project's approvals, a JSON file each, in the order they came."""

    def kept(self, project: str) -> list[Approval]:
        """Return each approval of `project`, in the order they came."""
        file = self.records.path / f"{project}.json"
        if not file.exists():
            return []
        return APPROVALS.validate_json(file.read_bytes())

    def kept_with(self, approving: Approving, approval: Approval) -> None:
        """Keep `approval` of `approving`'s project after those before it."""
        file = self.records.path / f"{approving.project}.json"
        kept = [*self.kept(approving.project), approval]
        file.write_bytes(APPROVALS.dump_json(kept))

    @lup.service
    async def landed(self, approving: Approving, by: Machine) -> None:
        """Approve the commit a landing lands, as the operator's yes to its review says: the machine's code that lands it records it here."""
        del by
        self.kept_with(approving, Approval(commit=approving.commit, how="landing"))

    @lup.command
    async def approve(self, approving: Approving, by: Operator) -> str:
        """Approve a commit of a project to run, as you answer the question asked before it does."""
        del by
        self.kept_with(approving, Approval(commit=approving.commit, how="asked"))
        return f"approved {approving.commit} of {approving.project} to run"

    @lup.service
    async def approval(self, asking: Asking, by: Machine) -> Approved:
        """Return the commit of a project the operator approved last, which is what of it runs; none before their first approval."""
        del by
        kept = self.kept(asking.project)
        return Approved(commit=kept[-1].commit if kept else None)

    @lup.service
    async def question(self, questioning: Questioning, by: Machine) -> Question:
        """Say what to ask the operator before a project's commit runs: what changed since the commit approved last, read from each object's own bytes, what of it a part holding something runs, and whether the dependencies changed.

        Raise `TreeError` where an object can't be read or isn't what its id
        says.
        """
        del by
        approved = await self.approval(Asking(project=questioning.project), Machine())
        compared = await Trees.compared(
            Comparing(
                repository=questioning.project,
                common=questioning.common,
                before=approved.commit,
                after=questioning.tip,
            )
        )
        return Question(
            project=questioning.project,
            before=approved.commit,
            tip=questioning.tip,
            changes=compared.changes,
            holding=holding_of(compared.changes, questioning.plan),
            dependencies=any(
                each.path.name in ["uv.lock", "pyproject.toml"]
                for each in compared.changes
            ),
        )
