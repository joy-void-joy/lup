"""Console drift reporting and reported generation for generate and check.

Wraps the ``generate`` engine in the console surfaces the CLI shares: drift
summaries, generation summaries, and conflict-aborted generation. Owns the
bodies of the ``generate`` and ``check`` commands, and reaches the rule
reference alongside them so one command settles every generated artifact
rather than leaving the repository-wide one to be remembered separately.
"""

from typing import Protocol
from pathlib import Path

import typer

from lup.devtools.harness.generate import (
    DriftReport,
    HarnessGenerationConflict,
    NativeHarnessComposition,
    generate as generate_target,
    inspect_generation,
)


class RepositoryWriter(Protocol):
    """One project-owned generated artifact outside a native tree."""

    def __call__(self, root: Path | None = None, *, check: bool = False) -> Path: ...


def report_generation(target: str, changed: list[Path], removed: list[Path]) -> None:
    typer.echo(
        f"{target} harness ready: {len(changed)} changed, {len(removed)} removed"
    )


def report_drift(report: DriftReport, *, paths: bool = False) -> None:
    proposal = report.proposal
    typer.echo(
        f"{report.target}: {len(proposal.writes)} writes, "
        f"{len(proposal.deletes)} deletes, {len(proposal.conflicts)} conflicts, "
        f"ownership={'present' if report.ownership_present else 'missing'}"
    )
    for conflict in proposal.conflicts:
        label = "sensitive local conflict" if conflict.sensitive else conflict.category
        typer.echo(f"  {conflict.path}: {label}")
    if paths:
        for write in proposal.writes:
            typer.echo(f"  + {write.artifact.path}")
        for delete in proposal.deletes:
            typer.echo(f"  - {delete.path}")


def generate_with_report(composition: NativeHarnessComposition) -> None:
    """Generate one composition's owned artifacts, reporting drift and results."""
    recipe = composition.recipe
    report = inspect_generation(recipe)
    report_drift(report, paths=True)
    try:
        materialized = generate_target(recipe)
    except HarnessGenerationConflict as error:
        typer.echo(str(error), err=True)
        typer.echo(
            "Existing unowned files were preserved. Reconcile them explicitly before "
            "adopting generated ownership.",
            err=True,
        )
        raise typer.Exit(1) from error
    report_generation(recipe.label, materialized.changed, materialized.removed)


def clean_repository_artifacts(writers: list[RepositoryWriter]) -> bool:
    """Whether every generated file outside the native trees is up to date."""
    stale = []
    for write in writers:
        try:
            write(check=True)
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            stale.append(write)
    return not stale


def generate_targets(
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
) -> None:
    """Generate owned artifacts for every composition the selector names."""
    for composition in compositions:
        generate_with_report(composition)
    for write in repository_writers:
        typer.echo(f"repository artifact ready: {write()}")


def drift_reports(
    compositions: list[NativeHarnessComposition],
) -> list[DriftReport]:
    """Ownership-aware drift for every composition the selector names.

    A library upgrade changes what the desired tree compiles to, so this is
    what tells an adopter their generated trees are behind — which is why
    ``dev check`` asks it too, rather than leaving it to a workflow file no
    initialization installs.
    """
    return [inspect_generation(composition.recipe) for composition in compositions]


def check_targets(
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
) -> None:
    """Report drift for every selected composition; exit nonzero when dirty."""
    reports = drift_reports(compositions)
    for report in reports:
        report_drift(report)
    stale = not clean_repository_artifacts(repository_writers)
    if stale or any(not report.clean for report in reports):
        raise typer.Exit(1)
