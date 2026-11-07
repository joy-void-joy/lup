"""`Versions` in the review: what its view says of what runs, and what each of its actions asks of the host, through the repository's modules as its process serves them, over a host that answers as the test says."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

import pytest

from lup.blocks import Blocks, Line, Offer
from lup_dev import Core, Modules, Project, Versions
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.serving import OperatorHost
from lup_dev.host.on_trial import (
    AcceptBranch,
    BranchListed,
    CopySwitching,
    DropBranch,
    LastSwitch,
    ListTrial,
    PickBranches,
    SwitchCopy,
    TrialListed,
    TrialSaid,
    VersionListed,
)
from lup_dev.host.protocol import (
    Activity,
    HostError,
    Limits,
    Listed,
    ListLaunches,
    Register,
    Reply,
    Request,
    Talker,
)
from lup_dev.host.workers import Acted, Acting, ActionAnswer, Viewing
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.marks import MarkStore, StoredMarks
from lup_dev.inbox.protocol import Exchanged
from lup_dev.layout import Layout
from lup_dev.worker import RepositoryModules
from lup_ledger.parties import Conversation

if TYPE_CHECKING:
    from pydantic import JsonValue

REPOSITORY = Path("/r.git")
AT = datetime(2026, 11, 7, 12, tzinfo=UTC)
DEV = "d38dbd2c0ffee"
LANDER = Conversation(repository=REPOSITORY, runtime="claude", session="s1", agent="a1")


def branch(
    name: str,
    *,
    within: bool = False,
    out: bool = False,
    conflict: str = "",
    party: Conversation | None = LANDER,
) -> BranchListed:
    return BranchListed(
        branch=name,
        tip=f"{name}-tip",
        landed=AT,
        within=within,
        out=out,
        conflict=conflict,
        party=party,
    )


def version(
    commit: str,
    *names: str,
    copy_kept: str | None = None,
    running: bool = False,
    ran: datetime | None = None,
) -> VersionListed:
    return VersionListed(
        commit=commit,
        dev=DEV,
        tips={each: f"{each}-tip" for each in names},
        at=AT,
        copy_kept=copy_kept,
        running=running,
        ran=ran,
    )


def trial(
    branches: list[BranchListed],
    versions: list[VersionListed] | None = None,
    **fields: JsonValue,
) -> TrialListed:
    return TrialListed.model_validate(
        {
            "integration": "dev",
            "running": "live",
            "dev": DEV,
            "live": "c1",
            "branches": branches,
            "versions": versions or [],
            "runs": "c1",
            **fields,
        }
    )


SKETCH = trial(
    [
        branch("fix-a", within=True),
        branch("fix-b", within=True),
        branch("rival", conflict="it conflicts with `fix-b`, in `a.py`"),
        branch("later", out=True),
    ],
    [
        version("c3", "fix-a", copy_kept="c3", ran=AT),
        version("c2", "fix-b"),
        version("c1", "fix-a", "fix-b", copy_kept="c1", running=True, ran=AT),
    ],
)
"""What the view's design was sketched as: two branches running, a rival, one taken out, and three versions, one kept and run, one with no copy, one running."""


def register() -> Register:
    return Register(
        launch="l1",
        runtime="claude",
        worktree=Path("/w"),
        repository=REPOSITORY,
        judge=Path("/judge"),
        limits=Limits(actions=[], protected=[]),
        github=None,
    )


AT_WORK = Listed(
    launches=[register()],
    talkers={"l1": [Talker(path="dev/parser", own="parser", session="s1", agent="a1")]},
)
"""A session of the repository running, with who landed the branches at work."""


