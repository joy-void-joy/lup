"""Deterministic ownership proof construction and atomic persistence."""

import hashlib
from pathlib import Path

from pydantic import ValidationError

from lup.harness.models import ArtifactTree, Harness, OwnedArtifact, OwnershipManifest
from lup.harness.reconciliation import content_digest


class OwnershipManifestError(RuntimeError):
    """Persisted ownership proof cannot be decoded as its schema."""


def source_digest(source: Harness) -> str:
    """Hash canonical declarations independently from rendered native output."""
    encoded = source.model_dump_json(exclude_none=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_manifest(
    source: Harness,
    tree: ArtifactTree,
    *,
    generator_version: str,
    target_requirements: list[str],
) -> OwnershipManifest:
    """Build proof for every generated artifact and no local file."""
    return OwnershipManifest(
        schema_version=1,
        generator_version=generator_version,
        source_digest=source_digest(source),
        target_requirements=target_requirements,
        files=[
            OwnedArtifact(
                path=artifact.path,
                category="generated",
                sha256=content_digest(artifact.content),
                semantic_id=artifact.semantic_id,
                executable=artifact.executable,
            )
            for artifact in tree.artifacts
        ],
    )


def load_manifest(path: Path) -> OwnershipManifest | None:
    """Load prior ownership proof if it exists."""
    if not path.exists():
        return None
    try:
        return OwnershipManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise OwnershipManifestError(
            f"ownership manifest at {path} cannot be decoded; repair or remove "
            "it, then regenerate"
        ) from error


def save_manifest(path: Path, manifest: OwnershipManifest) -> None:
    """Atomically replace ownership proof after successful materialization."""
    content = manifest.model_dump_json(indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename
