"""What `py eval` offers the sandbox to import from.

These never start Docker: the roots are derived from where the `lup` package
sits and from the checkout handed in, so they belong in the unit suite.
"""

from pathlib import Path

from lup.devtools.py.sandbox_eval import import_roots, library_root


class TestLibraryRoot:
    """Where the library imports from, whichever way this checkout obtained it."""

    def test_holds_the_lup_package(self) -> None:
        assert (library_root() / "lup" / "__init__.py").is_file()

    def test_is_on_the_path_the_running_lup_was_imported_from(self) -> None:
        import lup

        assert Path(lup.__file__).resolve().parent.parent == library_root()


class TestImportRoots:
    """A downstream checkout has no `packages/lup/`, and still gets the library."""

    def test_offers_the_library_without_a_monorepo_layout(self, tmp_path: Path) -> None:
        assert not (tmp_path / "packages").exists()

        assert import_roots(tmp_path)["library"] == library_root()

    def test_offers_the_project_source_when_the_checkout_has_some(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "src").mkdir()

        assert import_roots(tmp_path)["project"] == tmp_path / "src"

    def test_omits_the_project_when_the_checkout_has_no_source(
        self, tmp_path: Path
    ) -> None:
        assert "project" not in import_roots(tmp_path)
