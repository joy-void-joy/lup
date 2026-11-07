"""What moves what's on trial: the operator's picks and drops, and `dev` moving under it."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

import pytest

import lup_dev.trying
from lup_dev import cli
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.composing import apart
from lup_dev.copies import Copies, Kept, linked
from lup_dev.git import Git
from lup_dev.host.on_trial import (
    AcceptBranch,
    BranchListed,
    LastSwitch,
    TrialListed,
    TrialSaid,
)
from lup_dev.host.protocol import Branches, HostError, Looks, Reply, Request
from lup_dev.host.watch import Changes, TrialMoved
from lup_dev.host.workers import Listing, Offered, RepositoryAsking
from lup_dev.layout import CopyLayout, Layout
from lup_dev.policy.landing import Turns, no_room
from lup_dev.snapshots import Snapshot
from lup_dev.stored import write_model
from lup_dev.trial import (
    AcceptingTools,
    OnTrial,
    Plan,
    Trial,
    Trials,
    Version,
    message_of,
    moved_on,
    pins,
    plan,
    running_tip,
    trial_listed,
)
from lup_dev.trying import OwnViewsSaid, TrialAccepting, Trying

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from conftest import FakeClock, Shell

    from lup_dev.snapshots import Snapshots


AT = datetime(2026, 11, 6, tzinfo=UTC)
LIVE = Branches(integration="dev", running="live")


class World:
    """A repository laid out as lup's, with `origin` a bare forge holding `dev`, and the service's side of what's on trial; a zone's fingerprint is its commit's tree, so the same files are the same zone, as they are to trust."""

    def __init__(
        self,
        bare: Path,
        tmp_path: Path,
        shell: Shell,
        machine: Layout,
        clock: FakeClock,
    ) -> None:
        self.repository = bare
        self.shell = shell
        self.machine = machine
        self.forge = tmp_path / "forge.git"
        shell.git(tmp_path, "init", "-q", "--bare", str(self.forge))
        shell.git(bare, "remote", "set-url", "origin", str(self.forge))
        shell.git(bare, "branch", "dev", "main")
        shell.git(bare, "push", "-q", "origin", "dev")
        self.dev = bare / "tree" / "dev"
        shell.git(bare, "worktree", "add", "-q", str(self.dev), "dev")
        self.started: list[tuple[str, str]] = []
        self.asked: list[Path] = []
        self.approve(shell.git(bare, "rev-parse", "dev"))
        self.trying = Trying(
            layout=machine,
            clock=clock,
            say=lambda _: None,
            turns=Turns(),
            fingerprint=lambda _, commit: self.tree(commit),
            propose=self.proposed,
            start=self.switch_started,
        )

    def proposed(self, repository: Path) -> int | None:
        self.asked.append(repository)
        return 7

    def switch_started(self, copy: CopyLayout, commit: str) -> None:
        self.started.append((copy.home.name, commit))

    def tree(self, commit: str) -> str:
        """Return `commit`'s tree."""
        return self.shell.git(self.repository, "rev-parse", f"{commit}^{{tree}}")

    def approve(self, commit: str) -> None:
        """Keep `commit`'s zone as what's approved."""
        write_model(self.machine.approved(self.repository), self.approval(commit))

    def approval(self, commit: str) -> Approval:
        return Approval(
            commit=commit,
            fingerprint=self.tree(commit),
            paths=[],
            tool=ReleaseTool(name="lup-dev", version="0", registry="", pins={}),
            time=AT,
            branches=LIVE,
        )

    def branched(self, name: str, files: dict[str, str]) -> str:
        """Make `name` from `dev`, in a worktree of its own, with a commit writing `files`; return its tip."""
        root = self.repository / "tree" / name
        self.shell.git(
            self.repository, "worktree", "add", "-q", "-b", name, str(root), "dev"
        )
        for path, content in files.items():
            (root / path).write_text(content)
        self.shell.commit(root, f"write {name}")
        return self.shell.git(root, "rev-parse", "HEAD")

    def on_trial(self, *branches: tuple[str, str]) -> None:
        """Keep each `(name, tip)` as landed, with `live` as it would be."""
        dev = self.shell.git(self.repository, "rev-parse", "dev")
        trial = Trial(
            branches=[
                OnTrial(
                    branch=name,
                    tip=tip,
                    landed=AT,
                    party=None,
                )
                for name, tip in branches
            ]
        )
        Trials.of(self.machine, self.repository).write(trial)
        self.recompute(dev)

    def recompute(self, dev: str) -> None:
        """Move `live` as what asks nothing does: the record as `Trying.computed` leaves it."""
        git = Git.pinned(self.repository)
        trials = Trials.of(self.machine, self.repository)
        found = self.trying.computed(git, trials.read(), LIVE, dev)
        assert found.commit is not None
        trials.write(moved_on(found.trial, found.commit, dev, found.plan, AT))

    def kept_copy(self, commit: str, name: str = "built") -> Kept:
        """Have a copy of `commit`'s zone kept, approved, pinned, and installed."""
        copies = Copies(layout=self.machine.judge(self.repository))
        kept = Kept(
            name=name,
            repository=self.repository,
            approval=self.approval(commit),
            answered=AT,
        )
        copies.recorded(kept)
        copies.place(kept).home.mkdir(parents=True)
        copies.pin([*copies.pinned(), kept.commit])
        return kept

    def record(self) -> Trial:
        return Trials.of(self.machine, self.repository).read()

    def on_forge(self, ref: str) -> str | None:
        return (
            self.shell.git(self.forge, "for-each-ref", "--format=%(objectname)", ref)
            or None
        )

    def picked(self, *names: str) -> TrialSaid:
        return asyncio.run(self.trying.picked(self.repository, list(names)))

    def merged_onto_dev(self, branch: str) -> None:
        """Merge `branch` onto `dev`, on the forge too, as accepting it does."""
        self.shell.git(self.dev, "merge", "-q", "--no-edit", branch)
        self.shell.git(self.dev, "push", "-q", "origin", "dev")


