"""Every `uv run lup-devtools ...` written down, against what the CLI serves.

A command named in prose is an instruction, and one naming a command that does
not exist fails for whoever follows it rather than for whoever wrote it.
Twenty-two shipped at once: `dev hookssweep` in the hooks workflow's own step
7, `py info` reached without its `dev` group in the introspection tools' own
docstring, `dashboard` without `setup` in the page describing the dashboard.
Each was written beside the command it named.

Two mechanisms answer that, and this is the one with reach.
:class:`~lup.harness.models.CommandInvocation` makes a *composed* document
right by construction and cannot reach a docstring, a checked-in Markdown
file, or a refusal string in a catalog — which is where most of these were. So
the sweep reads what is written, wherever it is written, and resolves it
against :class:`~lup.devtools.dev.commands.CommandSurface`.

Scanning text is what a whole family of rules here exists to avoid, and it is
right this once for one reason: the alternative is not deriving the prose, it
is not checking it. What the sweep never does is decide what a command
*means* — it asks the walked app whether the words reach one, and the app
answers.
"""

# lup: ignore[import-re] — the executable's own name inside arbitrary English,
# which no parser owns: what follows it is handed to the walked app rather
# than interpreted here
import re
from pathlib import Path

from collections.abc import Callable, Sequence

from pydantic import BaseModel

from lup.devtools.dev.library import VENDORED_ROOT
from lup.devtools.dev.release import ReleaseSpec
from lup.devtools.dev.tracked import tracked_files
from lup.devtools.project import DevProject
from lup.workspace.paths import is_template_scaffold

# lup: ignore[re-call] — see the module note: recognizing the toolchain's name
# in prose, not parsing a structured format
MENTION = re.compile(r"uv run lup-devtools([^`\n\"']*)")
"""Where a mention starts, and everything up to whatever closes it.

Bounded by a backtick, a quote, or the line's end, because that is what
encloses a command every place one is written here: inline code in Markdown, a
docstring example line, a string literal in a catalog.
"""

# lup: ignore[re-call] — one plain command word, which is the shape the CLI's
# own names take; anything else ends the path and begins its arguments
COMMAND_WORD = re.compile(r"^[a-z][a-z0-9-]*$")
"""A word that could belong to a command path, rather than to its arguments."""


class WrittenCommand(BaseModel, frozen=True):
    """One `lup-devtools` invocation somebody wrote down, and where."""

    file: str
    line: int
    spelled: str

    def named(self) -> str:
        """This mention as a reader meets it: the site, then the words."""
        return f"{self.file}:{self.line}: uv run lup-devtools {self.spelled}"

    def command_words(self) -> list[str]:
        """The leading words that could name a command path.

        Stops where the first word that is not a plain command name appears,
        which is where the arguments begin: `--json`, a module path, or a
        placeholder the reader is meant to replace.
        """
        words = self.spelled.split()
        return [
            word
            for index, word in enumerate(words)
            if COMMAND_WORD.match(word)
            and all(COMMAND_WORD.match(earlier) for earlier in words[:index])
        ]


def unjudged_roots(
    project: DevProject,
    root: Path,
    admits: Callable[[list[str]], bool],
    release: ReleaseSpec,
) -> list[str]:
    """What the sweep does not read as instruction, as path prefixes.

    The release's changelog is history rather than instruction: each note
    records the commands as they existed at that release, which a rename
    since, or a project declining the module that served one, does not make
    wrong — and nobody rewrites a release to make it right. Its migration
    notes are folded in from declarations the sweep reads in the repository
    declaring them, so what a release tells a consumer to run is judged while
    it is still current.

    The rest are trees of two kinds, each judged where it reaches a reader
    rather than where it is written. A content-declaration tree is prose compiled into the generated
    trees, which the sweep reads in full: a module this project took is
    judged there against the CLI that serves it, and a module it declined
    renders nowhere, so its own prose naming its own commands is no reader's
    instruction and no blocker. A vendored library is another repository's
    code, written against a CLI serving every command group it ships and
    judged in the repository that authors it — so it is read only while this
    checkout is that repository: the template scaffold, whose CLI ``admits``
    every one of those groups. A scaffold that declined a module is an
    adoption under way, and judging the library there would refuse its own
    words about the very module that was just declined.
    """
    # Imported where it is asked: the roster wires the `dev` tree, whose gate
    # imports this module, so importing it above would close that loop.
    from lup.devtools.roster import LIBRARY_SPECS

    authoring = is_template_scaffold(root) and all(
        admits([spec.name]) for spec in LIBRARY_SPECS
    )
    declared = [f"{entry.directory.as_posix()}/" for entry in project.coverage.roots]
    vendored = [] if authoring else [f"{VENDORED_ROOT}/"]
    return [*declared, *vendored, release.changelog]


def written_commands(unjudged: Sequence[str] = ()) -> list[WrittenCommand]:
    """Every `uv run lup-devtools` mention in the tracked Python and Markdown.

    Generated trees are read in full, since they are what reaches a session:
    a wrong command arrives through the rendered skill rather than through
    the module that declared it. The declaration trees behind them, and a
    library this checkout only vendors, are ``unjudged`` —
    :func:`unjudged_roots` says why each is judged elsewhere.

    A test tree is not read. What a fixture spells is an input to a gate
    rather than an instruction to a reader: `dev worktree create feature` is
    there because the classifier must answer it, and it names no command on
    purpose. Reading those would make the sweep report the tests that hold
    this project to its policy.
    """

    def mentions(file: str) -> list[WrittenCommand]:
        try:
            text = Path(file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        return [
            WrittenCommand(file=file, line=number, spelled=tail.strip())
            for number, line in enumerate(text.splitlines(), start=1)
            for tail in MENTION.findall(line)
            if tail.strip()
        ]

    return [
        mention
        for file in tracked_files(suffixes=(".py", ".md"))
        if "tests/" not in file and not file.startswith(tuple(unjudged))
        for mention in mentions(file)
    ]


def unresolved(
    admits: Callable[[list[str]], bool], unjudged: Sequence[str] = ()
) -> list[WrittenCommand]:
    """Every written mention naming no command the composed CLI serves.

    Takes the question rather than the surface that answers it —
    :meth:`~lup.devtools.dev.commands.CommandSurface.admits` — because the
    module owning that surface also writes the page this sweep guards, and one
    of the two has to be able to import the other.

    A mention carrying no command word at all — `uv run lup-devtools --help`,
    or the toolchain named as a toolchain — is left alone: it instructs
    nothing this can check, and refusing it would refuse the sentence that
    introduces the CLI.
    """
    return [
        mention
        for mention in written_commands(unjudged)
        if (words := mention.command_words()) and not admits(words)
    ]


def refuse_unresolved_commands(
    admits: Callable[[list[str]], bool], unjudged: Sequence[str] = ()
) -> None:
    """Raise unless every written command names one the CLI serves.

    What generation does with the sweep's answer. A gate reports and leaves
    the tree as it found it, which is right for a check somebody runs; this
    runs while a document is being made, and a document telling its reader to
    run something that does not exist is not finished.
    """
    written = unresolved(admits, unjudged)
    if written:
        named = "\n  ".join(mention.named() for mention in written)
        raise ValueError(
            f"{len(written)} documented command(s) name nothing this CLI "
            f"serves:\n  {named}\nRun the command as written to see what it "
            "answers, then spell it as the CLI does."
        )
