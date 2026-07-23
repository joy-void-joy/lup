"""Console drift reporting and reported generation for generate and check.

Wraps the ``generate`` engine in the console surfaces the CLI shares: drift
summaries, generation summaries, and conflict-aborted generation. Owns the
bodies of the ``generate`` and ``check`` commands.
"""

from pathlib import Path

import typer

from lup_template.devtools.harness.composition import (
    NativeHarnessComposition,
    harness_compositions,
)
from lup_template.devtools.harness.generate import (
    DriftReport,
    HarnessGenerationConflict,
    generate as generate_target,
    inspect_generation,
)


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


def generate_targets(target: str) -> None:
    """Generate owned artifacts for every composition the selector names."""
    for composition in harness_compositions(target):
        generate_with_report(composition)


def check_targets(target: str) -> None:
    """Report drift for every selected composition; exit nonzero when dirty."""
    reports = [
        inspect_generation(composition.recipe)
        for composition in harness_compositions(target)
    ]
    for report in reports:
        report_drift(report)
    if any(not report.clean for report in reports):
        raise typer.Exit(1)
