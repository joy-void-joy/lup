# lup: ignore[import-re, re-call, string-replace]
# Renaming IS text surgery over source and config files — every .replace
# rewrites a known literal in place and the import-statement rewriter is a
# regex by nature, so those rules are opted out file-wide.
"""Package renaming for downstream project initialization.

Renames the ``lup_template`` Python package to a project-specific name,
updating imports, dotted string anchors (``resources.files`` and
``mock.patch`` targets, entry-point strings), entry points, and CLI
references, then reports surviving references for manual triage.
Framework vocabulary (``lup_tool``, ``lup-devtools``, ``.lup/``, etc.)
stays unchanged.

Examples::

    $ uv run lup-devtools dev init rename-package myproject
    $ uv run lup-devtools dev init rename-package myproject --dry-run
"""

import re
from pathlib import Path
import tomlkit
from tomlkit.container import Container
from tomlkit.items import Comment
import typer

from lup.workspace.paths import find_project_root
from lup.devtools.dev.plugin import set_marketplace_name
from lup_template.devtools.harness.catalog import declared_plugin
from lup.execution.shell import git

PACKAGE_IMPORT_RE = re.compile(
    r"""
    (?<![.\w])          # not preceded by dot or word char
    (?:from|import)     # keyword
    \s+
    lup_template        # the package name
    (?=\.|\.|\s|$)      # followed by dot, whitespace, or end
    """,
    re.VERBOSE,
)

PACKAGE_STRING_ANCHOR_RE = re.compile(
    r"""
    ["']                # opening quote
    lup_template        # the package name
    (?=\.)              # dotted module path only — bare literals stay vocabulary
    """,
    re.VERBOSE,
)

# lup: ignore[constant-declaration] — each entry is a name lup itself publishes,
# so what marks a line as framework is lup's vocabulary rather than a preference
FRAMEWORK_MARKERS = {
    "lup_tool",
    "LupMcpTool",
    "lup-tools",
    "lup-devtools",
    "lup-sandbox",
    "lup-mcp",
    "lup@local",
    "lup-template",
    "plugins/lup",
    "plugins/cache/local/lup",
}


def is_framework_reference(line: str) -> bool:
    """Check if a line's ``lup_template`` usage is framework vocabulary, not a package import."""
    return any(marker in line for marker in FRAMEWORK_MARKERS)


def is_renamer_module(path: Path) -> bool:
    """Check if ``path`` is the renamer module — its literals are rename vocabulary."""
    return path.as_posix().endswith("devtools/dev/init.py")


INITIALIZATION_MODULES = ["devtools/dev/init.py", "devtools/dev/app.py"]
"""Where initialization's own vocabulary is written down, for a caller that
does not say. A module that names what initialization removes says the name
because that is its subject, so a scan reporting lines still naming a deleted
path skips these for the same reason the rename skips the renamer: its
literals are the command rather than a reference the command left dangling."""


def declares_initialization(
    path: Path, modules: list[str] = INITIALIZATION_MODULES
) -> bool:
    """Whether ``path`` is one of initialization's own declaring modules."""
    spelled = path.as_posix()
    return any(spelled.endswith(module) for module in modules)


def rename_match(matched: str, new_name: str) -> str:
    """Rewrite the package name inside one matched piece of source text."""
    return matched.replace("lup_template", new_name, 1)


def rename_pattern_in_file(
    path: Path, pattern: re.Pattern[str], new_name: str, dry_run: bool
) -> list[str]:
    """Rename ``lup_template`` occurrences matched by ``pattern`` in a single file.

    Returns a list of change descriptions (empty if no changes); a dry run
    detects and describes without writing.
    """
    text = path.read_text()
    changes: list[str] = []

    def replace_match(m: re.Match[str]) -> str:
        full_match = m.group(0)
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start : line_end if line_end != -1 else len(text)]

        if is_framework_reference(line):
            return full_match

        replaced = rename_match(full_match, new_name)
        changes.append(f"  {path}: {full_match!r} -> {replaced!r}")
        return replaced

    new_text = pattern.sub(replace_match, text)
    if not dry_run and new_text != text:
        path.write_text(new_text)
    return changes


