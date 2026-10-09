"""The judge's review in the first lup's dashboard, through a stand-in host half.

The stand-in is a module written where the first lup's checkout keeps its host
half, so `LegacyDashboard` loads it by path as it loads the real one. It keeps the
relay and the answers as JSON files under the test's directory, recognizes a
review again by a fingerprint of everything it was parked with, and spends an
approval once, as the real host does. The tests answer, remark, expire and retire
reviews by writing those files while the dashboard's clock sleeps.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.install import (
    Answer,
    ChangedFile,
    Installed,
    Installer,
    InstallError,
    LineComment,
    Review,
    Toolchain,
)
from lup_dev.legacy_dashboard import LegacyDashboard
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


def review_hook_call(
    root, session, tool, arguments, preconditions, reason, rule, purpose, reviewer,
    answers="",
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
