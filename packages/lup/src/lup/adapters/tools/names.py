"""The framework's neutral tool-name vocabulary (SDK-free).

These are Claude Code's builtin tool names, adopted as the lingua
franca: each name is spelled once here, and every adapter translates its
backend's native tool identifiers to and from these constants. Consumers
reference the constants — or the grouped sets — instead of re-spelling
the strings, so a rename lands in one place. Per-engine builtin tables
(``tools/claude.py``, ``tools/codex.py``) build on this vocabulary.
"""

BASH = "Bash"
EDIT = "Edit"
GLOB = "Glob"
GREP = "Grep"
NOTEBOOK_EDIT = "NotebookEdit"
READ = "Read"
TASK = "Task"
TODO_WRITE = "TodoWrite"
WEB_FETCH = "WebFetch"
WEB_SEARCH = "WebSearch"
WRITE = "Write"

WEB_TOOLS: set[str] = {WEB_SEARCH, WEB_FETCH}  # lup: ignore[set-shape] — membership
"""The web-reaching builtins — search and fetch. Code that keys on whether a
turn touched the web matches against this set instead of re-listing the two
names."""
