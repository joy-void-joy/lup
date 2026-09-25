"""Claude Code's own words for standing its sandbox down.

A leaf on purpose, for the reason `login.py` is one: the launcher and the
image-side probe both need this spelling, and neither should pull the session
runtime in to get it.
"""

import json

from lup.providers.confinement import ProviderConfinement
from lup.types import JsonObject

# lup: ignore[constant-declaration] — Claude Code's own settings key for its
# sandbox, spelled as the CLI reads it
CLAUDE_SANDBOX_OFF: JsonObject = {"sandbox": {"enabled": False}}
"""The settings document standing Claude Code's own sandbox down.

Held as data beside the argv below, because the CLI reads one ``--settings``
document: a launch with more to say — an effort's settings — merges into this
rather than passing a second flag the CLI would read in its place."""

CLAUDE_CONFINEMENT = ProviderConfinement(
    off=["--settings", json.dumps(CLAUDE_SANDBOX_OFF)]
)
"""What tells Claude Code that the container around it is the boundary.

A settings merge rather than a flag, because that is the surface the key lives
on. It is passed at the command line rather than written into the generated
artifact, and the artifact goes on saying ``enabled: true`` -- which is the
right answer for the uncontained launch the same file serves.

The remedy the vendor documents for a sandbox that cannot start inside a
container is ``enableWeakerNestedSandbox``, described as considerably weaker
and appropriate only where an outer container is already the boundary. Where
that is true, a wall that has to be weakened to stand up is worth less than
saying plainly which wall is load-bearing.
"""
