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
    try:
        mapping = importlib.metadata.packages_distributions()
        return sorted(mapping.keys())
    except AttributeError:
        pass

    packages: list[str] = []  # lup: ignore[empty-collection] — per-dist fold
    for dist in importlib.metadata.distributions():
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for line in top_level.splitlines():
                pkg = line.strip()  # lup: ignore[string-strip] — metadata lines
                if pkg and not pkg.startswith("_"):
                    packages.append(pkg)
        else:
            name = dist.metadata["Name"]
            if name:
                # Distribution names use "-", import names "_" — the packaging
                # convention this fallback normalizes by.
                packages.append(name.replace("-", "_"))  # lup: ignore[string-replace]
    return sorted(dict.fromkeys(packages))
