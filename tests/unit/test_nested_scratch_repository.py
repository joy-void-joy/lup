"""A repository nested under this checkout's scratch is scratch, on every surface.

A probe kit is a throwaway project under `tmp/` given its own `git init`, so a
runtime launched inside it takes the kit as its project root rather than this
repository. That `.git` is also what the foreign-repository referral reads,
and it made every file in the kit "a different repository": each edit, each
redirect into it and each command's output landing there put a question to
the operator about a file nothing reviews — on both runtimes, and in the
preview that answers for them.

Every surface is driven here the way a session drives it — each runtime's
generated dispatcher run on the payload its harness sends, and `dev policy`'s
own reading — against one layout holding the kit and every repository that
keeps its question: one nested in the checkout outside any scratch root, one
beside the checkout, the same one reached through a `refs/` link, and a kit
under a sibling worktree's scratch.
"""

import json
import os
import sys
from pathlib import Path
from typing import Literal

import pytest
import sh

from lup.devtools.dev.policy_explain import verdict_for
from lup.harness.enforcement import declared_role_rows
from lup.policy.models import EditBatch, EditChange, ShellCommand
from lup.policy.rules import ShellPolicy
from lup.types import JsonObject
from lup_template.harness.catalog import declared_hook_set
from tests.unit.native import codex_denial
from tests.unit.repos import commit_file, initialized_repo

type Runtime = Literal["claude", "codex"]

DISPATCHERS: dict[Runtime, Path] = {
    "claude": Path(".claude/plugins/lup/hooks/scripts/policy.py"),
    "codex": Path(".codex/plugins/lup/hooks/scripts/policy.py"),
}

PREIMAGE = "value = 1"

REFUSED = "from typing import Any"
"""A line production refuses, so an allow is scratch answering, not a pass."""

KIT = "checkout/tmp/kit/probe.py"
"""The file this is about: inside a probe kit, under the checkout's `tmp/`."""

KEEPS_ITS_QUESTION = [
    pytest.param("checkout/vendor/lib/probe.py", id="nested-outside-scratch"),
    pytest.param("elsewhere/src/probe.py", id="beside-the-checkout"),
    pytest.param("elsewhere/tmp/probe.py", id="another-repositorys-own-tmp"),
    pytest.param("checkout/refs/elsewhere/src/probe.py", id="refs-link"),
    pytest.param("checkout/refs/elsewhere/tmp/probe.py", id="refs-link-into-tmp"),
    pytest.param("sibling/tmp/kit/probe.py", id="sibling-worktree-scratch"),
]
"""Every repository the checkout's scratch does not hold, spelled from the base.

`elsewhere/tmp/` is the one a precedence read off the wrong spelling would
open: against its own checkout it reads `tmp/probe.py`, which is exactly how
this repository declares scratch.
"""


@pytest.fixture(params=["claude", "codex"])
def runtime(request: pytest.FixtureRequest) -> Runtime:
    return request.param


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """The checkout a session works in, and every repository around it."""
    hooks = tmp_path / "no-hooks"
    checkout = tmp_path / "checkout"
    git = initialized_repo(checkout, hooks)
    commit_file(git, checkout, "README.md", "checkout\n", "chore: base")
    git("worktree", "add", "-b", "sibling", str(tmp_path / "sibling"))
    for nested in (
        "checkout/tmp/kit",
        "checkout/vendor/lib",
        "elsewhere",
        "sibling/tmp/kit",
    ):
        initialized_repo(tmp_path / nested, hooks)
    (checkout / "refs").mkdir()
    (checkout / "refs" / "elsewhere").symlink_to(tmp_path / "elsewhere")
    for held in (
        KIT,
        "checkout/vendor/lib/probe.py",
        "elsewhere/src/probe.py",
        "elsewhere/tmp/probe.py",
        "sibling/tmp/kit/probe.py",
    ):
        (tmp_path / held).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / held).write_text(f"{PREIMAGE}\n", encoding="utf-8")
    return tmp_path


def dispatched(runtime: Runtime, payload: JsonObject, base: Path) -> sh.RunningCommand:
    """One runtime's generated dispatcher, run on a payload as its harness runs it."""
    result = sh.Command(sys.executable)(
        "-I",
        "-S",
        str(DISPATCHERS[runtime].resolve()),
        _in=json.dumps(payload),
        _ok_code=[0, 2],
        _return_cmd=True,
        _env={**os.environ, "PLUGIN_DATA": str(base / "plugin-data")},
    )
    assert isinstance(result, sh.RunningCommand)
    return result


