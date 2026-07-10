"""Helpers shared across ``py`` commands — dotted-path resolution, module paths, failure exit."""

import functools
import importlib
import importlib.util
import sys
import typing
from pathlib import Path

import typer

from lup.workspace.paths import find_nearest_pyproject

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def resolve_object(path: str) -> tuple[object, str]:
    """Resolve a dotted or colon path to a Python object, returning (object, leaf_name).

    Accepts both ``module.sub.Object`` (dot form) and the entry-point
    ``module.sub:Object.attr`` (colon form, module left of the colon).
    """
    if ":" in path:
        module_path, _, attr_path = path.partition(":")
        attrs = [a for a in attr_path.split(".") if a]  # lup: ignore — dotted attr path
        try:
            obj: object = importlib.import_module(module_path)
        except ImportError as e:
            raise ValueError(f"Could not import module '{module_path}': {e}") from e
        for attr in attrs:
            try:
                obj = getattr(obj, attr)
            except AttributeError as e:
                raise ValueError(f"'{module_path}' has no attribute '{attr}'") from e
        return obj, attrs[-1] if attrs else module_path.rsplit(".", 1)[-1]

    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        module_path = ".".join(parts[:i])
        try:
            obj = importlib.import_module(module_path)
            for attr in parts[i:]:
                obj = getattr(obj, attr)
            return obj, parts[-1]
        except (ImportError, AttributeError):
            continue
    raise ValueError(f"Could not resolve: {path}")


def find_module_path(module_name: str) -> Path | None:
    """Find the file path for a module."""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin:
            return Path(spec.origin)
    except (ImportError, ModuleNotFoundError, ValueError):
        pass
    try:
        mod = importlib.import_module(module_name)
        if hasattr(mod, "__file__") and mod.__file__:
            return Path(mod.__file__)
    except (ImportError, ModuleNotFoundError):
        pass
    return None


def fail(msg: str) -> typing.NoReturn:
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)


@functools.cache
def categorize_import(module_name: str) -> str:
    root = module_name.split(".")[0]
    if root in sys.stdlib_module_names:
        return "stdlib"
    path = find_module_path(root)
    if path is None:
        return "third-party"
    if "site-packages" in str(path):
        return "third-party"
    project_root = find_nearest_pyproject()
    if project_root and str(path).startswith(str(project_root)):
        return "project"
    return "third-party"
