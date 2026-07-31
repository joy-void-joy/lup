"""Small deterministic helpers shared across pipeline stages.

Invocation-argument serialization for the adapter renderers, tree indexing
for reconciliation, the do-not-edit banner every commentable artifact opens
with, and the validation-failure error the compilation roots in
:mod:`lup.adapters.harness` raise.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.harness.models import Artifact, ArtifactTree
from lup.types import JsonValue


def argument_text(value: JsonValue) -> str:
    """Serialize one semantic invocation argument deterministically."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


GENERATE_COMMAND = "uv run lup-devtools harness generate all"
"""Regeneration command named by every banner harness generation writes."""


class CommentStyle(ABC):
    """Render banner lines in one file type's comment syntax."""

    @abstractmethod
    def wrap(self, lines: Sequence[str]) -> str:
        """Return the lines as one newline-terminated comment block."""


class LineCommentStyle(CommentStyle):
    """Open every line with a repeated single-line comment marker."""

    def __init__(self, marker: str) -> None:
        if not marker:
            raise ValueError("a line comment marker cannot be empty")
        self.marker = marker

    def wrap(self, lines: Sequence[str]) -> str:
        return "".join(f"{self.marker} {line}\n" for line in lines)


class BlockCommentStyle(CommentStyle):
    """Enclose every line in one opening and closing delimiter pair."""

    def __init__(self, opening: str, closing: str) -> None:
        if not opening or not closing:
            raise ValueError("a block comment needs both delimiters")
        self.opening = opening
        self.closing = closing

    def wrap(self, lines: Sequence[str]) -> str:
        return "".join(f"{self.opening} {line} {self.closing}\n" for line in lines)


class ArtifactMatcher(ABC):
    """Decide whether one banner route accepts a generated artifact."""

    @abstractmethod
    def matches(self, path: Path) -> bool:
        """Return whether this matcher accepts the artifact path."""


class SuffixMatcher(ArtifactMatcher):
    """Match any of a non-empty set of file suffixes."""

    def __init__(self, *suffixes: str) -> None:
        if not suffixes or not all(suffixes):
            raise ValueError("a suffix matcher needs at least one suffix")
        self.suffixes = suffixes

    def matches(self, path: Path) -> bool:
        return path.suffix in self.suffixes


class BannerRoute(BaseModel):
    """One immutable matcher and the comment style it selects."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    matcher: ArtifactMatcher
    style: CommentStyle


class BannerRouter:
    """Select an explicit style first, then the first artifact match."""

    def __init__(self, routes: list[BannerRoute]) -> None:
        names = [route.name for route in routes]
        if len(names) != len(dict.fromkeys(names)):
            raise ValueError("banner route names must be unique")
        self.routes = tuple(routes)

    def resolve(self, path: Path, style: str | None = None) -> CommentStyle:
        if style is not None:
            selected = next(
                (route for route in self.routes if route.name == style), None
            )
            if selected is None:
                raise LookupError(f"unknown banner comment style {style!r}")
            return selected.style
        selected = next(
            (route for route in self.routes if route.matcher.matches(path)), None
        )
        if selected is None:
            raise LookupError(f"no banner comment style spells {path.as_posix()!r}")
        return selected.style


BANNER_STYLES = BannerRouter(
    [
        BannerRoute(
            name="markdown",
            matcher=SuffixMatcher(".md"),
            style=BlockCommentStyle("<!--", "-->"),
        ),
        BannerRoute(
            name="hash",
            matcher=SuffixMatcher(".py", ".toml", ".conf", ".json5", ".sh"),
            style=LineCommentStyle("#"),
        ),
    ]
)
"""Every comment syntax a generated artifact's banner is spelled in."""


def generated_banner(
    path: Path,
    *,
    source: str,
    command: str = GENERATE_COMMAND,
    notes: Sequence[str] = (),
    style: str | None = None,
) -> str:
    """Open one generated artifact with its do-not-edit banner.

    The block ends in a blank line so a caller concatenates it directly onto
    the body. ``notes`` carries whatever else that artifact's reader needs at
    the very top — a second location it renders to, a pointer into the docs.
    """
    lines = [
        f"Generated from {source} by `{command}` — edit the source, not this file.",
        *notes,
    ]
    return BANNER_STYLES.resolve(path, style).wrap(lines) + "\n"


def banner_over_asset(body: str, path: Path, *, source: str) -> str:
    """Open a verbatim-copied asset with its banner, below any shebang.

    The asset is hand-written library source; only the copy that lands in a
    generated tree carries the banner, so the original never claims to be
    generated output.
    """
    lines = body.splitlines(keepends=True)
    banner = generated_banner(path, source=source)
    if not lines or not lines[0].startswith("#!"):
        return banner + body
    return lines[0] + banner + "".join(lines[1:])


class ArtifactValidationError(ValueError):
    """Complete desired output failed validation before materialization."""


def artifact_map(tree: ArtifactTree) -> dict[str, Artifact]:
    """Index an already validated tree by portable path."""
    return {artifact.path.as_posix(): artifact for artifact in tree.artifacts}
