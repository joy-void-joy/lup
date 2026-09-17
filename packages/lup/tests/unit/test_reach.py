"""What a scaffold's commits cost the repositories built on it.

The tally is read off which trees each commit touched, so the cases here are
commits placed in one tree or two. The one that matters is the commit in both:
it is a single change that a dependency bump carries half of, and counting it
under either clean carrier would hide the only failure the measurement exists
to find.
"""

from pathlib import Path

import pytest

from lup.devtools.dev.reach import Spread, carried, module_costs, touching
from tests.unit.test_ledger_placement import committed, repository

SPREAD = Spread(library=["lib/"], copied=["app/"], generated=["built/"])


def wrote(root: Path, name: str, text: str) -> None:
    """Place one file, making whatever tree it names."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def scaffold(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository shipping a library, a copied tree, and a generated one."""
    repository(root)
    monkeypatch.chdir(root)
    return root


def test_each_tree_is_counted_under_the_mechanism_that_carries_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = scaffold(tmp_path, monkeypatch)
    wrote(root, "lib/runtime.py", "x = 1\n")
    committed(root, "library alone")
    wrote(root, "app/prompts.py", "y = 1\n")
    committed(root, "copied alone")
    wrote(root, "built/tree.json", "{}\n")
    committed(root, "generated alone")
    wrote(root, "README.md", "elsewhere\n")
    committed(root, "neither")

    counted = carried("1 year ago", SPREAD).counted

    assert counted["imported"] == 1
    assert counted["copied"] == 1
    assert counted["generated"] == 1
    assert counted["neither"] == 1
    assert counted["split"] == 0


def test_a_commit_touching_both_halves_is_a_split_and_not_two_carriers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = scaffold(tmp_path, monkeypatch)
    wrote(root, "lib/runtime.py", "def opened(name): ...\n")
    wrote(root, "app/core.py", "opened('a')\n")
    committed(root, "a signature and its call site")

    reached = carried("1 year ago", SPREAD)

    assert reached.counted["split"] == 1
    assert reached.counted["imported"] == 0
    assert reached.counted["copied"] == 0
    assert reached.hand_carried() == 1


def test_a_generated_tree_moving_beside_the_library_is_not_its_own_carrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = scaffold(tmp_path, monkeypatch)
    wrote(root, "lib/declaration.py", "ROWS = [1]\n")
    wrote(root, "built/tree.json", "[1]\n")
    committed(root, "a declaration and the tree it compiles")

    counted = carried("1 year ago", SPREAD).counted

    assert counted["imported"] == 1
    assert counted["generated"] == 0


def test_a_copied_module_costs_what_changes_it_not_what_it_weighs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = scaffold(tmp_path, monkeypatch)
    wrote(root, "app/large.py", "\n".join(f"row = {n}" for n in range(200)) + "\n")
    committed(root, "one large module")
    for revision in range(3):
        wrote(root, "app/busy.py", f"revision = {revision}\n")
        committed(root, f"revision {revision}")

    costs = module_costs("1 year ago", SPREAD, root)

    assert [cost.path for cost in costs] == ["app/busy.py", "app/large.py"]
    assert costs[0].commits == 3
    assert costs[1].lines == 200


def test_a_project_that_ships_no_library_still_counts_what_it_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An undeclared tree is absent, not empty — and absent asks git nothing.

    A repository consuming its library rather than holding one declares no
    library prefix, and `git log --` with no paths after it would answer for
    the whole tree instead of for none of it. Every commit would read as a
    split, which is the one number this exists to report.
    """
    root = scaffold(tmp_path, monkeypatch)
    wrote(root, "app/prompts.py", "y = 1\n")
    committed(root, "copied alone")

    spread = Spread(library=[], copied=["app/"], generated=[])

    assert touching("1 year ago", spread.library) == []
    assert carried("1 year ago", spread).counted["copied"] == 1
    assert carried("1 year ago", spread).counted["split"] == 0
