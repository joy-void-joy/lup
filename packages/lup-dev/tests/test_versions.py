"""`Versions` in the review: what its view says of what runs, and what each of its actions asks of the host, through the repository's modules as its process serves them, over a host that answers as the test says."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

import pytest

from lup.blocks import Block, Blocks, Fold, Line, Offer
from lup.doors import served
from lup_dev import Core, Modules, Project, Versions
from lup_dev.declaration.modules.versions import RunningAgain
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.serving import Operator, OperatorHost, Room, ask
from lup_dev.errors import LupDevError
from lup_dev.host.on_trial import (
    AcceptBranch,
    BranchListed,
    ChangeBranches,
    CopySwitching,
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
    merging: bool = False,
    merge_said: str = "",
) -> BranchListed:
    return BranchListed(
        branch=name,
        tip=f"{name}-tip",
        landed=AT,
        within=within,
        out=out,
        conflict=conflict,
        party=party,
        merging=merging,
        merge_said=merge_said,
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


def every(blocks: list[Block]) -> list[Block]:
    """Return `blocks`, and what's under each that folds any."""
    return [
        inner
        for each in blocks
        for inner in [
            each,
            *(
                every(each.content)
                if isinstance(each, Fold) and isinstance(each.content, list)
                else []
            ),
        ]
    ]


def line(blocks: Blocks, id_: str) -> Line:
    found = next(each for each in every(blocks.blocks) if each.id == id_)
    assert isinstance(found, Line)
    return found


def offered(blocks: Blocks, id_: str, verb: str) -> Offer:
    return next(each for each in line(blocks, id_).offers if each.verb == verb)


def verbs_on(blocks: Blocks, id_: str) -> list[str | None]:
    return [each.verb for each in line(blocks, id_).offers]


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
    assert "merge" not in [each.name for each in without.looks.verbs]
    selected = resolve(Project(modules=Modules.only(Core(), Versions(running="live"))))
    [row] = [
        each for each in selected.looks.drawers if each.place.under == "repository"
    ]
    assert (row.module, row.view, row.place.called) == (
        "versions",
        "what_runs",
        "what runs",
    )
    assert "merge" in [each.name for each in selected.looks.verbs]


