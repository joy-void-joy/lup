"""Behavior tests for the non-interactive agent shell environment.

Agent shells must never reach an interactive prompt (ssh passphrase, git
editor, pager); these pin that the defaults are present, that a caller's
explicit environment always wins over them, and that merging never mutates
the caller's mapping.
"""

from lup.coordination.identity import LaunchedMember
from lup.harness.environment import (
    NON_INTERACTIVE_SHELL_ENV,
    launcher_decided_names,
    non_interactive_environment,
)


def test_defaults_present_over_empty_base() -> None:
    merged = non_interactive_environment({})
    assert merged == NON_INTERACTIVE_SHELL_ENV
    assert merged["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"
    assert merged["GIT_TERMINAL_PROMPT"] == "0"


def test_base_overrides_defaults() -> None:
    base = {"GIT_SSH_COMMAND": "ssh -i /custom/key", "HOME": "/home/user"}
    merged = non_interactive_environment(base)
    assert merged["GIT_SSH_COMMAND"] == "ssh -i /custom/key"
    assert merged["HOME"] == "/home/user"
    assert merged["GIT_EDITOR"] == "true"


def test_an_inherited_virtual_environment_does_not_bind_the_child_project() -> None:
    merged = non_interactive_environment(
        {"HOME": "/home/user", "VIRTUAL_ENV": "/source/.venv"}
    )

    assert merged["HOME"] == "/home/user"
    assert "VIRTUAL_ENV" not in merged


def test_merge_does_not_mutate_base() -> None:
    base = {"HOME": "/home/user"}
    merged = non_interactive_environment(base)
    merged["GIT_PAGER"] = "less"
    assert base == {"HOME": "/home/user"}
    assert NON_INTERACTIVE_SHELL_ENV["GIT_PAGER"] == "cat"


def test_every_variable_a_launcher_mints_is_one_the_suite_takes_away() -> None:
    """The two lists have to agree, so the next one added is caught here.

    They disagreed once and the cost was not a failing test but a misleading
    one: the coordination identity was exported by every launch and cleared by
    none, so the roster's naming tests asked what a session with no name is
    called and were answered with the name of whoever ran the suite. Green on
    a machine with nothing exported, red inside every launched session, and
    red for a reason that named neither list.
    """
    minted = LaunchedMember(member_id="m", cli_name="n").environment()

    assert set(minted) <= set(launcher_decided_names({}))
