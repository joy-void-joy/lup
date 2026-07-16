"""Walk repository Python files for seam-boundary breaches.

Backs ``lup-devtools dev check --boundaries`` and the standalone check
row: every git-tracked ``.py`` file outside the sanctioned homes (the
adapters package, tests) runs through :mod:`lup.codescan.boundaries`.
The tree is expected to hold zero breaches — this is the regression
guard that keeps backend dispatch from creeping back outside the seam.
"""

from pathlib import Path

import typer

from lup.codescan.boundaries import (
    BoundaryBreach,
    find_boundary_breaches,
    find_kernel_import_breaches,
    find_native_spelling_breaches,
    path_is_sanctioned,
)
from lup_template.devtools.utils import git, output_json


class FoundBreach(BoundaryBreach):
    """A :class:`~lup.codescan.boundaries.BoundaryBreach` tagged with its file."""

    file: str


def scan_boundaries() -> list[FoundBreach]:
    """Every seam breach across tracked, non-sanctioned Python files."""
    return [
        FoundBreach(file=rel, **breach.model_dump())
        for rel in str(
            git("ls-files", "--cached", "--others", "--exclude-standard")
        ).splitlines()
        if Path(rel).suffix == ".py"
        and Path(rel).exists()
        and not path_is_sanctioned(Path(rel))
        for breach in [
            *find_boundary_breaches(Path(rel).read_text(encoding="utf-8")),
            *find_native_spelling_breaches(Path(rel).read_text(encoding="utf-8")),
            *(
                find_kernel_import_breaches(Path(rel).read_text(encoding="utf-8"))
                if rel == "packages/lup/src/lup/policy/kernel.py"
                else ()
            ),
        ]
    ]


def report(as_json: bool) -> None:
    """List every breach; exit non-zero when any exist."""
    found = scan_boundaries()
    if as_json:
        output_json([breach.model_dump() for breach in found])
    elif found:
        for breach in found:
            typer.echo(f"{breach.file}:{breach.line}  {breach.module}")
    else:
        typer.echo("seam boundaries: ok")
    if found:
        raise typer.Exit(1)
