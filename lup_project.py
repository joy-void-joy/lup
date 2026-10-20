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
    Package,
    Packages,
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
    """What only lup's repository needs: building lup's engine and its dashboard's page, guarding its policy, its guidance.

    - The engine is built before the gate's first step, and again only when its
      bundle is older than one of its sources, since tests that ask a stale engine
      fail for reasons the change didn't cause. Its command is the tool alone, which
      the gate runs through the project's runner, and trust on launch runs the same
      step the same way to build the copy the operator approves
      (`lup_dev/launch/trust.py`). npm, which installs its bundler, joins the
      room's image as Arch's `npm`.
    - The dashboard's page is built the same way, after the engine: its types
      generated from the API's description, type-checked, tested and bundled
      (`packages/lup-dashboard/build.py`), again only when one of its sources,
      the host's models the API describes among them, is newer than the page.
    - The data that sets lup's policy (`lup_dev.catalog`) is protected, so the
      operator reviews every change to it before it lands.
    - Working on lup is `AGENTS.md`, the project's own section of the guidance,
      after the sections of lup's modules.
    - The guidance sections lup's modules ship are the operator's documents, as
      `AGENTS.md` and `DESIGN.md` are: every project's sessions read them, so
      each change waits for the operator, who sees how the guidance changes.
    - Chromium is in the room alone, for sessions to drive the dashboard's page
      headless with Playwright, looking at what they build; nothing on the host
      needs it, so it's a package of the room's image rather than a requirement.
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

    packages: Packages = Packages.of(
        Package(name="chromium", why="Playwright drives it to look at the dashboard")
    )
    paths: Paths = Paths.of(
        protected=["packages/lup-dev/src/lup_dev/catalog/**"],
        operator_documents=["packages/**/guidance.md", "packages/**/guidance/*.md"],
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
        Step(
            name="dashboard",
            command=["python", "packages/lup-dashboard/build.py"],
            builds="packages/lup-dashboard/src/lup_dashboard/page/index.html",
            sources=[
                "packages/lup-dashboard/page/src/**/*",
                "packages/lup-dashboard/page/index.html",
                "packages/lup-dashboard/page/package.json",
                "packages/lup-dashboard/page/package-lock.json",
                "packages/lup-dashboard/page/tsconfig.json",
                "packages/lup-dashboard/page/vite.config.ts",
                "packages/lup-dashboard/build.py",
                "packages/lup-dashboard/src/lup_dashboard/api.py",
                "packages/lup-dashboard/src/lup_dashboard/server.py",
                "packages/lup-dev/src/lup_dev/host/protocol.py",
                "packages/lup-dev/src/lup_dev/inbox/protocol.py",
                "packages/lup-dev/src/lup_dev/inbox/store.py",
                "packages/lup/src/lup/sessions/results.py",
                "packages/lup/src/lup/tools/speaking.py",
                "uv.lock",
            ],
        ),
        before="rules",
    )
    guidance: Guidance = Guidance.of(Section(name="lup", path=Path("AGENTS.md")))


project = Project(
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
