"""Small deterministic helpers shared across pipeline stages.

Invocation-argument serialization for the adapter renderers, harness-location
composition over the spellings each adapter owns, tree indexing for
reconciliation, and the validation-failure error the compilation roots in
:mod:`lup.adapters.harness` raise.
"""

import json

from pydantic import BaseModel, ConfigDict

from lup.harness.contracts import NativePathSpelling
from lup.harness.models import Artifact, ArtifactTree, NativePath, PluginPath
from lup.types import JsonValue


def argument_text(value: JsonValue) -> str:
    """Serialize one semantic invocation argument deterministically."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class NativePaths(BaseModel):
    """The spellings one renderer needs: its own, and every runtime's.

    Composition holds both so this module can render a location for the reader
    or for every runtime at once without naming a platform itself — the product
    names arrive through ``runtime_name``.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    own: NativePathSpelling
    every: list[NativePathSpelling]


def tree_path(paths: NativePaths, part: NativePath) -> str:
    """Spell one harness-tree location for the reader, or for every runtime."""
    match part.scope:
        case "this_tree":
            return paths.own.tree(part.location)
        case "every_tree":
            return ", ".join(
                f"{one.tree(part.location)} under {one.runtime_name}"
                for one in paths.every
            )


def plugin_path(paths: NativePaths, part: PluginPath) -> str:
    """Spell one plugin-owned location for the reader, or for every runtime."""
    match part.scope:
        case "this_tree":
            return paths.own.plugin(part.plugin, part.location, part.member)
        case "every_tree":
            return ", ".join(
                f"{one.plugin(part.plugin, part.location, part.member)} "
                f"under {one.runtime_name}"
                for one in paths.every
            )


class ArtifactValidationError(ValueError):
    """Complete desired output failed validation before materialization."""


def artifact_map(tree: ArtifactTree) -> dict[str, Artifact]:
    """Index an already validated tree by portable path."""
    return {artifact.path.as_posix(): artifact for artifact in tree.artifacts}
