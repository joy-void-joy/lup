"""Asking the policy about a command that cannot be an argument.

An escalation marker has to lead the command it promotes, so the command
carrying one spans two lines and cannot be spelled as one argument without
putting the marker inside the shell line that asks the question. What is
pinned here is that the same verdict is reachable from a file and from a
pipe, and that a command named twice or not at all is refused rather than
guessed at.
"""

from pathlib import Path

from typer.testing import CliRunner

from lup.devtools.hooks.app import create_hooks_app
from lup.harness.models import HookSet
from lup.policy.everyday import CommandFamily

HOOKS = HookSet(
    id="test",
    policy_ids=["shell"],
    everyday_commands=[
        CommandFamily(what="asking git what happened", commands=["git status"])
    ],
)
"""A declaration holding a table that answers for ordinary read commands."""

ESCALATED = "# lup: escalate[sandbox]: the host holds the socket\nls /run/lup\n"
"""A command whose leading line is the marker that promotes its refusal."""

runner = CliRunner()


def classify(*arguments: str, stdin: str | None = None) -> str:
    """Run one classification and hand back everything it printed."""
    return runner.invoke(
        create_hooks_app(lambda: HOOKS), ["classify", *arguments], input=stdin
    ).output


def test_file_carries_a_command_an_argument_cannot(tmp_path: Path) -> None:
    """A multi-line command reaches the policy through a path."""
    script = tmp_path / "escalated.sh"
    script.write_text(ESCALATED, encoding="utf-8")
    assert "escalate[sandbox]" in classify("--file", str(script))


def test_stdin_reaches_the_same_verdict(tmp_path: Path) -> None:
    """`-` names the stream, and answers what the file answered."""
    script = tmp_path / "escalated.sh"
    script.write_text(ESCALATED, encoding="utf-8")
    assert classify("--file", "-", stdin=ESCALATED) == classify("--file", str(script))


def test_naming_the_command_twice_is_refused(tmp_path: Path) -> None:
    """Two spellings have no answer to which one was meant."""
    script = tmp_path / "escalated.sh"
    script.write_text(ESCALATED, encoding="utf-8")
    assert "name the command once" in classify("git status", "--file", str(script))


def test_naming_no_command_is_refused() -> None:
    """Neither spelling leaves nothing to classify."""
    assert "name the command once" in classify()


def test_an_argument_still_classifies() -> None:
    """The route every caller already uses is untouched."""
    assert "git status" in classify("git status")


def test_sweep_reads_a_list_from_stdin() -> None:
    """The list a sweep judges arrives the same two ways one command does."""
    result = runner.invoke(
        create_hooks_app(lambda: HOOKS), ["sweep", "-"], input="git status\n"
    )
    assert result.exit_code == 0
    assert "git status" in result.output
