"""`Python`: how a Python project runs its tools, where its tests are, and their steps."""

from pathlib import Path

from lup_dev.catalog import gate as lup_gate
from lup_dev.catalog.paths import PythonPaths
from lup_dev.declaration.kinds import Gate, Guidance, Paths, Pytest, Section, TestRoots
from lup_dev.declaration.module import Module
from lup_dev.declaration.runner import Runner, Uv


class Python(Module):
    """Python's tools: how the project runs them, where its tests are, and the gate's steps."""

    name = "python"

    paths: Paths = Paths.of(
        protected=PythonPaths().protected,
        source_trees=PythonPaths().source_trees,
        python=PythonPaths().python,
        conftest=PythonPaths().conftest,
    )
    """The Python tools' manifests, lockfiles and configuration files, protected;
    where code lives; what's a Python module, and a suite's conftest."""
    runner: Runner = Uv()
    """How the project runs its tools: uv, unless the project says."""
    tests: TestRoots = TestRoots.of(Pytest(root=Path("tests")))
    """The test roots: the test role, and what pytest's `testpaths` must cover."""
    gate: Gate = Gate.of(*lup_gate.Gate().steps)
    """ruff, the formatter, pyright, pytest and import-linter, as the catalog has
    them."""
    guidance: Guidance = Guidance.of(
        Section(
            name="python",
            package="lup_dev.declaration.modules",
            path=Path("guidance/python.md"),
        )
    )
    """Running the project's tools: the runner, the gate, and how tests are written."""
