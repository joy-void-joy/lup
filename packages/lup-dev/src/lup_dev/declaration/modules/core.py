"""`Core`: the core's parts a project can change, which every project holds."""

from lup_dev.catalog.paths import CorePaths
from lup_dev.catalog.room import StandardMachine
from lup_dev.declaration.kinds import Guidance, Package, Packages, Paths, Session
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
    """lup's core: every project's path roles, room and sessions, and what every module talks through."""

    name = "core"

    paths: Paths = Paths.of(
        protected=CorePaths().protected,
        operator_documents=CorePaths().operator_documents,
        scratch=CorePaths().scratch,
        docs=CorePaths().docs,
        data=CorePaths().data,
    )
    """Every protected path but the Python tools' files, which are `Python`'s; the
    operator's documents, scratch, docs and data. Nothing is excluded unless the
    project says."""
    packages: Packages = standard_machine()
    """The standard machine, every room's whatever the host: the shell and the
    usual tools, an agent's everyday work, what the runtimes call on, and editors
    (`lup_dev.catalog.room`)."""
    session: Session = Session()
    """How every session runs: the subagents' prompt cache, auto memory, and the
    built-in tools removed from context, lup's unless the project says."""
    guidance: Guidance = Guidance()
    """The sections of guidance `Core` brings: none of lup's, so a project's own
    section, where it has no module of its own, goes here."""
