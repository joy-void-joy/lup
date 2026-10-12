"""ruff's findings on the files a change touches, in the engine's `Finding` shape.

ruff owns generic Python hygiene (`docs/conventions.md`, *Who owns each concern*).
Its findings are information at each checkpoint and must be clean when the turn
ends; they never refuse an edit. A finding ruff fixes safely is marked `fixable`,
and the agent never hears of it: the session landing the work applies the fix. It
runs with `--ignore-noqa`, so lup's own `# lup: ignore` is the one suppression,
applied by the judge to every owner alike.

It runs through the project's runner, as the gate's ruff step does, but with the
runner's command for the judge, which never writes the project's files: for
`Uv()`, `uv.lock` is read without relocking (`lup_dev.declaration.runner`).
"""

import shlex
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

import sh
from pydantic import TypeAdapter

from lup.types import Model
from lup_dev.codescan.contract import Finding, Position, Source, Span
from lup_dev.errors import LupDevError

if TYPE_CHECKING:
    from lup_dev.declaration.runner import Runner


class RuffError(LupDevError):
    """ruff couldn't run in the worktree's environment, or failed there."""


class Linter(ABC):
    """A linter the judge asks about the files a change touches."""

    @abstractmethod
    def findings(
        self, root: Path, sources: list[Source], runner: Runner
    ) -> list[Finding]:
        """Return the findings in `sources`, as written or as their would-be content.

        The linter runs as the project's `runner` runs a tool for the judge.
        """


class Ruff(Linter):
    """ruff as the project's runner finds it in the worktree.

    That's the project's own where its environment has one, as for the gate's
    ruff step; with `Uv()`, else the one on the path. It runs as the runner's
    `judging` command. Files on disk are checked in one run; would-be content one
    file at a time, through stdin, under the file's own name so its
    configuration applies.
    """

    @override
    def findings(
        self, root: Path, sources: list[Source], runner: Runner
    ) -> list[Finding]:
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
        # `--exit-zero` keeps a failure apart from findings: the runner's failures
        # (uv's) exit 1, as ruff's findings otherwise would.
        command = runner.judging(
            [
                "ruff",
                "check",
                "--ignore-noqa",
                "--force-exclude",
                "--exit-zero",
                "--output-format",
                "json",
            ]
        )
        program, *fixed = command

        def ran(*arguments: str, content: str | None = None) -> list[Finding]:
            try:
                output = sh.Command(program)(
                    *fixed,
                    *arguments,
                    _in=content,
                    _cwd=str(root),
                    _tty_out=False,
                    _return_cmd=True,
                )
            except sh.CommandNotFound as missing:
                message = (
                    f"`{program}` isn't on the `PATH`, so ruff can't run in {root}"
                )
                raise RuffError(message) from missing
            except sh.ErrorReturnCode as failed:
                shown = shlex.join(command)
                message = f"`{shown}` failed in {root}: {failed.stderr.decode()}"
                raise RuffError(message) from failed
            return [
                message.finding() for message in messages.validate_json(output.stdout)
            ]

        on_disk = [
            str(root / source.path) for source in sources if source.content is None
        ]
        written = [
            finding
            for source in sources
            if source.content is not None
            for finding in ran(
                "--stdin-filename", str(root / source.path), "-", content=source.content
            )
        ]
        return [*(ran(*on_disk) if on_disk else []), *written]
