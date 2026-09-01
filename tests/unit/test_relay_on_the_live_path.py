"""The question the dispatcher reaches is the question the queue holds.

The relay being "one authority" is a claim about the *live* path or it is not
a claim at all: a record only the in-process seam wrote would be a store the
compiled dispatcher does not use, and the compiled dispatcher is what a native
session actually runs.

So this drives the emitted script — not a renderer, not the canonical policy —
and reads the queue back through the surface a reviewer reads it through.
"""

import json
from pathlib import Path

import sh

from lup.devtools.dev.questions import relay

DISPATCHER = Path(".claude/plugins/lup/hooks/scripts/policy.py")


def judged(command: str, cwd: Path) -> None:
    """Put one command through the script a native session runs."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    sh.Command(str(DISPATCHER.resolve()))(
        _in=json.dumps(payload), _ok_code=[0, 2], _cwd=str(cwd), _return_cmd=True
    )


def test_a_question_the_dispatcher_reaches_is_parked_in_the_relay(
    tmp_path: Path,
) -> None:
    """Written from the boundary that reaches the verdict, so both runtimes do.

    The alternative is a queue populated only by whichever path happened to
    call the library — which is the shape that makes "every final ask is
    recorded" true of some asks.
    """
    judged("git push --delete origin feat", tmp_path)

    parked = relay(tmp_path).questions()

    assert [entry.state for entry in parked] == ["pending"]
    assert "removing a remote ref" in parked[0].reason


def test_a_parked_question_carries_the_rule_that_asked_it(tmp_path: Path) -> None:
    """A queue of unattributable questions is one nobody can tune.

    The reviewer reading it needs to know which gate produced it — and the
    person answering the same question for the third time needs somewhere to
    go and change it.
    """
    judged("git push --delete origin feat", tmp_path)

    parked = relay(tmp_path).questions()[0]

    assert parked.rule == "shell:git.push"
    assert parked.requirement == "human_only"


def test_the_same_question_twice_folds_to_one_record(tmp_path: Path) -> None:
    """A session asks the same thing repeatedly and a queue is read by a person.

    Fifty identical rows is a queue nobody reads, which is the same failure the
    undo layer's dedup exists to prevent, in the same shape.
    """
    judged("git push --delete origin feat", tmp_path)
    judged("git push --delete origin feat", tmp_path)

    assert len(relay(tmp_path).questions()) == 1


def test_a_permitted_operation_parks_nothing(tmp_path: Path) -> None:
    """The queue holds questions, and an allow asked nobody anything."""
    judged("git status", tmp_path)

    assert relay(tmp_path).questions() == []
