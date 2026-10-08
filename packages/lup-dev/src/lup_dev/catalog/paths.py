"""The path patterns lup's roles start from, before a project adds its own.

Patterns are relative to a worktree's root and matched whole, `**` spanning any
number of directories (`PurePath.full_match`). `lup_dev.policy.roles` says how each list
is used and in which order (`docs/judging-writes.md`, *What each change gets*).
"""

from lup.types import Model


class Paths(Model):
    """lup's default path patterns, one list per role."""

    protected: list[str] = [
        "**/pyproject.toml",
        "**/uv.lock",
        "**/package.json",
        "**/bun.lock",
        ".github/**",
        ".git/**",
        ".githooks/**",
        ".husky/**",
        ".pre-commit-config.yaml",
        ".vscode/**",
        ".devcontainer/**",
        # lup: ignore("runtime-mention", why="data naming a runtime's own files")
        ".claude/**",
        # lup: ignore("runtime-mention", why="data naming a runtime's own files")
        ".codex/**",
        "**/sync.json",
        "**/sync.json.local",
        "**/.env*.local",
        "**/.gitignore",
    ]
    """Every write to these asks the operator.

    - dependency manifests and lockfiles, which choose what runs;
    - what runs outside the agent's reach: CI, git's own directory and hooks,
      pre-commit, editor and container configurations, the runtimes' settings;
    - what widens a later launch, `sync.json` and `sync.json.local`;
    - secrets, `.env*.local`;
    - `.gitignore`, since what it ignores the checkpoint never sees.
    """
    operator_documents: list[str] = ["DESIGN.md", "AGENTS.md"]
    """The operator's documents: changing one is a design decision, so it asks."""
    scratch: list[str] = ["**/tmp/**", ".lup/**"]
    """Scratch work, and the saved versions under `.lup/`: allowed at any size."""
    docs: list[str] = ["**/*.md", "docs/**"]
    """Documentation: allowed at any size."""
    data: list[str] = [
        "*.json",
        "*.jsonl",
        "*.ndjson",
        "*.csv",
        "*.tsv",
        "*.yaml",
        "*.yml",
        "*.toml",
        "*.xml",
        "*.parquet",
    ]
    """Data formats, by file name: allowed outside a source tree, production inside."""
    source_trees: list[str] = ["**/src/**"]
    """Where code lives: a data file here ships with it, so it's production.

    A directory holding an `__init__.py` is a source tree too.
    """
    python: list[str] = ["*.py", "*.pyi"]
    """Python modules, by file name: what lup's rules and the engine read."""
    conftest: str = "conftest.py"
    """The module pytest reads beside a suite's tests, which counts as a test."""
