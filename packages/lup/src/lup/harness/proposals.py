"""Persistence for explicit, patch-only canonical-source reconciliation."""

import hashlib
from pathlib import Path

from lup.harness.models import ReconciliationMetadata
from lup.harness.reconciliation import source_patch_base_digest


class ReconciliationProposalWriter:
    """Persist one immutable source patch without applying or importing it."""

    def write(self, root: Path, source_patch: str) -> ReconciliationMetadata:
        if not source_patch.endswith("\n"):
            source_patch += "\n"
        patch_sha256 = hashlib.sha256(source_patch.encode("utf-8")).hexdigest()
        proposal_id = patch_sha256[:16]
        record = ReconciliationMetadata(
            proposal_id=proposal_id,
            base_digest=source_patch_base_digest(root, source_patch),
            source_patch_sha256=patch_sha256,
        )
        directory = root / ".lup" / "reconcile" / proposal_id
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError("reconciliation proposal directory escapes its root")
        patch_path = directory / "source.patch"
        metadata_path = directory / "metadata.json"
        expected_patch = source_patch.encode("utf-8")
        expected_metadata = (record.model_dump_json(indent=2) + "\n").encode("utf-8")
        for path, expected in [
            (patch_path, expected_patch),
            (metadata_path, expected_metadata),
        ]:
            if path.exists() and path.read_bytes() != expected:
                raise FileExistsError(f"reconciliation proposal collision at {path}")
        self.write_once(patch_path, expected_patch)
        self.write_once(metadata_path, expected_metadata)
        return record

    def write_once(self, path: Path, content: bytes) -> None:
        """Atomically create one proposal member when it is not already exact."""
        if path.exists():
            return
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename
