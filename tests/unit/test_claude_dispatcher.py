"""The generated Claude permission dispatcher, executed for real.

The dispatcher is the only thing a live session actually runs, so a defect
there is invisible to every test that exercises the kernel directly. These
run the emitted script on a fresh interpreter with JSON on stdin, the way
the harness invokes it.
"""

import json
from pathlib import Path

import pytest
import sh

from lup.types import JsonObject
from tests.unit.repos import initialized_repo

DISPATCHER = Path(".claude/plugins/lup/hooks/scripts/policy.py")


def decide(payload: object) -> dict[str, object]:  # lup: ignore[dict-str-payload]
    """Run the generated dispatcher over one hook payload."""
    output = str(
        sh.Command("python3")("-I", "-S", str(DISPATCHER), _in=json.dumps(payload))
    )
    return json.loads(output)


def edit_payload(path: str, old: str, new: str, replace_all: bool) -> object:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": path,
            "old_string": old,
            "new_string": new,
            "replace_all": replace_all,
        },
    }


def test_a_replace_all_edit_is_judged_rather_than_refused() -> None:
    """Every occurrence is spliced, so the rules decide instead of erroring.

    Requiring the preimage to occur exactly once rejected `replace_all`'s own
    semantics, and the rejection surfaced as an approval prompt no rule
    produced — leaving the whole class of multi-site edit ungoverned.
    """
    decision = decide(
        edit_payload(
            "packages/lup/tests/unit/test_path_roles.py", "PathRoleRow", "RoleRow", True
        )
    )
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "allow"
    assert specific["permissionDecisionReason"] == "small safe edit"


def test_a_preimage_that_is_absent_is_still_a_malformed_edit() -> None:
    decision = decide(
        edit_payload(
            "packages/lup/tests/unit/test_path_roles.py", "no-such-text", "x", True
        )
    )
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "ask"
    assert "does not occur" in str(specific["permissionDecisionReason"])


def test_an_ambiguous_single_edit_still_requires_an_unambiguous_preimage() -> None:
    """Without `replace_all` the exactly-once requirement is the tool's own."""
    decision = decide(
        edit_payload(
            "packages/lup/tests/unit/test_path_roles.py",
            "PathRoleRow",
            "RoleRow",
            False,
        )
    )
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "ask"
    assert "exactly once" in str(specific["permissionDecisionReason"])


def test_a_declared_test_root_is_not_judged_against_production_conventions() -> None:
    """The role reaches the deployed dispatcher, not just the kernel.

    One identical edit, two roots: the conventions describe how production
    reads, and a test's subject is production's behaviour rather than its
    own shape.
    """
    shared = "from lup.policy.kernel.roles import path_role"
    production = decide(
        edit_payload(
            "packages/lup/src/lup/devtools/dev/antipatterns.py",
            shared,
            "from typing import Any",
            False,
        )
    )
    under_test = decide(
        edit_payload(
            "packages/lup/tests/unit/test_path_roles.py",
            shared,
            "from typing import Any",
            False,
        )
    )
    denied = production["hookSpecificOutput"]
    allowed = under_test["hookSpecificOutput"]
    assert isinstance(denied, dict)
    assert isinstance(allowed, dict)
    assert denied["permissionDecision"] == "deny"
    assert allowed["permissionDecision"] == "allow"


def test_an_overwide_suppression_is_placed_rather_than_left_to_the_author() -> None:
    """The gate rewrites the call instead of making the author budget columns.

    An inline directive whose reason outgrows the line is what pushes an agent
    to shorten an identifier to buy room. The hook moves it onto the line
    above, so the reason survives whole and nobody had to choose.
    """
    reason = "a justification long enough that keeping it inline outgrows the line"
    decision = decide(
        edit_payload(
            "packages/lup/src/lup/devtools/dev/antipatterns.py",
            "from lup.devtools.utils import git, output_json",
            f"from typing import Any  # lup: ignore[any-type] — {reason}",
            False,
        )
    )

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    placed = specific["updatedInput"]
    assert isinstance(placed, dict)
    assert placed["new_string"] == (
        f"# lup: ignore[any-type] — {reason}\nfrom typing import Any"
    )


def test_a_suppression_that_fits_is_left_exactly_where_it_was_written() -> None:
    """Placing is a normal form, so what is already canonical is not touched."""
    decision = decide(
        edit_payload(
            "packages/lup/src/lup/devtools/dev/antipatterns.py",
            "from lup.devtools.utils import git, output_json",
            "from typing import Any  # lup: ignore[any-type] — at a boundary",
            False,
        )
    )

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert "updatedInput" not in specific


