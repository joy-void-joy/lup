"""Reviews in the first lup's dashboard, through a stand-in host half.

The stand-in is a module written where the first lup's checkout keeps its host
half, so `LegacyDashboard` and `LegacyQueue` load it by path as they load the real
one. It keeps the relay and the answers as JSON files under the test's directory,
recognizes a review again by a fingerprint of everything it was parked with, and
spends an approval once, as the real host does; replies go to a file of their own
beside the relay, and a transition moves an entry's fields. The tests answer,
remark, expire and retire reviews by writing those files, the installer's while
its clock sleeps.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sh
from filelock import FileLock
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.install import (
    ChangedFile,
    Installed,
    Installer,
    InstallError,
    Review,
    Toolchain,
)
from lup_dev.legacy_dashboard import (
    LegacyDashboard,
    LegacyQueue,
    Notices,
    NotifySend,
    Proposal,
    RecordedReply,
    Reply,
)
from lup_dev.policy.importers import BackgroundSpawner
from lup_dev.review import (
    Answer,
    Answered,
    Gone,
    LineComment,
    Look,
    Remark,
    ReviewedFile,
    ReviewError,
    ReviewRequest,
    Waiting,
)
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from conftest import Kit, Shell

HOST = '''
"""A stand-in for the first lup's host half: the functions lup-dev calls."""

import hashlib
import json
from pathlib import Path

HOME = Path(__file__).parent / "answers"


def review_home(cwd):
    return Path(cwd)


def review_answers_home(variable):
    assert variable == "LUP_REVIEW_ANSWERS"
    return HOME


def review_answers(relay, home):
    return Path(home) / "answers.jsonl"