def rename_in_pyproject(path: Path, new_name: str, dry_run: bool) -> list[str]:
    """Update pyproject.toml: package name, CLI entry point, devtools import path."""
    text = path.read_text()
    changes: list[str] = []
    new_text = text

    old_name_line = 'name = "lup-template"'
    new_name_line = f'name = "{new_name}"'
    if old_name_line in new_text:
        new_text = new_text.replace(old_name_line, new_name_line, 1)
        changes.append(f"  package name: lup-template -> {new_name}")

    old_cli = 'lup = "lup_template.environment.cli.__main__:app"'
    new_cli = f'{new_name} = "{new_name}.environment.cli.__main__:app"'
    if old_cli in new_text:
        new_text = new_text.replace(old_cli, new_cli, 1)
        changes.append(f"  CLI entry point: lup -> {new_name}")

    # Every remaining place the manifest spells the package, each keyed by
    # what it configures rather than by the table it happens to sit in. The
    # entry point moved from `[project.scripts]` to
    # `[project.entry-points."lup.devtools"]` and this went on matching the old
    # spelling, so a renamed project kept an entry point naming a package that
    # no longer existed -- and the failure it produced was `The environment
    # must register exactly one 'lup.devtools' application entry point; found
    # 2`, which names neither the manifest nor the rename. The package-data
    # keys were never handled at all, so a renamed project shipped no assets.
    #
    # Matched on the module path rather than on the whole line for that
    # reason: a key that moves tables keeps its value, and the value is the
    # part this is about.
    for spelling, what in (
        ("lup_template.devtools.main:app", "devtools application entry point"),
        ("lup_template.devtools.dashboard", "dashboard package data"),
        ("lup_template.devtools.harness.content", "harness content package data"),
    ):
        renamed = spelling.replace("lup_template", new_name, 1)
        if spelling in new_text:
            new_text = new_text.replace(spelling, renamed, 1)
            changes.append(f"  {what}: {spelling} -> {renamed}")

    if not dry_run and new_text != text:
        path.write_text(new_text)
    return changes


def clear_scaffold_flag(path: Path, dry_run: bool) -> list[str]:
    """Drop ``[tool.lup] template`` — this repository has adopted the template.

    Adopting is what turns the scaffold's customization markers from inventory
    into decisions this domain has not made yet, so the flag that says "still
    the scaffold" goes when the name does.

    Edited through tomlkit rather than by matching the line, because the key
    carries an explanatory comment and matching text would put a second copy
    of that comment here to drift against the first — a reworded comment would
    silently stop clearing the flag, and the repository that adopted the
    template would never be told what it still owes. The parser sees the key
    whatever the prose around it says, and preserves the rest of the file's
    formatting.

    The comment goes with it. Deleting the key alone leaves the paragraph that
    explains it standing over nothing, which downstream reads as an
    instruction about a setting that is not there.
    """

    def drop_with_preamble(table: Container, name: str) -> None:
        """Remove one key and the standalone comment lines introducing it."""
        body = table.body
        index = next(
            position
            for position, (key, _) in enumerate(body)
            if key is not None and key.key == name
        )
        start = index
        while start and isinstance(body[start - 1][1], Comment):
            start -= 1
        del body[start : index + 1]

    document = tomlkit.parse(path.read_text())
    match document:
        case {"tool": {"lup": {"template": _} as lup}}:
            drop_with_preamble(lup.value, "template")
        case _:
            return []
    if not dry_run:
        path.write_text(tomlkit.dumps(document))
    return ["  scaffold flag: cleared — dev check now lists open decisions"]


def rename_cli_app_name(cli_path: Path, new_name: str, dry_run: bool) -> list[str]:
    """Update the Typer app name in the CLI module."""
    if not cli_path.exists():
        return []

    text = cli_path.read_text()
    old = 'name="lup"'
    if old not in text:
        return []

    if not dry_run:
        cli_path.write_text(text.replace(old, f'name="{new_name}"', 1))
    return [f"  CLI app name: lup -> {new_name}"]


