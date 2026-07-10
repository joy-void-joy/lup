"""Helpers for ``py search`` — find symbols across packages."""

import importlib
import importlib.metadata
import inspect
import typing

# ---------------------------------------------------------------------------
# py search — find symbols across packages
# ---------------------------------------------------------------------------


class SearchMatch(typing.TypedDict):
    symbol: str
    kind: str
    import_path: str


def scan_module_symbols(module_name: str, pattern: str) -> list[SearchMatch]:
    """Import a module and search dir() for matching symbols."""
    try:
        mod = importlib.import_module(module_name)
    except (ImportError, AttributeError, TypeError, RuntimeError, OSError):
        return []

    pattern_lower = pattern.lower()
    matches: list[SearchMatch] = []

    for name in dir(mod):
        if name.startswith("_"):
            continue
        if pattern_lower not in name.lower():
            continue

        member = getattr(mod, name, None)
        if member is None:
            continue

        if inspect.isclass(member):
            kind = "class"
        elif inspect.isfunction(member) or inspect.isbuiltin(member):
            kind = "function"
        elif inspect.ismodule(member):
            continue
        else:
            kind = type(member).__name__

        matches.append(
            SearchMatch(symbol=name, kind=kind, import_path=f"{module_name}.{name}")
        )

    return matches


def get_top_level_packages() -> list[str]:
    """Get importable top-level package names from installed distributions."""
    try:
        mapping = importlib.metadata.packages_distributions()
        return sorted(mapping.keys())
    except AttributeError:
        pass

    packages: set[str] = set()
    for dist in importlib.metadata.distributions():
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for line in top_level.strip().splitlines():
                pkg = line.strip()
                if pkg and not pkg.startswith("_"):
                    packages.add(pkg)
        else:
            name = dist.metadata["Name"]
            if name:
                packages.add(name.replace("-", "_"))
    return sorted(packages)