class Host(OperatorHost):
    """What stands in for the host service: answers what the module asks with what the test sets, keeping what it's asked."""

    def __init__(
        self, listed: TrialListed | None = SKETCH, launches: Listed = AT_WORK
    ) -> None:
        self.listed = listed
        self.launches = launches
        self.sent: list[Request] = []
        self.refusing: str | None = None

    @override
    async def asked[R: Reply](self, request: Request, reply: type[R]) -> R:
        self.sent.append(request)
        if self.refusing is not None:
            raise HostError(self.refusing)
        match request:
            case ListTrial():
                answer: Reply = TrialSaid(listed=self.listed)
            case ListLaunches():
                answer = self.launches
            case SwitchCopy(commit=commit):
                answer = CopySwitching(commit=commit, log=Path("/log"))
            case _:
                answer = TrialSaid(said=f"did {request.kind}")
        return cast("R", answer)

    def changing(self) -> list[Request]:
        """Return what it was asked beyond reading."""
        return [
            each for each in self.sent if not isinstance(each, ListTrial | ListLaunches)
        ]


class Unexchanged(Exchanges):
    """No conversation exchanged anything: `Versions` reads none."""

    @override
    async def exchanged(self, viewed: object) -> Exchanged:
        return Exchanged(sent=[], received=[])


def modules(host: Host, tmp_path: Path) -> RepositoryModules:
    layout = Layout(state=tmp_path, data=tmp_path)
    return RepositoryModules(
        repository=REPOSITORY,
        resolved=resolve(
            Project(modules=Modules.only(Core(), Versions(running="live")))
        ),
        recorded={},
        layout=layout,
        exchanges=Unexchanged(),
        marks=StoredMarks(store=MarkStore.kept_in(layout)),
        host=host,
    )


def seen(host: Host, tmp_path: Path) -> Blocks:
    viewing = Viewing(
        repository=REPOSITORY, module="versions", view="what_runs", argument={}
    )
    return asyncio.run(modules(host, tmp_path).view(viewing)).blocks


def line(blocks: Blocks, id_: str) -> Line:
    found = next(each for each in blocks.blocks if each.id == id_)
    assert isinstance(found, Line)
    return found


def offered(blocks: Blocks, id_: str, verb: str) -> Offer:
    return next(each for each in line(blocks, id_).offers if each.verb == verb)


def acted(host: Host, tmp_path: Path, action: str, *arguments: JsonValue) -> Acted:
    asked = Acting(
        repository=REPOSITORY,
        module="versions",
        action=action,
        arguments=list(arguments),
    )
    return asyncio.run(modules(host, tmp_path).act(asked))


def test_a_repository_without_versions_places_no_row_and_one_with_it_does() -> None:
    without = resolve(Project(modules=Modules.only(Core())))
    assert all(each.place.under == "agent" for each in without.looks.drawers)
    assert "run" not in [each.name for each in without.looks.verbs]
    selected = resolve(Project(modules=Modules.only(Core(), Versions(running="live"))))
    [row] = [
        each for each in selected.looks.drawers if each.place.under == "repository"
    ]
    assert (row.module, row.view, row.place.called) == (
        "versions",
        "what_runs",
        "what runs",
    )
    assert "run" in [each.name for each in selected.looks.verbs]


