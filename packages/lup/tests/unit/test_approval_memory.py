"""A question answered yes once is answered the same way for the same call.

The runtime's prompt exposes its answer to no hook, so the memory is read off
the two events a hook does see: the call was asked about, and then it ran.
These pin the primitives the compiled dispatchers share -- what keys a call,
what makes an observation an answer, and how an answer is taken back.
"""

from pathlib import Path

from lup.policy.assets.host import (
    approvals_log,
    approval_fingerprint,
    approval_subject,
    forget_approval,
    note_asked,
    note_ran,
    remembered_approval,
)

COMMAND = "git push --delete origin topic"


def test_a_call_asked_about_and_then_run_is_remembered(tmp_path: Path) -> None:
    held = approval_fingerprint("shell", COMMAND, tmp_path)
    assert remembered_approval(tmp_path, held) == ""

    note_asked(tmp_path, held, "shell", COMMAND)
    assert remembered_approval(tmp_path, held) == ""

    when = note_ran(tmp_path, held)
    assert when
    assert remembered_approval(tmp_path, held) == when


def test_a_call_that_ran_without_being_asked_is_not_remembered(tmp_path: Path) -> None:
    """A rule permitted it; nobody decided anything worth remembering."""
    held = approval_fingerprint("shell", COMMAND, tmp_path)

    assert note_ran(tmp_path, held) == ""
    assert remembered_approval(tmp_path, held) == ""
    assert not approvals_log(tmp_path).exists()


def test_forgetting_makes_the_next_identical_call_ask_again(tmp_path: Path) -> None:
    held = approval_fingerprint("shell", COMMAND, tmp_path)
    note_asked(tmp_path, held, "shell", COMMAND)
    note_ran(tmp_path, held)

    assert forget_approval(tmp_path, held)
    assert remembered_approval(tmp_path, held) == ""
    assert not forget_approval(tmp_path, held)
    # The log is append-only: nothing was erased, the standing moved.
    assert len(approvals_log(tmp_path).read_text().splitlines()) == 3


def test_asking_twice_before_an_answer_writes_one_standing(tmp_path: Path) -> None:
    held = approval_fingerprint("shell", COMMAND, tmp_path)
    note_asked(tmp_path, held, "shell", COMMAND)
    note_asked(tmp_path, held, "shell", COMMAND)

    assert len(approvals_log(tmp_path).read_text().splitlines()) == 1


def test_the_same_text_elsewhere_or_of_another_kind_is_another_call(
    tmp_path: Path,
) -> None:
    here = approval_fingerprint("shell", COMMAND, tmp_path / "a")
    assert here != approval_fingerprint("shell", COMMAND, tmp_path / "b")
    assert here != approval_fingerprint("fetch", COMMAND, tmp_path / "a")
    assert here == approval_fingerprint("shell", COMMAND, tmp_path / "a")


def test_the_memory_keys_a_command_and_a_fetch_under_either_runtimes_name() -> None:
    """Only the judged text: a description or a prompt beside it is not the call."""
    assert approval_subject("Bash", {"command": "ls", "description": "list"}) == {
        "kind": "shell",
        "text": "ls",
    }
    assert approval_subject("WebFetch", {"url": "https://x.test/", "prompt": "p"}) == {
        "kind": "fetch",
        "text": "https://x.test/",
    }
    assert approval_subject("web_fetch", {"url": "https://x.test/"}) == {
        "kind": "fetch",
        "text": "https://x.test/",
    }
    assert approval_subject("Edit", {"file_path": "a.py"}) is None
    assert approval_subject("Bash", {}) is None


def test_a_line_that_is_not_a_record_is_skipped(tmp_path: Path) -> None:
    held = approval_fingerprint("shell", COMMAND, tmp_path)
    note_asked(tmp_path, held, "shell", COMMAND)
    with approvals_log(tmp_path).open("a", encoding="utf-8") as sink:
        sink.write("not json\n{}\n")

    assert note_ran(tmp_path, held)
    assert remembered_approval(tmp_path, held)
