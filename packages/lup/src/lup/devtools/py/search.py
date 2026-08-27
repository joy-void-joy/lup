"""Helpers for ``py search`` — find symbols across packages and project source."""

import ast
import importlib
import importlib.metadata
import inspect
import itertools
import typing
from pathlib import Path

# ---------------------------------------------------------------------------
# py search — find symbols across packages
# ---------------------------------------------------------------------------


class SearchMatch(typing.TypedDict):
    symbol: str
    kind: str
    import_path: str


def source_module_name(source: Path) -> str:
    """Derive a dotted module name from a Python source file's package chain."""
    package_names = [
        parent.name
        for parent in itertools.takewhile(
            lambda parent: (parent / "__init__.py").is_file(), source.parents
        )
    ]
    stem = [] if source.name == "__init__.py" else [source.stem]
    return ".".join([*reversed(package_names), *stem])


def project_python_files(
    root: Path,
    ignored_directories: frozenset[str] = frozenset(  # lup: ignore[frozenset-shape]
        {"build", "dist", "node_modules", "__pycache__"}
    ),
) -> typing.Iterator[Path]:
    """Yield project Python files without entering environment or build trees."""
    for directory, directory_names, filenames in root.walk():
        directory_names[:] = [
            name
            for name in directory_names
            if not name.startswith(".") and name not in ignored_directories
        ]
        for filename in filenames:
            source = directory / filename
            if source.suffix == ".py":
                yield source


def scan_source_symbols(source: Path, pattern: str) -> list[SearchMatch]:
    """Find importable definitions in one Python source file."""
    matches: list[SearchMatch] = []
    module_name = source_module_name(source)
    pattern_lower = pattern.lower()

    def add(name: str, kind: str, qualifier: tuple[str, ...]) -> None:
        if name.startswith("_") or pattern_lower not in name.lower():
            return
        import_path = ".".join((module_name, *qualifier, name))
        matches.append(SearchMatch(symbol=name, kind=kind, import_path=import_path))

    def add_target(target: ast.expr, qualifier: tuple[str, ...]) -> None:
        match target:
            case ast.Name(id=name):
                add(name, "variable", qualifier)
            case ast.Tuple(elts=elements) | ast.List(elts=elements):
                for element in elements:
                    add_target(element, qualifier)

    def collect(statements: list[ast.stmt], qualifier: tuple[str, ...]) -> None:
        for statement in statements:
            match statement:
                case ast.ClassDef(name=name, body=body):
                    add(name, "class", qualifier)
                    collect(body, (*qualifier, name))
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                    add(name, "function", qualifier)
                case ast.Assign(targets=targets):
                    for target in targets:
                        add_target(target, qualifier)
                case ast.AnnAssign(target=target):
                    add_target(target, qualifier)

    try:
        module = ast.parse(source.read_text(), filename=str(source))
    except (OSError, SyntaxError, UnicodeError):
        return []
    collect(module.body, ())
    return matches


def scan_project_symbols(root: Path, pattern: str) -> list[SearchMatch]:
    """Search definitions throughout one project's Python source."""
    return [
        match
        for source in project_python_files(root)
        for match in scan_source_symbols(source, pattern)
    ]


def scan_module_symbols(module_name: str, pattern: str) -> list[SearchMatch]:
    """Import a module and search dir() for matching symbols."""
    try:
        mod = importlib.import_module(module_name)
    except (ImportError, AttributeError, TypeError, RuntimeError, OSError):
        return []

    pattern_lower = pattern.lower()

    def match_of(name: str) -> SearchMatch | None:
        if name.startswith("_") or pattern_lower not in name.lower():
            return None
        member = getattr(mod, name, None)
        if member is None or inspect.ismodule(member):
            return None
        if inspect.isclass(member):
            kind = "class"
        elif inspect.isfunction(member) or inspect.isbuiltin(member):
            kind = "function"
        else:
            kind = type(member).__name__
        return SearchMatch(symbol=name, kind=kind, import_path=f"{module_name}.{name}")

    return [m for name in dir(mod) if (m := match_of(name)) is not None]


def get_top_level_packages() -> list[str]:
    """Get importable top-level package names from installed distributions."""
    return sorted(importlib.metadata.packages_distributions().keys())
