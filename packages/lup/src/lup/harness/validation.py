"""Whole-tree validation of a rendered artifact tree, plus its result types.

Runs between rendering and reconciliation: the native compilation roots in
:mod:`lup.adapters.harness` validate every complete tree and refuse to
continue on any issue. ``ValidationResult`` is defined here because
validators are the only producers; this module also owns the
``ArtifactValidator`` seam they implement.
"""

from abc import ABC, abstractmethod
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from lup.harness.models import ArtifactTree


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    semantic_id: str
    message: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues


class ArtifactValidator(ABC):
    """Validate a complete in-memory artifact tree."""

    @abstractmethod
    def validate(self, tree: ArtifactTree) -> ValidationResult:
        """Return every deterministic validation issue."""


class DeterministicTreeValidator(ArtifactValidator):
    """Validate path uniqueness, ordering, identifiers, and normalized text."""

    def validate(self, tree: ArtifactTree) -> ValidationResult:
        path_counts = Counter(artifact.path.as_posix() for artifact in tree.artifacts)
        duplicate_issues = [
            ValidationIssue(
                semantic_id="artifact-tree",
                message=f"duplicate target path {path!r}",
            )
            for path, count in path_counts.items()
            if count > 1
        ]
        identifier_issues = [
            ValidationIssue(
                semantic_id="artifact-tree",
                message=f"artifact {artifact.path} has no semantic object id",
            )
            for artifact in tree.artifacts
            if not artifact.semantic_id
        ]
        newline_issues = [
            ValidationIssue(
                semantic_id=artifact.semantic_id,
                message=f"artifact {artifact.path} does not end in one LF newline",
            )
            for artifact in tree.artifacts
            if artifact.content
            and (
                not artifact.content.endswith("\n") or artifact.content.endswith("\n\n")
            )
        ]
        order = [artifact.path.as_posix() for artifact in tree.artifacts]
        order_issues = (
            []
            if order == sorted(order)
            else [
                ValidationIssue(
                    semantic_id="artifact-tree",
                    message="artifact paths are not in deterministic order",
                )
            ]
        )
        return ValidationResult(
            issues=[
                *duplicate_issues,
                *identifier_issues,
                *newline_issues,
                *order_issues,
            ]
        )
