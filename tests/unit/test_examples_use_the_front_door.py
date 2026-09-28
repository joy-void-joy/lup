"""Every shipped example takes its agent from the package root.

The corpus that teaches the library is the first thing a reader copies, so what
it reaches for is what they learn to reach for. A root exporting no agent could
teach nothing else: every example would open a session by importing an adapter
directly, which is the one tier `seam-boundary` fails the build over everywhere
else in the library, and the front door would be the defect.

This fails on the import line rather than on the day somebody tries the
example, and it is deliberately about the *agent* rather than about adapter
imports in general: an example whose whole subject is provider-specific policy
legitimately names `InnerSandbox`. What none of them may do is reach past
the root for `Claude` or `Codex`, because a reader who has to know
`lup.providers.claude` exists to get an agent has already been failed.
"""

import ast
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

# The agents the root exports. Importing one from the adapter defining it is
# what this test refuses; the adapters are where they live, not where an
# example is supposed to find them.
AGENTS = {"Claude", "Codex"}


def example_sources() -> list[Path]:
    found = sorted(path for path in EXAMPLES.glob("*.py") if path.name != "__init__.py")
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
def test_an_agent_is_taken_from_the_package_root(path: Path) -> None:
    imported = imported_names(ast.parse(path.read_text(encoding="utf-8")))
    reached = [
        (module, name)
        for module, name in imported
        if name in AGENTS and module != "lup"
    ]

    assert not reached, (
        f"{path.name} takes its agent from {reached[0][0]!r}. An agent is "
        "exported from the package root — `from lup import Claude` — and an "
        "example that reaches past it teaches a reader to do the same."
    )


@pytest.mark.parametrize("path", example_sources(), ids=lambda p: p.name)
def test_no_example_opens_a_session_through_an_adapter(path: Path) -> None:
    """The narrower thing that is always wrong: naming an opener.

    A `SessionOpener` is the engine an agent composes. An example holding
    one has not configured an agent differently — it has stepped inside the
    composition root, where the contract it depends on is not a public one.
    """
    imported = imported_names(ast.parse(path.read_text(encoding="utf-8")))
    openers = [
        (module, name) for module, name in imported if name.endswith("SessionOpener")
    ]

    assert not openers, f"{path.name} imports {openers[0][1]!r}, an internal engine"


def imported_modules(tree: ast.Module) -> list[str]:
    """Every module the file imports, whichever statement spells it."""
    modules: list[str] = []
    for node in ast.walk(tree):
        match node:
            case ast.ImportFrom(module=str(module)):
                modules.append(module)
            case ast.Import(names=aliases):
                modules.extend(alias.name for alias in aliases)
            case _:
                pass
    return modules


@pytest.mark.parametrize("path", example_sources(), ids=lambda p: p.name)
def test_an_example_imports_the_library_not_this_application(path: Path) -> None:
    """An example runs wherever lup is installed, so it reads nothing under `src/`.

    What it demonstrates is the library; a value it needs from a project — a
    hook set, a vocabulary — it declares itself. Reaching into this
    repository's application package makes the example one only this checkout
    can run.
    """
    applications = [
        package.name
        for package in (EXAMPLES.parent / "src").iterdir()
        if (package / "__init__.py").is_file()
    ]
    reached = [
        module
        for module in imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        if module.split(".")[0] in applications
    ]

    assert not reached, (
        f"{path.name} imports {reached[0]!r} from this repository's application; "
        "declare what the example needs in the example itself"
    )


def test_every_example_that_runs_a_turn_names_the_root() -> None:
    """Stated over the corpus, so the property cannot decay one file at a time.

    A per-file check passes vacuously for a corpus that has stopped using the
    front door entirely — the failure this whole test exists for. At least one
    example must import each agent from `lup`, or there is nothing being
    demonstrated.
    """
    reached = {
        name
        for path in example_sources()
        for module, name in imported_names(ast.parse(path.read_text(encoding="utf-8")))
        if module == "lup" and name in AGENTS
    }

    assert reached == AGENTS, (
        f"the examples demonstrate {sorted(reached)} from the package root; "
        f"every agent the root exports needs one — missing "
        f"{sorted(AGENTS - reached)}"
    )
