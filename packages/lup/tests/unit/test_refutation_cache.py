"""What a remembered refutation is keyed by, and what makes it a miss.

A refutation is the one verdict in the sweep that is not a function of its
file alone: it says what a receiver's type resolves to, and the checker
resolves that by following imports. So the key has to reach everything the
answer reached, and these pin that — a dependency changing has to be a miss,
because serving the old answer there is serving a verdict about code that is
no longer the code.
"""

from pathlib import Path

from pydantic import BaseModel

from lup.codescan.common import PythonSource, Refutation
from lup.codescan.oracle import (
    DefinitionOracle,
    DefinitionSite,
    SourceBuffer,
    SourcePosition,
)
from lup.devtools.dev.refutations import (
    FileRefutations,
    RefutationStore,
    entry_keys,
    environment_fingerprint,
    first_party_imports,
    import_closure,
    remembered_refutations,
)
from lup.types import StringMap


class SilentOracle(DefinitionOracle):
    """Resolves nothing, and counts what it was asked."""

    def __init__(self) -> None:
        self.asked: list[SourcePosition] = []

    def definitions(
        self,
        positions: list[SourcePosition],
        buffers: list[SourceBuffer] | None = None,
    ) -> list[list[DefinitionSite]]:
        self.asked.extend(positions)
        return [[] for _ in positions]


class Tree(BaseModel):
    """A little repository of module texts, to key and re-key."""

    texts: dict[str, str]

    def sources(self) -> list[PythonSource]:
        return [
            PythonSource(path=Path(f"{name}.py"), module=name, text=text)
            for name, text in self.texts.items()
        ]

    def keys(self) -> StringMap:
        return entry_keys(self.sources(), "fingerprint")

    def with_text(self, name: str, text: str) -> "Tree":
        return Tree(texts={**self.texts, name: text})


LEAF = "class Schema:\n    def get(self, key): ...\n"
MIDDLE = "from leaf import Schema\n\nvalue = Schema()\n"
TOP = "from middle import value\n\nvalue.get('k')\n"

CHAIN = Tree(texts={"leaf": LEAF, "middle": MIDDLE, "top": TOP})


def test_a_file_reaches_what_its_imports_reach() -> None:
    imports = first_party_imports(CHAIN.sources())

    assert import_closure("top", imports) == ["leaf", "middle", "top"]
    assert import_closure("leaf", imports) == ["leaf"]


def test_a_cycle_is_followed_once() -> None:
    cycle = Tree(texts={"a": "import b\n", "b": "import a\n"})

    assert import_closure("a", first_party_imports(cycle.sources())) == ["a", "b"]


def test_an_unchanged_tree_keys_the_same() -> None:
    assert CHAIN.keys() == CHAIN.keys()


def test_changing_a_file_changes_its_own_key() -> None:
    changed = CHAIN.with_text("top", f"{TOP}value.get('other')\n")

    assert changed.keys()["top.py"] != CHAIN.keys()["top.py"]


def test_changing_a_dependency_changes_the_dependents_key() -> None:
    """The property the whole scheme rests on.

    `top` never mentions `leaf`, but the checker resolves `value.get` into it
    through `middle` — so redeclaring `get` there is exactly the change that
    would flip the verdict in `top`, and exactly the one a key reading only
    `top` would miss.
    """
    changed = CHAIN.with_text("leaf", "class Schema:\n    def fetch(self): ...\n")

    assert changed.keys()["top.py"] != CHAIN.keys()["top.py"]
    assert changed.keys()["middle.py"] != CHAIN.keys()["middle.py"]


def test_an_unrelated_file_keeps_its_key() -> None:
    grown = CHAIN.with_text("stranger", "x = 1\n")

    assert grown.keys()["top.py"] == CHAIN.keys()["top.py"]


def test_a_different_environment_keys_differently() -> None:
    sources = CHAIN.sources()

    assert entry_keys(sources, "one") != entry_keys(sources, "two")


def test_a_second_run_asks_the_checker_nothing(tmp_path: Path) -> None:
    store = tmp_path / "refutations.json"
    first, second = SilentOracle(), SilentOracle()

    remembered_refutations(CHAIN.sources(), first, store, tmp_path)
    remembered_refutations(CHAIN.sources(), second, store, tmp_path)

    assert first.asked, "the cold run has to reach the checker"
    assert second.asked == [], "the warm run must not"


def test_a_changed_file_is_asked_about_again(tmp_path: Path) -> None:
    store = tmp_path / "refutations.json"
    remembered_refutations(CHAIN.sources(), SilentOracle(), store, tmp_path)

    changed = CHAIN.with_text("leaf", "class Schema:\n    def fetch(self): ...\n")
    again = SilentOracle()
    remembered_refutations(changed.sources(), again, store, tmp_path)

    assert again.asked, "a changed dependency has to be re-resolved"


def test_no_oracle_remembers_nothing(tmp_path: Path) -> None:
    """A run that could not ask must not teach the next one its silence."""
    store = tmp_path / "refutations.json"

    assert remembered_refutations(CHAIN.sources(), None, store, tmp_path) == {}
    assert not store.exists()


def test_an_unreadable_store_is_a_miss(tmp_path: Path) -> None:
    store = tmp_path / "refutations.json"
    store.write_text("{ not json", encoding="utf-8")

    assert RefutationStore.read(store).entries == {}


def test_a_remembered_refutation_comes_back_unasked(tmp_path: Path) -> None:
    store = tmp_path / "refutations.json"
    kept = Refutation(
        rule_id="dict-get", line=3, subject="value", evidence="resolves elsewhere"
    )
    # Keyed under the environment the reader will compute, not a stand-in:
    # the fingerprint is part of what an entry rests on, so an entry written
    # under a different one is correctly a miss.
    written = entry_keys(CHAIN.sources(), environment_fingerprint(tmp_path))
    RefutationStore(
        entries={
            path: FileRefutations(
                key=key, refutations=[kept] if path == "top.py" else []
            )
            for path, key in written.items()
        }
    ).write(store)

    oracle = SilentOracle()
    found = remembered_refutations(CHAIN.sources(), oracle, store, tmp_path)

    assert found == {"top.py": [kept]}
    assert oracle.asked == []
