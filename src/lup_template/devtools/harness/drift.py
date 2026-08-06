"""Console drift reporting and reported generation for generate and check.

Wraps the ``generate`` engine in the console surfaces the CLI shares: drift
summaries, generation summaries, and conflict-aborted generation. Owns the
bodies of the ``generate`` and ``check`` commands, and reaches the rule
reference alongside them so one command settles every generated artifact
rather than leaving the repository-wide one to be remembered separately.
"""

from pathlib import Path

import typer

from lup_template.devtools.dev.rules import write_rule_reference
from lup_template.devtools.dev.workflow import write_workflow
from lup_template.devtools.harness.composition import (
    EVERY_TARGET,
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


REPOSITORY_WIDE = [write_rule_reference, write_workflow]
"""Every generated file belonging to no one runtime's tree.

Each writes itself when asked and verifies itself when checked, so a caller
settles or audits all of them without knowing what any one of them renders."""


def clean_repository_artifacts() -> bool:
    """Whether every generated file outside the native trees is up to date."""
    stale = []
    for write in REPOSITORY_WIDE:
        try:
            write(check=True)
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            stale.append(write)
    return not stale


def generate_targets(target: str) -> None:
    """Generate owned artifacts for every composition the selector names."""
    for composition in harness_compositions(target):
        generate_with_report(composition)
    if target == EVERY_TARGET:
        for write in REPOSITORY_WIDE:
            typer.echo(f"repository artifact ready: {write()}")


def drift_reports(target: str) -> list[DriftReport]:
    """Ownership-aware drift for every composition the selector names.

    A library upgrade changes what the desired tree compiles to, so this is
    what tells an adopter their generated trees are behind — which is why
    ``dev check`` asks it too, rather than leaving it to a workflow file no
    initialization installs.
    """
    return [
        inspect_generation(composition.recipe)
        for composition in harness_compositions(target)
    ]


def check_targets(target: str) -> None:
    """Report drift for every selected composition; exit nonzero when dirty."""
    reports = drift_reports(target)
    for report in reports:
        report_drift(report)
    stale = target == EVERY_TARGET and not clean_repository_artifacts()
    if stale or any(not report.clean for report in reports):
        raise typer.Exit(1)