def native_review_records(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def review_records(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def append_relay_records(log, records):
    with (Path(log).parent / "replies.jsonl").open("a") as kept:
        for record in records():
            kept.write(json.dumps(record) + "\\n")


def transition_relay_entry(log, identifier, fields):
    entries = native_review_records(log)
    entries[identifier].update(fields)
    Path(log).write_text(json.dumps(entries))


def review_hook_call(
    root, session, tool, arguments, preconditions, reason, rule, purpose, reviewer,
    answers="", agent="",
):
    if not session:
        why = "the hook carries no session_id"
        return {"state": "unavailable", "id": "", "reason": why}
    relay = Path(root) / ".lup" / "questions.jsonl"
    entries = native_review_records(relay)
    called = [json.loads(arguments), json.loads(preconditions)]
    parked = [session, str(root), tool, *called]
    material = json.dumps([*parked, reason, rule, purpose, reviewer], sort_keys=True)
    fingerprint = hashlib.sha256(material.encode()).hexdigest()
    matches = [each for each in entries.values() if each["fingerprint"] == fingerprint]
    entry = matches[-1] if matches else None
    if entry is not None and entry["state"] == "pending":
        given = [
            record["answer"]
            for record in review_records(answers)
            if record["question"] == entry["id"] and "answer" in record
        ]
        if given and not given[0]["approved"]:
            return {"state": "rejected", "id": entry["id"], "reason": given[0]["note"]}
        if given:
            entry["state"] = "dispatched"
            relay.write_text(json.dumps(entries))
            return {"state": "approved", "id": entry["id"], "reason": ""}
        return {"state": "pending", "id": entry["id"], "reason": entry["reason"]}
    identifier = f"review-{len(entries) + 1}"
    entries[identifier] = {
        "id": identifier,
        "fingerprint": fingerprint,
        "state": "pending",
        "reason": reason,
        "requester": session,
        "agent": agent,
        "tool": tool,
        "rule": rule,
        "purpose": purpose,
        "requirement": reviewer,
        "payload": json.loads(arguments),
        "preconditions": json.loads(preconditions),
        "answers": answers,
    }
    relay.parent.mkdir(parents=True, exist_ok=True)
    relay.write_text(json.dumps(entries))
    return {"state": "pending", "id": identifier, "reason": reason}
'''

SINCE = "a" * 40
COMMIT = "b" * 40
EDITED = Path("packages/lup-dev/src/lup_dev/install.py")
MADE = Path("packages/lup-dev/src/lup_dev/made.py")
GONE = Path("uv.lock")


class Legacy:
    """The stand-in first lup: its checkout, the relay it keeps and its answers."""

    def __init__(self, root: Path, checkout: Path) -> None:
        self.root = root
        self.checkout = checkout
        assets = root / "packages" / "lup" / "src" / "lup" / "policy" / "assets"
        assets.mkdir(parents=True)
        (assets / "host.py").write_text(HOST)
        self.answers = assets / "answers" / "answers.jsonl"

    @property
    def relay(self) -> Path:
        return self.checkout / ".lup" / "questions.jsonl"

    def entries(self) -> dict[str, dict[str, object]]:
        return json.loads(self.relay.read_text())

    def waiting(self) -> str:
        [review] = [
            review
            for review, entry in self.entries().items()
            if entry["state"] == "pending"
        ]
        return review

    def record(self, record: dict[str, object]) -> None:
        self.answers.parent.mkdir(parents=True, exist_ok=True)
        with self.answers.open("a") as answers:
            answers.write(json.dumps(record) + "\n")

    def answer(
        self,
        review: str,
        *,
        approved: bool,
        note: str = "",
        comments: list[dict[str, object]] | None = None,
    ) -> None:
        answer = {
            "approved": approved,
            "principal": "operator",
            "receipt": "recorded",
            "note": note,
            "comments": comments or [],
        }
        self.record({"question": review, "fingerprint": "f", "answer": answer})

    def remark(
        self, review: str, note: str, comments: list[dict[str, object]] | None = None
    ) -> None:
        remark = {"principal": "operator", "note": note, "comments": comments or []}
        self.record({"question": review, "fingerprint": "f", "remark": remark})

    def move(self, review: str, state: str, outcome: str = "") -> None:
        entries = self.entries()
        entries[review]["state"] = state
        entries[review]["outcome"] = outcome
        self.relay.write_text(json.dumps(entries))

    def replies(self) -> list[RecordedReply]:
        replied = self.checkout / ".lup" / "replies.jsonl"
        if not replied.is_file():
            return []
        return [
            RecordedReply.model_validate_json(line)
            for line in replied.read_text().splitlines()
        ]


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "lup"
    root.mkdir()
    return root


@pytest.fixture
def legacy(tmp_path: Path, checkout: Path) -> Legacy:
    return Legacy(tmp_path / "legacy", checkout)


def dashboard(checkout: Path, legacy: Legacy, kit: Kit) -> LegacyDashboard:
    return LegacyDashboard(checkout=checkout, legacy=legacy.root, clock=kit.clock)


def review(since: str | None = SINCE) -> Review:
    return Review(
        since=since,
        commit=COMMIT,
        files=[
            ChangedFile(path=EDITED, before="old\nkept\n", after="new\nkept\n"),
            ChangedFile(path=MADE, before=None, after='"""Made."""\n'),
            ChangedFile(path=GONE, before="version = 1\n", after=None),
        ],
        shortstat="3 files changed, 2 insertions(+), 2 deletions(-)",
    )


def export(checkout: Path, since: str = SINCE) -> Path:
    return checkout / ".lup" / "install-review" / since


def comment(path: Path, note: str, side: str = "after") -> dict[str, object]:
    return {"path": str(path), "start": 1, "end": 2, "side": side, "note": note}


def test_the_review_is_one_propose_of_every_file_whole(
    checkout: Path, legacy: Legacy, kit: Kit
) -> None:
    seen: list[dict[str, object]] = []

    def answered() -> None:
        review = legacy.waiting()
        seen.append(legacy.entries()[review])
        assert (export(checkout) / EDITED).read_text() == "old\nkept\n"
        assert (export(checkout) / GONE).read_text() == "version = 1\n"
        assert not (export(checkout) / MADE).exists()
        legacy.answer(review, approved=True)

    kit.clock.on_sleep.append(answered)
    answer = dashboard(checkout, legacy, kit).answer(review())
    assert answer == Answer(approved=True)
    [entry] = seen
    assert entry["tool"] == "Propose"
    assert entry["requester"] == "lup-dev install"
    assert entry["rule"] == "lup-dev-install"
    assert entry["requirement"] == "human_only"
    assert entry["reason"] == review().heading()
    assert entry["answers"] == str(legacy.answers)
    assert entry["preconditions"] == {
        str(export(checkout) / EDITED): "old\nkept\n",
        str(export(checkout) / MADE): None,
        str(export(checkout) / GONE): "version = 1\n",
    }
    payload = entry["payload"]
    assert isinstance(payload, dict)
    assert payload["files"] == [
        {"path": str(export(checkout) / EDITED), "content": "new\nkept\n", "about": ""},
        {"path": str(export(checkout) / MADE), "content": '"""Made."""\n', "about": ""},
        {"path": str(export(checkout) / GONE), "content": None, "about": ""},
    ]
    assert review().heading() in payload["why"]
    assert ".lup/install-review/" + SINCE in payload["why"]
    assert not export(checkout).exists()
    assert legacy.entries()["review-1"]["state"] == "dispatched"


def test_the_first_install_keeps_its_review_under_whole(
    checkout: Path, legacy: Legacy, kit: Kit
) -> None:
    def answered() -> None:
        entry = legacy.entries()[legacy.waiting()]
        preconditions = entry["preconditions"]
        assert isinstance(preconditions, dict)
        assert str(export(checkout, "whole") / EDITED) in preconditions
        legacy.answer(legacy.waiting(), approved=True)

    kit.clock.on_sleep.append(answered)
    first = review(since=None).model_copy(
        update={
            "files": [
                ChangedFile(path=EDITED, before=None, after="new\n"),
                ChangedFile(path=MADE, before=None, after="made\n"),
            ]
        }
    )
    assert dashboard(checkout, legacy, kit).answer(first).approved


def test_the_operator_sees_what_waits_and_how_to_serve_it(
    checkout: Path, legacy: Legacy, kit: Kit, capsys: pytest.CaptureFixture[str]
) -> None:
    kit.clock.on_sleep.append(lambda: legacy.answer("review-1", approved=False))
    dashboard(checkout, legacy, kit).answer(review())
    assert capsys.readouterr().out.splitlines() == [
        review().heading(),
        (
            "It waits for your answer as review review-1 in the first lup's "
            "dashboard, which this serves:"
        ),
        (
            f"    uv run --directory {legacy.root} lup-devtools dashboard serve "
            f"--root {checkout}"
        ),
        (
            "Unanswered for an hour, it expires and is parked again under another "
            "id: what you sent as remarks stays with it, drafts not yet sent don't."
        ),
        "Ctrl-C withdraws the review and installs nothing.",
    ]


def test_comments_and_remarks_come_back_on_the_checkouts_paths(
    checkout: Path, legacy: Legacy, kit: Kit, capsys: pytest.CaptureFixture[str]
) -> None:
    def answered() -> None:
        review = legacy.waiting()
        legacy.remark(
            review, "first thought", [comment(export(checkout) / GONE, "why")]
        )
        legacy.answer(
            review,
            approved=False,
            note="not yet",
            comments=[comment(export(checkout) / EDITED, "old line", side="before")],
        )

    kit.clock.on_sleep.append(answered)
    answer = dashboard(checkout, legacy, kit).answer(review())
    assert answer == Answer(
        approved=False,
        note="first thought\n\nnot yet",
        comments=[
            LineComment(path=GONE, first=1, last=2, side="after", note="why"),
            LineComment(path=EDITED, first=1, last=2, side="before", note="old line"),
        ],
    )
    assert legacy.entries()["review-1"]["state"] == "pending"
    assert (
        f"What you wrote stays in the first lup's answers file, {legacy.answers}."
        in capsys.readouterr().out
    )
    assert not export(checkout).exists()


def test_an_expired_review_is_parked_again_keeping_its_remarks(
    checkout: Path, legacy: Legacy, kit: Kit, capsys: pytest.CaptureFixture[str]
) -> None:
    def expired() -> None:
        legacy.remark("review-1", "said before the hour")
        legacy.move("review-1", "expired", "its requester ended")
        kit.clock.on_sleep.append(answered)

    def answered() -> None:
        legacy.answer("review-2", approved=True, note="fine")

    kit.clock.on_sleep.append(expired)
    answer = dashboard(checkout, legacy, kit).answer(review())
    assert answer == Answer(approved=True, note="said before the hour\n\nfine")
    assert legacy.entries()["review-2"]["state"] == "dispatched"
    assert (
        "Review review-1 expired unanswered; it's parked again as review review-2."
        in capsys.readouterr().out
    )
    assert kit.clock.slept == 4


def test_a_review_that_leaves_the_queue_otherwise_refuses(
    checkout: Path, legacy: Legacy, kit: Kit
) -> None:
    kit.clock.on_sleep.append(
        lambda: legacy.move("review-1", "stale", "a file changed since it was recorded")
    )
    with pytest.raises(
        InstallError, match="left the dashboard unanswered, stale: a file changed"
    ):
        dashboard(checkout, legacy, kit).answer(review())
    assert not export(checkout).exists()


def test_ctrl_c_withdraws_the_review_by_removing_its_files(
    checkout: Path, legacy: Legacy, kit: Kit, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted() -> None:
        assert export(checkout).exists()
        raise KeyboardInterrupt

    kit.clock.on_sleep.append(interrupted)
    with pytest.raises(KeyboardInterrupt):
        dashboard(checkout, legacy, kit).answer(review())
    assert not export(checkout).exists()
    assert "Withdrawn:" in capsys.readouterr().out


def test_a_review_answered_already_is_read_back_and_spent_once(
    checkout: Path, legacy: Legacy, kit: Kit
) -> None:
    def answered() -> None:
        legacy.answer(legacy.waiting(), approved=True)
        raise KeyboardInterrupt

    kit.clock.on_sleep.append(answered)
    with pytest.raises(KeyboardInterrupt):
        dashboard(checkout, legacy, kit).answer(review())
    answer = dashboard(checkout, legacy, kit).answer(review())
    assert answer == Answer(approved=True)
    assert legacy.entries()["review-1"]["state"] == "dispatched"
    assert kit.clock.slept == 2


def test_a_review_declined_already_is_declined_again(
    checkout: Path, legacy: Legacy, kit: Kit
) -> None:
    kit.clock.on_sleep.append(
        lambda: legacy.answer("review-1", approved=False, note="no")
    )
    dashboard(checkout, legacy, kit).answer(review())
    again = dashboard(checkout, legacy, kit).answer(review())
    assert again == Answer(approved=False, note="no")
    assert list(legacy.entries()) == ["review-1"]


def test_a_host_that_cant_park_refuses(
    checkout: Path, legacy: Legacy, kit: Kit
) -> None:
    nobody = dashboard(checkout, legacy, kit).model_copy(update={"requester": ""})
    with pytest.raises(InstallError, match="the hook carries no session_id"):
        nobody.answer(review())
    assert not export(checkout).exists()


def test_a_missing_first_lup_refuses_naming_the_setting(
    checkout: Path, tmp_path: Path, kit: Kit
) -> None:
    missing = LegacyDashboard(
        checkout=checkout, legacy=tmp_path / "nowhere", clock=kit.clock
    )
    with pytest.raises(InstallError, match="LUP_INTERIM_REVIEW_LEGACY_CHECKOUT"):
        missing.answer(review())
    assert not export(checkout).exists()


def test_the_first_lup_is_found_beside_the_repository_as_the_hook_finds_it(
    bare: Path, tmp_path: Path, kit: Kit, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = bare / "tree" / "main"
    monkeypatch.delenv("LUP_INTERIM_REVIEW_LEGACY_CHECKOUT", raising=False)
    found = LegacyDashboard.configured(worktree, LupDevSettings(), kit.clock)
    assert found.legacy == tmp_path / "lup-legacy.git" / "tree" / "dev"
    assert found.host == (
        found.legacy
        / "packages"
        / "lup"
        / "src"
        / "lup"
        / "policy"
        / "assets"
        / "host.py"
    )
    monkeypatch.setenv("LUP_INTERIM_REVIEW_LEGACY_CHECKOUT", "elsewhere/legacy")
    beside = LegacyDashboard.configured(worktree, LupDevSettings(), kit.clock)
    assert beside.legacy == tmp_path / "elsewhere" / "legacy"
    monkeypatch.setenv("LUP_INTERIM_REVIEW_LEGACY_CHECKOUT", str(tmp_path / "abs"))
    absolute = LegacyDashboard.configured(worktree, LupDevSettings(), kit.clock)
    assert absolute.legacy == tmp_path / "abs"


class Recording(Toolchain):
    """Records what it was asked to install, and builds nothing."""

    installed: list[Path] = []

    def build(self, checkout: Path) -> None:
        pass

    def install(self, checkout: Path) -> None:
        self.installed.append(checkout)


def test_the_installer_installs_on_the_dashboards_approval(
    tmp_path: Path, kit: Kit, shell: Shell
) -> None:
    root = tmp_path / "work"
    source = root / "packages" / "lup-dev" / "src" / "lup_dev" / "__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text('"""The environment."""\n')
    shell.git(root, "init", "-q", "-b", "dev")
    shell.git(root, "config", "user.email", "test@example.com")
    shell.git(root, "config", "user.name", "Test")
    shell.git(root, "config", "commit.gpgsign", "false")
    shell.commit(root, "first")
    head = shell.git(root, "rev-parse", "HEAD")
    legacy = Legacy(tmp_path / "legacy", root)
    on_line = comment(
        root / ".lup" / "install-review" / "whole" / source.relative_to(root), "ok"
    )
    kit.clock.on_sleep.append(
        lambda: legacy.answer(legacy.waiting(), approved=True, comments=[on_line])
    )
    toolchain = Recording()
    installer = Installer(
        checkout=root,
        layout=kit.layout,
        toolchain=toolchain,
        reviewer=LegacyDashboard(checkout=root, legacy=legacy.root, clock=kit.clock),
        clock=kit.clock,
        runtimes=[],
    )
    outcome = installer.install()
    assert isinstance(outcome, Installed)
    assert outcome.approval.commit == head
    assert toolchain.installed == [root]
    assert outcome.report().splitlines()[-1] == (
        "  packages/lup-dev/src/lup_dev/__init__.py:1-2 (after): ok"
    )


LANDED = Path("packages/lup-dev/tests/test_made.py")
HEADING = "Reviews park in the first lup's dashboard."


class Raised(Notices):
    """Records each desktop notice instead of raising it."""

    def __init__(self) -> None:
        self.raised: list[str] = []

    def notify(self, summary: str, body: str) -> None:
        self.raised.append(f"{summary}: {body}")


@pytest.fixture
def notices() -> Raised:
    return Raised()


def queue(checkout: Path, legacy: Legacy, kit: Kit, notices: Raised) -> LegacyQueue:
    return LegacyQueue(
        worktree=checkout,
        legacy=legacy.root,
        store=kit.layout.store(checkout),
        clock=kit.clock,
        notices=notices,
        spawner=kit.spawner,
    )


def request(number: int = 1, requester: str = "session-1") -> ReviewRequest:
    return ReviewRequest(
        number=number,
        requester=requester,
        agent="agent-1",
        heading=HEADING,
        files=[
            ReviewedFile(
                path=EDITED,
                before="old\nkept\n",
                after="new\nkept\n",
                context="`install.py` imports the answers.",
                asks=["a public-API change", "an added ignore"],
            ),
            ReviewedFile(
                path=MADE,
                before=None,
                after='"""Made."""\n',
                context="A module for what's made.",
            ),
            ReviewedFile(
                path=GONE,
                before="version = 1\n",
                after=None,
                context="Deleted: nothing pins versions.",
                asks=["a protected path"],
            ),
            ReviewedFile(
                path=LANDED,
                before=None,
                after="def test_made(): ...\n",
                context="The tests for `made.py`.",
                landed=True,
            ),
        ],
    )


def exported(checkout: Path, number: int = 1) -> Path:
    return checkout / ".lup" / "review" / str(number) / "before"


def test_a_review_parks_as_one_propose_with_each_files_standing(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    queue(checkout, legacy, kit, notices).park(request())
    entry = legacy.entries()["review-1"]
    assert entry["tool"] == "Propose"
    assert entry["requester"] == "session-1"
    assert entry["agent"] == "agent-1"
    assert entry["rule"] == "lup-dev-submit"
    assert entry["requirement"] == "human_only"
    assert entry["reason"] == HEADING
    export = exported(checkout)
    assert entry["preconditions"] == {
        str(export / EDITED): "old\nkept\n",
        str(export / MADE): None,
        str(export / GONE): "version = 1\n",
        str(export / LANDED): None,
    }
    payload = entry["payload"]
    assert isinstance(payload, dict)
    assert payload["files"] == [
        {
            "path": str(export / EDITED),
            "content": "new\nkept\n",
            "about": (
                "`install.py` imports the answers.\n\nNeeds your review: a "
                "public-API change; an added ignore."
            ),
        },
        {
            "path": str(export / MADE),
            "content": '"""Made."""\n',
            "about": (
                "A module for what's made.\n\nNothing here asks for review; the "
                "agent asked for your view."
            ),
        },
        {
            "path": str(export / GONE),
            "content": None,
            "about": (
                "Deleted: nothing pins versions.\n\nNeeds your review: a protected "
                "path."
            ),
        },
        {
            "path": str(export / LANDED),
            "content": "def test_made(): ...\n",
            "about": (
                "The tests for `made.py`.\n\nContext, already landed: nothing here "
                "is applied."
            ),
        },
    ]
    why = Proposal.model_validate(payload).why
    assert why.startswith(f"{HEADING}\n\n")
    assert ".lup/review/1/before/" in why
    assert (export / EDITED).read_text() == "old\nkept\n"
    assert (export / GONE).read_text() == "version = 1\n"
    assert not (export / MADE).exists()
    assert not (export / LANDED).exists()
    assert notices.raised == [f"A change waits for your review: {HEADING}"]
    assert kit.spawner.spawned == [checkout]


def test_looking_reads_remarks_then_the_answer_on_the_worktrees_paths(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    assert parked.look(1) == Look(state=Waiting())
    export = exported(checkout)
    legacy.remark("review-1", "first thought", [comment(export / GONE, "why")])
    remark = Remark(
        note="first thought",
        comments=[LineComment(path=GONE, first=1, last=2, side="after", note="why")],
    )
    assert parked.look(1) == Look(state=Waiting(), remarks=[remark])
    legacy.answer(
        "review-1",
        approved=False,
        note="not yet",
        comments=[comment(export / EDITED, "old line", side="before")],
    )
    declined = Answer(
        approved=False,
        note="not yet",
        comments=[
            LineComment(path=EDITED, first=1, last=2, side="before", note="old line")
        ],
    )
    assert parked.look(1) == Look(state=Answered(answer=declined), remarks=[remark])
    assert notices.raised == [f"A change waits for your review: {HEADING}"]


def test_an_expired_review_still_waits_and_one_retired_is_gone(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request(1))
    parked.park(request(2))
    legacy.move("review-1", "expired", "its requester ended")
    legacy.move("review-2", "stale", "a file changed since it was recorded")
    assert parked.look(1) == Look(state=Waiting())
    assert parked.look(2) == Look(
        state=Gone(why="stale: a file changed since it was recorded")
    )


def test_spending_an_approval_marks_it_carried_out_and_lets_the_review_go(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    legacy.answer("review-1", approved=True)
    parked.spend(1)
    assert legacy.entries()["review-1"]["state"] == "dispatched"
    assert list(legacy.entries()) == ["review-1"]
    assert not exported(checkout).exists()
    with pytest.raises(ReviewError, match="no review 1 is parked"):
        parked.look(1)


def test_spending_what_isnt_approved_refuses_and_parks_nothing(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    with pytest.raises(ReviewError, match="review 1 isn't approved"):
        parked.spend(1)
    legacy.answer("review-1", approved=False, note="no")
    with pytest.raises(ReviewError, match="review 1 isn't approved"):
        parked.spend(1)
    assert list(legacy.entries()) == ["review-1"]
    assert legacy.entries()["review-1"]["state"] == "pending"
    assert exported(checkout).exists()


def test_withdrawing_cancels_the_review_and_removes_its_export(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    parked.withdraw(1, "superseded by review 2")
    entry = legacy.entries()["review-1"]
    assert entry["state"] == "cancelled"
    assert entry["outcome"] == "withdrawn: superseded by review 2"
    assert not exported(checkout).exists()
    with pytest.raises(ReviewError, match="no review 1 is parked"):
        parked.look(1)


def test_withdrawing_a_review_that_left_only_lets_it_go(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    legacy.move("review-1", "stale", "a file changed")
    parked.withdraw(1, "the draft moved under it")
    assert legacy.entries()["review-1"]["state"] == "stale"
    assert not exported(checkout).exists()


def test_a_reply_is_the_first_lups_reply_in_the_reviews_thread(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    parked.reply(1, "I'll rename `made.py`.")
    assert legacy.replies() == [
        RecordedReply(
            question="review-1",
            reply=Reply(
                author="session-1", text="I'll rename `made.py`.", at=kit.clock.now()
            ),
        )
    ]
    with pytest.raises(ReviewError, match="this one is empty"):
        parked.reply(1, "  ")
    assert notices.raised == [f"A change waits for your review: {HEADING}"]


def test_the_frozen_mark_is_a_reply_and_a_notice_the_first_time_only(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    parked.frozen(1)
    parked.frozen(1)
    assert [each.reply.text for each in legacy.replies()] == [parked.mark]
    assert [each.question for each in legacy.replies()] == ["review-1"]
    assert notices.raised == [
        f"A change waits for your review: {HEADING}",
        f"An agent waits on your review: {HEADING}",
    ]


def test_the_keeper_parks_expired_reviews_again_silently_until_none_waits(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request(1))
    parked.park(request(2))
    parked.frozen(2)
    legacy.remark("review-1", "said before the hour")
    legacy.move("review-1", "expired", "its requester ended")
    legacy.move("review-2", "expired", "its requester ended")

    def answered() -> None:
        legacy.answer("review-3", approved=True, note="fine")
        legacy.answer("review-4", approved=False, note="no")

    kit.clock.on_sleep.append(answered)
    parked.keep()
    assert kit.clock.slept == parked.poll.total_seconds()
    assert legacy.entries()["review-3"]["state"] == "pending"
    assert legacy.entries()["review-4"]["state"] == "pending"
    assert [(each.question, each.reply.text) for each in legacy.replies()] == [
        ("review-2", parked.mark),
        ("review-4", parked.mark),
    ]
    assert notices.raised == [
        f"A change waits for your review: {HEADING}",
        f"A change waits for your review: {HEADING}",
        f"An agent waits on your review: {HEADING}",
    ]
    assert parked.look(1) == Look(
        state=Answered(answer=Answer(approved=True, note="fine")),
        remarks=[Remark(note="said before the hour")],
    )
    assert parked.look(2) == Look(
        state=Answered(answer=Answer(approved=False, note="no"))
    )
    assert not parked.running()
    legacy.answer("review-3", approved=True)
    parked.spend(1)
    assert legacy.entries()["review-3"]["state"] == "dispatched"


def test_a_keeper_stops_at_once_with_nothing_waiting(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.keep()
    parked.park(request())
    legacy.answer("review-1", approved=True)
    parked.keep()
    assert kit.clock.slept == 0
    assert not parked.running()


def test_one_keeper_runs_per_worktree(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    running = FileLock(kit.layout.store(checkout).keeper)
    with running:
        assert parked.running()
        parked.park(request())
        parked.keep()
    assert kit.spawner.spawned == []
    assert kit.clock.slept == 0


def test_parking_a_number_parked_already_refuses(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    parked.park(request())
    with pytest.raises(ReviewError, match="review 1 is parked already"):
        parked.park(request())
    assert list(legacy.entries()) == ["review-1"]
    assert exported(checkout).exists()


def test_a_review_the_host_wont_park_refuses_and_leaves_nothing(
    checkout: Path, legacy: Legacy, kit: Kit, notices: Raised
) -> None:
    parked = queue(checkout, legacy, kit, notices)
    with pytest.raises(ReviewError, match="the hook carries no session_id"):
        parked.park(request(requester=""))
    assert not exported(checkout).exists()
    assert notices.raised == []
    assert kit.spawner.spawned == []
    with pytest.raises(ReviewError, match="no review 1 is parked"):
        parked.look(1)


def test_a_queue_without_the_first_lup_refuses_naming_the_setting(
    checkout: Path, legacy: Legacy, tmp_path: Path, kit: Kit, notices: Raised
) -> None:
    missing = queue(checkout, legacy, kit, notices).model_copy(
        update={"legacy": tmp_path / "nowhere"}
    )
    with pytest.raises(ReviewError, match="LUP_INTERIM_REVIEW_LEGACY_CHECKOUT"):
        missing.park(request())
    assert not exported(checkout).exists()


def test_the_queue_reaches_the_first_lup_and_the_store_as_configured(
    bare: Path, tmp_path: Path, kit: Kit, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = bare / "tree" / "main"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LUP_INTERIM_REVIEW_LEGACY_CHECKOUT", "elsewhere/legacy")
    configured = LegacyQueue.configured(worktree, LupDevSettings(), kit.clock)
    assert configured.legacy == tmp_path / "elsewhere" / "legacy"
    assert configured.store.home.is_relative_to(tmp_path / "xdg" / "lup")
    assert configured.spawner == BackgroundSpawner(command=["review", "keep"])
    assert configured.notices == NotifySend()


def test_the_keeper_runs_as_lup_devs_hidden_review_keep(
    bare: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = bare / "tree" / "main"
    legacy = Legacy(tmp_path / "legacy", worktree)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LUP_INTERIM_REVIEW_LEGACY_CHECKOUT", str(legacy.root))
    ran = CliRunner().invoke(cli.app, ["review", "keep", str(worktree)])
    assert ran.exit_code == 0, ran.output
    listed = CliRunner().invoke(cli.app, ["--help"]).output
    assert "Reviews parked for your answer." not in listed


def test_the_keeper_is_started_as_its_own_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []

    class Command:
        def __init__(self, program: str) -> None:
            self.program = program

        def __call__(self, *arguments: str, **options: object) -> None:
            assert options["_bg"] is True
            started.append([self.program, *arguments])

    monkeypatch.setattr(sh, "Command", Command)
    log = tmp_path / "store" / "keeper.log"
    BackgroundSpawner(command=["review", "keep"]).spawn(tmp_path / "work", log)
    [command] = started
    assert command[1:] == [
        "-m",
        "lup_dev.cli",
        "review",
        "keep",
        str(tmp_path / "work"),
    ]
    assert log.parent.is_dir()


def test_a_desktop_notice_goes_through_notify_send_where_its_installed(
    tmp_path: Path,
) -> None:
    told = tmp_path / "told"
    notifier = tmp_path / "notify-send"
    notifier.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {told}\n')
    notifier.chmod(0o755)
    NotifySend(executable=str(notifier)).notify("A change waits", "the heading")
    assert told.read_text().splitlines() == [
        "--app-name=lup",
        "A change waits",
        "the heading",
    ]
    NotifySend(executable=str(tmp_path / "absent")).notify("nothing", "shown")


def test_a_failing_desktop_notice_is_said_on_standard_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notifier = tmp_path / "notify-send"
    notifier.write_text("#!/bin/sh\necho 'no display' >&2\nexit 1\n")
    notifier.chmod(0o755)
    NotifySend(executable=str(notifier)).notify("A change waits", "the heading")
    assert "the desktop notice failed: no display" in capsys.readouterr().err


def test_a_reviewed_file_says_what_the_change_does_to_it() -> None:
    made = ReviewedFile(path=MADE, before=None, after="x\n", context="made")
    assert made.kind() == "created"
    assert made.model_copy(update={"before": "y\n"}).kind() == "overwritten"
    gone = ReviewedFile(path=GONE, before="x\n", after=None, context="gone")
    assert gone.kind() == "deleted"
    with pytest.raises(ValueError, match="no text on either side"):
        ReviewedFile(path=GONE, before=None, after=None, context="nothing")
    with pytest.raises(ValueError, match="landed already"):
        ReviewedFile(
            path=GONE, before="x", after="y", context="c", landed=True, asks=["a"]
        )