@pytest.fixture
def machine(tmp_path: Path) -> Layout:
    return Layout(data=tmp_path / "data", state=tmp_path / "state")


@pytest.fixture
def world(
    bare: Path, tmp_path: Path, shell: Shell, machine: Layout, clock: FakeClock
) -> World:
    return World(bare, tmp_path, shell, machine, clock)


def test_picking_a_set_with_no_copy_kept_asks_the_operator_and_builds_nothing(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a), ("b", b))
    replied = world.picked("a")
    assert world.record().tips == {"a": a}
    assert [each.out for each in world.record().branches] == [False, True]
    assert world.asked == [world.repository]
    assert world.started == []
    assert replied.switching is None
    assert (
        "a build runs its code on this machine, so it waits on your yes" in replied.said
    )
    assert world.on_forge("refs/heads/live") == world.record().live


def test_picking_a_set_whose_copy_is_kept_moves_the_host_at_once_asking_nothing(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a))
    built = world.record().live
    assert built is not None
    kept = world.kept_copy(built)
    world.on_trial(("a", a), ("b", b))
    replied = world.picked("a")
    assert world.asked == []
    assert world.started == [("built", kept.commit)]
    assert replied.switching is not None
    assert replied.switching.commit == kept.commit
    # `live` moves on to a new commit, a fast-forward, with the same tree.
    live = world.record().live
    assert live not in (None, built)
    assert world.tree(live or "") == world.tree(built)


def test_picking_what_s_approved_already_moves_live_and_restarts_nothing(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    live = world.record().live
    assert live is not None
    world.approve(live)
    world.on_trial(("a", a))
    replied = world.picked("a")
    assert world.asked == []
    assert world.started == []
    assert "nothing restarts" in replied.said


def test_two_that_conflict_can_t_be_picked_together_and_nothing_moves(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"a.txt": "other\n"})
    world.on_trial(("a", a), ("b", b))
    before = world.record()
    with pytest.raises(HostError, match=r"`a` and `b` can't be picked together"):
        world.picked("a", "b")
    assert world.record() == before
    assert world.asked == []


