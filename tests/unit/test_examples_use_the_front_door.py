"""Every shipped example builds its client from the package root.

The corpus that teaches the library is the first thing a reader copies, so what
it reaches for is what they learn to reach for. Before the root exported a
constructor there was nothing else it *could* teach: six of the seven
non-trivial examples opened by importing an adapter directly, which is the one
tier `seam-boundary` fails the build over everywhere else in the library. They
were not sloppy — they were correct, and the front door was the defect.

This is the standing version of that finding. It fails on the import line
rather than at the day somebody tries the example, and it is deliberately about
*construction* rather than about adapter imports in general: an example whose
whole subject is provider-specific policy legitimately names
`ClaudeSessionConfig`. What none of them may do is reach past the root to build
a client, because a reader who has to know `lup.providers.claude.runtime` exists
has already been failed.
"""

import ast
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

# The constructors, and the module each one is defined in. Reaching the second
# spelling is what this test refuses; the adapters are where they live, not
# where an example is supposed to find them.
CONSTRUCTORS = {"create_claude", "create_codex"}


def example_sources() -> list[Path]:
    found = sorted(
        path
        for path in EXAMPLES.glob("*.py")
        if path.name not in {"__init__.py", "common.py"}
    )
    assert found, "no examples found to check"
    return found


def imported_names(tree: ast.Module) -> list[tuple[str, str]]:
    """Every `from <module> import <name>` in the file, as pairs."""
    return [
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]


@pytest.mark.parametrize("path", example_sources(), ids=lambda p: p.name)
def test_a_constructor_is_taken_from_the_package_root(path: Path) -> None:
    imported = imported_names(ast.parse(path.read_text(encoding="utf-8")))
    reached = [
        (module, name)
        for module, name in imported
        if name in CONSTRUCTORS and module != "lup"
    ]

    assert not reached, (
        f"{path.name} builds its client from {reached[0][0]!r}. A constructor is "
        "exported from the package root — `from lup import create_claude` — and "
        "an example that reaches past it teaches a reader to do the same."
    )


@pytest.mark.parametrize("path", example_sources(), ids=lambda p: p.name)
def test_no_example_opens_a_session_through_an_adapter(path: Path) -> None:
    """The narrower thing that is always wrong: naming an opener.

    A `SessionOpener` is the engine a constructor composes. An example holding
    one has not configured a client differently — it has stepped inside the
    composition root, where the contract it depends on is not a public one.
    """
    imported = imported_names(ast.parse(path.read_text(encoding="utf-8")))
    openers = [
        (module, name) for module, name in imported if name.endswith("SessionOpener")
    ]

    assert not openers, f"{path.name} imports {openers[0][1]!r}, an internal engine"


def test_every_example_that_runs_a_turn_names_the_root() -> None:
    """Stated over the corpus, so the property cannot decay one file at a time.

    A per-file check passes vacuously for a corpus that has stopped using the
    front door entirely — the failure this whole test exists for. At least one
    example must import a constructor from `lup`, or there is nothing being
    demonstrated.
    """
    reached = {
        name
        for path in example_sources()
        for module, name in imported_names(ast.parse(path.read_text(encoding="utf-8")))
        if module == "lup" and name in CONSTRUCTORS
    }

    assert reached == CONSTRUCTORS, (
        f"the examples demonstrate {sorted(reached)} from the package root; "
        f"every constructor the root exports needs one — missing "
        f"{sorted(CONSTRUCTORS - reached)}"
    )