def write_payload(path: str, content: str) -> JsonObject:
    """One Write hook payload, the way a live session sends it."""
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def decide_from(
    payload: JsonObject, cwd: Path
) -> dict[str, object]:  # lup: ignore[dict-str-payload]
    """Run the dispatcher from a working directory that is not the repo."""
    output = str(
        sh.Command("python3")(
            "-I",
            "-S",
            str(DISPATCHER.resolve()),
            _in=json.dumps(payload),
            _cwd=str(cwd),
        )
    )
    return json.loads(output)


def test_absolute_paths_resolve_against_their_worktree_not_the_launch_directory() -> (
    None
):
    """A session always sends absolute paths, and may be launched anywhere.

    Every repo-relative rule matches on the relativized path, so anchoring it
    on the working directory decides policy by where the runtime happened to
    start: from a sibling directory nothing matched, which left the role
    relaxations off and — far worse — let a protected path through.
    """
    root = Path(".").resolve()
    outside = root.parent
    protected = decide_from(
        write_payload(str(root / "README.md"), "# replaced\n"), outside
    )
    under_test = decide_from(
        write_payload(str(root / "tests" / "unit" / "probe.py"), "x = {}\n"), outside
    )
    asked = protected["hookSpecificOutput"]
    allowed = under_test["hookSpecificOutput"]
    assert isinstance(asked, dict)
    assert isinstance(allowed, dict)
    assert asked["permissionDecision"] == "ask"
    assert allowed["permissionDecision"] == "allow"


def bash_payload(command: str) -> JsonObject:
    """One Bash hook payload, the way a live session sends it."""
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def effect_from(command: str, cwd: Path) -> tuple[str, str]:
    """The effect and reason the emitted dispatcher returns for one command."""
    specific = decide_from(bash_payload(command), cwd)["hookSpecificOutput"]
    assert isinstance(specific, dict)
    return str(specific["permissionDecision"]), str(
        specific["permissionDecisionReason"]
    )


@pytest.fixture
def delete_repo(tmp_path: Path) -> Path:
    """A repository holding one committed file of each kind that matters."""
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    git = initialized_repo(work, tmp_path / "no-hooks")
    for index in range(8):
        (work / "src" / f"file{index}.py").write_text("value = 1\n", encoding="utf-8")
    git("add", "src")
    git("commit", "-m", "chore: base")
    (work / "untracked.py").write_text("value = 2\n", encoding="utf-8")
    return work


def test_removing_a_committed_unmodified_file_is_granted(delete_repo: Path) -> None:
    """Git holds exactly what is on disk, so the delete costs a checkout.

    The kernel reads no filesystem and runs no Git, so this only passes when
    the emitted script resolved recoverability itself and handed it over.
    """
    effect, _reason = effect_from("rm src/file0.py", delete_repo)

    assert effect == "allow"


def test_removing_an_untracked_file_still_asks(delete_repo: Path) -> None:
    """Nothing holds a copy, so nothing could restore it afterwards."""
    effect, _reason = effect_from("rm untracked.py", delete_repo)

    assert effect == "ask"


def test_removing_a_directory_asks_and_names_the_way_through(
    delete_repo: Path,
) -> None:
    """Nothing in the command bounds what a directory holds, however clean.

    The refusal has to say what is open instead, or the agent reads a delete
    it expected to pass as an unexplained wall.
    """
    effect, reason = effect_from("rm -rf src", delete_repo)

    assert effect == "ask"
    assert "name the files instead" in reason


def test_a_sweep_of_restorable_files_asks_even_though_each_is_restorable(
    delete_repo: Path,
) -> None:
    """Restoring is a repair somebody has to know to perform.

    Every file here is committed and clean, so the per-file grant would take
    all of them; past the declared limit the delete reads as a sweep instead.
    """
    named = " ".join(f"src/file{index}.py" for index in range(8))

    effect, _reason = effect_from(f"rm {named}", delete_repo)

    assert effect == "ask"


def test_writing_a_generated_plugin_tree_is_refused_by_absolute_path(
    delete_repo: Path,
) -> None:
    """A session sends whatever spelling it likes, and may run anywhere.

    Recognizing only the repo-relative spelling would fail open on exactly
    the form that reaches past the worktree the runtime started in.
    """
    outside = delete_repo / ".claude" / "plugins" / "lup" / "hooks" / "policy.py"

    effect, reason = effect_from(f"rm {outside}", delete_repo)

    assert effect == "deny"
    assert "harness generate all" in reason


def test_an_unreadable_target_asks_instead_of_letting_the_edit_through() -> None:
    """Reading the edited file is part of judging it, so a read failure asks.

    `OSError` sat outside the handled set, so an unreadable target raised past
    it and the script died with a traceback. That exit reaches PreToolUse as a
    non-blocking error, which lets the very call the dispatcher could not judge
    proceed — the inverse of the property this boundary exists to hold.
    """
    decision = decide(edit_payload("packages/lup/src/lup/absent.py", "a", "b", False))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "ask"