def test_the_view_says_what_runs_as_the_sketch_has_it(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    assert blocks.text().splitlines() == [
        "what runs · dev + fix-a fix-b",
        "[x] fix-a  on trial",
        "[x] fix-b  on trial",
        "[ ] rival  conflicts with `fix-b`, in `a.py`",
        "[ ] later  out, by you · needs your yes, then minutes to build",
        "",
        "Ctrl+Enter runs what's marked: a set you've run moves the host in seconds, restarting it; one you haven't needs your yes, then minutes to build.",
        "",
        "versions",
        " *  dev d38dbd2 + fix-a fix-b  running",
        "    dev d38dbd2 + fix-b        no copy kept · needs your yes, then minutes to build",
        "    dev d38dbd2 + fix-a        ran",
    ]


def test_the_row_counts_what_conflicts_as_flagged_for_the_operator(
    tmp_path: Path,
) -> None:
    blocks = seen(Host(), tmp_path)
    assert (blocks.tally.holds, blocks.tally.flagged, blocks.tally.review) == (0, 1, 0)


def test_a_box_says_what_ticking_it_takes_before_it_s_pressed(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    # Out of what runs leaves `fix-a` alone: a kept copy holds that.
    assert (
        offered(blocks, "branch fix-b", "run").says
        == "take it out: moves the host in seconds"
    )
    # Leaves `fix-b` alone: no copy holds that, and it's run as a version with none.
    assert (
        offered(blocks, "branch fix-a", "run").says
        == "take it out: needs your yes, then minutes to build"
    )
    assert (
        offered(blocks, "branch later", "run").says
        == "put it in: needs your yes, then minutes to build"
    )
    assert (
        "refused while what it conflicts with"
        in offered(blocks, "branch rival", "run").says
    )


def test_each_box_offers_what_the_operator_may_do_with_it(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    assert [each.verb for each in line(blocks, "branch fix-a").offers] == [
        "run",
        "done",
        "decline",
    ]
    tick = offered(blocks, "branch fix-a", "run")
    assert tick.action == Acting.named()
    assert tick.argument["action"] == "pick"
    assert tick.argument["argument"] == {"branch": "fix-a", "on": False}
    assert offered(blocks, "branch later", "run").argument["argument"] == {
        "branch": "later",
        "on": True,
    }


def test_a_comment_on_a_branch_reaches_who_landed_it(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    by = line(blocks, "branch fix-a").by
    assert by is not None
    assert (by.runtime, by.session, by.agent) == ("claude", "s1", "a1")


def test_a_branch_whose_lander_ended_says_where_a_comment_waits(tmp_path: Path) -> None:
    ended = Listed(
        launches=[register()],
        talkers={
            "l1": [
                Talker(
                    path="dev/parser",
                    own="parser",
                    session="s1",
                    agent="a1",
                    activity=Activity(state="ended", since=AT),
                )
            ]
        },
    )
    said = line(seen(Host(launches=ended), tmp_path), "branch fix-a").said()
    assert "dev/parser has ended: a comment waits for their session" in said
    gone = Listed(launches=[register()])
    said = line(seen(Host(launches=gone), tmp_path), "branch fix-a").said()
    assert "a1 has ended: a comment waits for their session" in said


def test_a_branch_nobody_is_known_to_have_landed_takes_no_comment(
    tmp_path: Path,
) -> None:
    listed = trial([branch("old", within=True, party=None)])
    assert line(seen(Host(listed), tmp_path), "branch old").by is None


def test_with_no_session_running_it_says_merging_needs_one(tmp_path: Path) -> None:
    host = Host(launches=Listed(launches=[]))
    blocks = seen(host, tmp_path)
    assert "no session of this repository is running: start one first" in blocks.text()
    assert (
        "refused until a session of this repository runs"
        in offered(blocks, "branch fix-a", "done").says
    )
    running = seen(Host(), tmp_path)
    assert "no session of this repository" not in running.text()
    assert offered(running, "branch fix-a", "done").says == "merge it onto dev"


def test_a_session_of_another_repository_is_no_room_to_merge_in(tmp_path: Path) -> None:
    elsewhere = register().model_copy(update={"repository": Path("/other.git")})
    blocks = seen(Host(launches=Listed(launches=[elsewhere])), tmp_path)
    assert "no session of this repository is running" in blocks.text()


def test_a_version_offers_running_it_again_only_where_a_copy_is_kept(
    tmp_path: Path,
) -> None:
    blocks = seen(Host(), tmp_path)
    assert offered(blocks, "version c3", "run").argument["argument"] == {
        "commit": "c3",
        "current": True,
        "branches": ["fix-a"],
    }
    assert [each.verb for each in line(blocks, "version c1").offers] == ["done"]
    assert [each.verb for each in line(blocks, "version c2").offers] == ["done"]
    assert (
        offered(blocks, "version c1", "done").says
        == "merge it: each of its branches onto dev"
    )
    assert offered(blocks, "version c1", "done").argument["argument"] == {
        "branches": ["fix-a", "fix-b"],
        "tips": ["fix-a-tip", "fix-b-tip"],
    }


def test_a_version_of_nothing_but_dev_has_nothing_to_merge(tmp_path: Path) -> None:
    listed = trial([], [version("c0", copy_kept="c0", running=True, ran=AT)])
    assert line(seen(Host(listed), tmp_path), "version c0").offers == []


def test_a_running_version_ticks_since_its_copy_answered(tmp_path: Path) -> None:
    status = line(seen(Host(), tmp_path), "version c1").spans[-1]
    assert status.ticking is not None
    assert status.ticking.since == AT
    assert status.ticking.said == "running {}"


def test_a_set_picked_that_waits_on_the_operator_s_yes_says_so_on_the_summary(
    tmp_path: Path,
) -> None:
    listed = trial(
        [branch("fix-a", within=True)],
        [version("c1", copy_kept="c1", running=True, ran=AT), version("c2", "fix-a")],
        live="c2",
    )
    assert seen(Host(listed), tmp_path).text().splitlines()[0] == (
        "what runs · dev · dev + fix-a waits on your yes"
    )


def test_a_switch_that_fell_back_says_why(tmp_path: Path) -> None:
    last = LastSwitch(
        commit="c9abcdefgh", at=AT, said="it didn't start", answered=False
    )
    blocks = seen(Host(SKETCH.model_copy(update={"last": last})), tmp_path)
    assert (
        line(blocks, "fell back").said()
        == "The last switch, to c9abcde, didn't answer: it didn't start"
    )
    answered = last.model_copy(update={"answered": True})
    blocks = seen(Host(SKETCH.model_copy(update={"last": answered})), tmp_path)
    assert "fell back" not in [each.id for each in blocks.blocks]


def test_what_can_t_be_read_is_said_in_the_view_rather_than_failing_it(
    tmp_path: Path,
) -> None:
    host = Host()
    host.refusing = "the host runs a copy from before"
    blocks = seen(host, tmp_path)
    assert blocks.text().splitlines() == [
        "what runs · can't be read",
        "What's on trial can't be read: the host runs a copy from before",
    ]


def test_ticking_makes_one_pick_of_what_runs_and_every_box_marked(
    tmp_path: Path,
) -> None:
    host = Host()
    answer = acted(
        host,
        tmp_path,
        "pick",
        {"branch": "fix-a", "on": False},
        {"branch": "later", "on": True},
    )
    assert host.changing() == [
        PickBranches(branches=["fix-b", "later"], repository=REPOSITORY)
    ]
    assert answer.answers == [
        ActionAnswer(said="did trial-pick"),
        ActionAnswer(said="did trial-pick"),
    ]


def test_a_box_sent_again_picks_the_same_set(tmp_path: Path) -> None:
    host = Host()
    acted(host, tmp_path, "pick", {"branch": "fix-a", "on": True})
    assert host.changing() == [
        PickBranches(branches=["fix-a", "fix-b"], repository=REPOSITORY)
    ]


def test_a_refused_pick_refuses_every_box_of_it_in_the_host_s_words(
    tmp_path: Path,
) -> None:
    host = Host()

    async def refused(request: Request, reply: type[Reply]) -> Reply:
        if isinstance(request, PickBranches):
            message = "`fix-b` and `rival` can't be picked together"
            raise HostError(message)
        return await Host.asked(host, request, reply)

    host.asked = refused  # type: ignore[method-assign]
    answer = acted(
        host,
        tmp_path,
        "pick",
        {"branch": "rival", "on": True},
        {"branch": "later", "on": True},
    )
    assert [each.refused for each in answer.answers] == [
        "`fix-b` and `rival` can't be picked together"
    ] * 2


def test_merging_accepts_each_branch_in_turn_as_the_host_s_own_request(
    tmp_path: Path,
) -> None:
    host = Host()
    answer = acted(
        host,
        tmp_path,
        "merge",
        {"branches": ["fix-a", "fix-b"], "tips": ["fix-a-tip", "fix-b-tip"]},
    )
    assert host.changing() == [
        AcceptBranch(branch="fix-a", repository=REPOSITORY),
        AcceptBranch(branch="fix-b", repository=REPOSITORY),
    ]
    assert answer.answers == [ActionAnswer(said="did trial-accept\ndid trial-accept")]


def test_a_branch_landed_again_since_it_was_marked_isn_t_merged_or_dropped(
    tmp_path: Path,
) -> None:
    host = Host()
    merged = acted(
        host, tmp_path, "merge", {"branches": ["fix-a"], "tips": ["an-older-tip"]}
    )
    dropped = acted(host, tmp_path, "drop", {"branch": "fix-a", "tip": "an-older-tip"})
    assert (
        merged.answers[0].refused
        == "fix-a landed again since you marked it: look at it again"
    )
    assert (
        dropped.answers[0].refused
        == "fix-a landed again since you marked it: look at it again"
    )
    assert host.changing() == []


def test_dropping_is_the_host_s_own_request(tmp_path: Path) -> None:
    host = Host()
    answer = acted(host, tmp_path, "drop", {"branch": "fix-a", "tip": "fix-a-tip"})
    assert host.changing() == [DropBranch(branch="fix-a", repository=REPOSITORY)]
    assert answer.answers == [ActionAnswer(said="did trial-drop")]


def test_a_version_on_dev_as_it_stands_runs_again_by_being_picked(
    tmp_path: Path,
) -> None:
    host = Host()
    answer = acted(
        host,
        tmp_path,
        "run_again",
        {"commit": "c3", "current": True, "branches": ["fix-a"]},
    )
    assert host.changing() == [PickBranches(branches=["fix-a"], repository=REPOSITORY)]
    assert answer.answers == [ActionAnswer(said="did trial-pick")]


def test_an_older_version_runs_again_by_the_host_s_own_switch_to_its_copy(
    tmp_path: Path,
) -> None:
    older = version("c0", "fix-a", copy_kept="c0", ran=AT).model_copy(
        update={"dev": "an0ther0dev"}
    )
    moved = version("c8", "fix-b", copy_kept="c8", ran=AT).model_copy(
        update={"tips": {"fix-b": "an-older-tip"}}
    )
    listed = trial([branch("fix-a", within=True), branch("fix-b")], [older, moved])
    blocks = seen(Host(listed), tmp_path)
    assert offered(blocks, "version c0", "run").argument["argument"] == {
        "commit": "c0",
        "current": False,
        "branches": ["fix-a"],
    }
    assert offered(blocks, "version c8", "run").argument["argument"] == {
        "commit": "c8",
        "current": False,
        "branches": ["fix-b"],
    }
    host = Host()
    answer = acted(host, tmp_path, "run_again", {"commit": "c0"})
    assert host.changing() == [SwitchCopy(commit="c0")]
    assert answer.answers == [
        ActionAnswer(said="The host moves to c0, in a few seconds.")
    ]


def test_a_version_gone_back_to_says_what_the_running_branch_still_holds(
    tmp_path: Path,
) -> None:
    listed = trial(
        [branch("fix-a", within=True)],
        [
            version("c1", copy_kept="c1", running=True, ran=AT),
            version("c2", "fix-a", copy_kept="c2"),
        ],
        live="c2",
    )
    assert seen(Host(listed), tmp_path).text().splitlines()[0] == (
        "what runs · dev · live holds dev + fix-a"
    )


def test_an_action_on_a_repository_computing_no_running_branch_is_refused(
    tmp_path: Path,
) -> None:
    host = Host(None)
    answer = acted(host, tmp_path, "pick", {"branch": "fix-a", "on": True})
    assert answer.answers[0].refused == f"{REPOSITORY} computes no running branch"


@pytest.mark.parametrize("action", ["pick", "merge", "drop", "run_again"])
def test_each_action_is_the_operator_s_and_answers_a_verb_declared(
    action: str, tmp_path: Path
) -> None:
    resolved = modules(Host(), tmp_path).resolved
    owner = next(each for each in resolved.served if each.module.name == "versions")
    assert modules(Host(), tmp_path).acting("versions", action) == owner
