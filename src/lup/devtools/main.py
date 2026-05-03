"""Root CLI app composing all devtools sub-apps.

All development tooling is exposed as the ``lup-devtools`` entry point.
Each sub-app groups related commands.

Examples::

    $ uv run lup-devtools --help
    $ uv run lup-devtools agent inspect --json
    $ uv run lup-devtools agent version
    $ uv run lup-devtools session list
    $ uv run lup-devtools session show <session_id>
    $ uv run lup-devtools git branches
    $ uv run lup-devtools git worktree create feat-name
    $ uv run lup-devtools git check --no-test
    $ uv run lup-devtools sync list
    $ uv run lup-devtools usage --no-detail
"""

import typer

from lup.devtools.agent import app as agent_app
from lup.devtools.api import app as api_app
from lup.devtools.git import app as git_app
from lup.devtools.session import app as session_app
from lup.devtools.sync import app as sync_app
from lup.devtools.usage import app as usage_app

app = typer.Typer(
    help="lup-devtools: development and analysis tools",
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

app.add_typer(agent_app, name="agent", help="Agent introspection and debugging")
app.add_typer(api_app, name="api", help="API inspection")
app.add_typer(git_app, name="git", help="Worktrees, branch analysis, and checks")
app.add_typer(
    session_app, name="session", help="Traces, metrics, feedback, and commits"
)
app.add_typer(sync_app, name="sync", help="Upstream sync tracking")
app.add_typer(usage_app, name="usage", help="Claude Code usage display")
