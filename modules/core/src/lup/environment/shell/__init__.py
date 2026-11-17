"""The shell's environment side: what a project's modules declare for their views to name, answering a view, and the dashboard's server, which serves the page and what it watches.

`looks.py` gathers the kinds and answers views; `server.py` is the server.
Its reasons are in `README.md` in `lup/shell/`.
"""

from lup.environment.shell.looks import Looks, Owned, Used, viewed

__all__ = ["Looks", "Owned", "Used", "viewed"]
