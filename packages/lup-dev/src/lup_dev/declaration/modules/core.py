"""`Core`: the core's parts a project can change, which every project holds."""

from lup_dev.catalog import paths as lup_paths
from lup_dev.declaration.kinds import Paths
from lup_dev.declaration.module import Module
from lup_dev.declaration.modules.python import CONFIGURATION


class Core(Module):
    """lup's core: the path roles every project has, and what every module talks through."""

    name = "core"

    paths: Paths = Paths.of(
        protected=[
            pattern
            for pattern in lup_paths.Paths().protected
            if pattern not in CONFIGURATION
        ],
        operator_documents=lup_paths.Paths().operator_documents,
        scratch=lup_paths.Paths().scratch,
        docs=lup_paths.Paths().docs,
        data=lup_paths.Paths().data,
    )
    """Every protected path but the Python tools' files, which are `Python`'s; the
    operator's documents, scratch, docs and data. Nothing is excluded unless the
    project says."""
