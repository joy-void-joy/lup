"""The plugin a project offers Codex, read from the project that offers it.

A scoped home is seeded without account-wide plugin state, on the stated
understanding that it "installs its own against a verified digest". Nothing
performed that for a session, so a session opened by an application carried no
dispatcher — and looked exactly like one that carried it. This is where a home
learns which plugin is its own.

Read from the project rather than declared into a session because that is what
it is a property of: a session's working directory need not be inside the
project at all, and for an agent it usually is not.
"""

import json
from pathlib import Path

from lup.adapters.codex.marketplace import MARKETPLACE_MANIFEST, CodexMarketplace

DECLARATION = {
    "name": "example-repository",
    "plugins": [
        {
            "name": "lup",
            "source": {"path": "./.codex/plugins/lup", "source": "local"},
        }
    ],
}


def project(root: Path, declaration: object = DECLARATION) -> Path:
    """A project root declaring one marketplace, as the harness generates it."""
    manifest = root / MARKETPLACE_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(declaration), encoding="utf-8")
    return root


def test_a_project_names_the_plugin_it_offers(tmp_path: Path) -> None:
    """Everything the installer needs, without a second place to declare it."""
    declared = CodexMarketplace.declared(project(tmp_path))

    assert declared is not None
    assert declared.name == "example-repository"
    assert declared.plugin == "lup"
    assert declared.source == (tmp_path / ".codex" / "plugins" / "lup").resolve()


def test_the_selector_pairs_the_plugin_with_its_marketplace(tmp_path: Path) -> None:
    """How the CLI names a plugin, kept beside what it is derived from."""
    declared = CodexMarketplace.declared(project(tmp_path))

    assert declared is not None
    assert declared.selector == "lup@example-repository"


def test_a_project_offering_no_codex_tree_declares_nothing(tmp_path: Path) -> None:
    """Opting out of a runtime is not a misconfiguration."""
    assert CodexMarketplace.declared(tmp_path) is None


def test_a_manifest_listing_no_plugin_declares_nothing(tmp_path: Path) -> None:
    """An empty roster is an answer, and indexing it would be a crash."""
    empty = {"name": "example-repository", "plugins": []}

    assert CodexMarketplace.declared(project(tmp_path, empty)) is None


def test_the_source_is_resolved_against_the_project_that_declared_it(
    tmp_path: Path,
) -> None:
    """The manifest states a relative path; an installer needs a real one."""
    declared = CodexMarketplace.declared(project(tmp_path))

    assert declared is not None
    assert declared.source.is_absolute()
