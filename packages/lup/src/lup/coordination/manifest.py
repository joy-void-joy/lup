# lup: ignore[constant-declaration]
# The file name here is how one process announces a cohort and another finds
# it, so a caller free to choose it is a caller free to open a cohort nobody
# can discover — an identity of this layout rather than a parameter.
"""What makes one directory a cohort, written where the cohort is.

A roster, a message stream and a journal in one directory are a cohort, and
until something says so that is a convention rather than a fact. Every reader
had to know it: the run that owns the directory, the tool server attaching to
it, and the console steering it each rebuilt the same construction out of the
same assumption, and a peer that wanted to *find* a cohort it did not create
had nothing to read at all.

So the fact is written down. The manifest is the one file whose presence
answers "is this a cohort?", and its contents answer the two things a reader
cannot fold out of the streams beside it: which run this is, and what it is
for. Everything else stays derived — who is present is the roster's fold, and
what is queued is the mail's, because those move and this does not.

Published by whoever opens the cohort and read by everyone else, which is the
asymmetry the three call sites already had without saying so. A reader that
found no manifest is not refused: a directory written before anything
published one still folds, and a cohort that answers to its members while
being invisible to a stranger is a better failure than one that will not open.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from lup.channels.models import publish_atomic, utc_now

MANIFEST_FILE = "cohort.json"

MANIFEST_GLOB = f"**/{MANIFEST_FILE}"
"""How a walk finds every cohort beneath a tree, at whatever depth they sit.

Depth is the consumer's: a resolver keeps one directory per run under its own
state root, and a session that spawned agents keeps one beside its notes. A
walk that assumed either would find the other's cohorts nowhere.
"""


class CohortManifest(BaseModel, frozen=True):
    """One cohort as a stranger reads it: which run, since when, and what for.

    Carrying the description rather than leaving it to the roster is what
    makes a listing of cohorts useful. A member's task says what that member
    is doing; nothing a member holds says what the population was assembled
    for, and an operator choosing between three run directories is choosing
    between purposes.
    """

    run_id: str
    opened_at: datetime
    description: str = ""
    """What this population was assembled for, in the opener's own words."""


class DiscoveredCohort(BaseModel, frozen=True):
    """One cohort a walk found, and the directory it was found in.

    The directory is not in the manifest because a manifest that named its own
    location would be wrong the moment a run directory was copied or archived,
    and the walk that opened it already knows where it looked.
    """

    root: Path
    manifest: CohortManifest


def manifest_path(root: Path) -> Path:
    """Where one cohort's manifest sits, given the directory holding it."""
    return root / MANIFEST_FILE


def publish_manifest(root: Path, run_id: str, description: str = "") -> CohortManifest:
    """Announce this directory as a cohort, unless it already says so.

    First writer wins, so re-opening a cohort keeps the moment it was first
    assembled rather than restamping it on every attach — which is what an
    operator reading "since when" is actually asking. A run resumed after a
    park is the same population, and a manifest that said otherwise would date
    the population from its last interruption.
    """
    found = read_manifest(root)
    if found is not None:
        return found
    manifest = CohortManifest(
        run_id=run_id, opened_at=utc_now(), description=description
    )
    root.mkdir(parents=True, exist_ok=True)
    publish_atomic(manifest_path(root), manifest)
    return manifest


def read_manifest(root: Path) -> CohortManifest | None:
    """What this directory says it is, or nothing where it says nothing.

    An unreadable manifest answers the same as an absent one. The file is a
    claim about a directory whose streams are readable either way, so refusing
    to open the cohort over a mangled claim would cost a reader the population
    to protect it from the description.
    """
    path = manifest_path(root)
    if not path.is_file():
        return None
    try:
        return CohortManifest.model_validate_json(path.read_text("utf-8"))
    except ValueError:
        return None


def cohorts_under(root: Path) -> list[DiscoveredCohort]:
    """Every cohort beneath one tree, each with the directory holding it.

    What a peer that did not create anything reaches for. Sorted by when each
    was assembled, newest first, because a stranger looking for a cohort to
    join is almost always looking for the one that is still going.
    """
    found = [
        DiscoveredCohort(root=path.parent, manifest=manifest)
        for path in sorted(root.glob(MANIFEST_GLOB))
        if (manifest := read_manifest(path.parent)) is not None
    ]
    return sorted(found, key=lambda entry: entry.manifest.opened_at, reverse=True)