def verdict(runtime: Runtime, payload: JsonObject, base: Path) -> tuple[str, str]:
    """The effect a session meets before the call runs, and the reason it reads.

    Codex has no ask at this boundary: it parks the question as a review and
    answers with a structured refusal naming who can release it, which is the
    same question put where Codex can carry one. Only exit 2 is a refusal.
    """
    result = dispatched(runtime, payload, base)
    if runtime == "codex":
        if result.exit_code == 2:
            return "deny", result.stderr.decode()
        if not result.stdout:
            return "allow", ""
        return "ask", codex_denial(result)
    specific = json.loads(str(result))["hookSpecificOutput"]
    return str(specific["permissionDecision"]), str(
        specific["permissionDecisionReason"]
        if "permissionDecisionReason" in specific
        else ""
    )


def session(base: Path) -> str:
    """Where every call here is made from: the checkout holding the kit."""
    return str(base / "checkout")


def edit(runtime: Runtime, target: Path, base: Path) -> JsonObject:
    """One edit of *target* that production refuses, as each runtime carries it."""
    call: JsonObject = (
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": PREIMAGE,
                "new_string": REFUSED,
            },
        }
        if runtime == "claude"
        else {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    f"*** Begin Patch\n*** Update File: {target}\n"
                    f"@@\n-{PREIMAGE}\n+{REFUSED}\n*** End Patch"
                )
            },
        }
    )
    return {
        "session_id": "kit-probe",
        "hook_event_name": "PreToolUse",
        "cwd": session(base),
        **call,
    }


def created(runtime: Runtime, target: Path, base: Path) -> JsonObject:
    """One new file at *target*, whole, as each runtime carries a creation.

    Production asks about any file arriving whole, so an allow here is the
    scratch role answering for the file rather than the size of the change.
    """
    lines = [REFUSED, "value: Any = 1"]
    call: JsonObject = (
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "\n".join(lines)},
        }
        if runtime == "claude"
        else {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "\n".join(
                    [
                        "*** Begin Patch",
                        f"*** Add File: {target}",
                        *(f"+{line}" for line in lines),
                        "*** End Patch",
                    ]
                )
            },
        }
    )
    return {
        "session_id": "kit-probe",
        "hook_event_name": "PreToolUse",
        "cwd": session(base),
        **call,
    }


def shell(event: str, command: str, base: Path) -> JsonObject:
    """One shell call at *event*, as both runtimes carry it."""
    return {
        "session_id": "kit-probe",
        "hook_event_name": event,
        "cwd": session(base),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def reported(runtime: Runtime, command: str, base: Path) -> str:
    """What one runtime's review of a command that already ran tells the agent."""
    result = dispatched(runtime, shell("PostToolUse", command, base), base)
    if runtime == "codex":
        return result.stderr.decode() if result.exit_code == 2 else ""
    answered = json.loads(str(result))
    return str(answered["reason"]) if "reason" in answered else ""


def test_an_edit_inside_a_kit_under_scratch_is_scratch(
    runtime: Runtime, base: Path
) -> None:
    assert verdict(runtime, edit(runtime, base / KIT, base), base)[0] == "allow"


def test_a_file_created_inside_a_kit_under_scratch_is_scratch(
    runtime: Runtime, base: Path
) -> None:
    inside = created(runtime, base / "checkout/tmp/kit/hooks/record.py", base)
    beside = created(runtime, base / "elsewhere/new.py", base)

    assert verdict(runtime, inside, base)[0] == "allow"
    effect, reason = verdict(runtime, beside, base)
    assert effect == "ask"
    assert "different repository" in reason


@pytest.mark.parametrize("spelled", KEEPS_ITS_QUESTION)
def test_a_repository_this_checkouts_scratch_does_not_hold_keeps_its_question(
    runtime: Runtime, base: Path, spelled: str
) -> None:
    effect, reason = verdict(runtime, edit(runtime, base / spelled, base), base)

    assert effect == "ask"
    assert "different repository" in reason


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("echo hello > tmp/kit/run.log", id="redirect"),
        pytest.param("sed -i 's/1/2/' tmp/kit/probe.py", id="rewrite-in-place"),
    ],
)
def test_a_shell_write_into_the_kit_is_scratch(
    runtime: Runtime, base: Path, command: str
) -> None:
    assert verdict(runtime, shell("PreToolUse", command, base), base)[0] == "allow"


