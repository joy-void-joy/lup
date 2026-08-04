"""The generated Claude permission dispatcher, executed for real.

The dispatcher is the only thing a live session actually runs, so a defect
there is invisible to every test that exercises the kernel directly. These
run the emitted script on a fresh interpreter with JSON on stdin, the way
the harness invokes it.
"""

import json
from pathlib import Path

import sh

from lup.types import JsonObject

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
        edit_payload("tests/unit/test_path_roles.py", "PathRoleRow", "RoleRow", True)
    )
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "allow"
    assert specific["permissionDecisionReason"] == "small safe edit"


def test_a_preimage_that_is_absent_is_still_a_malformed_edit() -> None:
    decision = decide(
        edit_payload("tests/unit/test_path_roles.py", "no-such-text", "x", True)
    )
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "ask"
    assert "does not occur" in str(specific["permissionDecisionReason"])


def test_an_ambiguous_single_edit_still_requires_an_unambiguous_preimage() -> None:
    """Without `replace_all` the exactly-once requirement is the tool's own."""
    decision = decide(
        edit_payload("tests/unit/test_path_roles.py", "PathRoleRow", "RoleRow", False)
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
            "src/lup_template/devtools/dev/antipatterns.py",
            shared,
            "from typing import Any",
            False,
        )
    )
    under_test = decide(
        edit_payload(
            "tests/unit/test_path_roles.py",
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
