"""lup's code rules: patterns that are rarely the right choice, told to an agent as they write them, and `# lup:` comments, read with pyright's own tree (`README.md` here)."""

from lup_code_rules.directives import Defer, Directive, Ignore, Malformed, Note
from lup_code_rules.reading import (
    Deferrals,
    Reworded,
    changed_deferrals,
    deferrals_changed,
    read_directives,
    typescript_directives,
)
from lup_code_rules.reports import (
    Examples,
    FileReport,
    Finding,
    Flagged,
    Position,
    RuleInfo,
    Span,
)

# The module, imported as it's first used: its promises, which it imports as
# it's defined, import this front door, and find it whole.
lazy from lup_code_rules.module import CodeRules, Exempt, Rules

__all__ = [
    "CodeRules",
    "Defer",
    "Deferrals",
    "Directive",
    "Examples",
    "Exempt",
    "FileReport",
    "Finding",
    "Flagged",
    "Ignore",
    "Malformed",
    "Note",
    "Position",
    "Reworded",
    "RuleInfo",
    "Rules",
    "Span",
    "changed_deferrals",
    "deferrals_changed",
    "read_directives",
    "typescript_directives",
]
