# lup: ignore[import-re, re-call]
"""Seam-boundary scan: per-engine adapter imports stay inside the seam.

``lup.adapters`` holds the neutral seam contracts plus every SDK-specific
module behind them. Consumer code composes through the seam — ``wiring``,
the ``Engine`` front doors, the neutral contracts — and never imports a
per-engine implementation package; backend dispatch outside the seam is
what the adapter layer exists to eliminate. This scan finds those imports
so ``dev check`` fails on a breach instead of trusting convention.

The engines (``lup.adapters.engines.*``) are deliberately not banned:
passing ``engine=ClaudeEngine()`` is the documented custom-wiring API,
and each engine is an import-light front door. What the ban covers is
the implementation packages behind them — ``clients``, ``background``,
``profiles``, and ``tools`` under a ``claude``/``codex`` name. A
deliberate exception carries ``# lup: ignore[seam-boundary]``.
"""

import re
from pathlib import Path

from pydantic import BaseModel

from lup.codescan.common import IGNORE_RE, file_level_ignore, ignore_rule_ids

RULE_ID = "seam-boundary"
"""The id an inline or file-level `# lup: ignore[...]` names to except a site."""

ENGINE_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(?P<module>lup\.adapters\.(?:clients|background|profiles|tools)"
    r"\.(?:claude|codex)\b[\w.]*)"
)
"""A per-engine implementation import at statement position.

Import statements are line-shaped and cannot contain string literals, so
line-matching is sound and an `# lup: ignore` on a matched line can only
be a real comment.
"""


def path_is_sanctioned(rel_path: Path) -> bool:
    """Whether per-engine imports are at home under this repo-relative path.

    Inside the adapters package the per-engine modules compose each other —
    that is the seam itself — and tests exercise engine internals directly
    by design. Everywhere else a per-engine import is a breach.
    """
    posix = rel_path.as_posix()
    return "lup/adapters/" in posix or posix.startswith("tests/")


class BoundaryBreach(BaseModel):
    """One per-engine adapter import outside the seam's sanctioned homes."""

    line: int
    module: str
    text: str


def find_boundary_breaches(text: str) -> list[BoundaryBreach]:
    """Per-engine adapter imports in ``text``, minus ignored ones.

    Honors the shared escape hatches: an inline ``# lup: ignore`` on the
    import line (bare, or typed naming :data:`RULE_ID`) and the file-level
    directive in the first lines.
    """
    file_ignore = file_level_ignore(text)
    if file_ignore is not None and (
        file_ignore.rule_ids is None or RULE_ID in file_ignore.rule_ids
    ):
        return []

    def line_breach(line_no: int, line: str) -> BoundaryBreach | None:
        match = ENGINE_IMPORT_RE.match(line)
        if match is None:
            return None
        ignore = IGNORE_RE.search(line)
        if ignore is not None:
            ids = ignore_rule_ids(ignore)
            if ids is None or RULE_ID in ids:
                return None
        return BoundaryBreach(
            line=line_no, module=match.group("module"), text=line.strip()
        )

    candidates = (
        line_breach(line_no, line)
        for line_no, line in enumerate(text.splitlines(), start=1)
    )
    return [breach for breach in candidates if breach is not None]
