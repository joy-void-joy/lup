"""Minting a launch's boundary, measuring it, and writing it down for the session.

The launcher is the only thing that knows all three parts at once: what the
project declared, what this particular launch built, and what the probes came
back with. The compiled dispatcher inside the session knows none of them -- it
runs as a bare script, long after generation, with no way to ask the container
runtime anything -- so the launch writes the answer down and the session reads
it back. That is the same arrangement the mount table already uses, for the
same reason.

What the ledger replaces is a variable. Containment used to be
``LUP_CONTAINED``, a constant baked into the image, and a constant answers yes
for any container built from that image, for a bare ``run`` holding none of the
lease, and -- since a launcher forwards its own environment -- for an
uncontained session started from a shell that happened to export it. Keyed by a
value minted here, the ledger answers only for the launch that wrote it.

The sentinels are deliberately not secrets, and the argv carries one. They
discriminate *launches*, not principals: what they defeat is a constant and an
inherited variable, which is the whole of the accidental case this layer
governs. An agent determined to forge one could read it out of `ps`, and the
threat model says so -- this is a guardrail over a fallible agent, not an
isolation product over a hostile one.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_hex

from pydantic import BaseModel, Field

from lup.harness.requirements import SENTINEL_VARIABLE
from lup.policy.boundary import BoundaryPreflight
from lup.types import EnvVars

# lup: ignore[constant-declaration] — an identity this repository defines, and
# the one half of the handshake no probe reads: the launcher writes a ledger
# named for a value and the dispatcher believes the ledger this names
NONCE_VARIABLE = "LUP_BOUNDARY_NONCE"
"""Which ledger this session's dispatcher is entitled to believe."""


class LaunchSentinels(BaseModel, frozen=True):
    """The values one launch mints to tell its own sides apart.

    Independent rather than derived. The whole question a placement probe asks
    is which side answered, and two values either can be computed from are one
    value wearing two names.
    """

    nonce: str = Field(default_factory=lambda: token_hex(16))
    inside: str = Field(default_factory=lambda: token_hex(16))
    host: str = Field(default_factory=lambda: token_hex(16))

    def within(self) -> EnvVars:
        """What a process inside the boundary is given, for the argv that starts it."""
        return {SENTINEL_VARIABLE: self.inside, NONCE_VARIABLE: self.nonce}

    def outside(self) -> EnvVars:
        """What the launcher's own environment carries, for a host-side probe."""
        return {SENTINEL_VARIABLE: self.host, NONCE_VARIABLE: self.nonce}


def ledger_path(root: Path, nonce: str, ledger: str = ".lup/preflight") -> Path:
    """Where this launch's measurement is written, named for the launch.

    Named rather than shared, and that is not tidiness. One file per checkout
    is a file two concurrent sessions overwrite for each other, and the loser
    reads a boundary belonging to a launch that is not its own -- which is the
    same class of wrong answer as the inherited variable this replaces, arrived
    at from the other direction.
    """
    return root / ledger / f"{nonce}.json"


def record_preflight(
    preflight: BoundaryPreflight, sentinels: LaunchSentinels, root: Path
) -> Path:
    """Write what this launch measured, in the shape a bare script can read.

    Every value is a list of strings, which is not the shape a pydantic dump
    would take and is deliberately the shape the dispatcher's existing reader
    already validates. The half that reads this may reach nothing but a pinned
    standard library, so what it is handed has to be checkable by hand -- and a
    reader that has to understand two shapes is a reader with a branch nobody
    exercised.

    Written on every launch, contained or not. An uncontained launch used to
    write nothing at all, which left whatever a contained launch wrote last
    standing as this session's answer.
    """
    boundary = preflight.boundary
    written = ledger_path(root, sentinels.nonce)
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(
        json.dumps(
            {
                "profile": [boundary.name],
                "contained": ["yes"] if boundary.contained else [],
                "unjudged_ambient": [boundary.unjudged_ambient],
                "delivered": [
                    entry.capability for entry in preflight.evidence if entry.delivered
                ],
                "blocked": preflight.blocked(),
                "writable_roots": [str(item) for item in boundary.writable_roots],
                "managed_roots": [str(item) for item in boundary.managed_roots],
            },
            indent=2,
        )
    )
    return written


def retire_mount_table(root: Path, ledger: str = ".lup/boundary.json") -> None:
    """Take away a mount table that describes a boundary this launch is not behind.

    ``record_boundary`` writes the table on every *contained* launch and
    nothing ever removed it, so an uncontained launch in the same checkout
    read whatever the last contained one left. What that buys is the reader's
    worst case: a refusal attributed to a read-only mount that is not there,
    which teaches an agent to reach for the host when the bug was its own.
    Its own docstring already names staleness as the hazard and per-launch
    rewriting as the answer -- this is the half of that answer the posture
    with no table to write was missing.
    """
    (root / ledger).unlink(missing_ok=True)


def release_ledger(root: Path, nonce: str) -> None:
    """Take this launch's measurement away when its session ends.

    On the way out rather than on the way in, and the difference is a session
    somebody else is running. A launch that swept every ledger but its own
    would be correct exactly once -- with a second session open, it takes away
    a boundary that session's dispatcher is still reading, and that session
    falls back to no boundary for the rest of its life. Fail-closed, and wrong.

    Missing is not a failure. A ledger already gone is one an operator tidied,
    a container removed with its mount, or a previous exit removed twice.
    """
    ledger_path(root, nonce).unlink(missing_ok=True)


def sweep_ledgers(root: Path, older_than: timedelta = timedelta(days=7)) -> int:
    """Remove measurements left behind by launches that never got to exit.

    The crash path, and only that. A session that ends normally takes its own
    ledger with it, so anything still here after a week belongs to a launch
    that was killed -- and a window measured in days cannot reach a session
    somebody is still using, which is the property that makes sweeping safe to
    do on the way in.
    """
    directory = root / ".lup" / "preflight"
    if not directory.is_dir():
        return 0
    cutoff = datetime.now(UTC) - older_than
    stale = [
        item
        for item in directory.glob("*.json")
        if datetime.fromtimestamp(item.stat().st_mtime, UTC) < cutoff
    ]
    for item in stale:
        item.unlink()
    return len(stale)
