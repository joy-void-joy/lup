"""Reusable complete-tree validation capabilities."""

from collections import Counter

from lup.harness.contracts import ArtifactValidator
from lup.harness.models import (
    ArtifactTree,
    ValidationIssue,
    ValidationResult,
)

# lup: Same
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