def test_a_name_not_on_trial_is_refused(world: World) -> None:
    with pytest.raises(HostError, match=r"`nope` isn't on trial"):
        world.picked("nope")


def test_picking_nothing_runs_dev_alone(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    world.picked()
    assert world.record().tips == {}
    live = world.record().live
    assert live is not None
    dev = world.shell.git(world.repository, "rev-parse", "dev")
    assert world.tree(live) == world.tree(dev)
    assert (
        world.shell.git(world.repository, "merge-base", "--is-ancestor", a, live) == ""
    )


def test_a_copy_that_would_need_the_ledger_restored_refuses_moving_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a))
    built = world.record().live
    assert built is not None
    world.kept_copy(built)
    world.on_trial(("a", a), ("b", b))
    before = world.record()

    def needing(_snapshots: Snapshots, _copy: str) -> Snapshot:
        return Snapshot.model_construct()

    monkeypatch.setattr(lup_dev.trying, "needs_ledger", needing)
    with pytest.raises(HostError, match="can't read the ledger as it stands"):
        world.picked("a")
    assert world.record() == before
    assert world.started == []


def test_dropping_a_branch_in_live_recomputes_without_it_and_no_revert_is_made(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a), ("b", b))
    first = world.record().live
    trial = world.record()
    on = trial.on("a")
    assert on is not None
    replied = world.trying.dropping(world.repository, trial, on)
    assert list(world.record().tips) == ["b"]
    assert world.record().on("a") is None
    live = world.record().live
    assert live is not None
    assert first == world.shell.git(world.repository, "rev-parse", f"{live}^1")
    shown = world.shell.git(world.repository, "ls-tree", "--name-only", live)
    assert "a.txt" not in shown
    assert "b.txt" in shown
    assert world.asked == [world.repository]
    assert "waits on your yes" in replied.said


def test_dropping_one_out_of_live_changes_nothing_that_runs(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"a.txt": "other\n"})
    world.on_trial(("a", a), ("b", b))
    live = world.record().live
    trial = world.record()
    on = trial.on("b")
    assert on is not None
    world.trying.dropping(world.repository, trial, on)
    assert world.record().live == live
    assert world.record().on("b") is None
    assert world.asked == []


def test_dev_moving_with_nothing_the_host_runs_follows_asking_nothing(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    live = world.record().live
    assert live is not None
    # The fake zone is the whole tree, so what asks is any change: approve the
    # commit it'll come to, as a change the zone doesn't hold reads to trust.
    (world.dev / "docs.md").write_text("docs\n")
    world.shell.commit(world.dev, "docs")
    world.shell.git(world.repository, "push", "-q", "origin", "dev")
    git = Git.pinned(world.repository)
    dev = world.shell.git(world.repository, "rev-parse", "dev")
    with apart(git) as store:
        found = plan(store, dev, "dev", world.record())
        tree = store.kept(found.tree)
    write_model(
        world.machine.approved(world.repository),
        world.approval(live).model_copy(update={"fingerprint": tree}),
    )
    moved = asyncio.run(world.trying.moved_dev(world.repository))
    assert moved == []
    assert world.asked == []
    next_live = world.record().live
    assert next_live != live
    assert world.record().dev == dev
    assert world.shell.git(world.repository, "rev-parse", f"{next_live}^1") == live


def test_a_branch_dev_holds_is_accepted_and_leaves_the_trial(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a), ("b", b))
    world.shell.git(world.dev, "merge", "-q", "--no-ff", "--no-edit", "a")
    world.shell.git(world.repository, "push", "-q", "origin", "dev")
    asyncio.run(world.trying.moved_dev(world.repository))
    assert world.record().on("a") is None
    assert list(world.record().tips) == ["b"]
    live = world.record().live
    assert live is not None
    shown = world.shell.git(world.repository, "ls-tree", "--name-only", live)
    assert "a.txt" in shown
    assert "b.txt" in shown