def find_stale_references(root: Path) -> list[str]:
    """List surviving ``lup_template`` occurrences for manual triage.

    Covers reference forms the rewriting passes deliberately leave alone —
    docstring prose, path fragments, generated-content templates — so
    nothing dangles silently after a rename.
    """
    scan_files = [
        path
        for search_dir in [root / "src", root / "tests"]
        if search_dir.is_dir()
        for path in sorted(search_dir.rglob("*.py"))
        if not is_renamer_module(path)
    ]
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        scan_files.append(pyproject)
    return [
        f"  {path.relative_to(root)}:{lineno}: {line.strip()}"
        for path in scan_files
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if "lup_template" in line
    ]


SCAFFOLD_DEMONSTRATIONS = [
    Path("examples"),
    Path("tests/unit/test_policy_examples.py"),
    Path("tests/unit/test_examples_use_the_front_door.py"),
]
"""What the scaffold ships to demonstrate *itself*, for a caller that does not
say. Each of these composes lup's own runtime against lup's own README — a
front door being opened, a wrapper stack, a policy denying the call it declared
— so a domain that adopted the template inherits a directory of demos for a
library it is merely a consumer of, and two test modules driving them. Its own
examples, if it wants any, are about its own subject and share nothing with
these but a directory name. A fork shipping different demonstrations passes
its own list rather than editing this one."""

SKIPPED_TREES = ["fixtures"]
"""Directory names a mention scan never descends into, beside the obvious, for
a caller that does not say. The version-controlled, virtual-environment, and
bytecode trees are skipped because nothing in them is prose anyone repairs. A
fixture tree is skipped for the opposite reason: it says `examples/` on
purpose, as the data a test drives."""


def drop_scaffold_demonstrations(
    root: Path,
    dry_run: bool,
    demonstrations: list[Path] = SCAFFOLD_DEMONSTRATIONS,
) -> list[str]:
    """Remove the scaffold's demonstrations of itself.

    Deleted through git rather than the filesystem, so the removal is staged
    the way the package rename beside it is and a tracked file that is somehow
    absent fails loudly instead of being passed over.

    The README is not edited. It is human-owned here, and an adopting domain
    rewrites it about its own subject anyway — so a link into a directory that
    is going belongs to that rewrite rather than to a surgery performed behind
    the owner's back. :func:`surviving_mentions` reports it instead.
    """
    present = [path for path in demonstrations if (root / path).exists()]
    if not dry_run:
        for path in present:
            git("rm", "-r", "--quiet", str(path), _cwd=str(root))
    return [f"  {path.as_posix()}: removed" for path in present]


def mention_pattern(path: Path) -> re.Pattern[str]:
    """How a line names this path, in each spelling one can take.

    A file is named by its path and nothing else. A directory is named two
    ways — as a path, with the separator that makes it one, and as the import
    root a ``-m`` invocation spells with a dot. Both carry that separator on
    purpose: the bare name is an ordinary English word, and matching it alone
    reported every sentence that happened to use it. The dot form additionally
    requires a name after it, because a sentence ending in "examples." is
    prose about examples rather than a reference to the package.
    """
    name = re.escape(path.as_posix())
    if path.suffix:
        return re.compile(name)
    return re.compile(rf"{name}/|{name}\.(?=[A-Za-z_])")


def surviving_mentions(
    root: Path, removed: list[Path], skipped_trees: list[str] = SKIPPED_TREES
) -> list[str]:
    """Every line still naming something that was just removed.

    Reported rather than rewritten, for the reason the rename's own stale-
    reference pass reports: what names a deleted directory is prose, a link,
    or a configuration key, and each wants a different repair that only
    whoever owns the file can choose.

    A file inside what was removed is not scanned. It names its own siblings
    constantly and is going with them, so reporting it would bury the handful
    of lines somebody actually has to repair.
    """
    skipped = {".git", ".venv", "__pycache__", *skipped_trees}
    patterns = [mention_pattern(path) for path in removed]
    scanned = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix in [".py", ".md", ".toml"]
        and not skipped.intersection(path.parts)
        and not declares_initialization(path)
        and not any(path.is_relative_to(root / going) for going in removed)
    ]
    return [
        f"  {path.relative_to(root)}:{number}: {line.strip()}"
        for path in scanned
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if any(pattern.search(line) for pattern in patterns)
    ]


