"""The shell guard wrapped around every compiled dispatcher, executed for real.

The guard is the only part of the permission boundary that runs when the
dispatcher does not, so nothing that exercises the script itself can reach it.
These run the emitted command line through a real shell against a plugin root
holding a stand-in dispatcher, the way a native runtime invokes it.

A build product that will not start is the case that matters: a merge writing
conflict markers into the generated tree leaves a script the interpreter
cannot parse, and every routed tool -- the shell command that would abort the
merge included -- comes back refused. Refusing is right, since a script that
cannot judge is the one thing no boundary may read as permission. What the
cases below pin is that the refusal says which file broke, that it is
compiled rather than written, and what rebuilds it.
"""

from pathlib import Path

import pytest
import sh

from lup.formats.banner import REGENERATE_COMMAND
from lup.policy.dispatcher import REFUSAL_STATUS, guarded_hook_command

PLUGIN_ROOT_ENV = "LUP_TEST_PLUGIN_ROOT"

CONFLICTED = """#!/usr/bin/env python3
<<<<<<< HEAD
x = 1
=======
x = 2
>>>>>>> feature
"""
"""What a text merge leaves in a generated dispatcher it was allowed to merge."""

REFUSING = """#!/usr/bin/env python3
import sys

sys.stderr.write("lup policy: git push is refused by rule")
raise SystemExit(2)
"""
"""A dispatcher that ran, judged, and refused -- the verdict the guard passes."""

ALLOWING = """#!/usr/bin/env python3
import json
import sys

json.dump({"hookSpecificOutput": {"permissionDecision": "allow"}}, sys.stdout)
"""

CRASHING = """#!/usr/bin/env python3
raise RuntimeError("the kernel package is not beside the script")
"""


def guarded(root: Path) -> sh.RunningCommand:
    """Run the real guarded command with this directory as the plugin root."""
    return sh.Command("sh")(
        "-c",
        guarded_hook_command(PLUGIN_ROOT_ENV),
        _env={"PATH": "/usr/bin:/bin:/usr/local/bin", PLUGIN_ROOT_ENV: str(root)},
        _in="{}",
        _ok_code=list(range(128)),
        _tty_out=False,
        _return_cmd=True,
    )


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    (tmp_path / "hooks" / "scripts").mkdir(parents=True)
    return tmp_path


def install(root: Path, body: str) -> Path:
    script = root / "hooks" / "scripts" / "policy.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_a_conflicted_dispatcher_names_the_build_product_and_its_rebuild(
    plugin_root: Path,
) -> None:
    """The lockout case: markers in the tree, and no route out from inside."""
    script = install(plugin_root, CONFLICTED)

    done = guarded(plugin_root)

    assert done.exit_code == REFUSAL_STATUS
    complaint = str(done.stderr, "utf-8")
    assert "SyntaxError" in complaint
    assert str(script) in complaint
    assert "generated build product" in complaint
    assert REGENERATE_COMMAND in complaint
    assert "git merge --abort" in complaint


def test_a_dispatcher_that_is_not_there_refuses_out_loud(plugin_root: Path) -> None:
    """An absent script exits the refusal status too, and said nothing about it."""
    done = guarded(plugin_root)

    assert done.exit_code == REFUSAL_STATUS
    complaint = str(done.stderr, "utf-8")
    assert "no dispatcher at" in complaint
    assert REGENERATE_COMMAND in complaint


def test_a_dispatcher_that_crashed_is_told_the_same_thing(plugin_root: Path) -> None:
    """A refusal is the only non-zero exit either dispatcher takes deliberately."""
    install(plugin_root, CRASHING)

    done = guarded(plugin_root)

    assert done.exit_code == REFUSAL_STATUS
    complaint = str(done.stderr, "utf-8")
    assert "the kernel package is not beside the script" in complaint
    assert REGENERATE_COMMAND in complaint


def test_a_deliberate_refusal_carries_nothing_but_its_own_reason(
    plugin_root: Path,
) -> None:
    """A verdict is not a broken build product, and must not read as one."""
    install(plugin_root, REFUSING)

    done = guarded(plugin_root)

    assert done.exit_code == REFUSAL_STATUS
    assert str(done.stderr, "utf-8") == "lup policy: git push is refused by rule"


def test_a_judged_call_passes_through_the_guard_untouched(plugin_root: Path) -> None:
    """The guard is a wrapper, so an answered call has to reach the host whole."""
    install(plugin_root, ALLOWING)

    done = guarded(plugin_root)

    assert done.exit_code == 0
    assert str(done.stderr, "utf-8") == ""
    assert "allow" in str(done.stdout, "utf-8")