def test_a_branch_that_stops_merging_as_dev_moves_falls_out_and_it_s_said(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    (world.dev / "a.txt").write_text("dev's own\n")
    world.shell.commit(world.dev, "dev's own")
    world.shell.git(world.repository, "push", "-q", "origin", "dev")
    moved = asyncio.run(world.trying.moved_dev(world.repository))
    assert world.record().tips == {}
    on = world.record().on("a")
    assert on is not None
    assert on.conflict == "it conflicts with `dev`, in `a.txt`"
    assert moved[0] == "`a` left `live`: it conflicts with `dev`, in `a.txt`."


def test_a_branch_taken_out_comes_back_only_by_being_picked(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a), ("b", b))
    world.picked("a")
    (world.dev / "docs.md").write_text("docs\n")
    world.shell.commit(world.dev, "docs")
    world.shell.git(world.repository, "push", "-q", "origin", "dev")
    asyncio.run(world.trying.moved_dev(world.repository))
    assert list(world.record().tips) == ["a"]
    world.picked("a", "b")
    assert sorted(world.record().tips) == ["a", "b"]


def test_a_remote_out_of_reach_stops_no_pick_and_it_s_said(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    world.shell.git(world.repository, "remote", "set-url", "origin", "/nowhere/at/all")
    replied = world.picked()
    assert world.record().tips == {}
    assert "`live` isn't on `origin` yet" in replied.said


def test_what_runs_is_read_from_the_record_never_a_ref_a_room_writes(
    world: World,
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    live = world.record().live
    assert live is not None
    world.shell.git(world.repository, "update-ref", "refs/heads/live", a)
    assert running_tip(world.machine, world.repository) == live


def test_a_copy_stays_kept_while_a_branch_in_it_is_on_trial() -> None:
    a = OnTrial(branch="a", tip="ta", landed=AT)
    b = OnTrial(branch="b", tip="tb", landed=AT)
    plan_a = Plan(tips={"a": "ta"}, tree="t")
    plan_b = Plan(tips={"b": "tb"}, tree="t")
    trial = moved_on(Trial(branches=[a, b]), "one", "d", plan_a, AT)
    trial = moved_on(trial, "two", "d", plan_b, AT)
    assert pins(trial) == ["one", "two"]
    # `a` lands a new tip: its old version is let go, `b`'s kept.
    landed = trial.model_copy(
        update={"branches": [a.model_copy(update={"tip": "ta2"}), b]}
    )
    assert pins(landed) == ["two"]
    # Accepted, it goes off trial: nothing pins it.
    assert pins(trial.model_copy(update={"branches": []})) == []


def test_a_page_reads_what_s_on_trial_and_whether_one_alone_is_built(
    world: World, machine: Layout
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"a.txt": "other\n"})
    world.on_trial(("a", a), ("b", b))
    live = world.record().live
    assert live is not None
    kept = Kept(
        name="copy",
        repository=world.repository,
        approval=approval_of(live, "the zone at live"),
    )
    listed = trial_listed(machine, world.repository, [kept])
    assert listed is not None
    assert [
        (each.branch, each.within, each.built, each.conflict)
        for each in listed.branches
    ] == [
        ("a", True, True, ""),
        ("b", False, False, "it conflicts with `a`, in `a.txt`"),
    ]


def approval_of(commit: str, fingerprint: str) -> Approval:
    """Return an approval of `commit`, whose host zone has `fingerprint`."""
    return Approval(
        commit=commit,
        fingerprint=fingerprint,
        paths=[],
        tool=ReleaseTool(name="lup-dev", version="1", registry="r", pins={}),
        time=datetime(2026, 11, 7, tzinfo=UTC),
    )


def test_a_version_is_listed_with_the_copy_that_runs_it_and_what_runs(
    world: World,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    at = datetime(2026, 11, 7, tzinfo=UTC)
    trial = Trial(
        live="c",
        dev="d",
        versions=[
            Version(commit="a", dev="d", tips={"x": "1"}, at=at, fingerprint="one"),
            Version(commit="b", dev="d", tips={"y": "2"}, at=at, fingerprint="two"),
            Version(commit="c", dev="d", tips={"x": "1", "y": "2"}, at=at),
        ],
    )
    Trials.of(machine, world.repository).write(trial)
    write_model(machine.approved(world.repository), approval_of("older", "two"))
    declared_branches(machine, world.repository, Branches(running="live"))
    write_model(
        machine.approved(world.repository),
        approval_of("older", "two").model_copy(
            update={"branches": Branches(running="live")}
        ),
    )
    ran = Kept(
        name="kept",
        repository=world.repository,
        approval=approval_of("copy-of-a", "one"),
        answered=at,
    )
    listed = trial_listed(machine, world.repository, [ran])
    assert listed is not None
    assert listed.runs == "older"
    assert [
        (each.commit, each.copy_kept, each.running, each.ran)
        for each in listed.versions
    ] == [
        # Its copy is of another commit, holding the same of what the host runs.
        ("a", "copy-of-a", False, at),
        # What's approved holds what it holds, though no copy of its commit is kept.
        ("b", None, True, None),
        ("c", None, False, None),
    ]


def test_each_way_live_moves_records_the_zone_of_what_it_holds(
    world: World, machine: Layout
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a), ("b", b))
    trying = world.trying
    zone = world.tree
    asyncio.run(trying.picked(world.repository, ["a"]))
    latest = world.record().latest
    assert latest is not None
    assert latest.fingerprint == zone(latest.commit)
    asyncio.run(trying.changed(world.repository, ["b"], [], {}))
    latest = world.record().latest
    assert latest is not None
    assert latest.fingerprint == zone(latest.commit)


def test_following_dev_with_nothing_moved_keeps_the_zone_as_an_accept_does_twice(
    world: World, machine: Layout
) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    world.on_trial(("a", a))
    trying = world.trying
    asyncio.run(trying.picked(world.repository, ["a"]))
    before = world.record().latest
    assert before is not None
    assert before.fingerprint is not None
    # An accept follows `dev` as its push does, then as it's answered: the second finds
    # nothing to do, and reads no zone.
    asyncio.run(trying.moved_dev(world.repository))
    asyncio.run(trying.moved_dev(world.repository))
    after = world.record().latest
    assert after is not None
    assert (after.commit, after.fingerprint) == (before.commit, before.fingerprint)


def test_moved_on_for_a_commit_it_holds_keeps_what_was_read_of_it() -> None:
    at = datetime(2026, 11, 7, tzinfo=UTC)
    trial = Trial(
        live="c",
        dev="d",
        versions=[Version(commit="c", dev="d", at=at, fingerprint="zone")],
    )
    again = moved_on(trial, "c", "d", Plan(tips={}, tree="t"), at)
    assert again.versions[-1].fingerprint == "zone"
    told = moved_on(trial, "c", "d", Plan(tips={}, tree="t"), at, fingerprint="other")
    assert told.versions[-1].fingerprint == "other"


def conflicting(world: World) -> None:
    """Put on trial a branch running, and one it keeps out by conflicting, which nobody took out."""
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"a.txt": "other\n"})
    world.on_trial(("a", a), ("b", b))


