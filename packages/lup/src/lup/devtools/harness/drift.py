"""Console drift reporting and reported generation for generate and check.

Wraps the ``generate`` engine in the console surfaces the CLI shares: drift
summaries, generation summaries, and conflict-aborted generation. Owns the
bodies of the ``generate`` and ``check`` commands, and reaches the rule
reference alongside them so one command settles every generated artifact
rather than leaving the repository-wide one to be remembered separately.

:class:`DriftVerdict` is the single reading every refusing path shares: the
commit hook, continuous integration, and ``dev check`` all ask
:func:`inspect_drift` rather than composing the same two halves themselves,
so no tree can be stale to one of them and current to another.
"""

from typing import Protocol, runtime_checkable
from pathlib import Path

import typer
from pydantic import BaseModel

from lup.harness.banner import REGENERATE_COMMAND
from lup.devtools.harness.generate import (
    DriftReport,
    HarnessGenerationConflict,
    NativeHarnessComposition,
    generate as generate_target,
    inspect_generation,
)


@runtime_checkable
class RepositoryWriter(Protocol):
    """One project-owned generated artifact outside a native tree.

    Runtime-checkable so a declaration can carry a list of these: the roster's
    bundle is a model, and pydantic validates a named type by asking whether a
    value is one. For a callback protocol that question is whether the value is
    callable, which is as much as any caller here ever needed to know.
    """

    def __call__(self, root: Path | None = None, *, check: bool = False) -> Path: ...


def report_generation(target: str, changed: list[Path], removed: list[Path]) -> None:
    typer.echo(
        f"{target} harness ready: {len(changed)} changed, {len(removed)} removed"
    )


def ownership_state(report: DriftReport) -> str:
    """How the proof stands: absent, present but behind, or current."""
    if not report.ownership_present:
        return "missing"
    return "present" if report.manifest_current else "stale"


def report_drift(report: DriftReport, *, paths: bool = False) -> None:
    proposal = report.proposal
    typer.echo(
        f"{report.target}: {len(proposal.writes)} writes, "
        f"{len(proposal.deletes)} deletes, {len(proposal.conflicts)} conflicts, "
        f"ownership={ownership_state(report)}"
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


def repository_staleness(write: RepositoryWriter) -> list[str]:
    """Why one generated file outside the native trees is behind, if it is."""
    try:
        write(check=True)
    except RuntimeError as error:
        return [str(error)]
    return []


class RosterGap(BaseModel, frozen=True):
    """One declaration a target's tree renders nothing for."""

    target: str
    declaration: str

    def describe(self) -> str:
        """One line naming the target and what it left out."""
        return f"{self.target} renders nothing for {self.declaration}"


def roster_gaps(compositions: list[NativeHarnessComposition]) -> list[RosterGap]:
    """Every declaration a composition's desired tree carries no artifact for.

    The parity gate, written as completeness against the shared source rather
    than as a diff between two trees. Both readings catch a target that drops
    a skill the other keeps, but the trees themselves are not comparable: they
    shape a skill as ``commands/<name>.md`` and as ``skills/<name>/SKILL.md``,
    and each legitimately carries files the other has no equivalent for — a
    settings file, a config file. Diffing them would need an exception list
    that grows with every such file and would let a real gap hide in it.

    Measuring each target against :attr:`Harness.declared_ids` needs no
    exceptions: an artifact outside the roster is target-specific by
    construction and never considered, and a roster entry missing from one
    tree is named against that tree. It is also the stronger reading, because
    a declaration both targets dropped is still a gap here, where a diff
    between the two would call it parity.
    """
    return [
        RosterGap(target=composition.recipe.label, declaration=declared)
        for composition in compositions
        for rendered in [
            {artifact.semantic_id for artifact in composition.recipe.desired.artifacts}
        ]
        for declared in composition.recipe.source.rendered_ids
        if declared not in rendered
    ]


class DriftVerdict(BaseModel, frozen=True):
    """One reading of whether every generated artifact is what its source renders."""

    reports: list[DriftReport]
    """Ownership-aware drift for each native tree inspected."""

    stale_repository: list[str]
    """Why each generated file outside a native tree is behind its source."""

    @property
    def stale_trees(self) -> list[DriftReport]:
        """Every inspected tree holding an artifact its source no longer renders."""
        return [report for report in self.reports if not report.clean]

    @property
    def clean(self) -> bool:
        """Whether nothing generated is behind the source that renders it."""
        return not self.stale_trees and not self.stale_repository


def generate_targets(
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
) -> None:
    """Generate owned artifacts for every composition the selector names."""
    for composition in compositions:
        generate_with_report(composition)
    for write in repository_writers:
        typer.echo(f"repository artifact ready: {write()}")


def inspect_drift(
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
) -> DriftVerdict:
    """Read every generated artifact against the source that renders it.

    A library upgrade changes what the desired tree compiles to, and a comment
    edited in a source copied verbatim changes it without changing anything it
    does. Both are read the same way, over the bytes on disk rather than over
    what they mean, so an edit that only rewords a kernel comment is as stale
    as one that rewrites its logic.
    """
    return DriftVerdict(
        reports=[inspect_generation(item.recipe) for item in compositions],
        stale_repository=[
            message
            for write in repository_writers
            for message in repository_staleness(write)
        ],
    )


def report_stale(verdict: DriftVerdict) -> None:
    """Name every stale artifact, then the one command that settles them all."""
    for report in verdict.stale_trees:
        if not report.manifest_current:
            typer.echo(f"  stale proof: {report.target} ownership manifest", err=True)
        for write in report.proposal.writes:
            typer.echo(f"  stale: {write.artifact.path}", err=True)
        for delete in report.proposal.deletes:
            typer.echo(f"  orphaned: {delete.path}", err=True)
    for message in verdict.stale_repository:
        typer.echo(f"  {message}", err=True)
    typer.echo(
        f"generated artifacts are behind their source; run `{REGENERATE_COMMAND}` "
        "and include what it writes in this commit",
        err=True,
    )


def check_targets(
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
) -> None:
    """Report drift and roster parity for every selected composition.

    Both refusals are read here rather than in separate commands, because a
    tree can be perfectly current against a source that renders one target a
    skill short. Drift asks whether each tree is what its source renders;
    parity asks whether what it renders is the whole roster.
    """
    verdict = inspect_drift(compositions, repository_writers)
    for report in verdict.reports:
        report_drift(report)
    gaps = roster_gaps(compositions)
    for gap in gaps:
        typer.echo(f"  roster gap: {gap.describe()}", err=True)
    if not verdict.clean:
        report_stale(verdict)
    if not verdict.clean or gaps:
        raise typer.Exit(1)
