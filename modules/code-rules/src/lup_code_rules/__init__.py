"""lup's code rules: patterns that are rarely the right choice, told to an agent as they write them, and `# lup:` comments, read with pyright's own tree (`README.md` here)."""

from lup_code_rules.directives import Defer, Directive, Ignore, Malformed, Note
from lup_code_rules.module import CodeRules, Exempt, Rules

__all__ = [
    "CodeRules",
    "Defer",
    "Directive",
    "Exempt",
    "Ignore",
    "Malformed",
    "Note",
    "Rules",
]