def test_a_change_leaves_every_other_branch_as_it_stands(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"a.txt": "other\n"})
    c = world.branched("c", {"c.txt": "c\n"})
    world.on_trial(("a", a), ("b", b), ("c", c))
    trying = world.trying
    asyncio.run(trying.changed(world.repository, [], ["c"], {}))
    record = world.record()
    # Nobody took out what `a` keeps out: it's no more out for a tick of `c`.
    assert [(each.branch, each.out) for each in record.branches] == [
        ("a", False),
        ("b", False),
        ("c", True),
    ]
    assert list(record.tips) == ["a"]


def test_a_branch_a_change_lets_in_comes_back_as_nobody_took_it_out(
    world: World,
) -> None:
    conflicting(world)
    asyncio.run(world.trying.changed(world.repository, [], ["a"], {}))
    record = world.record()
    assert [(each.branch, each.out) for each in record.branches] == [
        ("a", True),
        ("b", False),
    ]
    assert list(record.tips) == ["b"]


def test_a_change_sets_a_box_back_and_refuses_what_conflicts_moving_nothing(
    world: World,
) -> None:
    conflicting(world)
    trying = world.trying
    before = world.record()
    with pytest.raises(HostError, match="can't be picked together"):
        asyncio.run(trying.changed(world.repository, ["b"], [], {}))
    assert world.record() == before
    # Taking out what it conflicts with in the same change, it runs.
    asyncio.run(trying.changed(world.repository, ["b"], ["a"], {}))
    assert list(world.record().tips) == ["b"]


