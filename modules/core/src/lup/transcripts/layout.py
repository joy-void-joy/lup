"""Where transcripts reads what it indexes on the operator's machine, each from their home with a leading `~`, and what it keeps in its own data."""

from pathlib import Path

HOMES = Path("~/.local/share/lup/homes")
"""The rooms' history homes, each project's under `projects/<digest>/<runtime>`,
and the one every project shares under `shared/<runtime>`, as the rooms keep them
(`lup/rooms/`)."""

ARCHIVE = Path("~/.local/share/lup/modules/transcripts")
"""The copies the second lup kept of every session's record, each repository's
under its digest, then `related/<name>/` for those named beside it, then the
runtime, then whose home it was kept from (`host`, `rooms`, `shared`)."""

LEDGER = Path("~/.local/state/lup/ledger/ledger.sqlite3")
"""The second lup's ledger, its inbox's database."""

INDEX = "index.sqlite3"
"""The index's database, in the part's own data."""

KEPT = "kept"
"""Where the part keeps its copy of the operator's own records, a directory
named after each runtime, in the runtime's own layout."""

LEDGER_COPY = "ledger"
"""Where the part keeps its copy of the second lup's ledger, read in its place."""
