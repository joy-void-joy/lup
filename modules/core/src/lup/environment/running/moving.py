"""Moving what a part kept where its module was renamed, as lup's machine starts, so it reads what it kept under the name it had.

A part keeps its data under `<module>.<Part>` in the machine's state
(`lup.environment.doors`), so renaming a module, for what the command line
types, would leave behind what its parts kept: the approvals, the secrets, the
projects registered, the inbox. Each directory kept under a name a part had is
moved to the one it has, where that one isn't there yet, before anything reads
either: the loader as it asks what's approved, and the machine as it starts its
parts.
"""

# lup: defer(issue=27, why="moves what machines that ran before the renames kept, and moves nothing once each has started since")

from pathlib import Path

from lup.doors.parts import Parts
from lup.hosting.module import Hosting
from lup.inbox.module import Inbox


def renamed() -> dict[str, str]:
    """Return each directory a part's data was kept under, by the one its module's name keeps it under: the machine's parts, which were `hosting`'s, and the inbox's, which was the core's."""
    return {
        **{
            f"hosting.{each.__name__}": f"{Hosting.name}.{each.__name__}"
            for each in Hosting().held(Parts)
        },
        "core.Inboxes": f"{Inbox.name}.Inboxes",
    }


def moved(data: Path, names: dict[str, str] | None = None) -> list[str]:
    """Move each directory under `data` kept under a name in `names`, by default `renamed()`, to the one it names, where that isn't there yet; return the names they're kept under, of those moved.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as made:
    ...     data = Path(made)
    ...     (data / "hosting.Approvals").mkdir()
    ...     (data / "hosting.Secrets").mkdir()
    ...     (data / "machine.Secrets").mkdir()
    ...     names = {"hosting.Approvals": "machine.Approvals", "hosting.Secrets": "machine.Secrets"}
    ...     moved(data, names), sorted(each.name for each in data.iterdir())
    (['machine.Approvals'], ['hosting.Secrets', 'machine.Approvals', 'machine.Secrets'])
    """
    moving = {
        before: kept
        for before, kept in (renamed() if names is None else names).items()
        if (data / before).is_dir() and not (data / kept).exists()
    }
    for before, kept in moving.items():
        (data / before).rename(data / kept)
    return list(moving.values())
