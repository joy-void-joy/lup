"""ruff's findings on the files a change touches, in the engine's `Finding` shape.

ruff owns generic Python hygiene (`docs/conventions.md`, *Who owns each concern*).
Its findings are information at each checkpoint and must be clean when the turn
ends; they never refuse an edit. A finding ruff fixes safely is marked `fixable`,
and the agent never hears of it: the session landing the work applies the fix. It
runs with `--ignore-noqa`, so lup's own `# lup: ignore` is the one suppression,
applied by the judge to every owner alike.

The host never runs a project's environment, so the judge's ruff is its own,
installed with it (`docs/judging-writes.md`, *The engine: one typed tree*), never
the worktree's.
"""

import shlex
import sysconfig
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, override

from pydantic import TypeAdapter

from lup.programs import ProgramFailedError, ProgramMissingError, run
from lup.types import Model
from lup_dev.codescan.contract import Finding, Position, Source, Span
from lup_dev.confined import Confined
from lup_dev.errors import LupDevError


class RuffError(LupDevError):
    """The judge's ruff isn't installed beside it, or failed."""


class Linter(ABC):
    """A linter the judge asks about the files a change touches."""

    @abstractmethod
    def findings(self, root: Path, sources: list[Source]) -> list[Finding]:
        """Return the findings in `sources`, as written or as their would-be content."""


def installed() -> Path:
    """Return the ruff installed with the running `lup-dev`: where its Python installs scripts, as ruff's own `find_ruff_bin` looks first."""
    return Path(sysconfig.get_path("scripts")) / "ruff"


class Ruff(Model, Linter):
    """The judge's own ruff, installed with it as a dependency of `lup-dev`, never the worktree's.

    The copy of lup the operator approved carries it, held to the approved
    lock, so a branch changing ruff's version is judged by the approved ruff
    until its copy is approved, as pyright is (`docs/trust.md`). Each file goes
    to it on its input, under its own name so its configuration applies: a file
    on disk is read only where it resolves inside the worktree
    (`lup_dev.confined`), and left out otherwise, so a link there can't have
    ruff read a file elsewhere on the host.
    """

    program: Path | None = None
    """The ruff to run; left out, the one installed with `lup-dev`."""

    @override
    def findings(self, root: Path, sources: list[Source]) -> list[Finding]:
        class Location(Model):
            """A place in ruff's JSON output."""

            row: int
            column: int

            def position(self) -> Position:
                """Return this place as a `Position`."""
                return Position(line=self.row, column=self.column)

        class Fix(Model):
            """The fix ruff offers for a finding, as far as the judge reads it."""

            applicability: Literal["safe", "unsafe", "display-only"]
            """Only a `safe` fix is applied by `ruff check --fix`."""

        class Message(Model):
            """One finding in `ruff check --output-format json`."""

            code: str | None
            message: str
            filename: Path
            location: Location
            end_location: Location
            fix: Fix | None = None
            """None where ruff has no fix, or the configuration makes it unfixable."""

            def finding(self) -> Finding:
                """Return this message as a ruff `Finding`, its path from the root."""
                path = self.filename
                return Finding(
                    path=path.relative_to(root) if path.is_relative_to(root) else path,
                    span=Span(
                        start=self.location.position(),
                        end=self.end_location.position(),
                    ),
                    owner="ruff",
                    rule=self.code or "invalid-syntax",
                    message=self.message,
                    fixable=self.fix is not None and self.fix.applicability == "safe",
                )

        messages = TypeAdapter(list[Message])
        program = self.program or installed()
        # `--exit-zero` keeps a failure apart from findings, which would otherwise
        # exit 1 too.
        command = [
            str(program),
            "check",
            "--ignore-noqa",
            "--force-exclude",
            "--exit-zero",
            "--output-format",
            "json",
        ]

        def ran(path: Path, content: str) -> list[Finding]:
            try:
                output = run(
                    *command,
                    "--stdin-filename",
                    str(root / path),
                    "-",
                    cwd=root,
                    stdin=content,
                )
            except ProgramMissingError as missing:
                message = (
                    f"the judge's ruff isn't at {program}: it's installed with "
                    "`lup-dev`, which depends on it"
                )
                raise RuffError(message) from missing
            except ProgramFailedError as failed:
                shown = shlex.join(command)
                message = f"`{shown}` failed in {root}: {failed.ran.said()}"
                raise RuffError(message) from failed
            return [
                message.finding() for message in messages.validate_json(output.output)
            ]

        worktree = Confined(root=root)

        def content(source: Source) -> str | None:
            return (
                worktree.text(source.path) if source.content is None else source.content
            )

        return [
            finding
            for source in sources
            if (text := content(source)) is not None
            for finding in ran(source.path, text)
        ]
