"""ruff's findings on the files a change touches, in the engine's `Finding` shape.

ruff owns generic Python hygiene (`docs/conventions.md`, *Who owns each concern*).
Its findings are information at each checkpoint and must be clean when the turn
ends; they never refuse an edit. A finding ruff fixes safely is marked `fixable`,
and the agent never hears of it: the session landing the work applies the fix. It
runs with `--ignore-noqa`, so lup's own `# lup: ignore` is the one suppression,
applied by the judge to every owner alike.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, override

import sh
from pydantic import TypeAdapter

from lup.types import Model
from lup_dev.codescan.contract import Finding, Position, Source, Span
from lup_dev.layout import CheckoutLayout


class Linter(ABC):
    """A linter the judge asks about the files a change touches."""

    @abstractmethod
    def findings(self, root: Path, sources: list[Source]) -> list[Finding]:
        """Return the findings in `sources`, as written or as their would-be content."""


class Ruff(Linter):
    """ruff, the project's own where it has one.

    Files on disk are checked in one run; would-be content one file at a time,
    through stdin, under the file's own name so its configuration applies.
    """

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

        local = CheckoutLayout(root=root).ruff
        ruff = sh.Command(str(local)) if local.is_file() else sh.Command("ruff")
        messages = TypeAdapter(list[Message])
        check = ["check", "--ignore-noqa", "--force-exclude", "--output-format", "json"]

        def ran(*arguments: str, content: str | None = None) -> list[Finding]:
            output = ruff(
                *check,
                *arguments,
                _in=content,
                _cwd=str(root),
                _ok_code=[0, 1],
                _tty_out=False,
                _return_cmd=True,
            )
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
