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

from lup.policy.grants import allowance_grants_environment, write_allowance_grants
from lup.policy.identity import AGENT_IDENTITY_ENV, ConcernAllowance
from lup.types import EnvVars, JsonObject
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


def test_a_call_placed_outside_the_sandbox_is_allowed_and_rewritten() -> None:
    """The unprompted placement, emitted by the script a session really runs.

    A remote read is unusable confined, so the vocabulary places it outside;
    the verdict stays an allow and the placement rides the rewrite channel.
    The rewrite has to carry the whole input rather than the flag alone,
    because it replaces the arguments instead of merging into them.
    """
    decision = decide(bash_payload("git ls-remote origin HEAD"))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "allow"
    assert specific["updatedInput"] == {
        "command": "git ls-remote origin HEAD",
        "dangerouslyDisableSandbox": True,
    }


def test_an_unplaced_call_carries_no_rewrite_at_all() -> None:
    """Saying nothing about the sandbox must not restate the session's own mode.

    An `updatedInput` on every call would make the dispatcher the author of a
    placement it never decided, and the rewrite replaces the arguments — so a
    verdict with nothing to say about where the call runs says nothing.
    """
    decision = decide(bash_payload("ls"))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "allow"
    assert "updatedInput" not in specific


NEW_DEVTOOLS_MODULE = write_payload(
    "src/lup_template/devtools/harness/newborn_probe.py", '"""Newborn."""\n'
)
"""Creating a devtools module: the gate a `new-devtools-module` grant opens."""


def session_environment(document: Path | None) -> EnvVars:
    """The whole environment one worker session is launched with, and keeps.

    Nothing is inherited, so an operator with either variable exported cannot
    decide the outcome of an assertion below. The grants variable names a
    document; what that document says is not part of the environment, and is
    free to change while the session runs.
    """
    return {
        AGENT_IDENTITY_ENV: "resolver-worker",
        **allowance_grants_environment(document),
    }


def effect_under(payload: JsonObject, environment: EnvVars) -> str:
    """The verdict the deployed dispatcher returns for one launched session."""
    output = str(
        sh.Command("python3")(
            "-I",
            "-S",
            str(DISPATCHER),
            _in=json.dumps(payload),
            _env=environment,
        )
    )
    specific = json.loads(output)["hookSpecificOutput"]
    assert isinstance(specific, dict)
    return str(specific["permissionDecision"])


def test_a_grant_made_after_a_session_started_releases_its_very_next_call(
    tmp_path: Path,
) -> None:
    """The environment never changes here; only the human's answer does.

    This is the whole point of reading at judgment. A worker that discovers
    mid-flight that it needs a gate asks, a human answers while that session
    is still running, and the answer has to reach the process that asked —
    which an allowance rendered into the environment at launch could not do.
    """
    document = tmp_path / "grants.json"
    launched = session_environment(document)
    assert effect_under(NEW_DEVTOOLS_MODULE, launched) == "ask"

    write_allowance_grants(document, [ConcernAllowance.NEW_DEVTOOLS_MODULE])

    assert effect_under(NEW_DEVTOOLS_MODULE, launched) == "allow"


def test_a_grant_taken_back_stops_releasing_its_gate_just_as_immediately(
    tmp_path: Path,
) -> None:
    """Symmetric by construction: the document is read, not remembered."""
    document = tmp_path / "grants.json"
    launched = session_environment(document)
    write_allowance_grants(document, [ConcernAllowance.NEW_DEVTOOLS_MODULE])
    assert effect_under(NEW_DEVTOOLS_MODULE, launched) == "allow"

    write_allowance_grants(document, [])

    assert effect_under(NEW_DEVTOOLS_MODULE, launched) == "ask"


def test_a_grant_made_before_the_session_started_is_honoured_too(
    tmp_path: Path,
) -> None:
    """A gate approved with the plan reaches the lease by the same route."""
    document = tmp_path / "grants.json"
    write_allowance_grants(document, [ConcernAllowance.NEW_DEVTOOLS_MODULE])

    assert effect_under(NEW_DEVTOOLS_MODULE, session_environment(document)) == "allow"


def test_a_session_holding_no_grant_sees_the_unchanged_lattice(
    tmp_path: Path,
) -> None:
    """Naming no document, and naming an empty one, both grant nothing."""
    empty = tmp_path / "grants.json"
    write_allowance_grants(empty, [])

    assert effect_under(NEW_DEVTOOLS_MODULE, session_environment(None)) == "ask"
    assert effect_under(NEW_DEVTOOLS_MODULE, session_environment(empty)) == "ask"


def test_one_leases_grant_cannot_release_a_siblings_gate(tmp_path: Path) -> None:
    """A session reads the document it was pointed at and no other."""
    write_allowance_grants(
        tmp_path / "sibling.json", [ConcernAllowance.NEW_DEVTOOLS_MODULE]
    )

    launched = session_environment(tmp_path / "mine.json")

    assert effect_under(NEW_DEVTOOLS_MODULE, launched) == "ask"


def test_a_stale_environment_cannot_grant_what_the_document_does_not(
    tmp_path: Path,
) -> None:
    """The retired variable is inert, so there is one answer and not two.

    An allowance carried as a value in the environment outlives whatever
    decided it. Left readable it would be a second source for a fact that has
    one, and the one it disagreed with would be the live one.
    """
    document = tmp_path / "grants.json"
    write_allowance_grants(document, [])
    launched = {
        **session_environment(document),
        "LUP_CONCERN_ALLOWANCES": '["new-devtools-module"]',
    }

    assert effect_under(NEW_DEVTOOLS_MODULE, launched) == "ask"
