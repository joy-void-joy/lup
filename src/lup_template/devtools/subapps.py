"""Typed roster of lup-devtools sub-apps shared by the CLI and generated docs.

The root Typer app in ``main.py`` wires its sub-apps from this roster, and the
harness content modules render their sub-app enumerations from it, so the CLI
and every generated document always agree on the same list.
"""

from pydantic import BaseModel, ConfigDict


class SubApp(BaseModel):
    """One lup-devtools sub-app: its CLI name and one-line help text."""

    model_config = ConfigDict(frozen=True)

    name: str
    help: str


SUBAPPS = [
    SubApp(name="agent", help="Agent introspection and debugging"),
    SubApp(name="dashboard", help="Host the local setup dashboard"),
    SubApp(name="dev", help="Worktrees, branches, and pre-flight checks"),
    SubApp(name="feedback", help="Feedback state, metrics, and commits"),
    SubApp(name="harness", help="Generate and launch Claude or Codex harnesses"),
    SubApp(name="py", help="Python module introspection"),
    SubApp(name="setup", help="Interactive setup wizard"),
    SubApp(name="sync", help="Track sync.json repos and review their commits"),
    SubApp(name="trace", help="Trace display, search, and analysis"),
    SubApp(name="usage", help="Claude Code usage display"),
    SubApp(name="version", help="Agent version, changelog, and bump"),
]


def subapp_summary() -> str:
    """Format the sub-app roster as an inline backticked name list."""
    return ", ".join(f"`{subapp.name}`" for subapp in SUBAPPS)


def subapp_bullets(indent: str = "") -> str:
    """Format the sub-app roster as Markdown bullet lines with help text."""
    return "".join(f"{indent}- `{subapp.name}` — {subapp.help}\n" for subapp in SUBAPPS)
