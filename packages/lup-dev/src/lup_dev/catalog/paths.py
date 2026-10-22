"""The path patterns lup's roles start from, before a project adds its own.

Patterns are relative to a worktree's root and matched whole, `**` spanning any
number of directories (`PurePath.full_match`). `lup_dev.policy.roles` says how each list
is used and in which order (`docs/judging-writes.md`, *What each change gets*).

Each module's patterns are its own list here, read by the module that holds them
(`lup_dev.declaration.modules`): `Core`'s are every project's, `Python`'s go with
`Python`, so a project in another language that replaces it takes them away.
"""

from lup.types import Model


class CorePaths(Model):
    """`Core`'s default path patterns, one list per role."""

    protected: list[str] = [
        "**/package.json",
        "**/bun.lock",
        ".github/**",
        ".git/**",
        ".githooks/**",
        ".husky/**",
        ".pre-commit-config.yaml",
        ".vscode/**",
        ".devcontainer/**",
        # lup: ignore("runtime-mention", why="a default a project's declaration can drop, so data rather than the adapter's own; a test keeps it in step with each adapter's `Runtime.settings`")
        ".claude/**",
        # lup: ignore("runtime-mention", why="a default a project's declaration can drop, so data rather than the adapter's own; a test keeps it in step with each adapter's `Runtime.settings`")
        ".codex/**",
        "**/sync.json",
        "**/sync.json.local",
        "**/.env*.local",
        "**/.gitignore",
        "AGENTS.local.md",
        "lup_project.local.py",
    ]
    """Every write to these asks the operator.

    - Node's manifest and lockfile, which choose what runs;
    - what runs outside the agent's reach: CI, git's own directory and hooks,
      pre-commit, editor and container configurations, the runtimes' settings;
    - what widens a later launch, `sync.json` and `sync.json.local`;
    - secrets, `.env*.local`;
    - `.gitignore`, since what it ignores the checkpoint never sees;
    - the person's own section of a session's guidance, `AGENTS.local.md` at the
      root, which steers every later session and which git ignores, so nothing
      else would show the operator a change to it;
    - the person's own layer of the declaration, `lup_project.local.py` at the
      root, which the host runs once trust on launch approves it, and which git
      ignores.
    """
    operator_documents: list[str] = ["DESIGN.md", "AGENTS.md"]
    """The operator's documents: changing one is a design decision, so it asks."""
    tests: list[str] = ["**/*.test.ts", "**/*.test.tsx"]
    """TypeScript's tests, wherever they are, as vitest, Jest and Bun find them by
    default: a test, so writing one asks nothing. pytest's tests are `Python`'s,
    by its test roots."""
    scratch: list[str] = ["**/tmp/**", ".lup/**", "**/*.log"]
    """Scratch work, the saved versions under `.lup/`, and any log, wherever it's
    written: a worker's gate log at a worktree's root was once flagged as a new
    production file, carrying the host's paths. Allowed at any size."""
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


class PythonPaths(Model):
    """`Python`'s default path patterns, one list per role."""

    protected: list[str] = [
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
    """Every write to these asks the operator.

    - the manifest and lockfile, which choose what runs;
    - the tools' own configuration files, each read before its table in
      `pyproject.toml`, so one written unasked would override what the gate checks
      (pyright's strictness, ruff's selection, uv's age gate) or which Python runs.
    """
    source_trees: list[str] = ["**/src/**"]
    """Where code lives: a data file here ships with it, so it's production.

    A directory holding an `__init__.py` is a source tree too.
    """
    python: list[str] = ["*.py", "*.pyi"]
    """Python modules, by file name: what lup's rules and the engine read."""
    conftest: list[str] = ["conftest.py"]
    """The module pytest reads beside a suite's tests, which counts as a test."""
