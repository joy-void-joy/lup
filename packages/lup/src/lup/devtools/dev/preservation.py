"""Record what a repository's surface holds, so a refactor cannot lose part of it.

A reorganisation that moves modules is judged by a claim nothing reads the
tree to check: *no capability disappeared*. The claim is made once, in a plan,
against a surface too large to hold in one reading — and a capability that
went missing looks exactly like one that moved, because both leave the old
import path unresolvable. So the assumption survives review by being
unfalsifiable rather than by being true.

A ledger makes it falsifiable. The surface is captured before the move as a
checked-in fixture; afterwards the same walk runs against the live tree and
every captured identity is resolved against it. One that resolves nowhere has
disappeared, and that is the failure. One that resolves somewhere other than
where it was captured has moved, and that is not — it is the migration map,
which is the second thing the capture is for: an adopter's imports are
repointed from the same difference that proves nothing was lost.

Identity is chosen so a move does not read as a loss. A command's identity is
the path a reader types, because that is what a caller depends on and what a
rename genuinely changes. An export's identity is its qualified name, because
the module holding it is exactly what a reorganisation is entitled to change
and the class holding it is not. Location rides along as evidence rather than
as identity: a name the live tree still declares anywhere has survived, so it
is reported as a move and never as a loss. Where a name several modules share
— ``logger``, ``app`` — moves with one of them, the move is recorded but casts
no vote in the migration map, whose pairs are drawn only from the names that
landed in exactly one place.

Deliberate removal is not a defeat for this. Deduplicating two spellings of
one thing drops a capability on purpose, and the way to record that is to
capture again: the entry leaves the fixture in a diff a reviewer reads, rather
than leaving the tree in a diff nobody does.

Only what a published root can import is walked. A generated plugin tree is
derived from the typed catalog that emits it, and a test names what it tests,
so neither is a surface an adopter can hold — counting them would grow the
ledger by half and make every regeneration read as a capability change.
"""

import json
from collections.abc import Iterable, Iterator, Set as AbstractSet
from enum import StrEnum
from itertools import groupby
from pathlib import Path

import typer
from pydantic import BaseModel

from lup.codescan.common import PACKAGE_ROOTS, module_name
from lup.codescan.symbols import defined_symbols
from lup.devtools.dev.boundaries import TrackedSource, tracked_python_sources
from lup.devtools.dev.commands import CommandEntry
from lup.devtools.dev.relocate import name_parts
from lup.devtools.project import DevProject
from lup.devtools.utils import git

LEDGER_FILE = Path("preservation-ledger.json")
"""Where a capture lands by default, relative to the checkout it describes.

A default rather than a fixed location: an adopter keeping its fixtures
somewhere else passes a path, and every entry point here takes one.
"""


class CapabilityKind(StrEnum):
    """What sort of thing one ledger entry promises stays reachable."""

    COMMAND = "command"
    EXPORT = "export"


class Capability(BaseModel, frozen=True):
    """One thing the repository offers, and where it offered it from."""

    kind: CapabilityKind

    identity: str
    """What a caller depends on: the typed command path, or the qualified name."""

    location: str
    """The module declaring it — empty for a command, whose path is its home."""

    def spelled(self) -> str:
        """This entry as one line, for a reader comparing two captures."""
        return f"{self.kind} {self.identity}" + (
            f" ({self.location})" if self.location else ""
        )


class ModuleSurface(BaseModel, frozen=True):
    """One module, and every name it declares at a scope an importer can reach.

    Grouped rather than held flat because that is how the file is read and how
    a refactor moves: a module arriving, leaving, or being renamed is one
    block in the diff instead of several hundred adjacent lines.
    """

    module: str
    declares: list[str]


