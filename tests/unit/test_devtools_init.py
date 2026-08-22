"""Behavior tests for `lup-devtools dev init`'s manifest rewrite.

The scaffold flag is what lets one rule read two ways: `# lup: template:`
markers are inventory in the scaffold that ships them and outstanding work in
the repository that adopted it. Clearing the flag is the moment that flips,
so these pin that adoption actually clears it — against this repository's own
`pyproject.toml`, because a flag the real manifest declares and the real
command fails to clear is the failure nobody would see until it had already
shipped into somebody else's repo.
"""

import ast
from pathlib import Path

import pytest
import tomlkit

import lup_template.devtools.harness.catalog as catalog
from lup.workspace.paths import is_template_scaffold
from lup_template.devtools.dev.init import (
    clear_scaffold_flag,
    ownership_listing,
    path_literal,
    rendered_listing,
    spliced,
)

REPO_PYPROJECT = Path("pyproject.toml")


def test_this_repository_declares_itself_the_scaffold() -> None:
    assert is_template_scaffold(Path.cwd())


def test_adoption_clears_the_flag_this_repository_actually_declares(
    tmp_path: Path,
) -> None:
    """The real manifest through the real command — the two cannot drift apart."""
    adopted = tmp_path / "pyproject.toml"
    adopted.write_text(REPO_PYPROJECT.read_text(), encoding="utf-8")

    changes = clear_scaffold_flag(adopted, dry_run=False)

    assert changes, "adoption reported no change against a manifest that declares it"
    assert not is_template_scaffold(tmp_path)
    # The prose explaining the flag goes with it; a comment about a key that is
    # no longer there reads downstream as an instruction nobody can act on.
    assert "inventory rather than outstanding work" not in adopted.read_text()


def test_clearing_keeps_the_rest_of_the_table(tmp_path: Path) -> None:
    """Only the flag goes; a sibling key in the same table is untouched."""
    adopted = tmp_path / "pyproject.toml"
    adopted.write_text(REPO_PYPROJECT.read_text(), encoding="utf-8")
    before = tomlkit.parse(adopted.read_text())["tool"]["lup"]["agent_version"]  # pyright: ignore[reportIndexIssue]

    clear_scaffold_flag(adopted, dry_run=False)

    after = tomlkit.parse(adopted.read_text())["tool"]["lup"]["agent_version"]  # pyright: ignore[reportIndexIssue]
    assert after == before


def test_a_downstream_manifest_is_left_alone(tmp_path: Path) -> None:
    """Clearing an already-adopted manifest reports nothing and writes nothing."""
    adopted = tmp_path / "pyproject.toml"
    adopted.write_text('[tool.lup]\nagent_version = "0.2.0"\n', encoding="utf-8")
    before = adopted.read_text()

    assert clear_scaffold_flag(adopted, dry_run=False) == []
    assert adopted.read_text() == before


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    adopted = tmp_path / "pyproject.toml"
    adopted.write_text(REPO_PYPROJECT.read_text(), encoding="utf-8")
    before = adopted.read_text()

    assert clear_scaffold_flag(adopted, dry_run=True)
    assert adopted.read_text() == before
    assert is_template_scaffold(tmp_path)


class TestOwnershipDeclaration:
    """The splice that rewrites `human_owned_files` in the real catalog.

    Read against this repository's own catalog rather than a fixture, because
    what makes the rewrite hard is the file it actually edits: a hook set
    spelled across two hundred lines, with em dashes in the comments ahead of
    the declaration that a character-indexed cut would land inside.
    """

    def catalog_source(self) -> str:
        return Path(catalog.__file__).read_text(encoding="utf-8")

    def test_the_declaration_is_found_in_the_real_catalog(self) -> None:
        listing = ownership_listing(
            ast.parse(self.catalog_source()), "human_owned_files"
        )
        named = [path_literal(element) for element in listing.elts]
        assert named == ["README.md"]

    def test_a_field_no_hook_set_declares_is_refused(self) -> None:
        with pytest.raises(ValueError, match="declares 'invented_field'"):
            ownership_listing(ast.parse(self.catalog_source()), "invented_field")

    def test_the_splice_lands_where_the_parser_says_and_reparses(self) -> None:
        source = self.catalog_source()
        listing = ownership_listing(ast.parse(source), "human_owned_files")
        rewritten = spliced(source, listing, rendered_listing([]))

        assert "human_owned_files=[]," in rewritten
        assert 'human_owned_files=[Path("README.md")]' not in rewritten
        replaced = ownership_listing(ast.parse(rewritten), "human_owned_files")
        assert replaced.elts == []

    def test_the_rewrite_round_trips_back_to_the_original_bytes(self) -> None:
        """Unlock then lock is the identity, which is what makes it safe to try."""
        source = self.catalog_source()
        emptied = spliced(
            source,
            ownership_listing(ast.parse(source), "human_owned_files"),
            rendered_listing([]),
        )
        restored = spliced(
            emptied,
            ownership_listing(ast.parse(emptied), "human_owned_files"),
            rendered_listing(["README.md"]),
        )
        assert restored == source

    def test_several_owned_paths_render_as_one_parsable_literal(self) -> None:
        assert rendered_listing(["README.md", "docs/decisions.md"]) == (
            '[Path("README.md"), Path("docs/decisions.md")]'
        )

    def test_an_element_that_is_not_a_path_call_names_nothing(self) -> None:
        listing = ast.parse('["README.md", Path("a.md")]').body[0]
        assert isinstance(listing, ast.Expr)
        assert isinstance(listing.value, ast.List)
        assert [path_literal(element) for element in listing.value.elts] == [
            None,
            "a.md",
        ]
