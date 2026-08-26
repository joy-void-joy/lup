"""What the pre-flight gate is answerable for when it runs inside a lease.

A resolver lease holds one concern's changes and is judged by `dev check`. An
unscoped anti-pattern gate makes that verdict depend on the whole repository,
so one finding nobody in the run introduced blocks every lease at once and no
revision round can converge on it. These pin the split.

The split is made by not reading a file rather than by discarding what reading
it found: the sweep's dominant cost is resolving the files it reads, and a
gate that read the whole repository to set most of it aside paid that cost to
reach a verdict it then threw away.
"""

from lup.devtools.dev.antipatterns import within_scope


def test_an_unscoped_gate_reads_every_file() -> None:
    # CI asks whether the tree is clean, so nothing is out of its scope.
    assert within_scope("a.py", None)
    assert within_scope("packages/lup/src/lup/providers/profiles.py", None)


def test_a_file_outside_the_changed_paths_is_not_read() -> None:
    changed = ["packages/lup/src/lup/touched.py"]

    assert within_scope("packages/lup/src/lup/touched.py", changed)
    assert not within_scope("packages/lup/src/lup/providers/profiles.py", changed)


def test_a_lease_that_changed_nothing_the_rules_hit_is_green() -> None:
    # The case that deadlocked run resolve-9e060ad9bb53: every lease read the
    # same pre-split ProfileStore, and the gate failed identically in all of
    # them however much the worker changed elsewhere.
    assert not within_scope(
        "packages/lup/src/lup/providers/profiles.py",
        ["packages/lup/src/lup/devtools/dev/worktree.py"],
    )


def test_a_scope_naming_nothing_reads_nothing() -> None:
    # A tree that changed nothing is answerable for nothing, which is not the
    # same answer as a tree nobody scoped.
    assert not within_scope("a.py", [])


def test_a_named_directory_covers_what_sits_under_it() -> None:
    scope = ["packages/lup/src/lup/devtools"]

    assert within_scope("packages/lup/src/lup/devtools/dev/check.py", scope)
    assert not within_scope("packages/lup/src/lup/devtools_other/check.py", scope)
