"""Convergent ownership-safe artifact materialization."""

import hashlib
from pathlib import Path

from lup.harness.contracts import Materializer
from lup.harness.models import MaterializationResult, ReconciliationProposal


class MaterializationConflictError(RuntimeError):
    """A proposal is unresolved or stale at materialization time."""


def file_digest(path: Path) -> str | None:
    """Hash a file if it currently exists."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_target(root: Path, relative: Path) -> Path:
    """Resolve a managed path while rejecting a symlink escape from its root."""
    resolved_root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise MaterializationConflictError(
            f"managed path escapes its root through a symlink: {relative}"
        )
    return candidate


class AtomicMaterializer(Materializer):
    """Replace changed owned files atomically and delete only with prior proof."""

    def apply(self, proposal: ReconciliationProposal) -> MaterializationResult:
        if proposal.conflicts:
            paths = ", ".join(
                conflict.path.as_posix() for conflict in proposal.conflicts
            )
            raise MaterializationConflictError(
                f"proposal {proposal.id} has unresolved conflicts: {paths}"
            )
        for write in proposal.writes:
            path = safe_target(proposal.root, write.artifact.path)
            actual = file_digest(path)
            if actual != write.previous_sha256:
                raise MaterializationConflictError(
                    f"stale base for {write.artifact.path}: expected "
                    f"{write.previous_sha256!r}, found {actual!r}"
                )
            if path.exists() and write.previous_executable is not None:
                executable = bool(path.stat().st_mode & 0o111)
                if executable != write.previous_executable:
                    raise MaterializationConflictError(
                        f"stale executable mode for {write.artifact.path}"
                    )
        for deletion in proposal.deletes:
            path = safe_target(proposal.root, deletion.path)
            actual = file_digest(path)
            if actual != deletion.prior_ownership_sha256:
                raise MaterializationConflictError(
                    f"ownership proof changed for {deletion.path}"
                )

        changed: list[Path] = []  # lup: ignore[empty-collection]
        for write in proposal.writes:
            artifact = write.artifact
            path = safe_target(proposal.root, artifact.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{proposal.id}.tmp")
            temporary.write_text(artifact.content, encoding="utf-8", newline="\n")
            temporary.chmod(0o755 if artifact.executable else 0o644)
            temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename
            changed.append(artifact.path)

        removed: list[Path] = []  # lup: ignore[empty-collection]
        for deletion in proposal.deletes:
            path = safe_target(proposal.root, deletion.path)
            path.unlink()
            removed.append(deletion.path)
        return MaterializationResult(changed=changed, removed=removed)
