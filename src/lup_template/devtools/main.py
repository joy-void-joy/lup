"""Root CLI app composing all devtools sub-apps.

All development tooling is exposed as the ``lup-devtools`` entry point.
Each sub-app groups related commands.

What this module holds is the declaration the library's roster is wired over,
plus this project's own delta: the sub-apps only it has, and — through
``subapps.SELECTION`` — any of lup's it declines. The inherited half is not
named here, so a sub-app lup grows arrives with the next lock refresh instead
of waiting for somebody to notice it and add a line.

The module is ``main.py`` rather than ``__main__.py`` or ``app.py`` because
``lup-devtools`` is launched through the ``[project.scripts]`` console entry
point (``lup_template.devtools.main:app``), never as ``python -m
lup_template.devtools``. A ``__main__.py`` would imply the latter and add a
second launch path to keep in sync; ``app.py`` is reserved for the per-sub-app
modules (``dev/app.py``, ``trace/app.py``, ...) so the root composer keeps a
distinct name.

Examples::

    $ uv run lup-devtools --help
    $ uv run lup-devtools agent inspect --json
    $ uv run lup-devtools py info requests
    $ uv run lup-devtools trace show <session_id>
    $ uv run lup-devtools feedback status
    $ uv run lup-devtools dev branches
    $ uv run lup-devtools dev worktree create feat-name
    $ uv run lup-devtools dev check --no-test
    $ uv run lup-devtools report
    $ uv run lup-devtools version
    $ uv run lup-devtools sync status
    $ uv run lup-devtools usage claude --no-detail
"""

from pathlib import Path

import typer

import lup_template.agent.prompts as prompts
from lup.providers.claude.usage.reader import claude_usage_entry
from lup.providers.codex.usage.reader import codex_usage_entry
from lup.devtools.dev import conflicts
from lup.devtools.dev.commands import write_command_reference
from lup.devtools.feedback.models import AgentPrompt
from lup.devtools.harness.resolve import ConfiguredModel
from lup.devtools.roster import DevtoolsDeclarations
from lup.devtools.subapps import SubApp, compose
from lup.workspace.paths import find_nearest_pyproject
from lup_template.agent.config import engine_for_model, settings
from lup_template.devtools.agent import app as agent_app
import lup_template.devtools.dev.app as dev
from lup_template.devtools.harness.composition import (
    REPOSITORY_WIDE,
    TARGETS,
    profile_directory,
)
from lup_template.devtools.setup import INTEGRATIONS
from lup_template.devtools.subapps import APPLICATION_SPECS, SELECTION


def assembled_prompt() -> AgentPrompt:
    """This application's system prompt, as the health report weighs it.

    The source is the module that renders the sections rather than a path
    matched by shape, so renaming the package during initialization moves it.
    """
    return AgentPrompt(
        sections=prompts.SECTIONS,
        rendered=prompts.get_system_prompt(),
        source=Path(prompts.__file__),
    )


def command_reference(root: Path | None = None, *, check: bool = False) -> Path:
    """Write or verify the reference for every command this CLI serves.

    Reads ``app`` when it runs rather than taking it as an argument: the
    declarations below are built before the sub-apps are mounted onto it, and
    a repository writer runs long after both. Wired from the composition root
    because that is the only module that has the whole CLI — a writer declared
    beside the other two would have to import this one, which nothing does.
    """
    return write_command_reference(app, root, check=check)


DECLARATIONS = DevtoolsDeclarations(
    dev=dev.declared,
    targets=TARGETS,
    repository_writers=[*REPOSITORY_WIDE, command_reference],
    prompt=assembled_prompt,
    relocate_roots=[
        Path("src"),
        # The library's own package root as well as the tree that holds it: a
        # sweep needs the wide one to find every importer, and carrying the
        # module's file needs the one its dotted name resolves against, or a
        # relocation inside the library repoints every import and moves
        # nothing. Overlapping roots are read once each.
        Path("packages"),
        Path("packages/lup/src"),
        Path("tests"),
        Path("examples"),
    ],
    integrations=INTEGRATIONS,
    usage_entries=[claude_usage_entry(), codex_usage_entry()],
    model=ConfiguredModel(
        name=settings.model, adapter=engine_for_model(settings.model)
    ),
    profiles=profile_directory(),
)
"""What this repository tells the library's roster about itself.

One value reaches every sub-app the library ships, so a factory that grows an
argument grows a field here with a default rather than breaking a call site.
``relocate_roots`` names four because this repository vendors the library it
publishes; ``usage_entries`` names both backends because it runs on both.
"""

# lup: ignore[constant-declaration] — this CLI's own composition: which sub-apps
# only it has and under what name, decided here because nothing sits above it
APPLICATION_APPS = {
    "agent": agent_app,
}
"""Where each application spec meets the Typer app answering to its name.

This module is the composition root and nothing imports it, which is what
lets the apps be named here without the guidance that documents them coming
along. A spec with no app raises on the first invocation rather than serving
a CLI missing a command the docs promise.
"""

app = typer.Typer(
    help="lup-devtools: development and analysis tools",
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

ROSTER = {
    entry.spec.name: entry
    for entry in SELECTION.over(
        DECLARATIONS.roster(),
        [
            SubApp(spec=spec, app=APPLICATION_APPS[spec.name])
            for spec in APPLICATION_SPECS
        ],
    )
}
"""Every sub-app this CLI serves, by name, before anything is mounted onto one.

Mounted from here because the trees below belong to a sub-app the library
built: the module that owns them cannot reach back for an app composed after
it, and replacing the whole entry to add two commands would restate every
argument the inherited one takes.
"""

dev.extend(ROSTER["dev"].app)

compose(app, list(ROSTER.values()))


@app.callback()
def report_a_conflicted_manifest() -> None:
    """Say what to run when `uv` is about to stop being able to start.

    Every other command here is documented as ``uv run lup-devtools ...``, and
    a conflicted ``pyproject.toml`` turns all of them into a parse error from
    a tool that never reached this program. This runs on whichever invocation
    does get through, so the diagnosis reaches the session before the failure
    does rather than after.
    """
    root = find_nearest_pyproject()
    if root is not None and conflicts.manifest_conflicted(root):
        typer.echo(conflicts.conflicted_manifest_notice(root), err=True)
