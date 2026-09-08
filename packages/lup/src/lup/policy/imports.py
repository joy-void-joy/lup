"""Typed import ownership shared by repository audits and native edit hooks."""

import ast
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

from lup.policy.kernel.rows import ImportBoundaryRow


class ImportBoundary(BaseModel, frozen=True):
    """An import family, its permitted owners, and its diagnostic identity.

    Roots are repository-relative; a trailing slash names a directory and
    otherwise a root names one file. Source roots locate Python packages for
    relative imports, without importing or executing the proposed source.
    """

    modules: list[str] = Field(min_length=1)
    owners: list[str] = []
    source_roots: list[str] = []
    rule_id: str
    message: str

    @field_validator("modules")
    @classmethod
    def module_names(cls, values: list[str]) -> list[str]:
        """A misspelled namespace cannot silently disable its dependency guard."""
        for value in values:
            try:
                tree = ast.parse(f"import {value}")
            except (SyntaxError, ValueError) as error:
                raise ValueError(f"invalid module namespace: {value!r}") from error
            match tree.body:
                case [ast.Import(names=[ast.alias(name=name, asname=None)])] if (
                    name == value
                ):
                    continue
                case _:
                    raise ValueError(f"invalid module namespace: {value!r}")
        return values

    @field_validator("owners", "source_roots")
    @classmethod
    def repository_roots(cls, values: list[str]) -> list[str]:
        """Ownership declarations use unambiguous repository-relative POSIX paths."""

        def normalized(value: str) -> str:
            path = PurePosixPath(value)
            if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
                raise ValueError(
                    f"expected a repository-relative POSIX root: {value!r}"
                )
            return path.as_posix() + ("/" if value.endswith("/") else "")

        return [normalized(value) for value in values]

    def erased(self) -> ImportBoundaryRow:
        """The same ownership declaration in the dependency-free kernel."""
        return ImportBoundaryRow(
            modules=self.modules,
            owners=self.owners,
            source_roots=self.source_roots,
            rule_id=self.rule_id,
            message=self.message,
        )
