"""The plugin a project offers Codex, read from the project rather than told.

``sanitized_codex_config`` strips account-wide plugin state when it seeds a
scoped home, on the stated understanding that "a scoped home installs its own
against a verified digest". This is where a home learns *which* one, so that
sentence can be true of a session and not only of a launcher.

Read from the project rather than declared into a session, because that is
what it is a property of. A session's working directory is not the project —
an agent may run in a scratch directory outside it entirely — while the
process opening the session is inside the project by construction, which is
the same source ``harness launch`` already resolves its plugin from.
"""

import json
from pathlib import Path

from pydantic import BaseModel

MARKETPLACE_MANIFEST = Path(".agents") / "plugins" / "marketplace.json"
"""Where a project declares the plugins it offers a Codex home."""


class CodexMarketplace(BaseModel, frozen=True):
    """One project's plugin offering: what it is called and where it lives."""

    name: str
    """The marketplace name a home registers the source under."""

    plugin: str
    """The plugin's own name, which the selector pairs with the marketplace."""

    source: Path
    """The plugin's root, resolved against the project that declared it."""

    @property
    def selector(self) -> str:
        """How the Codex CLI names this plugin when installing or removing it."""
        return f"{self.plugin}@{self.name}"

    @classmethod
    def declared(cls, root: Path) -> "CodexMarketplace | None":
        """The plugin this project offers, or None where it offers none.

        None rather than an error: a project with no Codex tree is a project
        that opts out of this runtime, not one that is misconfigured, and the
        manifest is generated so a malformed one is a generator bug worth
        raising over rather than absorbing.
        """
        manifest = root / MARKETPLACE_MANIFEST
        if not manifest.is_file():
            return None
        declaration = json.loads(manifest.read_text(encoding="utf-8"))
        offered = declaration["plugins"]
        if not offered:
            return None
        first = offered[0]
        return cls(
            name=declaration["name"],
            plugin=first["name"],
            source=(root / first["source"]["path"]).resolve(),
        )
