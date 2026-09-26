"""``lup-launch``: open a session only after its operator approved what the launch runs.

Installed as a tool from a pinned lup, and run instead of ``uv run
lup-devtools harness <runtime>``::

    uv tool install 'lup[web] @ git+https://github.com/joy-void-joy/lup@<commit>#subdirectory=packages/lup'
    lup-launch claude [ARGS...]

Everything after the runtime is handed to the project's own ``harness
<runtime>`` untouched. ``lup-launch run <command...>`` hands any other
``lup-devtools`` command over the same way -- ``lup-launch run setup gemini``
-- for the host commands that must not run unreviewed checkout code either:
the setup wizard above all, which asks for secrets.

Before any of the checkout's code runs, the launcher reads the host zone
(:mod:`lup.trust.zone`) and compares it with what this machine's operator
approved (:mod:`lup.trust.record`). The same tree launches at once. Anything
else -- a first launch, an edit, a commit checked out, a change arriving in a
sibling worktree, a rewritten machine registry -- is a question in the
launcher's own review inbox and at the terminal (:mod:`lup.trust.answer`),
and nothing runs until it is answered. A rejection ends the launch there; an
approval is recorded on the host and the project's launch is handed an export
of exactly what was approved (:mod:`lup.trust.handoff`).

One step runs the approved code before the launch proper: after a question is
answered, the launcher runs the project's generation from the export and
records the tree it leaves as approved too, when everything it changed is
vouched for by the generator's own ownership proof. Without it a project
whose generated trees are read-only in its sessions would ask twice for every
change to its sources: once for the change, and again at the next launch for
the files regenerating it rewrote.
"""

import hashlib
import os
import shlex
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from lup.devtools.dev.questions import captured_preview
from lup.devtools.launcher import CONSOLE_SCRIPT
from lup.harness.ownership import OWNERSHIP_FILENAME, OwnershipManifest
from lup.policy.relay import PersistentQuestion, QuestionRelay
from lup.trust.answer import Preview, asked_and_answered
from lup.trust.handoff import Executor, Runner, executed, handoff, materialized, ran
from lup.trust.objects import ObjectStore
from lup.trust.record import Approval, StateLocation, TrustRecord, TrustState
from lup.trust.review import (
    TrustEvidence,
    TrustPreview,
    asked_once,
    baseline,
    freed,
    launch_question,
    question_reason,
)
from lup.trust.zone import (
    FreeZones,
    HostZone,
    LiveCheckout,
    TrustError,
    declared_free_zones,
    host_zone,
)
from lup.types import EnvVars

type Asker = Callable[
    [PersistentQuestion, QuestionRelay, Preview, Path], PersistentQuestion
]
"""What obtains the operator's answer to one launch question; replaced in tests."""

FREE_ZONE_DECLARATION = PurePosixPath("pyproject.toml")
"""The file whose ``[tool.lup.trust]`` table declares the free zones."""

REGENERATION = ["harness", "generate", "all"]
"""What the launcher runs from an approved export before handing the launch off."""


def declared_in(
    zone: HostZone, store: ObjectStore, manifest: PurePosixPath = FREE_ZONE_DECLARATION
) -> FreeZones:
    """The free zones the zone's own manifest declares, read from the snapshot.

    From the stored copy rather than the file on disk, so what is compared and
    recorded is the declaration inside the tree being approved -- not a second
    reading of a file a session may have rewritten since it was hashed.
    """
    entry = zone.at(manifest)
    if entry is None or entry.mode not in ("100644", "100755"):
        return FreeZones()
    return declared_free_zones(store.read(entry.oid, "blob"))


def proofs(zone: HostZone, store: ObjectStore) -> dict[PurePosixPath, str]:
    """Every generated file the zone's ownership proofs vouch for, with its digest.

    A proof that does not parse vouches for nothing, which is the safe way to
    be wrong: its files are then asked about at the next launch.
    """

    def vouched_by(content: bytes) -> dict[PurePosixPath, str]:
        try:
            proof = OwnershipManifest.model_validate_json(content)
        except ValidationError:
            return {}
        return {
            PurePosixPath(owned.path.as_posix()): owned.sha256 for owned in proof.files
        }

    return {
        path: digest
        for entry in zone.entries
        if entry.path.name == OWNERSHIP_FILENAME and entry.mode in ("100644", "100755")
        for path, digest in vouched_by(store.read(entry.oid, "blob")).items()
    }


