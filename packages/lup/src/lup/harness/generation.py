"""Small deterministic helpers shared across pipeline stages.

Invocation-argument serialization for the adapter renderers, tree indexing
for reconciliation, and the validation-failure error
:mod:`lup.harness.validation` raises.
"""

import json


from lup.harness.models import Artifact, ArtifactTree
from lup.types import JsonValue


def argument_text(value: JsonValue) -> str:
    """Serialize one semantic invocation argument deterministically."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def plugin_served_tool(plugin: str, server: str) -> str:
    """Address one tool server a plugin brings, on a runtime that namespaces them.

    A plugin's servers are scoped by the plugin that loaded them, so the bare
    key a server is declared under matches nothing: a permission, a hook
    matcher, or a skill's tool grant written against it never fires. One
    spelling here because two artifacts have to agree on the name — the
    settings that grant these tools, and the skills and agents that ask for
    them — and a grant that stops matching its permission is invisible until
    an agent is refused a tool its own declaration listed.

    Only the namespacing runtime needs this. Codex declares each server under
    its bare key and addresses it there, so its config and its grants already
    agree and neither is rewritten.
    """
    return f"mcp__plugin_{plugin}_{server}"


class ArtifactValidationError(ValueError):
    """Complete desired output failed validation before materialization."""


def artifact_map(tree: ArtifactTree) -> dict[str, Artifact]:
    """Index an already validated tree by portable path."""
    return {artifact.path.as_posix(): artifact for artifact in tree.artifacts}
