"""lup's own declaration, as far as judging writes reads it.

lup is developed with itself (`DESIGN.md`, *How lup reaches a project*). The
defaults apply, with one addition: the data that sets lup's policy
(`lup_dev.catalog`) is a protected path, so the operator reviews every change to
it before it lands.
"""

from lup_dev.project import Project, Protected

project = Project(
    protected=Protected.default().add("packages/lup-dev/src/lup_dev/catalog/**"),
)
