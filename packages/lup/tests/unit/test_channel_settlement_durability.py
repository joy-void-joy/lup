"""A settled answer is complete before it becomes the one immutable winner."""

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from lup.channels.slot import Slot
from lup.coordination.questions import QuestionAnswer
from lup.resolver.mailbox import QuestionMailbox
from lup.resolver.models import (
    AnswerBatch,
    MaterialQuestion,
    QuestionBatch,
    ResolveState,
)
from lup.resolver.recovery import IntegrationRecoveryDesk, IntegrationRecoveryMode
from tests.unit.test_channels import Decision
from tests.unit.test_resolver_recovery import RecoveryFixture
from tests.unit.test_resolver_recovery import recovery as recovery_fixture

recovery = recovery_fixture


def test_failed_payload_sync_never_publishes_an_empty_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = Slot(tmp_path / "decision", Decision)
    fsync = os.fsync

    def fail_payload(descriptor: int) -> None:
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("payload sync failed")
        fsync(descriptor)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", fail_payload)
        with pytest.raises(OSError, match="payload sync failed"):
            slot.settle(Decision(value="incomplete"))
    assert slot.settled() is None
    assert list(slot.root.iterdir()) == []
    assert slot.settle(Decision(value="retry"))
    assert slot.settled() == Decision(value="retry")


def test_concurrent_writers_publish_exactly_one_complete_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = Slot(tmp_path / "decision", Decision)
    link = Path.hardlink_to
    publishing = Barrier(2)

    def complete_before_link(target: Path, source: Path) -> None:
        assert Decision.model_validate_json(source.read_bytes()).value in {"a", "b"}
        assert stat.S_IMODE(source.stat().st_mode) == 0o600
        assert slot.settled() is None
        publishing.wait(timeout=5)
        link(target, source)

    monkeypatch.setattr(Path, "hardlink_to", complete_before_link)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [
            (value, pool.submit(slot.settle, Decision(value=value)))
            for value in ("a", "b")
        ]
        winners = [value for value, future in writes if future.result(timeout=5)]
    assert len(winners) == 1
    assert slot.settled() == Decision(value=winners[0])
    assert [path.name for path in slot.root.iterdir()] == ["settled.json"]


def test_publication_syncs_payload_before_link_and_new_directory_chain_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = Slot(tmp_path / "new" / "slots" / "decision", Decision)
    fsync, link = os.fsync, Path.hardlink_to
    synced: list[os.stat_result] = []

    def observe_sync(descriptor: int) -> None:
        synced.append(os.fstat(descriptor))
        fsync(descriptor)

    def observe_link(target: Path, source: Path) -> None:
        assert len(synced) == 1 and stat.S_ISREG(synced[0].st_mode)
        assert synced[0].st_ino == source.stat().st_ino
        assert not target.exists()
        link(target, source)

    monkeypatch.setattr(os, "fsync", observe_sync)
    monkeypatch.setattr(Path, "hardlink_to", observe_link)
    assert slot.settle(Decision(value="durable"))
    assert [record.st_ino for record in synced if stat.S_ISDIR(record.st_mode)] == [
        directory.stat().st_ino
        for directory in (
            slot.root,
            slot.root.parent,
            slot.root.parent.parent,
            tmp_path,
        )
    ]


def test_directory_sync_failure_keeps_complete_published_incumbent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = Slot(tmp_path / "decision", Decision)
    fsync = os.fsync

    def fail_directory(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("directory sync failed")
        fsync(descriptor)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", fail_directory)
        with pytest.raises(OSError, match="directory sync failed"):
            slot.settle(Decision(value="winner"))
    assert slot.settled() == Decision(value="winner")
    assert not slot.settle(Decision(value="retry"))
    assert [path.name for path in slot.root.iterdir()] == ["settled.json"]


def test_interrupted_recovery_answer_publication_can_retry(
    recovery: RecoveryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = MaterialQuestion(
        id="design", concern_id="a", prompt="Keep the interface?"
    )
    answer = QuestionAnswer(question_id=question.id, value="yes")
    original = recovery.repository.load().model_copy(
        update={
            "questions": QuestionBatch(run_id="recover", questions=[question]),
            "answers": AnswerBatch(run_id="recover", answers=[answer]),
        }
    )
    recovery.repository.save(original)

    def interrupt_link(target: Path, source: Path) -> None:
        assert source.is_file() and not target.exists()
        raise InterruptedError("interrupted before publication")

    with monkeypatch.context() as fault:
        fault.setattr(Path, "hardlink_to", interrupt_link)
        with pytest.raises(InterruptedError, match="before publication"):
            IntegrationRecoveryDesk(recovery.repository).recover(
                IntegrationRecoveryMode.RESTORE
            )
    mailbox = QuestionMailbox(recovery.repository.root)
    assert mailbox.settled_answer(question.id) is None
    assert recovery.repository.load() == original
    assert list(recovery.repository.root.rglob(".settled.json.*")) == []
    archives = list(
        (recovery.repository.root / "integration" / "recovery").glob("*/state.json")
    )
    assert len(archives) == 1
    assert ResolveState.model_validate_json(archives[0].read_text()) == original

    IntegrationRecoveryDesk(recovery.repository).recover(
        IntegrationRecoveryMode.RESTORE
    )
    settled = mailbox.settled_answer(question.id)
    assert settled is not None and settled.answer == answer
    state = recovery.repository.load()
    assert state.answers is not None and state.answers.answers == [answer]
