"""Read the model lineup a Codex CLI reports about itself.

``codex debug models --bundled`` prints the catalog the CLI ships: every
model slug and the reasoning efforts each advertises. It is the same catalog
:meth:`~lup.providers.codex.builtins.CodexBuiltins.model_catalog`
bounds a session's tools against, read with the same flag, so the lineup lup
types a Codex model against is the one a session opened through it accepts.

The app-server's own protocol types an effort as "a non-empty reasoning
effort value advertised by the model" rather than as a closed ladder, which is
why the efforts are read per model here: which rungs exist is the catalog's
answer, not a list this library keeps.
"""

from pathlib import Path

import sh
from pydantic import BaseModel

from lup.providers.catalog import CatalogModel, ModelCatalog
from lup.providers.codex import CODEX_PROGRAM


class CodexReasoningLevel(BaseModel, frozen=True, extra="ignore"):
    """One effort a model advertises, as the catalog spells it."""

    effort: str


class CodexCatalogEntry(BaseModel, frozen=True, extra="ignore"):
    """One model of ``codex debug models``, as far as a selection reads it."""

    slug: str
    supported_reasoning_levels: list[CodexReasoningLevel] = []


class CodexCatalogReport(BaseModel, frozen=True, extra="ignore"):
    """The whole report ``codex debug models`` prints."""

    models: list[CodexCatalogEntry]

    def lineup(self, observed: str) -> ModelCatalog:
        """Every slug the CLI lists, with the efforts each advertises."""
        return ModelCatalog(
            runtime="codex",
            observed=observed,
            models=[
                CatalogModel(
                    id=entry.slug,
                    efforts=[
                        level.effort for level in entry.supported_reasoning_levels
                    ],
                )
                for entry in self.models
            ],
        )


def codex_catalog(executable: Path = CODEX_PROGRAM) -> ModelCatalog:
    """The lineup the installed Codex CLI ships, read from the CLI."""
    program = sh.Command(str(executable))
    report = CodexCatalogReport.model_validate_json(
        str(program("debug", "models", "--bundled"))
    )
    return report.lineup(str(program("--version")).strip())
