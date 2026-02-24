"""Image persistence utilities."""

import hashlib
from collections.abc import Sequence
from pathlib import Path

MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def save_images(
    images: Sequence[tuple[str, bytes]],
    images_dir: Path,
) -> list[Path]:
    """Save raw image data to disk, returning the written paths.

    Files are named by a short content hash to avoid duplicates.
    The directory is created if it doesn't exist.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for media_type, data in images:
        ext = MIME_TO_EXT.get(media_type, ".bin")
        name = hashlib.sha256(data).hexdigest()[:12] + ext
        path = images_dir / name
        if not path.exists():
            path.write_bytes(data)
        paths.append(path)
    return paths
