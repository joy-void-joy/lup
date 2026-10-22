"""`Core`: the core's parts a project can change, which every project holds."""

from pathlib import Path

from lup_dev.catalog.paths import CorePaths
from lup_dev.catalog.room import StandardMachine
from lup_dev.declaration.kinds import (
    Credentials,
    Guidance,
    Package,
    Packages,
    Paths,
    Section,
    Session,
)
from lup_dev.declaration.module import Module


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
        operator_documents=CorePaths().operator_documents,
        tests=CorePaths().tests,
        scratch=CorePaths().scratch,
        docs=CorePaths().docs,
        data=CorePaths().data,
    )
    """Every protected path but the Python tools' files, which are `Python`'s; the
    operator's documents, TypeScript's tests, scratch, docs and data. Nothing is
    excluded unless the project says."""
    packages: Packages = standard_machine()
    """The standard machine, every room's whatever the host: the shell and the
    usual tools, an agent's everyday work, what the runtimes call on, and `nano`,
    beside which a launch installs the operator's own editor
    (`lup_dev.catalog.room`)."""
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
