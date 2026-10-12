"""lup's own declaration, as far as judging writes reads it.

lup is developed with itself (`DESIGN.md`, *How lup reaches a project*). The
defaults apply, with these additions:
- while lup is being built, only a protected path's change asks the operator
  (`asks`): the design is reviewed in notes before the code and at landing
  (`AGENTS.md`, *How work goes*);
- the data that sets lup's policy (`lup_dev.catalog`) is a protected path, so the
  operator reviews every change to it before it lands;
- the bridge's interim hooks are excluded: uv scripts with their own dependencies,
  outside the conventions, which go with the bridge. They stay protected, as
  everything in a runtime's own directory is, so a change to one still asks;
- the library's front door is exempt from `runtime-mention`: it names the
  runtimes, as the clients a caller chooses between;
- the catalog is exempt from `constant-home`: it's where lup's policy data lives,
  the home of the constants it holds.
"""

from lup_dev.project import Exemption, Project, Protected

project = Project(
    asks="protected",
    protected=Protected.default().add("packages/lup-dev/src/lup_dev/catalog/**"),
    # lup: ignore("runtime-mention", why="data naming a runtime's own files")
    excluded=[".claude/hooks/**"],
    exempt=[
        Exemption(
            rule="runtime-mention",
            paths=["packages/lup/src/lup/__init__.py"],
            why="the front door, where callers choose a runtime by its client's name",
        ),
        Exemption(
            rule="constant-home",
            paths=["packages/lup-dev/src/lup_dev/catalog/**"],
            why="the catalog is where lup's policy data lives: its constants' home",
        ),
    ],
)
