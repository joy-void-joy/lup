"""Root CLI app composing all devtools sub-apps.

All development tooling is exposed as the ``lup-devtools`` entry point.
Each sub-app groups related commands.

Examples::

    $ uv run lup-devtools --help
    $ uv run lup-devtools agent inspect --json
    $ uv run lup-devtools trace show my-session
    $ uv run lup-devtools feedback collect --all-time
    $ uv run lup-devtools metrics summary --all-versions
    $ uv run lup-devtools git commit-results --dry-run
    $ uv run lup-devtools sync list
    $ uv run lup-devtools usage --no-detail
"""

import typer

from lup.devtools.agent import app as agent_app
from lup.devtools.api import app as api_app
from lup.devtools.branch import app as branch_app
from lup.devtools.bump import app as bump_app
from lup.devtools.charts import app as charts_app
from lup.devtools.conflict import app as conflict_app
from lup.devtools.feedback import app as feedback_app
from lup.devtools.git import app as git_app
from lup.devtools.init import app as init_app
from lup.devtools.metrics import app as metrics_app
from lup.devtools.pr import app as pr_app
from lup.devtools.sync import app as sync_app
from lup.devtools.trace import app as trace_app
from lup.devtools.usage import app as usage_app
from lup.devtools.worktree import app as worktree_app

app = typer.Typer(
    help="lup-devtools: development and analysis tools",
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

app.add_typer(agent_app, name="agent", help="Agent introspection and debugging")
app.add_typer(api_app, name="api", help="API inspection and module info")
app.add_typer(branch_app, name="branch", help="Branch inventory and cleanup")
app.add_typer(bump_app, name="bump", help="Version bump operations")
app.add_typer(charts_app, name="charts", help="Terminal chart visualizations")
app.add_typer(conflict_app, name="conflict", help="Merge conflict assessment and audit")
app.add_typer(feedback_app, name="feedback", help="Feedback collection")
app.add_typer(git_app, name="git", help="Git operations for sessions")
app.add_typer(init_app, name="init", help="Project initialization")
app.add_typer(metrics_app, name="metrics", help="Aggregate metrics")
app.add_typer(pr_app, name="pr", help="PR lifecycle (status, merge, push, checks)")
app.add_typer(sync_app, name="sync", help="Upstream sync tracking")
app.add_typer(trace_app, name="trace", help="Trace analysis")
app.add_typer(usage_app, name="usage", help="Claude Code usage display")
app.add_typer(worktree_app, name="worktree", help="Worktree management")
