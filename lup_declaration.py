"""lup's own declaration: the modules lup is made of, declared as any project's are.

The gate checks the promises of every module it resolves to (`lup_declaration`
in `pyproject.toml`'s pytest settings).
"""

# lup: defer(issue=13, why="named apart from `lup_project.py`, which the second lup, judging this repository's sessions until this lup runs its own, reads as its own declaration and would refuse")

from lup import Modules, Project

project = Project(modules=Modules.default())
