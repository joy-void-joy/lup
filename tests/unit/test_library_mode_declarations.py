"""What developing lup adds to a checkout follows whether lup is vendored in it.

The catalog carries facts about lup developing itself — its suite, its frontend
and bundles, its release and publication, its policy's protection, its
declaration tree — and an adopter inherits the catalog with the rest of the
copied half. Written down, each went on pointing into ``packages/lup/`` after
`dev library git` removed it, and the adopter had to find and hand-edit every
one. Derived from the library mode, `dev library git` is all it takes.
"""

from functools import partial
from pathlib import Path, PurePath

from lup.devtools.dev.library import DISTRIBUTION, VENDORED_ROOT
from lup.web.build import write_web_bundles
from lup.web.schema import write_view_schema
from lup_template.devtools.main import relocation_roots
from lup_template.harness.catalog import (
    application_roots,
    declared_coverage,
    declared_release,
    declared_spread,
    declared_test_roots,
    portable_harness,
    publish,
    vendors_library,
    workflow,
)
from lup_template.harness.composition import repository_writers


def declared_paths(vendored: bool) -> list[str]:
    """Every path the lup-development declarations name, in one library mode."""
    roots = application_roots(vendored=vendored)
    hooks = portable_harness(vendored=vendored).declared_hooks
    frontend = workflow(vendored).frontend
    spread = declared_spread(vendored)
    paths: list[str | PurePath] = [
        *(root.directory for root in declared_test_roots(vendored)),
        *spread.library,
        *spread.copied,
        declared_release(vendored).version_file,
        *([frontend.workspace] if frontend is not None else []),
        *(entry.directory for entry in declared_coverage(vendored).roots),
        *roots.generated,
        *roots.composition,
        *roots.native_dependencies,
        *hooks.protected_edit_roots,
        *(role.root for role in hooks.path_roles),
        *relocation_roots(vendored),
    ]
    return [PurePath(path).as_posix() for path in paths]


def writers(vendored: bool) -> list[object]:
    """What each repository-wide writer calls, in one library mode."""
    return [
        writer.func if isinstance(writer, partial) else writer
        for writer in repository_writers(vendored)
    ]


def test_a_library_resolved_as_a_dependency_leaves_nothing_pointing_into_it() -> None:
    """After `dev library git`, no declaration names the tree it removed."""
    named = [path for path in declared_paths(False) if path.startswith(VENDORED_ROOT)]

    assert named == []
    assert workflow(False).frontend is None
    assert publish(False).package == ""
    assert write_view_schema not in writers(False)
    assert write_web_bundles not in writers(False)


def test_a_vendored_library_keeps_every_declaration_developing_it() -> None:
    """The scaffold itself is the vendored case, and loses none of its gate."""
    named = declared_paths(True)

    assert f"{VENDORED_ROOT}/src/lup/policy" in named
    assert f"{VENDORED_ROOT}/tests" in named
    assert f"{VENDORED_ROOT}/src/lup/harness/content" in named
    assert publish(True).package == DISTRIBUTION
    assert write_web_bundles in writers(True)
    assert [root.name for root in declared_test_roots(True)] == [
        "pytest",
        "pytest (lup)",
        "bun test",
    ]


def test_this_checkout_reads_as_vendoring_the_library_it_authors() -> None:
    """The mode is read off the manifest, which here makes lup a workspace member."""
    assert vendors_library()
    assert (Path(VENDORED_ROOT) / "pyproject.toml").is_file()
