# lup: ignore[constant-declaration]
# The env var name is one half of a contract the permission hook spells in its
# own vendored source, which cannot import this module. A caller replacing it
# would be naming a variable the other half does not write.
"""Where editing is currently happening, published for whoever resolves code.

A language server is started once, against the directory a session opened in,
and keeps that root for its whole life. Work happens somewhere else — this
project asks that every change be made in a worktree — and nothing about that
move reaches the server. It goes on resolving the same module names against
the launch checkout: not an error, an answer about the wrong tree.

The edited file is the one thing that knows where editing is happening, and
the permission hook already sees it on every edit. So the hook publishes the
checkout it belongs to, and the servers that would otherwise guess read it.

The reader and the writer never share a process, and the writer is the
hermetic hook runtime, which may not import this module. What crosses is a
path in the environment and a JSON object at the end of it — so this module
owns the shape, and a test pins the hook's bytes against it.
"""

from pathlib import Path

from pydantic import BaseModel

from lup.channels.models import publish_atomic

EDITION_ENV = "LUP_EDITION"
"""Names the file below. Absent means nobody published, which is not an error.

A session that never edits anything, a devtools command run by hand, a test:
all of them read no edition and fall back to the root they were given. The
variable is how the harness tells one process where the other one writes.
"""


class Edition(BaseModel, frozen=True):
    """The checkout an edit landed in, and the file that says so.

    Carries the file as well as the workspace because the workspace alone
    cannot be checked: a reader that disagrees needs to see which edit the
    claim came from, and a stale record is worth recognising by the file it
    names rather than by a timestamp alone.
    """

    workspace: Path
    file: Path


def publish_edition(path: Path, workspace: Path, file: Path) -> None:
    """Record that editing is happening in *workspace*, atomically."""
    publish_atomic(path, Edition(workspace=workspace, file=file))


def read_edition(path: Path | None) -> Edition | None:
    """The last published edition, or None when nobody has published one.

    Every failure is the same answer. A missing file is the ordinary case,
    and a corrupt one is a hint rather than a fact — this only ever refines
    a root the caller already has, so refusing to answer costs the caller
    nothing and raising would cost it a working tool.
    """
    if path is None or not path.is_file():
        return None
    try:
        return Edition.model_validate_json(path.read_text("utf-8"))
    except ValueError:
        return None
