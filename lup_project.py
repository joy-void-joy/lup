"""lup's own declaration: lup's default modules, lup's changes to them, and its own.

lup is developed with itself, declared through the surface a project uses
(`docs/declaration.md`, *lup declares itself the same way*). Each change to lup's
modules carries its reason, and what only lup's repository needs is a module of
its own, `LupDevelopment`.
"""

from pathlib import Path

from lup_dev import (
    CodeRules,
    Exemption,
    Exemptions,
    Gate,
    Guidance,
    Module,
    Modules,
    Paths,
    Project,
    Pytest,
    Python,
    Requirement,
    Rules,
    Section,
    Step,
    TestRoots,
)


class LupDevelopment(Module):
    """What only lup's repository needs: building lup's engine, guarding its policy, its guidance.

    - The engine is built before the gate's first step, and again only when its
      bundle is older than one of its sources, since tests that ask a stale engine
      fail for reasons the change didn't cause. Its command is the tool alone, which
      the gate runs through the project's runner, and the installer runs the same
      step the same way (`lup_dev/install.py`). npm, which installs its bundler,
      joins the room's image as Arch's `npm`.
    - The data that sets lup's policy (`lup_dev.catalog`) is protected, so the
      operator reviews every change to it before it lands.
    - The bridge's interim hooks are excluded: uv scripts with their own
      dependencies, outside the conventions, which go with the bridge. They stay
      protected, as everything in a runtime's own directory is, so a change to one
      still asks.
    - Working on lup is `AGENTS.md`, the project's own section of the guidance,
      after the sections of lup's modules.
    """

    name = "lup-development"
    requirements = [
        Requirement(
            tool="npm",
            why="installs the engine's bundler",
            install="it comes with Node",
            package="npm",
        )
    ]

    paths: Paths = Paths.of(
        protected=["packages/lup-dev/src/lup_dev/catalog/**"],
        # lup: ignore("runtime-mention", why="data naming a runtime's own files")
        excluded=[".claude/hooks/**"],
    )
    gate: Gate = Gate.of(
        Step(
            name="engine",
            command=["python", "packages/lup-dev/checker/build.py"],
            builds="packages/lup-dev/src/lup_dev/codescan/bundle/engine.js",
            sources=[
                "packages/lup-dev/checker/src/**/*",
                "packages/lup-dev/checker/build.py",
                "packages/lup-dev/checker/package.json",
                "packages/lup-dev/checker/package-lock.json",
                "packages/lup-dev/checker/tsconfig.json",
                "packages/lup-dev/src/lup_dev/catalog/rules.ts",
                "uv.lock",
            ],
        ),
        before="rules",
    )
    guidance: Guidance = Guidance.of(Section(name="lup", path=Path("AGENTS.md")))


project = Project(
    # While lup is being built, only a protected path's change asks the operator:
    # the design is reviewed in notes before the code and at landing (`AGENTS.md`,
    # *How work goes*).
    asks="protected",
    modules=Modules.default()
    .edit(
        Python(tests=TestRoots.of(Pytest(root=Path("packages/*/tests")))),
        why="each package's tests are in its own `tests/`",
    )
    .edit(
        CodeRules(rules=Rules().add("runtime-mention")),
        why="a rule about lup's own architecture, which lup's default leaves out",
    )
    .edit(
        CodeRules(
            exempt=Exemptions().add(
                Exemption(
                    rule="runtime-mention",
                    paths=["packages/lup/src/lup/__init__.py"],
                    why=(
                        "the front door, where callers choose a runtime by its "
                        "client's name"
                    ),
                ),
                Exemption(
                    rule="constant-home",
                    paths=["packages/lup-dev/src/lup_dev/catalog/**"],
                    why=(
                        "the catalog is where lup's policy data lives: its "
                        "constants' home"
                    ),
                ),
            )
        )
    )
    .add(LupDevelopment()),
)