def rename_package(
    new_name: str,
    dry_run: bool,
) -> None:
    """Rename the lup_template Python package to a project-specific name."""
    if not new_name.isidentifier():
        typer.echo(f"Error: {new_name!r} is not a valid Python identifier", err=True)
        raise typer.Exit(1)

    if new_name == "lup_template":
        typer.echo("Error: new name is the same as the current name", err=True)
        raise typer.Exit(1)

    root = find_project_root()
    src_dir = root / "src"
    old_pkg = src_dir / "lup_template"
    new_pkg = src_dir / new_name

    if not old_pkg.is_dir():
        typer.echo(f"Error: {old_pkg} does not exist", err=True)
        raise typer.Exit(1)

    if new_pkg.exists():
        typer.echo(f"Error: {new_pkg} already exists", err=True)
        raise typer.Exit(1)

    all_changes: list[str] = []  # lup: ignore[empty-collection] — change log

    python_files = [
        py_file
        for search_dir in [src_dir, root / "tests"]
        if search_dir.is_dir()
        for py_file in search_dir.rglob("*.py")
    ]

    typer.echo("Import renames:" if dry_run else "Renaming imports...")
    for py_file in sorted(python_files):
        all_changes.extend(
            rename_pattern_in_file(py_file, PACKAGE_IMPORT_RE, new_name, dry_run)
        )

    typer.echo("\nString anchors:" if dry_run else "Renaming string anchors...")
    for py_file in sorted(python_files):
        if not is_renamer_module(py_file):
            all_changes.extend(
                rename_pattern_in_file(
                    py_file, PACKAGE_STRING_ANCHOR_RE, new_name, dry_run
                )
            )

    pyproject = root / "pyproject.toml"
    typer.echo("\npyproject.toml:" if dry_run else "Updating pyproject.toml...")
    all_changes.extend(rename_in_pyproject(pyproject, new_name, dry_run))
    all_changes.extend(clear_scaffold_flag(pyproject, dry_run))

    cli_path = old_pkg / "environment" / "cli" / "__main__.py"
    typer.echo("\nCLI app name:" if dry_run else "Updating CLI app name...")
    all_changes.extend(rename_cli_app_name(cli_path, new_name, dry_run))

    typer.echo("\nMarketplace:" if dry_run else "Naming the plugin marketplace...")
    all_changes.extend(
        f"  {c}"
        for c in set_marketplace_name(root, new_name, declared_plugin().name, dry_run)
    )

    if dry_run:
        typer.echo("\nDirectory rename:")
        all_changes.append(f"  src/lup_template/ -> src/{new_name}/")
    else:
        typer.echo("Renaming package directory...")
        git("mv", str(old_pkg), str(new_pkg), _cwd=str(root))
        all_changes.append(f"  src/lup_template/ -> src/{new_name}/")

    typer.echo()
    if dry_run:
        typer.echo(f"Dry run: {len(all_changes)} changes would be made:")
    else:
        typer.echo(f"Done: {len(all_changes)} changes made:")
    for change in all_changes:
        typer.echo(change)

    if not dry_run:
        stale = find_stale_references(root)
        if stale:
            typer.echo(
                f"\nRemaining lup_template references ({len(stale)}) — review manually:"
            )
            for line in stale:
                typer.echo(line)
        typer.echo("\nNext steps:")
        typer.echo("  uv sync")
        typer.echo("  uv run pyright")
        typer.echo("  uv run ruff check .")
        typer.echo("  uv run pytest")