def test_the_view_says_what_runs_as_the_sketch_has_it(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    assert blocks.text().splitlines() == [
        "what runs · dev + fix-a fix-b",
        "[x] fix-a  on trial",
        "[x] fix-b  on trial",
        "[ ] rival  conflicts with `fix-b`, in `a.py`",
        "▸ out · 1",
        "",
        "Ctrl+Enter runs what's marked: a set you've run moves the host in seconds, restarting it; one you haven't needs your yes, then minutes to build.",
        "",
        "versions",
        " *  dev d38dbd2 + fix-a fix-b  running",
        "    dev d38dbd2 + fix-b        no copy kept · needs your yes, then minutes to build",
        "    dev d38dbd2 + fix-a        ran",
    ]


def test_what_s_left_out_folds_under_one_line_its_box_still_taking_it_back(
    tmp_path: Path,
) -> None:
    blocks = seen(Host(), tmp_path)
    fold = next(each for each in blocks.blocks if each.id == "out")
    assert isinstance(fold, Fold)
    assert not fold.open
    assert line(blocks, "branch later").said().startswith("[ ] later")
    assert verbs_on(blocks, "branch later") == ["done", "merge"]


def test_the_row_counts_what_conflicts_nobody_left_out(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    assert (blocks.tally.holds, blocks.tally.flagged, blocks.tally.review) == (0, 1, 0)
    left = SKETCH.model_copy(
        update={
            "branches": [
                branch("rival", conflict="it conflicts with `a`", out=True),
            ]
        }
    )
    assert seen(Host(left), tmp_path).tally.flagged == 0


def test_each_key_on_a_box_says_what_it_takes_before_it_s_pressed(
    tmp_path: Path,
) -> None:
    no_rival = SKETCH.model_copy(
        update={
            "branches": [each for each in SKETCH.branches if each.branch != "rival"]
        }
    )
    blocks = seen(Host(no_rival), tmp_path)
    # What's left without `fix-b` is `fix-a`, with a copy; without `fix-a`, `fix-b`, with none.
    assert (
        offered(blocks, "branch fix-b", "decline").says
        == "leave it out: moves the host in seconds"
    )
    assert (
        offered(blocks, "branch fix-a", "decline").says
        == "leave it out: needs your yes, then minutes to build"
    )
    blocks = seen(Host(), tmp_path)
    # Never run, only its merge could say for sure.
    assert (
        offered(blocks, "branch later", "done").says
        == "take it in: never run: likely your yes, then minutes to build"
    )
    assert "refused while what it conflicts with" in (
        offered(blocks, "branch rival", "done").says
    )


def test_leaving_out_what_keeps_another_out_says_that_comes_in(tmp_path: Path) -> None:
    listed = trial(
        [
            branch("a", within=True),
            branch("b", conflict="it conflicts with `a`, in `x.py`"),
        ]
    )
    says = offered(seen(Host(listed), tmp_path), "branch a", "decline").says
    assert says.startswith("leave it out, and b comes in: ")


def test_d_means_yes_and_x_no_each_marking_nothing_on_a_box_that_way_already(
    tmp_path: Path,
) -> None:
    blocks = seen(Host(), tmp_path)
    assert verbs_on(blocks, "branch fix-a") == ["decline", "merge"]
    assert verbs_on(blocks, "branch later") == ["done", "merge"]
    leave = offered(blocks, "branch fix-a", "decline")
    assert leave.argument["action"] == "pick"
    assert leave.argument["argument"] == {
        "branch": "fix-a",
        "on": False,
        "tip": "fix-a-tip",
    }
    assert leave.draws == "[ ]"
    assert leave.runs == "last"
    take = offered(blocks, "branch later", "done")
    assert take.argument["argument"] == {
        "branch": "later",
        "on": True,
        "tip": "later-tip",
    }
    assert take.draws == "[x]"


def test_x_on_a_box_out_by_a_conflict_alone_stops_it_coming_back(
    tmp_path: Path,
) -> None:
    blocks = seen(Host(), tmp_path)
    assert verbs_on(blocks, "branch rival") == ["done", "decline", "merge"]
    assert offered(blocks, "branch rival", "decline").says == (
        "leave it out: it stops coming back by itself"
    )


def test_merging_offers_its_own_key_on_a_branch(tmp_path: Path) -> None:
    merge = offered(seen(Host(), tmp_path), "branch fix-a", "merge")
    assert merge.argument["action"] == "merge"
    assert merge.argument["argument"] == {
        "branches": ["fix-a"],
        "tips": ["fix-a-tip"],
    }
    assert merge.says == "merge it onto dev"


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


def test_a_branch_nobody_is_known_to_have_landed_says_so_and_takes_no_comment(
    tmp_path: Path,
) -> None:
    listed = trial([branch("old", within=True, party=None)])
    found = line(seen(Host(listed), tmp_path), "branch old")
    assert found.by is None
    assert "who landed it isn't known: a comment has nobody to reach" in found.said()
    assert "has ended" not in found.said()


def test_with_no_session_running_it_says_merging_needs_one(tmp_path: Path) -> None:
    host = Host(launches=Listed(launches=[]))
    blocks = seen(host, tmp_path)
    assert "no session of this repository is running: start one first" in blocks.text()
    assert (
        "refused until a session of this repository runs"
        in offered(blocks, "branch fix-a", "merge").says
    )
    running = seen(Host(), tmp_path)
    assert "no session of this repository" not in running.text()


def test_a_session_of_another_repository_is_no_room_to_merge_in(tmp_path: Path) -> None:
    elsewhere = register().model_copy(update={"repository": Path("/other.git")})
    blocks = seen(Host(launches=Listed(launches=[elsewhere])), tmp_path)
    assert "no session of this repository is running" in blocks.text()


def test_a_branch_merging_says_so_and_offers_nothing_more(tmp_path: Path) -> None:
    listed = trial([branch("a", within=True, merging=True)])
    found = line(seen(Host(listed), tmp_path), "branch a")
    assert "merging: its gate runs in a session's room" in found.said()
    assert found.offers == []


def test_what_stopped_a_merge_is_said_on_its_line_and_whole_under_it(
    tmp_path: Path,
) -> None:
    words = "Not landed: the gate failed\nFAILED tests/test_a.py\n1 failed"
    listed = trial([branch("a", within=True, merge_said=words)])
    blocks = seen(Host(listed), tmp_path)
    found = line(blocks, "branch a")
    assert "Not landed: the gate failed" in found.said()
    assert "FAILED" not in found.said()
    # It can be tried again from there.
    assert "merge" in verbs_on(blocks, "branch a")
    assert line(blocks, "said a 1").said() == "FAILED tests/test_a.py"


def test_a_merge_that_failed_shows_though_the_branch_is_out(tmp_path: Path) -> None:
    listed = trial([branch("a", out=True, merge_said="Not landed: no")])
    blocks = seen(Host(listed), tmp_path)
    assert "Not landed: no" in blocks.text()
    assert "out" not in [each.id for each in blocks.blocks]


def test_what_a_room_wrote_is_kept_to_one_printable_line(tmp_path: Path) -> None:
    listed = trial(
        [branch("a", conflict="it conflicts with `b`, in `x\x1b[31m\ny.py`")]
    )
    found = line(seen(Host(listed), tmp_path), "branch a").said()
    assert "\x1b" not in found
    assert "\n" not in found


def test_what_the_last_merges_said_shows_once_their_branches_are_gone(
    tmp_path: Path,
) -> None:
    listed = trial([], merged=["Landed fix-a on `dev`.\nCleaned up its worktree."])
    text = seen(Host(listed), tmp_path).text()
    assert "Landed fix-a on `dev`." in text
    assert "Cleaned up" not in text


def test_y_on_a_version_runs_it_again_only_where_a_copy_is_kept(tmp_path: Path) -> None:
    blocks = seen(Host(), tmp_path)
    run = offered(blocks, "version c3", "done")
    assert run.argument["argument"] == {
        "commit": "c3",
        "current": True,
        "branches": ["fix-a"],
        "tips": ["fix-a-tip"],
        "dev": DEV,
    }
    assert run.draws == " *  "
    assert run.runs == "last"
    assert verbs_on(blocks, "version c1") == ["merge"]
    assert verbs_on(blocks, "version c2") == ["merge"]
    assert offered(blocks, "version c1", "merge").says == (
        "merge it: each of its branches onto dev"
    )
    assert offered(blocks, "version c1", "merge").argument["argument"] == {
        "branches": ["fix-a", "fix-b"],
        "tips": ["fix-a-tip", "fix-b-tip"],
    }


def test_a_version_offers_no_merge_that_couldn_t_succeed(tmp_path: Path) -> None:
    old = version("c0", "gone", copy_kept="c0", ran=AT)
    moved = version("c8", "fix-a", copy_kept="c8", ran=AT).model_copy(
        update={"tips": {"fix-a": "an-older-tip"}}
    )
    merging = version("c9", "busy", copy_kept="c9", ran=AT)
    listed = trial(
        [branch("fix-a", within=True), branch("busy", within=True, merging=True)],
        [old, moved, merging],
    )
    blocks = seen(Host(listed), tmp_path)
    for each in ["version c0", "version c8", "version c9"]:
        assert "merge" not in verbs_on(blocks, each)


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


def test_every_box_of_a_send_is_one_change_of_those_alone(tmp_path: Path) -> None:
    host = Host()
    answer = acted(
        host,
        tmp_path,
        "pick",
        {"branch": "fix-a", "on": False, "tip": "fix-a-tip"},
        {"branch": "later", "on": True, "tip": "later-tip"},
    )
    assert host.sent == [
        ChangeBranches(
            taking=["later"],
            leaving=["fix-a"],
            seen={"fix-a": "fix-a-tip", "later": "later-tip"},
            repository=REPOSITORY,
        )
    ]
    assert answer.answers == [
        ActionAnswer(said="did trial-change"),
        ActionAnswer(said="did trial-change"),
    ]


class Refusing(Host):
    """A host refusing every request of `kind`, in `words`, reading all else."""

    def __init__(self, kind: type[Request], words: str) -> None:
        super().__init__()
        self.kind = kind
        self.words = words

    @override
    async def asked[R: Reply](self, request: Request, reply: type[R]) -> R:
        if isinstance(request, self.kind):
            self.sent.append(request)
            raise HostError(self.words)
        return await super().asked(request, reply)


def test_a_refused_change_refuses_every_box_of_it_in_the_host_s_words(
    tmp_path: Path,
) -> None:
    words = "`fix-b` and `rival` can't be picked together"
    answer = acted(
        Refusing(ChangeBranches, words),
        tmp_path,
        "pick",
        {"branch": "rival", "on": True},
        {"branch": "later", "on": True},
    )
    assert [each.refused for each in answer.answers] == [words, words]


def test_a_merge_asks_the_host_apart_at_the_tip_it_was_seen(tmp_path: Path) -> None:
    host = Host()
    answer = acted(
        host,
        tmp_path,
        "merge",
        {"branches": ["fix-a", "fix-b"], "tips": ["fix-a-tip", "fix-b-tip"]},
    )
    assert host.changing() == [
        AcceptBranch(
            branch="fix-a", repository=REPOSITORY, tip="fix-a-tip", apart=True
        ),
        AcceptBranch(
            branch="fix-b", repository=REPOSITORY, tip="fix-b-tip", apart=True
        ),
    ]
    assert answer.answers == [ActionAnswer(said="did trial-accept\ndid trial-accept")]


def test_a_merge_refused_stays_drafted_saying_why_and_what_went(tmp_path: Path) -> None:
    class HalfRefusing(Host):
        @override
        async def asked[R: Reply](self, request: Request, reply: type[R]) -> R:
            if isinstance(request, AcceptBranch) and request.branch == "fix-b":
                message = "fix-b landed again since you marked it: look at it again"
                raise HostError(message)
            return await super().asked(request, reply)

    answer = acted(
        HalfRefusing(),
        tmp_path,
        "merge",
        {"branches": ["fix-a", "fix-b"], "tips": ["fix-a-tip", "an-older-tip"]},
    )
    [only] = answer.answers
    assert only.refused == (
        "fix-b landed again since you marked it: look at it again\ndid trial-accept"
    )


def test_a_merge_sent_again_asks_only_what_s_left(tmp_path: Path) -> None:
    listed = trial([branch("fix-a", merging=True), branch("fix-b", within=True)])
    host = Host(listed)
    answer = acted(host, tmp_path, "merge", {"branches": ["gone", "fix-a", "fix-b"]})
    assert host.changing() == [
        AcceptBranch(branch="fix-b", repository=REPOSITORY, apart=True)
    ]
    # Nothing's refused: a branch off trial clears its mark, said.
    assert answer.answers == [
        ActionAnswer(
            said=(
                "`gone` isn't on trial any more.\n`fix-a` is merging already.\n"
                "did trial-accept"
            )
        )
    ]


def test_a_version_on_dev_as_it_stands_runs_again_by_being_picked_as_it_was_seen(
    tmp_path: Path,
) -> None:
    host = Host()
    answer = acted(
        host,
        tmp_path,
        "run_again",
        {
            "commit": "c3",
            "current": True,
            "branches": ["fix-a"],
            "tips": ["fix-a-tip"],
            "dev": DEV,
        },
    )
    assert host.changing() == [
        PickBranches(
            branches=["fix-a"],
            repository=REPOSITORY,
            seen={"fix-a": "fix-a-tip"},
            dev=DEV,
        )
    ]
    assert answer.answers == [ActionAnswer(said="did trial-pick")]


def test_a_version_moved_since_it_was_marked_says_so_running_nothing(
    tmp_path: Path,
) -> None:
    host = Host()
    moved_dev: dict[str, JsonValue] = {
        "commit": "c3",
        "current": True,
        "branches": ["fix-a"],
        "tips": ["fix-a-tip"],
        "dev": "an0ther",
    }
    relanded: dict[str, JsonValue] = {
        **moved_dev,
        "dev": DEV,
        "tips": ["an-older-tip"],
    }
    gone: dict[str, JsonValue] = {
        **moved_dev,
        "dev": DEV,
        "branches": ["gone"],
        "tips": ["its-tip"],
    }
    answers = acted(host, tmp_path, "run_again", moved_dev, relanded, gone).answers
    assert host.changing() == []
    assert [each.refused for each in answers] == [None, None, None]
    assert all("moved since you marked it" in each.said for each in answers)


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
    for each in ["version c0", "version c8"]:
        again = offered(blocks, each, "done").argument["argument"]
        assert not RunningAgain.model_validate(again).current
    host = Host()
    answer = acted(host, tmp_path, "run_again", {"commit": "c0"})
    assert host.changing() == [SwitchCopy(commit="c0")]
    assert answer.answers == [
        ActionAnswer(said="The host moves to c0, in a few seconds.")
    ]


def test_a_version_doesn_t_run_again_while_a_merge_runs(tmp_path: Path) -> None:
    host = Host(trial([branch("busy", merging=True)]))
    [only] = acted(host, tmp_path, "run_again", {"commit": "c0"}).answers
    assert "busy is merging" in (only.refused or "")
    assert host.changing() == []


def test_an_action_on_a_repository_computing_no_running_branch_is_refused(
    tmp_path: Path,
) -> None:
    host = Host(None)
    answer = acted(host, tmp_path, "merge", {"branches": ["fix-a"]})
    assert answer.answers[0].refused == f"{REPOSITORY} computes no running branch"


@pytest.mark.parametrize(
    ("action", "verb"),
    [("pick", "done"), ("merge", "merge"), ("run_again", "done")],
)
def test_each_action_is_the_operator_s_alone_on_a_verb_declared(
    action: str, verb: str, tmp_path: Path
) -> None:
    resolved = modules(Host(), tmp_path)
    owner = resolved.acting("versions", action)
    assert owner is not None
    method = served(owner.serving)[action]
    door = method.acting()
    assert door is not None
    assert door.verb == verb
    assert verb in [each.name for each in resolved.resolved.looks.verbs]
    ask(owner.serving, action, Operator())
    with pytest.raises(LupDevError, match="never by `Room`"):
        ask(owner.serving, action, Room(launch=register()))
