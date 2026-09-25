"""Prepare Codex's own home from a checkout, without opening an agent turn."""

from pathlib import Path
import sys
from typing import Annotated

import typer
from pydantic import ValidationError

from lup.providers.codex.harness_runtime import CodexPluginInstaller, PluginCacheConfig
from lup.providers.codex.home import (
    CodexWorktreeHomeStore,
    install_declared_policy,
    trust_project,
)
from lup.providers.codex.marketplace import CodexMarketplace
from lup.providers.codex.profile import CodexProfileSettings


def install_codex_plugin(
    root: Path,
    home: Path,
    force: bool = False,
    trusted: bool = False,
    plugin_root: Path | None = None,
) -> None:
    """Install the checkout's plugin and verify native discovery and hook trust.

    ``plugin_root`` offers the plugin from somewhere other than the checkout
    -- a mode's variant, compiled beside it -- and the checkout stays the
    project the home trusts and the working directory everything is asked
    from, since that is where the session opens.
    """
    source = plugin_root or root
    declared = CodexMarketplace.declared(source)
    if declared is None:
        return
    if trusted:
        home.mkdir(parents=True, exist_ok=True)
        trust_project(home, root)
    installer = CodexPluginInstaller(
        PluginCacheConfig(
            codex_home=home, marketplace=declared.name, plugin=declared.plugin
        )
    )
    cache = installer.ensure(declared.source, root, force=force)
    installer.verify(cache, root)
    install_declared_policy(
        home,
        source,
        seed=trusted or CodexWorktreeHomeStore().derived(home),
        workspace=root,
    )
    typer.echo(f"Verified installed Codex plugin in {home}: {cache.installed_root}")


app = typer.Typer()


@app.command()
def prepare(
    root: Annotated[Path, typer.Option("--root")],
    home: Annotated[Path, typer.Option("--home")],
    force: Annotated[bool, typer.Option("--force")] = False,
    trusted: Annotated[bool, typer.Option("--trust-project")] = False,
    settings_stdin: Annotated[bool, typer.Option("--settings-stdin")] = False,
    plugin_root: Annotated[Path | None, typer.Option("--plugin-root")] = None,
) -> None:
    """Prepare one native home from the installed library's implementation."""
    if settings_stdin:
        try:
            CodexProfileSettings.model_validate_json(sys.stdin.read()).install(
                home, enforce_policy=CodexMarketplace.enforced(plugin_root or root)
            )
        except (ValidationError, ValueError):
            raise typer.BadParameter(
                "Cannot prepare the selected Codex profile; its settings were not logged."
            ) from None
    install_codex_plugin(root, home, force, trusted, plugin_root)


if __name__ == "__main__":
    app()