def test_a_change_is_refused_where_a_branch_landed_again_since_it_was_seen(
    world: World,
) -> None:
    conflicting(world)
    trying = world.trying
    with pytest.raises(HostError, match="landed again since you marked it"):
        asyncio.run(trying.changed(world.repository, [], ["a"], {"a": "an-older-tip"}))
    assert list(world.record().tips) == ["a"]


def test_a_change_to_a_branch_off_trial_says_so_and_does_the_rest(world: World) -> None:
    conflicting(world)
    trying = world.trying
    said = asyncio.run(trying.changed(world.repository, ["gone"], [], {}))
    assert said.said == "`gone` isn't on trial any more."
    both = asyncio.run(trying.changed(world.repository, ["gone"], ["a"], {}))
    assert "`gone` isn't on trial any more." in both.said
    assert [each.branch for each in world.record().branches if each.out] == ["a"]


def test_a_pick_is_refused_where_dev_or_a_branch_moved_since_it_was_seen(
    world: World,
) -> None:
    conflicting(world)
    trying = world.trying
    with pytest.raises(HostError, match="landed again since you marked it"):
        asyncio.run(trying.picked(world.repository, ["a"], seen={"a": "an-older-tip"}))
    with pytest.raises(HostError, match="moved since you marked it"):
        asyncio.run(trying.picked(world.repository, ["a"], dev="an-older-dev"))


class Tools(AcceptingTools):
    """What stands in for a session's room as a branch is accepted: what the gate says, as the host's would, a word of its own for each, and when it may go on."""

    def __init__(
        self,
        world: World,
        said: str = "Landed it.",
        *,
        ready: bool = True,
    ) -> None:
        self.world = world
        self.said = said
        self.is_ready = ready
        self.asked: list[str] = []
        self.gate = asyncio.Event()

    @override
    def ready(self, repository: Path, on: OnTrial) -> None:
        if not self.is_ready:
            raise HostError(no_room(on.branch))

    @override
    async def accepted(self, repository: Path, on: OnTrial) -> str:
        self.asked.append(on.branch)
        await self.gate.wait()
        if self.said == "Landed it.":
            self.world.merged_onto_dev(on.branch)
        return self.said


def accepting(
    world: World, tools: Tools, changes: Changes | None = None
) -> TrialAccepting:
    return TrialAccepting(
        trying=world.trying, tools=tools, changes=changes or Changes()
    )


def asked_apart(world: World, branch: str) -> AcceptBranch:
    return AcceptBranch(branch=branch, apart=True, repository=world.repository)


def test_a_merge_apart_answers_at_once_saying_so_on_its_line_and_what_came_of_it_after(
    world: World,
) -> None:
    conflicting(world)
    tools = Tools(world)
    changes = Changes()
    handler = accepting(world, tools, changes)
    trying = world.trying
    request = asked_apart(world, "a")

    async def exercised() -> None:
        said = await handler.answer(request)
        assert isinstance(said, TrialSaid)
        assert "`a` is merging" in said.said
        listed = trying.listed(world.repository)
        assert listed is not None
        assert [each.merging for each in listed.branches if each.branch == "a"] == [
            True
        ]
        tools.gate.set()
        await asyncio.gather(*trying.merges.of(world.repository).tasks)

    asyncio.run(exercised())
    listed = trying.listed(world.repository)
    assert listed is not None
    assert "a" not in [each.branch for each in listed.branches]
    assert [each.splitlines()[0] for each in listed.merged] == ["Landed it."]
    assert changes.touches.get(TrialMoved(repository=world.repository)) == changes.count


