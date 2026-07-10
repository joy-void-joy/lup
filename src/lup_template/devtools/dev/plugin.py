# lup: ignore[dict-get]
# Every read here probes Claude-settings JSON whose keys are all optional,
# so dict-get is opted out file-wide.
"""Marketplace naming for the local lup plugin.

Marketplace names live in one global namespace
(``~/.claude/plugins/known_marketplaces.json``), so a shared name like
``lup`` or ``local`` collides across every project and worktree that
registers it — an install from one repo shadows the others. Naming each
repo's marketplace after its own project (while the plugin entry stays
``lup``, so the ``/lup:*`` command namespace is identical everywhere)
keeps installs from clashing.

``set_marketplace_name`` wires one name into the two files that hold it:

- ``.claude/plugins/.claude-plugin/marketplace.json`` — top-level ``name``
- ``.claude/settings.json`` — ``extraKnownMarketplaces`` (self-registration)
  and ``enabledPlugins`` (``lup@<name>``)

Run it via ``lup-devtools dev plugin name``; ``rename_package`` calls it so
``/lup:init`` names the marketplace after the project in the same step.
"""

import json
import tomllib
from pathlib import Path
from typing import TypedDict, cast

import typer

from lup.workspace.paths import find_project_root

PLUGIN_NAME = "lup"
SELF_PATH = "./.claude/plugins"


class DirectorySource(TypedDict, total=False):
    source: str
    path: str
    url: str


class MarketplaceEntry(TypedDict):
    source: DirectorySource


class MarketplaceJson(TypedDict, total=False):
    name: str


class SettingsJson(TypedDict, total=False):
    extraKnownMarketplaces: dict[str, MarketplaceEntry]
    enabledPlugins: dict[str, bool]  # lup: ignore[dict-str-payload] — settings wire


def plugin_root(root: Path) -> Path:
    return root / ".claude" / "plugins"


def marketplace_file(root: Path) -> Path:
    return plugin_root(root) / ".claude-plugin" / "marketplace.json"


def settings_file(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def default_marketplace_name(root: Path) -> str:
    """Marketplace name defaults to the project's package name ([project].name)."""
    with (root / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    name = data.get("project", {}).get("name")
    if not name:
        raise typer.BadParameter(
            "No [project].name in pyproject.toml; pass a marketplace name explicitly"
        )
    return name


def validate_name(name: str) -> str:
    if not name or any(c in name for c in " \t@/"):
        raise typer.BadParameter(
            f"Invalid marketplace name {name!r}: no spaces, '@', or '/'"
        )
    return name


def write_json(path: Path, data: object) -> None:  # lup: ignore[bare-object]
    path.write_text(json.dumps(data, indent=2) + "\n")


def points_at_self(entry: MarketplaceEntry, root: Path) -> bool:
    """True when a marketplace entry is this repo's own local plugin dir."""
    source = entry.get("source")
    if source is None or source.get("source") != "directory":
        return False
    target = (root / source.get("path", "")).resolve()
    return target in {plugin_root(root).resolve(), root.resolve()}


def apply_marketplace_json(root: Path, name: str, dry_run: bool) -> list[str]:
    path = marketplace_file(root)
    if not path.exists():
        raise typer.BadParameter(f"No marketplace.json at {path}")
    raw = json.loads(path.read_text())
    data = cast(MarketplaceJson, raw)  # lup: ignore[cast] — TypedDict from JSON
    old = data.get("name")
    if old == name:
        return []
    if not dry_run:
        data["name"] = name
        write_json(path, data)
    return [f"marketplace.json: name {old!r} -> {name!r}"]


def apply_settings_json(root: Path, name: str, dry_run: bool) -> list[str]:
    path = settings_file(root)
    settings = (
        cast(SettingsJson, json.loads(path.read_text()))  # lup: ignore[cast]
        if path.exists()
        else SettingsJson()
    )
    changes: list[str] = []  # lup: ignore[empty-collection] — change log

    known = settings.get("extraKnownMarketplaces") or {}
    for key in [k for k, v in known.items() if k != name and points_at_self(v, root)]:
        del known[key]
        changes.append(f"settings.json: drop extraKnownMarketplaces[{key!r}]")
    desired: MarketplaceEntry = {"source": {"source": "directory", "path": SELF_PATH}}
    if known.get(name) != desired:
        known[name] = desired
        changes.append(
            f"settings.json: extraKnownMarketplaces[{name!r}] -> {SELF_PATH}"
        )

    # Exactly one lup marketplace is enabled — this repo's own — so stale
    # self-enables (lup@lup, lup@local, …) can't shadow it.
    enabled = settings.get("enabledPlugins") or {}
    target = f"{PLUGIN_NAME}@{name}"
    for key in [k for k in enabled if k.startswith(f"{PLUGIN_NAME}@") and k != target]:
        del enabled[key]
        changes.append(f"settings.json: drop enabledPlugins[{key!r}]")
    if enabled.get(target) is not True:
        enabled[target] = True
        changes.append(f"settings.json: enable {target!r}")

    if changes and not dry_run:
        settings["extraKnownMarketplaces"] = known
        settings["enabledPlugins"] = enabled
        write_json(path, settings)
    return changes


def set_marketplace_name(root: Path, name: str, dry_run: bool = False) -> list[str]:
    """Point this repo's plugin marketplace at ``name`` (plugin entry stays ``lup``).

    Idempotent: rewrites marketplace.json and settings.json only where they
    disagree with ``name``. Returns a list of human-readable change lines.
    """
    name = validate_name(name)
    return apply_marketplace_json(root, name, dry_run) + apply_settings_json(
        root, name, dry_run
    )


def name_marketplace(name: str | None, dry_run: bool) -> None:
    """CLI entry for ``lup-devtools dev plugin name`` (see module docstring)."""
    root = find_project_root()
    resolved = name or default_marketplace_name(root)
    changes = set_marketplace_name(root, resolved, dry_run)
    if not changes:
        typer.echo(f"Marketplace already named {resolved!r}; nothing to do.")
        return
    typer.echo(
        f"Dry run — {len(changes)} change(s) for {resolved!r}:"
        if dry_run
        else f"Named marketplace {resolved!r}:"
    )
    for change in changes:
        typer.echo(f"  {change}")
