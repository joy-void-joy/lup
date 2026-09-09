"""A command written down is judged against the CLI that would run it.

Both halves are here: the surface, which answers what the app serves, and the
refusal, which is what generation does with an answer of no. The corpus scan
between them reads a checkout and is exercised by the gate that runs it.
"""

import typer
import pytest

from lup.devtools.dev.commands import CommandSurface
from lup.devtools.dev.documented import (
    WrittenCommand,
    refuse_unresolved_commands,
)
from lup.harness.models import CommandInvocation


def sample_app() -> typer.Typer:
    """A CLI with each shape the judgement has to tell apart.

    A leaf at depth one, a group that only leads somewhere, a group that runs
    on its own as well, and a leaf taking an argument — which is where a word
    spelled like a command name is not one.
    """
    app = typer.Typer()
    dev = typer.Typer(no_args_is_help=True)
    hooks = typer.Typer(no_args_is_help=True)
    report = typer.Typer(invoke_without_command=True)

    @app.command("version")
    def version_cmd() -> None:
        """Print the version."""

    @app.command("generate")
    def generate_cmd(target: str) -> None:
        """Generate one target, or all of them."""

    @hooks.command("sweep")
    def sweep_cmd() -> None:
        """Sweep the declared corpus."""

    @report.callback()
    def report_cmd() -> None:
        """Report what is left, with or without a subcommand."""

    @report.command("open")
    def report_open_cmd() -> None:
        """Report only the open items."""

    dev.add_typer(hooks, name="hooks")
    dev.add_typer(report, name="report")
    app.add_typer(dev, name="dev")
    return app


@pytest.fixture
def surface() -> CommandSurface:
    return CommandSurface.of(sample_app())


@pytest.mark.parametrize(
    ("written", "admitted"),
    [
        # The spelling that started this: a group's subcommand run together as
        # one word reaches `dev`, and `hookssweep` is nobody's child.
        ("dev hookssweep", False),
        ("dev hooks sweep", True),
        # A group named as a family names something real, even where typing it
        # alone would only print help.
        ("dev hooks", True),
        ("dev", True),
        # An argument may be spelled exactly like a command name, so past a
        # command that runs, every further word belongs to it.
        ("generate all", True),
        ("version", True),
        # A group that runs on its own, with and without the subcommand it
        # also has.
        ("dev report", True),
        ("dev report open", True),
        # Nothing at any depth.
        ("nonesuch", False),
        ("dev nonesuch", False),
    ],
)
def test_a_written_command_is_admitted_only_where_the_app_serves_it(
    surface: CommandSurface, written: str, admitted: bool
) -> None:
    assert surface.admits(written.split()) is admitted


def test_a_group_that_only_leads_somewhere_is_not_something_to_run(
    surface: CommandSurface,
) -> None:
    """The stricter question, which a declaration asks and prose does not.

    Naming `dev hooks` in a sentence is naming something real; telling a
    reader to *run* it names a command that answers with its own help. The
    two questions have different answers and one table serves both.
    """
    assert surface.runs(["dev", "hooks", "sweep"])
    assert surface.runs(["dev", "report"])
    assert not surface.runs(["dev", "hooks"])
    assert not surface.runs(["dev"])


def test_the_words_before_the_arguments_are_what_gets_resolved() -> None:
    """A mention is a command and then whatever the reader supplies.

    The path stops at the first word that is not a plain command name, so a
    module path, a flag and a placeholder are never looked up — and a word
    after one of them is not looked up either, or `--json` would be followed
    by whatever came next.
    """
    written = WrittenCommand(file="skill.md", line=1, spelled="dev py info lup.policy")
    assert written.command_words() == ["dev", "py", "info"]

    flagged = WrittenCommand(file="skill.md", line=1, spelled="dev check --json since")
    assert flagged.command_words() == ["dev", "check"]

    placeheld = WrittenCommand(
        file="skill.md", line=1, spelled="dev hooks sweep <file>"
    )
    assert placeheld.command_words() == ["dev", "hooks", "sweep"]


def test_generation_refuses_rather_than_reports() -> None:
    """What a document being made does with an answer of no.

    A gate reports and leaves the tree as it found it, which is right for a
    check somebody runs. Generation is making the file a reader will follow,
    so it raises, and the message carries every site — one is never the only
    one, because prose is copied.
    """
    with pytest.raises(ValueError, match="name nothing this CLI serves"):
        refuse_unresolved_commands(lambda words: False)


def test_a_declared_invocation_spells_the_executable_once() -> None:
    """The construct's whole point: the path is a value, the prefix is not.

    A skill declaring one cannot misspell `uv run lup-devtools`, and what
    follows the command is the reader's — a placeholder resolves against
    nothing and is carried through untouched.
    """
    invocation = CommandInvocation(path=["dev", "hooks", "sweep"], arguments="<file>")

    assert invocation.spelled() == "uv run lup-devtools dev hooks sweep <file>"
    assert invocation.shell_command == invocation.spelled()
    assert CommandInvocation(path=["dev", "check"]).spelled() == (
        "uv run lup-devtools dev check"
    )
