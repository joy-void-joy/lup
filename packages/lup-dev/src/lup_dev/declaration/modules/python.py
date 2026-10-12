"""`Python`: how a Python project runs its tools, where its tests are, and their steps."""

from pathlib import Path

from lup_dev.catalog import gate as lup_gate
from lup_dev.catalog import paths as lup_paths
from lup_dev.declaration.kinds import Gate, Paths, Pytest, TestRoots
from lup_dev.declaration.module import Module
from lup_dev.declaration.runner import Runner, Uv

CONFIGURATION = [
    "**/pyproject.toml",
    "**/uv.lock",
    "**/ruff.toml",
    "**/.ruff.toml",
    "**/pyrightconfig.json",
    "**/pytest.toml",
    "**/.pytest.toml",
    "**/pytest.ini",
    "**/setup.cfg",
    "**/tox.ini",
    "**/.importlinter",
    "**/uv.toml",
    "**/.python-version",
]
"""The Python tools' manifests, lockfiles and configuration files, protected.

They choose what runs, and each tool reads its own file before its table in
`pyproject.toml`, so one written unasked would override what the gate checks
(pyright's strictness, ruff's selection, uv's age gate) or which Python runs. The
catalog lists them among every protected path (`lup_dev.catalog.paths`); `Core`
holds the rest.
"""


class Python(Module):
    """Python's tools: how the project runs them, where its tests are, and the gate's steps."""

    name = "python"

    paths: Paths = Paths.of(
        protected=CONFIGURATION,
        source_trees=lup_paths.Paths().source_trees,
        python=lup_paths.Paths().python,
        conftest=[lup_paths.Paths().conftest],
    )
    runner: Runner = Uv()
    """How the project runs its tools: uv, unless the project says."""
    tests: TestRoots = TestRoots.of(Pytest(root=Path("tests")))
    """The test roots: the test role, and what pytest's `testpaths` must cover."""
    gate: Gate = Gate.of(*lup_gate.Gate().steps)
    """ruff, the formatter, pyright, pytest and import-linter, as the catalog has
    them."""
