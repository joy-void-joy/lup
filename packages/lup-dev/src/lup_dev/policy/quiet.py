"""A conversation's quiet: the kinds of findings they aren't told after their calls for a while, and what stands that they weren't told, once it lifts.

`docs/judging-writes.md`, *Quiet*, and `DESIGN.md`, *Quiet*. During a wide
change, a refactor across sixty files or several edits in a row to one, an agent
knows their work is broken and will fix it later, so being told each finding as
it appears is noise. They ask, with lup's tool `quiet`, not to be told some
kinds (`Kind`): what a report would tell of them it doesn't, and doesn't
remember as told (`Look.held`, `news`), while what they were told before stays
known. When they lift the quiet, they're told once what stands now that they
weren't told: not each state in between, but the files as they stand, read
against what they know.

What's held is kept with the session's conversations (`Conversations.quiet`), so
every hook of the session reads it, whichever worktree it judges in. The tool is
served by the host service beside `judged` and run here, in the repository's
process (`policy/tools.py`), since telling what stands needs the engine the
judge keeps warm.
"""

from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.codescan.contract import Finding, Owner
from lup_dev.policy.checkpoint import (
    Bench,
    ConversationRecord,
    Worktree,
    on_disk,
    standing,
    watch,
    worktrees,
)
from lup_dev.policy.report import Kind, Look, Part, Quiet, placed, summary
from lup_dev.policy.worktrees import SessionIndex

if TYPE_CHECKING:
    from pathlib import Path

EVER_TOLD = (
    "Refusals, held writes and the operator's answers, moves of `HEAD`, values "
    "never published, and the list a turn's end is held on still come through."
)
"""What no quiet holds, said whenever one's set."""


class Unheard(Model):
    """What stands in one worktree that a conversation wasn't told, each file by its absolute path."""

    touched: list[Finding] = []
    """lup's findings, type errors and ruff's findings in the files they touched."""
    importers: list[Finding] = []
    """Type errors in the files importing them that they watch."""


def quieted(bench: Bench, session: str, agent: str, kinds: list[Kind]) -> str:
    """Hold `kinds` back from conversation `agent` of `session` from now on, and say what that does; no kinds lifts their quiet, telling what stands that they weren't told (`lifted`)."""
    held = list(dict.fromkeys(kinds))
    record = ConversationRecord(layout=bench.services.layout, session=session)
    before = record.quieting(agent, held)
    if not held:
        return lifted(bench, session, agent, quiet=before)
    quiet = Quiet(kinds=held)
    released: list[Kind] = [kind for kind in before.kinds if kind not in held]
    later = (
        [
            (
                f"What it held of {Quiet(kinds=released).said()} is told as those "
                "files are read again, or when the quiet lifts."
            )
        ]
        if released
        else []
    )
    return " ".join(
        [
            (
                f"You're quiet: lup doesn't tell you {quiet.said()} after your "
                "calls, until `quiet` with no kinds lifts it and tells you what "
                "stands then that you weren't told."
            ),
            *later,
            EVER_TOLD,
        ]
    )


def lifted(bench: Bench, session: str, agent: str, *, quiet: Quiet) -> str:
    """Tell conversation `agent` of `session`, whose quiet held `quiet` before it lifted, what stands that they weren't told, and remember it told.

    In each worktree their session holds: in the files they touched, lup's findings,
    type errors and ruff's; in the files importing them where the importers pass
    found errors, pyright's, once the pass it may be running is done, as a
    turn's end waits for it. A report too long for a tool's answer is fitted as
    a hook's is (`Bench.said`).
    """
    opening = (
        "lup's quiet is lifted: it tells you every finding after your calls again."
        if quiet.kinds
        else "You weren't quiet: lup tells you every finding after your calls."
    )
    index = SessionIndex(layout=bench.services.layout)
    with index.lock(session):
        held = index.read(session)
    unheard = (
        []
        if held is None
        else [
            unheard_in(bench, each, session, agent) for each in worktrees(bench, held)
        ]
    )
    parts = summary(
        [found for each in unheard for found in each.touched],
        [found for each in unheard for found in each.importers],
    )
    if held is None or not parts:
        return (
            f"{opening} Nothing stands in the files you touched that you weren't told."
        )
    heading = f"{opening} What stands in the files you touched that you weren't told:"
    return bench.said(held.repository, [Part(whole=heading), *parts])


def unheard_in(bench: Bench, worktree: Worktree, session: str, agent: str) -> Unheard:
    """Return what stands in `worktree` that conversation `agent` of `session` wasn't told, and remember it told (`Session.news`).

    A file under an open hold is nobody's until the operator answers, so it's
    left out, as a turn's end leaves it; so is one the engine doesn't read, gone
    or of a role nothing checks, whose findings they were told stay known.
    """
    services = bench.services
    worktree.importers().wait(
        services.checker, worktree.declaration.runner, services.clock
    )
    with worktree.lock():
        record = worktree.session(session, bench.runtime)
        watch(worktree, record, worktree.importers().collect())
        worktree.keep(record)
        kept = [each.path for each in worktree.store.state().holding]

    def read_here(path: Path) -> bool:
        return (
            path not in kept
            and (worktree.root / path).is_file()
            and worktree.roles.checked(path)
        )

    touched = [path for path in record.touched.get(agent, []) if read_here(path)]
    watched = [
        path
        for path in record.watched.get(agent, [])
        if read_here(path) and path not in touched
    ]
    found = standing(bench, worktree, [*touched, *watched])
    every: list[Owner] = ["lup", "pyright", "ruff"]

    def read(path: Path, owners: list[Owner]) -> Look:
        return Look(
            path=path,
            owners=owners,
            findings=[
                each for each in found if each.path == path and each.owner in owners
            ],
            content=on_disk(worktree.root, path),
        )

    mine = [read(path, every) for path in touched]
    theirs = [read(path, ["pyright"]) for path in watched]
    with worktree.lock():
        record = worktree.session(session, bench.runtime)
        new = dict.fromkeys(record.news(agent, [*mine, *theirs]))
        worktree.keep(record)

    def told(looks: list[Look]) -> list[Finding]:
        return placed(
            worktree.root,
            [each for look in looks for each in look.findings if each in new],
        )

    return Unheard(touched=told(mine), importers=told(theirs))
