"""Root CLI app composing all devtools sub-apps.

All development tooling is exposed as the ``lup-devtools`` entry point.
Each sub-app groups related commands.

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
    $ uv run lup-devtools version
    $ uv run lup-devtools sync status
    $ uv run lup-devtools claude usage --no-detail
"""

import typer

from lup_template.devtools.agent import app as agent_app
from lup_template.devtools.claude.app import app as claude_app
from lup_template.devtools.py import app as py_app
from lup_template.devtools.dev.app import app as dev_app
from lup_template.devtools.feedback.app import app as feedback_app
from lup_template.devtools.setup import app as setup_app
from lup_template.devtools.sync import app as sync_app
from lup_template.devtools.trace.app import app as trace_app
from lup_template.devtools.version import app as version_app

app = typer.Typer(
    help="lup-devtools: development and analysis tools",
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

app.add_typer(agent_app, name="agent", help="Agent introspection and debugging")
app.add_typer(
    claude_app, name="claude", help="Run Claude Code for this project (+ usage)"
)
app.add_typer(py_app, name="py", help="Python module introspection")
app.add_typer(dev_app, name="dev", help="Worktrees, branches, and pre-flight checks")
app.add_typer(
    feedback_app, name="feedback", help="Feedback state, metrics, and commits"
)
app.add_typer(setup_app, name="setup", help="Interactive setup wizard")
app.add_typer(sync_app, name="sync", help="Upstream sync tracking")
app.add_typer(trace_app, name="trace", help="Trace display, search, and analysis")
app.add_typer(version_app, name="version", help="Agent version, changelog, and bump")
