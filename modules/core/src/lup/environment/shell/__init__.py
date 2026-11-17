"""The shell's environment side: answering a view, and the dashboard's server, which serves the page and what it watches.

`viewing.py` answers views; `server.py` is the server. Its reasons are in
`README.md` in `lup/shell/`.
"""

from lup.environment.shell.viewing import viewed

__all__ = ["viewed"]
