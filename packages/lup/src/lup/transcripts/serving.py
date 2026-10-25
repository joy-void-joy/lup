"""Copying each session's record of the repository when a launch opens and when it stops.

The launch's runtime says which of its records are the repository's sessions'
(`Records.kept`), from the directories they ran in: the repository's git
directory, and each of its worktrees. Each record is copied into the module's own
data directory for the repository, under the runtime's name, laid out as the
runtime lays them out: a file is copied where the copy is missing, or differs in
size or time from the record, so what the runtime has added or grown since the
last copy is copied, and what's unchanged isn't read again. A runtime only adds
to its records, so a copy taken when a launch opens catches whatever an earlier
launch that never stopped left.
"""

import asyncio
import shutil
from typing import TYPE_CHECKING

from lup.tools.hook import lup_hook
from lup_dev.declaration.serving import ModuleHooks, Moment
from lup_dev.git import Git

if TYPE_CHECKING:
    from pathlib import Path

    from lup.transcripts.module import Transcripts
    from lup_dev.host.records import Record


def stale(source: Path, copy: Path) -> bool:
    """Say whether `copy` is missing, or differs in size or time from `source`."""
    if not copy.is_file():
        return True
    held, kept = source.stat(), copy.stat()
    return (held.st_size, held.st_mtime_ns) != (kept.st_size, kept.st_mtime_ns)


def copied(records: list[Record], target: Path) -> int:
    """Copy each file of `records` into `target` where it's stale, and return how many were copied."""
    pairs = [
        (each, target / record.place / each.relative_to(record.source))
        for record in records
        for each in (
            [record.source]
            if record.source.is_file()
            else sorted(path for path in record.source.rglob("*") if path.is_file())
        )
    ]
    stale_pairs = [(source, copy) for source, copy in pairs if stale(source, copy)]
    for source, copy in stale_pairs:
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copy)
    return len(stale_pairs)


class TranscriptsHooks(ModuleHooks):
    """Keeping the repository's sessions' records: what the runtime added or grew, when a launch opens and when it stops."""

    module: Transcripts

    @lup_hook(on=["launched", "stopped"])
    async def keep(self, _moment: Moment) -> None:
        """Copy every record of the repository's sessions the runtime added or grew since the last copy."""
        repository = self.launch.repository
        under = [repository, *Git.pinned(repository).worktrees()]
        records = self.records.kept(under)
        target = self.data / self.launch.runtime
        await asyncio.to_thread(copied, records, target)