def test_a_merge_the_gate_stops_stays_on_trial_saying_why_as_the_host_says_it_in_words(
    world: World,
) -> None:
    conflicting(world)
    tools = Tools(world, said="Not landed: the gate failed on the merge.")
    handler = accepting(world, tools)
    trying = world.trying
    request = asked_apart(world, "a")

    async def exercised() -> None:
        await handler.answer(request)
        tools.gate.set()
        await asyncio.gather(*trying.merges.of(world.repository).tasks)

    asyncio.run(exercised())
    listed = trying.listed(world.repository)
    assert listed is not None
    [a] = [each for each in listed.branches if each.branch == "a"]
    assert not a.merging
    assert a.merge_said == "Not landed: the gate failed on the merge."
    assert listed.merged == []


def test_a_merge_with_no_room_or_landed_again_is_refused_as_it_s_asked(
    world: World,
) -> None:
    conflicting(world)
    handler = accepting(world, Tools(world, ready=False))
    request = asked_apart(world, "a")
    with pytest.raises(HostError, match="no session of this repository is running"):
        asyncio.run(handler.answer(request))
    assert world.trying.merges.of(world.repository).underway == []
    ready = accepting(world, Tools(world))
    seen = request.model_copy(update={"tip": "an-older-tip"})
    with pytest.raises(HostError, match="landed again since you marked it"):
        asyncio.run(ready.answer(seen))


def test_what_moves_the_host_waits_while_a_merge_runs(world: World) -> None:
    conflicting(world)
    tools = Tools(world)
    handler = accepting(world, tools)
    trying = world.trying
    request = asked_apart(world, "a")

    async def exercised() -> None:
        await handler.answer(request)
        with pytest.raises(HostError, match="moving the host now would stop it"):
            await trying.changed(world.repository, [], ["b"], {})
        with pytest.raises(HostError, match="moving the host now would stop it"):
            await trying.picked(world.repository, [])
        with pytest.raises(HostError, match="merging already"):
            await handler.answer(request)
        tools.gate.set()
        await asyncio.gather(*trying.merges.of(world.repository).tasks)

    asyncio.run(exercised())


def test_merges_go_one_at_a_time_each_checked_as_its_turn_comes(world: World) -> None:
    a = world.branched("a", {"a.txt": "a\n"})
    b = world.branched("b", {"b.txt": "b\n"})
    world.on_trial(("a", a), ("b", b))
    tools = Tools(world)
    handler = accepting(world, tools)
    trying = world.trying

    async def exercised() -> None:
        for each in ["a", "b"]:
            await handler.answer(asked_apart(world, each))
        await settled_loop()
        # The first is at its gate, and the second hasn't started on what would be stale.
        assert tools.asked == ["a"]
        # It lands again as it waits: its turn finds that, and doesn't merge what was seen.
        again = world.record()
        moved = again.model_copy(
            update={
                "branches": [
                    each.model_copy(update={"tip": "landed-again"})
                    if each.branch == "b"
                    else each
                    for each in again.branches
                ]
            }
        )
        Trials.of(world.machine, world.repository).write(moved)
        tools.gate.set()
        await asyncio.gather(*trying.merges.of(world.repository).tasks)

    asyncio.run(exercised())
    assert tools.asked == ["a"]
    listed = trying.listed(world.repository)
    assert listed is not None
    [b_listed] = [each for each in listed.branches if each.branch == "b"]
    assert "landed again" in b_listed.merge_said


async def settled_loop() -> None:
    """Let every task the loop has ready run until none is left ready."""
    for _ in range(20):
        await asyncio.sleep(0)


