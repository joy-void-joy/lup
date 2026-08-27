"""Codex's own words for standing its sandbox down.

A leaf on purpose, for the reason `login.py` is one: the launcher and the
image-side probe both need this spelling, and neither should pull the session
runtime in to get it.
"""

from lup.providers.confinement import ProviderConfinement

CODEX_CONFINEMENT = ProviderConfinement(off=["--sandbox", "danger-full-access"])
"""What tells Codex that the container around it is the boundary.

A mode name rather than a settings document, which is the whole reason the
carrier holds argv words instead of a flag.

Codex's own documentation names this case directly: configure the container to
provide the isolation, then run with full access inside it. The alternative is
worse than merely redundant here rather than differently strict --
``workspace-write`` turns network access off, and a contained session's route
out is the network. The strict-looking envelope would cut the session off from
the egress boundary built for it.
"""
