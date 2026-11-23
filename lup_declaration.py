"""lup's own declaration: the modules lup is made of, declared as any project's are, the machine's parts among them, since lup's repository is the home one.

The gate checks the promises of every module it resolves to (`lup_declaration`
in `pyproject.toml`'s pytest settings).
"""

# lup: defer(issue=13, why="named apart from `lup_project.py`, which the second lup, judging this repository's sessions until this lup runs its own, reads as its own declaration and would refuse")

from lup import Gate, Module, Modules, Project, Step, Steps
from lup.code_rules import CodeRules
from lup.hosting.module import Hosting
from lup.sessions.part import Sessions


class Page(Module):
    """The dashboard's page, built from its sources.

    The dashboard's page, built from its sources here alone: a project installs it
    built.

    Its gate step installs the page's packages from its lockfile, generates its
    types from what it reads of the core, type-checks it, checks its promises
    and builds it (`modules/core/page/package.json`, `gate`).
    """

    name = "page"
    steps: Steps = Steps.of(
        Step(
            name="page",
            command=["pnpm", "--dir", "modules/core/page", "run", "--silent", "gate"],
            together=True,
        )
    )


project = Project(
    modules=Modules.default()
    .edit(
        Gate(
            steps=Steps().replace(
                "promises",
                Step(
                    name="promises",
                    command=["pytest", "-n", "12", "--dist", "worksteal"],
                    together=True,
                ),
                why=(
                    "on twelve workers, stealing work so one slow file doesn't "
                    "hold the run: fewer than every core leaves room for other "
                    "sessions' gates"
                ),
            )
        ),
        why="lup's promises are many, and run on several workers",
    )
    .add(Hosting(), Sessions(), Page(), CodeRules())
)