def generated_only(before: HostZone, after: HostZone, store: ObjectStore) -> bool:
    """Whether everything that differs between two zones is the generator's own work.

    A changed or added file counts only where the regenerated proof names it
    with exactly the digest of the bytes now there; a removed file only where
    the approved proof owned it; a proof itself only where the approved tree
    already held one at that path. Anything else changed in the window -- by
    a session writing while generation ran, say -- keeps the tree unapproved,
    and the next launch asks about it.
    """
    earlier = {entry.path: entry for entry in before.entries}
    later = {entry.path: entry for entry in after.entries}
    owned_after = proofs(after, store)
    owned_before = proofs(before, store)

    def vouched(path: PurePosixPath) -> bool:
        if path.name == OWNERSHIP_FILENAME:
            return path in earlier
        if path not in later:
            return path in owned_before
        entry = later[path]
        if entry.mode not in ("100644", "100755") or path not in owned_after:
            return False
        digest = hashlib.sha256(store.read(entry.oid, "blob")).hexdigest()
        return digest == owned_after[path]

    return all(
        vouched(path)
        for path in {*earlier, *later}
        if (earlier[path] if path in earlier else None)
        != (later[path] if path in later else None)
    )


def zones_to_read(
    record: TrustRecord,
    checkout: LiveCheckout,
    manifest: PurePosixPath = FREE_ZONE_DECLARATION,
) -> FreeZones:
    """The free zones this launch reads the checkout under.

    The approved ones wherever anything was approved. Before that there are
    none to trust, and the checkout's own declaration is taken -- it is shown
    in the first question, and becomes the approved list only once answered.
    """
    if record.free is not None:
        return FreeZones(free=record.free)
    live = checkout.root / manifest
    return declared_free_zones(live.read_bytes()) if live.is_file() else FreeZones()


def operator_approval(
    checkout: LiveCheckout,
    state: TrustState,
    store: ObjectStore,
    zone: HostZone,
    read_under: FreeZones,
    declared: FreeZones,
    named: str,
    ask: Asker,
    console: Console,
) -> HostZone:
    """Ask about one unapproved zone, record the answer, and return what may launch.

    What may launch is the zone under the free zones the approved tree itself
    declares, which is the zone as read when those did not change. Where the
    approval widened them, the paths newly freed are taken out: they were
    shown, and from now on they are not reviewed.
    """
    record = state.read()
    if record.free is None and declared != read_under:
        raise TrustError(
            "pyproject.toml changed while it was being read, so the free zones it "
            "declares are not the ones the zone was read under; launch again."
        )
    base_tree = record.base_for(checkout.root)
    reason = question_reason(
        named,
        checkout.root,
        baseline(store, base_tree),
        zone,
        freed(declared, record.free),
    )
    evidence = TrustEvidence(
        worktree=str(checkout.root),
        runtime=named,
        base=base_tree,
        current=zone.tree,
        free=read_under.spelled(),
        declared=declared.spelled(),
    )
    relay = state.relay()
    question = asked_once(relay, launch_question(checkout.root, evidence, reason))
    answered = ask(
        question,
        relay,
        TrustPreview(checkout.root, store, otherwise=captured_preview),
        checkout.root,
    )
    if answered.state != "approved":
        note = answered.answer.note if answered.answer is not None else ""
        console.print(
            f"Launch rejected; nothing from {checkout.root} ran."
            + (f" Note: {note}" if note else ""),
            markup=False,
        )
        raise typer.Exit(1)
    narrowed = zone.without(declared, store)
    approvals = [
        Approval(tree=zone.tree, question=answered.id),
        Approval(tree=narrowed.tree, by="free zones", question=answered.id),
    ]
    with state.locked():
        state.write(
            state.read().approved(
                approvals, checkout.root, narrowed.tree, declared.free
            )
        )
    return narrowed


def regenerated_approval(
    checkout: LiveCheckout,
    state: TrustState,
    store: ObjectStore,
    approved: HostZone,
    zones: FreeZones,
    inherited: EnvVars,
    regenerate: Runner,
    console: Console,
    command: list[str] = REGENERATION,
) -> str:
    """Run the approved generation from its export, and approve the tree it leaves.

    Approved only where the generator vouches for every file that moved; the
    tree otherwise stays as approved, and the launch that follows regenerates
    and reports on its own terms.
    """
    export = materialized(store, approved.tree, state.export(approved.tree))
    if not regenerate(handoff(state, export.path, checkout.root, command, inherited)):
        console.print(
            "The approved generation did not complete; the launch reports why.",
            markup=False,
        )
        return approved.tree
    after = host_zone(checkout, store, zones)
    if after.tree == approved.tree:
        return approved.tree
    if not generated_only(approved, after, store):
        console.print(
            "Generation left changes it does not vouch for; the next launch asks "
            "about them.",
            markup=False,
        )
        return approved.tree
    with state.locked():
        state.write(
            state.read().approved(
                [Approval(tree=after.tree, by="regeneration")],
                checkout.root,
                after.tree,
                zones.free,
            )
        )
    return after.tree