@pytest.mark.parametrize(
    ("command", "asked"),
    [
        pytest.param(
            "echo hello > refs/elsewhere/tmp/run.log",
            "different repository",
            id="through-refs",
        ),
        # Creating a file outside the checkout is asked about before the
        # content gates are, and that question is the one this keeps.
        pytest.param(
            "echo hello > ../elsewhere/src/run.log", "an outside path", id="beside"
        ),
    ],
)
def test_a_shell_write_into_another_repository_keeps_its_question(
    runtime: Runtime, base: Path, command: str, asked: str
) -> None:
    effect, reason = verdict(runtime, shell("PreToolUse", command, base), base)

    assert effect == "ask"
    assert asked in reason


def test_a_command_writing_into_the_kit_is_not_reported_afterwards(
    runtime: Runtime, base: Path
) -> None:
    """The output a command leaves in the kit is scratch once it has landed too."""
    (base / "checkout/tmp/kit/run.log").write_text("ran\n", encoding="utf-8")

    assert reported(runtime, "date > tmp/kit/run.log", base) == ""


def test_a_command_writing_into_another_repository_is_still_reported(
    runtime: Runtime, base: Path
) -> None:
    (base / "elsewhere/src/run.log").write_text("ran\n", encoding="utf-8")

    found = reported(runtime, "date > ../elsewhere/src/run.log", base)

    assert "different repository" in found


def test_the_preview_reads_the_kit_as_scratch(base: Path) -> None:
    """`dev policy` answers for both runtimes, so it has to say what they say.

    Asked three ways: the path alone, the concrete change production refuses,
    and the shell forms that write into the kit.
    """
    checkout = base / "checkout"
    change = EditBatch(
        changes=[
            EditChange(
                path=base / KIT,
                before=f"{PREIMAGE}\n",
                after=f"{REFUSED}\n",
            )
        ]
    )
    document = base / "change.json"
    document.write_text(change.model_dump_json(), encoding="utf-8")
    readings = [
        verdict_for(subject, kind, False, checkout, declared_hook_set())
        for subject, kind in (
            (str(base / KIT), "edit"),
            (str(document), "edit-batch"),
            ("echo hello > tmp/kit/run.log", "shell"),
            ("sed -i 's/1/2/' tmp/kit/probe.py", "shell"),
        )
    ]

    assert {reading.effect for read in readings for reading in read.readings} == {
        "allow"
    }


@pytest.mark.parametrize(
    ("target", "effect"),
    [
        pytest.param("tmp/kit/probe.py", "allow", id="kit"),
        pytest.param("../elsewhere/src/probe.py", "ask", id="another-repository"),
    ],
)
def test_a_rewrite_judged_from_its_row_alone_reads_the_same(
    base: Path, target: str, effect: str
) -> None:
    """With no edit policy composed, the classifier judges a rewrite from its row.

    The row has to carry every fact the edit path reads — which repository
    holds the file, and how this checkout spells it — or the verdict would
    turn on which of the two answered. A target spelled relative to the
    session is anchored there before its repository is asked for: read bare,
    it named none, and a rewrite of another repository's file was judged by
    this one's conventions instead of meeting the referral.
    """
    hooks = declared_hook_set()
    classifier = ShellPolicy(
        hooks.resolved_shell_rules(),
        path_roles=declared_role_rows(list(hooks.path_roles)),
    )
    command = f"sed -i 's/{PREIMAGE}/{REFUSED}/' {target}"

    decided = classifier.decide(ShellCommand(command=command, cwd=base / "checkout"))

    assert decided.effect == effect
    if effect == "ask":
        assert "different repository" in decided.reason


@pytest.mark.parametrize("spelled", KEEPS_ITS_QUESTION)
def test_the_preview_keeps_every_other_repositorys_question(
    base: Path, spelled: str
) -> None:
    previewed = verdict_for(
        str(base / spelled), "edit", False, base / "checkout", declared_hook_set()
    )

    assert {reading.effect for reading in previewed.readings} == {"ask"}
    assert all(
        "different repository" in reading.reason for reading in previewed.readings
    )