class Ledger(BaseModel, frozen=True):
    """A whole surface as it stood at one revision, with what was walked."""

    revision: str
    """The commit the capture read, so a divergence traces to a range."""

    roots: list[str]
    """The import roots walked, named so a later capture covers the same tree."""

    commands: list[str]
    """Every operation the composed CLI answered to, as a reader types it."""

    modules: list[ModuleSurface]

    @classmethod
    def read(cls, path: Path = LEDGER_FILE) -> "Ledger":
        """Load a capture from disk."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, path: Path = LEDGER_FILE) -> None:
        """Persist this capture, formatted so a diff reads line by line."""
        path.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )

    def capabilities(self) -> Iterator[Capability]:
        """Every entry this capture holds, flattened to one shape."""
        for command in self.commands:
            yield Capability(kind=CapabilityKind.COMMAND, identity=command, location="")
        for surface in self.modules:
            for name in surface.declares:
                yield Capability(
                    kind=CapabilityKind.EXPORT, identity=name, location=surface.module
                )

    def homes(self) -> dict[str, list[str]]:
        """Each export identity this capture holds, and the modules declaring it."""
        declared = sorted(
            (name, surface.module)
            for surface in self.modules
            for name in surface.declares
        )
        return {
            identity: [module for _, module in group]
            for identity, group in groupby(declared, key=lambda pair: pair[0])
        }


class Relocation(BaseModel, frozen=True):
    """A capability that survived, at an address none of its captures named."""

    capability: Capability

    homes: list[str]
    """Where it is declared now — several, when the name is a shared one."""

    def spelled(self) -> str:
        """The move as one line: what it was, and where it went."""
        return f"{self.capability.spelled()} → {', '.join(self.homes)}"


class Divergence(BaseModel, frozen=True):
    """What a live tree does and does not still answer for a capture."""

    disappeared: list[Capability]
    """Captured, and now declared by nothing — the failure this exists to find."""

    relocated: list[Relocation]
    """Captured, still reachable, and no longer where it was."""

    arrived: list[Capability]
    """Live and uncaptured, so a reader can see what the range added."""

    def intact(self) -> bool:
        """Whether every captured capability is still reachable somewhere."""
        return not self.disappeared

    # lup: ignore[dict-str-payload] — module paths on both sides, open and
    # data-driven: whichever modules the range under review happened to move
    def module_moves(self) -> dict[str, str]:
        """Old module to new, for every relocation naming one destination.

        The argument list for repointing an adopter, derived rather than
        written down: each relocated export that landed in exactly one module
        votes for that module pair, and a pair is reported once. A name that
        landed in several is left out as ambiguous evidence — the pairs its
        module siblings supply cover the same move.
        """
        return {
            relocation.capability.location: relocation.homes[0]
            for relocation in sorted(
                self.relocated, key=lambda relocation: relocation.capability.identity
            )
            if len(relocation.homes) == 1 and relocation.capability.location
        }


def walked_roots(
    project: DevProject, roots: AbstractSet[str] = PACKAGE_ROOTS
) -> AbstractSet[str]:
    """The roots a capture covers: the library's, plus what the app publishes.

    Read from the declaration rather than written down, for the reason
    :class:`~lup.devtools.project.DevProject` exists: initialization renames
    the application's package, and a root named here would go on naming one
    that is gone.
    """
    return {*roots, project.package}


def surfaces(
    sources: Iterable[TrackedSource], roots: AbstractSet[str]
) -> Iterator[ModuleSurface]:
    """Every walked module one of ``roots`` can import, and what it declares.

    A source resolving to a module path outside every root is not skipped for
    being uninteresting — it is unreachable, and a name nothing can import is
    not a capability whatever else it is. A path no import statement could
    spell at all — a generated tree under a dot directory — parses to no
    names and is left out by the same test.
    """
    for source in sources:
        module = module_name(source.path, roots)
        parts = name_parts(module)
        if parts is not None and parts[0] in roots:
            yield ModuleSurface(
                module=module,
                declares=[symbol.name for symbol in defined_symbols(source.text)],
            )


def operations(context: typer.Context) -> Iterator[CommandEntry]:
    """Every operation the CLI this command is running under answers to.

    Taken from the context rather than from an imported app, for the reason
    the command reference takes its app as an argument: the composed CLI is a
    root nothing imports, and naming one here would pick a single project's.
    A command already running under that root can see the whole of it.
    """
    yield from CommandEntry.beneath(context.find_root().command, [])


def capture(
    commands: Iterable[CommandEntry],
    project: DevProject,
    sources: Iterable[TrackedSource] | None = None,
) -> Ledger:
    """Walk the live tree into a ledger, at the revision it is standing on.

    The operations arrive already walked rather than as an app to walk. The
    composed CLI is a root nothing imports, and the command that captures is
    itself inside it — so the caller, which is running under that root, hands
    over what it can already see.
    """
    roots = walked_roots(project)
    walked = tracked_python_sources(project) if sources is None else list(sources)
    return Ledger(
        revision=str(git("rev-parse", "HEAD")).strip(),
        roots=sorted(roots),
        commands=[entry.spelled() for entry in commands],
        modules=sorted(surfaces(walked, roots), key=lambda one: one.module),
    )


def compare(captured: Ledger, live: Ledger) -> Divergence:
    """Resolve every captured identity against a later walk of the same tree.

    An export is judged against the whole live surface rather than against its
    own module, which is what lets a move read as a move: the name resolving
    anywhere is enough to say it survived, and where it resolves is what makes
    the migration map.
    """
    homes = live.homes()
    commands = {*live.commands}
    held = {*captured.capabilities()}

    def answers(capability: Capability) -> list[str]:
        """Where the live tree answers for this capability, if anywhere."""
        match capability.kind:
            case CapabilityKind.COMMAND:
                return [capability.identity] if capability.identity in commands else []
            case CapabilityKind.EXPORT:
                return homes.get(capability.identity, [])

    return Divergence(
        disappeared=[
            capability
            for capability in captured.capabilities()
            if not answers(capability)
        ],
        relocated=[
            Relocation(capability=capability, homes=found)
            for capability in captured.capabilities()
            if (found := answers(capability))
            and capability.location
            and capability.location not in found
        ],
        arrived=[
            capability for capability in live.capabilities() if capability not in held
        ],
    )