def trusted_launch(
    start: Path,
    command: list[str],
    named: str,
    ask: Asker,
    console: Console,
    inherited: EnvVars,
    execute: Executor = executed,
    regenerate: Runner = ran,
    location: StateLocation | None = None,
) -> None:
    """Establish trust in the checkout at ``start``, then hand ``command`` to its launch.

    ``command`` is what the project's CLI is given after its own name --
    ``["harness", "claude", ...]``, or ``["setup", "gemini"]`` -- and
    ``named`` is what the question says answering runs: the runtime, or the
    command. Nothing of the checkout is executed before ``execute`` is
    called, and ``execute`` is never called for a zone nobody approved.
    """
    checkout = LiveCheckout.at(start, inherited)
    state = TrustState.of(checkout.identity(), checkout.common, location)
    store = state.store()
    record = state.read()
    read_under = zones_to_read(record, checkout)
    zone = host_zone(checkout, store, read_under)
    if record.approves(zone.tree):
        console.print(
            f"Host zone unchanged since its approval ({zone.tree}).", markup=False
        )
        launched = zone.tree
        kept = read_under
    else:
        kept = declared_in(zone, store)
        narrowed = operator_approval(
            checkout, state, store, zone, read_under, kept, named, ask, console
        )
        launched = regenerated_approval(
            checkout, state, store, narrowed, kept, inherited, regenerate, console
        )
    with state.locked():
        state.write(state.read().approved([], checkout.root, launched, kept.free))
    export = materialized(store, launched, state.export(launched))
    for link in export.withheld:
        console.print(
            f"Withheld the link {link}: it points outside the approved tree.",
            markup=False,
        )
    execute(handoff(state, export.path, checkout.root, command, inherited))


def status(start: Path, console: Console, inherited: EnvVars) -> None:
    """Print what this machine approved for the checkout at ``start``."""
    checkout = LiveCheckout.at(start, inherited)
    state = TrustState.of(checkout.identity(), checkout.common)
    record = state.read()
    console.print(f"repository   {checkout.common}", markup=False)
    console.print(f"state        {state.root}", markup=False)
    console.print(
        "free zones   "
        + (
            ", ".join(FreeZones(free=record.free).spelled()) or "none"
            if record.free is not None
            else "nothing approved yet"
        ),
        markup=False,
    )
    for approval in record.approvals:
        console.print(
            f"approved     {approval.tree}  {approval.at:%Y-%m-%d %H:%M}  by {approval.by}",
            markup=False,
        )
    for launched in record.worktrees:
        console.print(
            f"launched     {launched.tree}  from {launched.worktree}", markup=False
        )


app = typer.Typer(
    add_completion=False,
    help="Launch a session only after approving what the launch runs on this machine.",
)


@app.command(
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
    }
)
def launch(
    context: typer.Context,
    runtime: Annotated[
        str | None,
        typer.Argument(
            help="The runtime to launch, as the project's `harness` command names it, "
            "or `run` and any `lup-devtools` command, such as `run setup`; "
            "everything after it is passed on unchanged"
        ),
    ] = None,
    root: Annotated[
        Path | None,
        typer.Option(help="The checkout to launch (default: the one enclosing here)"),
    ] = None,
    port: Annotated[
        int,
        typer.Option(
            min=0,
            max=65535,
            help="Loopback port for the review inbox (0: any free one)",
        ),
    ] = 0,
    open_page: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the review inbox in a browser"),
    ] = True,
    show_status: Annotated[
        bool,
        typer.Option(
            "--status", help="Print what this machine approved, and launch nothing"
        ),
    ] = False,
) -> None:
    """Review what a launch would run on this machine, then hand it to the project.

    ``lup-launch run <command...>`` is the same review over any other
    project command, run from the approved export with this terminal handed
    through -- ``lup-launch run setup gemini`` prompts for its key with the
    typing hidden, from code the operator approved.
    """
    console = Console()
    # lup: ignore[os-environ] — the launcher hands its own environment on to the
    # launch it starts, and reads git's variables only to drop them
    inherited = dict(os.environ)
    start = root if root is not None else Path.cwd()
    try:
        if show_status:
            status(start, console, inherited)
            return
        if runtime is None:
            raise typer.BadParameter(
                "name the runtime to launch, such as `claude`, or `run` and a "
                "devtools command, such as `run setup`"
            )
        match [runtime, *context.args]:
            case ["run"]:
                raise typer.BadParameter(
                    "name the devtools command to run, such as `lup-launch run setup`"
                )
            case ["run", *devtools]:
                command = devtools
                named = shlex.join([CONSOLE_SCRIPT, *devtools])
            case _:
                command = ["harness", runtime, *context.args]
                named = runtime

        def ask(
            question: PersistentQuestion,
            relay: QuestionRelay,
            preview: Preview,
            checkout: Path,
        ) -> PersistentQuestion:
            return asked_and_answered(
                question, checkout, relay, preview, console, port, open_page
            )

        trusted_launch(start, command, named, ask, console, inherited)
    except TrustError as error:
        console.print(str(error), markup=False)
        raise typer.Exit(2) from error
