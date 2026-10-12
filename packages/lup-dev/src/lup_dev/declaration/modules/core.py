"""`Core`: the core's parts a project can change, which every project holds."""

from lup_dev.catalog.paths import CorePaths
from lup_dev.declaration.kinds import Paths
from lup_dev.declaration.module import Module


class Core(Module):
    """lup's core: the path roles every project has, and what every module talks through."""

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
