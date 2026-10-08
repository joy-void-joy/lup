"""lup's own declaration, as far as judging writes reads it.

lup is developed with itself (`DESIGN.md`, *How lup reaches a project*). The
defaults apply, with two additions:
- the data that sets lup's policy (`lup_dev.catalog`) is a protected path, so the
  operator reviews every change to it before it lands;
- the bridge's interim hooks (`.claude/hooks/`) are excluded: uv scripts with their
  own dependencies, outside the conventions, which go with the bridge. They stay
  protected, as everything under `.claude/` is, so a change to one still asks.
"""

from lup_dev.project import Project, Protected

project = Project(
    protected=Protected.default().add("packages/lup-dev/src/lup_dev/catalog/**"),
    excluded=[".claude/hooks/**"],
)
