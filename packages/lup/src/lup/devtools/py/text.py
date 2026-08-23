"""Literal text search over explicitly scoped Python source paths."""

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel


class SourceTextMatch(BaseModel, frozen=True):
    """One complete matching source line and where it was found."""

    path: Path
    line_number: int
    text: str


def python_source_paths(roots: Iterable[Path]) -> list[Path]:
    """Enumerate Python files without descending into hidden or cache trees."""
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"Python source path does not exist: {root}")
        if root.is_file():
            if root.suffix != ".py":
                raise ValueError(f"Source file is not Python: {root}")
            paths.append(root)
            continue
        for directory, directories, files in root.walk():
            directories[:] = [
                name
                for name in directories
                if not name.startswith(".") and name != "__pycache__"
            ]
            paths.extend(directory / name for name in files if name.endswith(".py"))
    return sorted(dict.fromkeys(paths))


def source_text_matches(
    pattern: str, roots: Iterable[Path], ignore_case: bool = False
) -> list[SourceTextMatch]:
    """Find a literal pattern in complete lines from the selected Python files."""
    if not pattern or "\n" in pattern or "\r" in pattern:
        raise ValueError("pattern must be one non-empty line")
    needle = pattern.casefold() if ignore_case else pattern

    def matching(line: str) -> bool:
        haystack = line.casefold() if ignore_case else line
        return needle in haystack

    return [
        SourceTextMatch(path=path, line_number=line_number, text=line)
        for path in python_source_paths(roots)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if matching(line)
    ]
