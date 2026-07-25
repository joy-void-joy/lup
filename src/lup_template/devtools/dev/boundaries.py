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
    audit_path_boundaries,
    find_kernel_import_breaches,
)
from lup_template.devtools.utils import git, output_json


class FoundBreach(BoundaryBreach):
    """A :class:`~lup.codescan.boundaries.BoundaryBreach` tagged with its file."""

    file: str


def scan_boundaries() -> list[FoundBreach]:
    """Every native import, spelling, and kernel-import breach in the tree."""
    found: list[FoundBreach] = []  # lup: ignore[empty-collection]
    tracked = str(
        git("ls-files", "--cached", "--others", "--exclude-standard")
    ).splitlines()
    for rel in tracked:
        path = Path(rel)
        if path.suffix != ".py" or not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings = audit_path_boundaries(path, text)
        found.extend(
            FoundBreach(
                file=rel,
                line=finding.line,
                module=finding.module,
                text=finding.text,
            )
            for finding in findings
            if finding.kind == "missing"
        )
        if rel.startswith("packages/lup/src/lup/policy/kernel/"):
            found.extend(
                FoundBreach(file=rel, **breach.model_dump())
                for breach in find_kernel_import_breaches(text)
            )
    return found


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