def test_a_project_s_view_isn_t_told_of_lup_s_own_switches(
    world: World,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    declared_branches(machine, world.repository, Branches(running="live"))
    write_model(
        machine.host.switched,
        LastSwitch(
            commit="c", at=datetime(2026, 11, 7, tzinfo=UTC), said="x", answered=False
        ),
    )
    listed = world.trying.listed(world.repository)
    assert listed is not None
    assert listed.last is None


class Lists(RepositoryAsking):
    """A repository's process that says what it serves, keeping whom it was asked of, or refusing."""

    def __init__(self, refusing: str | None = None) -> None:
        self.asked_of: list[Path] = []
        self.refusing = refusing

    @override
    async def asked(self, repository: Path, request: Request) -> Reply:
        assert isinstance(request, Listing)
        self.asked_of.append(repository)
        if self.refusing is not None:
            raise HostError(self.refusing)
        return Offered()

    @override
    def watching(self, repository: Path) -> AbstractAsyncContextManager[None]:
        raise AssertionError(repository)

    @override
    def looks(self) -> dict[Path, Looks]:
        return {}


def keeps_a_copy(machine: Layout, repository: Path) -> None:
    """Keep a copy of the repository's running, as lup's own repository's is."""
    copies = Copies(layout=machine.judge(repository))
    kept = Kept(name="copy", repository=repository, approval=approval_of("c", "z"))
    copies.place(kept).bin.mkdir(parents=True)
    copies.recorded(kept)
    copies.switch(copies.place(kept))
    linked(machine.host_copies, copies.layout.home)


def said_as_it_starts(machine: Layout, process: Lists, changes: Changes) -> list[str]:
    """Run what has lup's own repository say how its views look, as the service starts, and return what it said."""
    said: list[str] = []
    companion = OwnViewsSaid(
        layout=machine, asking=process, changes=changes, say=said.append
    )

    async def exercised() -> None:
        await companion.begin()
        if companion.saying is not None:
            await companion.saying
        await companion.end()

    asyncio.run(exercised())
    return said


def test_lup_s_own_repository_says_its_views_as_the_service_starts_where_it_has_a_row(
    world: World,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    keeps_a_copy(machine, world.repository)
    declared_branches(machine, world.repository, Branches(running="live"))
    process = Lists()
    changes = Changes()
    assert said_as_it_starts(machine, process, changes) == []
    assert process.asked_of == [world.repository]
    assert changes.count == 1


def test_lup_s_own_repository_starts_no_process_where_it_computes_no_running_branch(
    world: World,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    keeps_a_copy(machine, world.repository)
    declared_branches(machine, world.repository, Branches())
    process = Lists()
    assert said_as_it_starts(machine, process, Changes()) == []
    assert process.asked_of == []


def test_a_process_that_doesn_t_start_is_said_and_stops_nothing(
    world: World,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    keeps_a_copy(machine, world.repository)
    declared_branches(machine, world.repository, Branches(running="live"))
    changes = Changes()
    said = said_as_it_starts(machine, Lists("it wouldn't start"), changes)
    assert said == [
        f"{world.repository}: how its views look isn't known yet: it wouldn't start"
    ]
    assert changes.count == 0


def test_a_project_running_its_integration_branch_has_nothing_on_trial(
    world: World,
    machine: Layout,
    declared_branches: Callable[[Layout, Path, Branches], None],
) -> None:
    declared_branches(machine, world.repository, Branches())
    assert trial_listed(machine, world.repository, []) is None
    with pytest.raises(HostError, match="with nothing on trial"):
        world.picked()


def test_live_s_message_says_what_it_holds() -> None:
    said = message_of("dev", "d1", {"a": "t1"})
    assert said == "live: `dev` with `a`\n\ndev: d1\na: t1"


def test_a_listing_says_where_each_branch_stands_and_what_to_type() -> None:
    listed = TrialListed(
        integration="dev",
        running="live",
        branches=[
            BranchListed(branch="a", tip="t1", landed=AT, within=True, built=True),
            BranchListed(branch="b", tip="t2", landed=AT, conflict="it conflicts"),
            BranchListed(branch="c", tip="t3", landed=AT, out=True),
        ],
    )
    said = "\n".join(cli.trial_lines(listed))
    assert "`live`: `dev` with `a`." in said
    assert "- `a` at t1: in `live`, its copy built." in said
    assert "- `b` at t2: it conflicts." in said
    assert "- `c` at t3: out: you took it out." in said
    assert "lup-dev live pick" in said
    assert cli.trial_lines(None) == [
        "This repository computes no running branch, so nothing is on trial."
    ]


def test_the_operator_s_commands_are_refused_in_an_agent_s_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    with pytest.raises(HostError, match=r"inside a .* session"):
        cli.live_client()
