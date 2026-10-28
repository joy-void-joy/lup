"""`Core`: the core's parts a project can change, which every project holds."""

from datetime import timedelta
from pathlib import Path
from typing import Annotated

from pydantic import Field

from lup.blocks import SHELL_FOLDS, SHELL_VERBS
from lup_dev.catalog.paths import CorePaths
from lup_dev.catalog.room import PackageAge, StandardMachine
from lup_dev.declaration.kinds import (
    Credentials,
    Folds,
    Guidance,
    Package,
    Packages,
    Paths,
    Section,
    Session,
    Verbs,
)
from lup_dev.declaration.looks import HOLD
from lup_dev.declaration.module import Module
from lup_dev.host.records import PAUSE


def standard_machine() -> Packages:
    """Return the standard machine: every room's packages, each with its group's reason.

    >>> [each.entry.name for each in standard_machine().resolve([], [])][:3]
    ['bash', 'coreutils', 'findutils']
    """
    return Packages.of(
        *(
            Package(name=name, why=group.why)
            for group in StandardMachine().groups
            for name in group.names
        )
    )


class Core(Module):
    """lup's core: every project's path roles, room, sessions and limits on the operator's credentials, and what every module talks through."""

    name = "core"

    paths: Paths = Paths.of(
        protected=CorePaths().protected,
        secret=CorePaths().secret,
        operator_documents=CorePaths().operator_documents,
        tests=CorePaths().tests,
        scratch=CorePaths().scratch,
        docs=CorePaths().docs,
        data=CorePaths().data,
    )
    """Every protected path but the Python tools' files, which are `Python`'s; the
    files that hold secrets; the operator's documents, TypeScript's tests,
    scratch, docs and data. Nothing is excluded unless the project says."""
    packages: Packages = standard_machine()
    """The standard machine, every room's whatever the host: the shell and the
    usual tools, an agent's everyday work, what the runtimes call on, and `nano`,
    beside which a launch installs the operator's own editor
    (`lup_dev.catalog.room`)."""
    package_age: Annotated[timedelta, Field(ge=timedelta(0))] = PackageAge().minimum
    """How long a package must have been published before the room's package
    managers install it: three days, unless the project says. The launch writes
    it into the user-level settings of each package manager the room's image
    holds, which a project's own setting outranks (`docs/launch.md`, *The
    package age gate*)."""
    folds: Folds = Folds.of(*SHELL_FOLDS)
    """The shell's fold kinds, an agent's group, an item, its context, and a
    file's, a body's and a run of unchanged lines', which every repository's
    looks carry first: a person's layer changes how each starts and whether
    `zR` and `zM` reach it, `Folds().replace("lines", …)`."""
    verbs: Verbs = Verbs.of(*SHELL_VERBS, HOLD, PAUSE)
    """The verbs the review's keys say, Space and a key: the shell's, done,
    decline, send to and comment, which apply to anything; the judge's, hold;
    and the runtime adapters', pause, the core's until each is a module. A
    person's layer gives one another key with `.replace`."""
    session: Session = Session()
    """How every session runs: the subagents' prompt cache, auto memory, idle
    compaction, the built-in tools removed from context and the account's
    connectors. lup's, which the person's own runtime settings outrank, unless
    the project says, which outranks theirs."""
    credentials: Credentials = Credentials()
    """What the host does with the operator's credentials for a launched session
    without asking, and the refs no push updates: lup's
    (`lup_dev.catalog.credentials`), unless the project says."""
    guidance: Guidance = Guidance.of(
        Section(
            name="core",
            package="lup_dev.declaration.modules",
            path=Path("guidance/core.md"),
        )
    )
    """The room: what's mounted and what isn't, where the walls are, what's the
    agent's to decide and what's the operator's, and the judge. A project's own
    section, where it has no module of its own, goes here too, after it."""
