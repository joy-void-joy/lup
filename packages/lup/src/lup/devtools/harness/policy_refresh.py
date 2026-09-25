"""Accept changed destination policy bytes for a live, already granted launch."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

import typer
import sh
from pydantic import BaseModel, TypeAdapter, ValidationError

from lup.devtools.harness.preflight import NONCE_VARIABLE, ledger_path
from lup.execution.shell import git
from lup.policy.assets.host import (
    policy_data_literals,
    policy_snapshot_digest,
    policy_snapshot_files,
    worktree_refusal,
)
from lup.policy.snapshots import (
    DestinationPolicy,
    PolicyRuntime,
    RepositoryPolicyAuthority,
    evaluator_source,
)
from lup.sandbox.rail import Lease, lease_for, repository_layout
from lup.types import JsonObject, JsonValue


class PolicyLaunchLedger(BaseModel, extra="allow"):
    """The grant field plus boundary measurements preserved without reinterpretation.

    The runtime is read as the closed vocabulary rather than as text: it is
    spelled into the path an evaluator is accepted from, and the ledger is a
    file in the checkout the session works in.
    """

    destination_policies: list[str] = []
    destination_authorities: list[str] = []
    writable_roots: list[str] = []
    read_only_roots: list[str] = []
    runtime: list[PolicyRuntime] = []

    def grant_for(
        self, checkout: Path, launch: Path, runtime: PolicyRuntime | None = None
    ) -> DestinationPolicy:
        """A checkout no grant named, reached through an authority the launch holds.

        Two authorities reach one. An explicitly mounted writable bare
        repository covers the worktrees beneath that mount. The launch
        checkout's own repository covers the worktrees its own lease holds:
        the lease that opens a session mounts that repository's shared
        directory writable, so a worktree the session cuts there is one it
        could already write, and whose edits were already judged as that
        repository's code, by the policy the session launched with. Accepting
        it changes which of that repository's generated policies judges those
        edits and nothing about what the launch may write -- which is why,
        under either authority, the deepest measured root over the checkout
        has to hold it writable.

        Either way the checkout has to be a worktree Git registered, and
        neither the launch checkout nor one nested inside a checkout of its
        repository: :func:`~lup.policy.assets.host.worktree_refusal` says
        which of those failed, and why none of it proves where a worktree came
        from.

        The evaluator accepted is the one generated for the runtime the launch
        opened. The ledger records it; ``runtime`` names it for a ledger that
        records none, and must agree with whichever the ledger does record.
        """
        if not checkout.is_dir():
            raise ValueError(
                f"No recorded writable repository authority covers {checkout}"
            )
        try:
            top = Path(
                git.out("-C", str(checkout), "rev-parse", "--show-toplevel").strip()
            ).resolve()
        except sh.ErrorReturnCode as error:
            raise ValueError(f"{checkout} is not a Git worktree") from error
        if top != checkout:
            raise ValueError(f"Use the canonical Git worktree root: {top}")
        repository = str(repository_layout(checkout).common.resolve())
        mounted: list[PolicyRuntime] = [
            row.runtime
            for row in (
                RepositoryPolicyAuthority.model_validate_json(encoded)
                for encoded in self.destination_authorities
            )
            if row.repository == repository and checkout.is_relative_to(Path(row.root))
        ]
        own = repository == str(repository_layout(launch).common.resolve())
        covering = {
            Path(path): writable
            for paths, writable in (
                (self.writable_roots, True),
                (self.read_only_roots, False),
            )
            for path in paths
            if checkout.is_relative_to(Path(path))
        }
        deepest = max(covering, key=lambda path: len(path.parts), default=None)
        if (not mounted and not own) or deepest is None or not covering[deepest]:
            raise ValueError(
                f"No recorded writable repository authority covers {checkout}; changing repository access requires another launch"
            )
        refusal = worktree_refusal(str(checkout), str(launch))
        if refusal:
            raise ValueError(refusal)
        if not mounted and not self.leased(checkout, launch):
            raise ValueError(
                f"{checkout} lies outside the launch repository's own lease: "
                f"neither the shared directory {repository} nor a checkout the "
                "launch leased holds it, so it is writable only through some "
                "other mount, and a mount grants no policy authority. Cut the "
                f"worktree under {repository}, or name it with --mount at the "
                "next launch"
            )
        recorded: list[PolicyRuntime] = [*self.runtime, *mounted]
        if any(name != recorded[0] for name in recorded):
            raise ValueError(
                "This launch's grants name more than one runtime "
                f"({', '.join(dict.fromkeys(recorded))}); "
                "changing repository access requires another launch"
            )
        launched = recorded[0] if recorded else runtime
        if launched is None:
            raise ValueError(
                "This launch recorded no runtime; name the one it opened with "
                "--runtime claude or --runtime codex"
            )
        if runtime is not None and runtime != launched:
            raise ValueError(
                f"This launch opened {launched}; --runtime {runtime} names another runtime"
            )
        return DestinationPolicy(
            repository=repository,
            checkout=str(checkout),
            runtime=launched,
            writable_roots=[str(checkout)],
            read_only_roots=self.read_only_roots,
        )

    def leased(self, checkout: Path, launch: Path) -> bool:
        """Whether the launch repository's own lease holds a checkout.

        Recomputed from Git here rather than read back from the ledger the
        session's checkout holds: the checkout, every worktree Git lists, and
        the shared directory writable, its `config` and `hooks/` read-only.
        Git lists a registered worktree wherever it sits, so the lease would
        hold any one of them as a mount of its own; what counts is a root
        other than the checkout's own registration -- the shared directory,
        where the session cuts its worktrees -- or the checkout itself where
        the launch measured it writable as a mount of its own, a sibling that
        was there when the session started. A worktree reachable only through
        some other writable mount lies outside it.
        """
        own = lease_for(launch)
        roots = {root.resolve(): inside for root, inside in own.writable.items()}
        beneath = Lease(
            writable={
                root: inside for root, inside in roots.items() if root != checkout
            },
            read_only={
                root.resolve(): inside for root, inside in own.read_only.items()
            },
        )
        measured = [Path(item).resolve() for item in self.writable_roots]
        return beneath.writable_at(checkout) or (
            checkout in roots and checkout in measured
        )


class ConstantChange(BaseModel, frozen=True):
    """One named constant of a generated policy, as the entries accepting it trades."""

    name: str
    removed: list[str]
    added: list[str]


class PolicyPreview(BaseModel, frozen=True):
    """What accepting a checkout's generated policy changes, shown before anything is.

    The data is read from both sides' ``policy_data.py`` without running
    either -- :func:`~lup.policy.assets.host.policy_data_literals` -- because
    the side being accepted was written by the session asking for it. The
    code beside that data is compared rather than read: every evaluator file
    whose bytes differ is named, because accepting runs it.
    """

    checkout: str
    runtime: PolicyRuntime
    digest: str
    judging: str
    changes: list[ConstantChange]
    code: list[str]

    def lines(self) -> list[str]:
        """The preview as the operator reads it, one compact line per entry."""
        entries = [
            line
            for change in self.changes
            for line in [
                f"  {change.name}",
                *[f"    - {entry}" for entry in change.removed],
                *[f"    + {entry}" for entry in change.added],
            ]
        ]
        code = [
            "  Code that runs once accepted, whose bytes differ:",
            *[f"    {name}" for name in self.code],
        ]
        return [
            f"Accepting the {self.runtime} policy {self.checkout} generates "
            f"({self.digest}),",
            f"in place of the one that judges it now ({self.judging}):",
            *(entries or ["  No constant differs."]),
            *(code if self.code else ["  No code differs."]),
        ]


class RefreshDeclined(Exception):
    """The operator was shown what accepting would change and said no."""


def entry_line(entry: JsonValue) -> str:
    """One entry of a generated constant, on one line.

    A row shows the fields that say something, each as its JSON value. Every
    row of a table carries the same fields, so one left out reads as empty,
    and a flag turned on or a reason filled in shows as the field appearing.
    """
    match entry:
        case dict():
            return " ".join(
                f"{key}={json.dumps(field, ensure_ascii=False)}"
                for key, field in entry.items()
                if not (field is None or field is False or field in ("", [], {}))
            )
        case _:
            return json.dumps(entry, ensure_ascii=False)


def constant_entries(value: JsonValue) -> list[str]:
    """Every entry a generated constant holds, one compact line each.

    A table's entries are its rows. A table of tables -- the anti-pattern
    rows keyed by suffix -- lists each row under its key, so a rule retired
    for one suffix reads apart from the same rule kept for another. Anything
    else is the one entry it is.
    """
    match value:
        case list():
            return [entry_line(item) for item in value]
        case dict() if value and all(isinstance(rows, list) for rows in value.values()):
            return [
                f"{key}: {entry_line(row)}"
                for key, rows in value.items()
                if isinstance(rows, list)
                for row in rows
            ]
        case _:
            return [entry_line(value)]


def constant_change(
    name: str, judging: JsonObject, accepting: JsonObject
) -> ConstantChange:
    """One constant's entries the accepted policy drops, and the ones it gains."""
    before = constant_entries(judging[name]) if name in judging else []
    after = constant_entries(accepting[name]) if name in accepting else []
    kept = {line for line in after}
    held = {line for line in before}
    return ConstantChange(
        name=name,
        removed=[line for line in before if line not in kept],
        added=[line for line in after if line not in held],
    )


def policy_preview(
    existing: DestinationPolicy, root: Path, runtime: PolicyRuntime
) -> PolicyPreview:
    """What accepting ``existing``'s generated policy changes for the launch at ``root``.

    Compared with the policy that judges the checkout now: the snapshot its
    grant accepted, where it holds one, and otherwise the launch checkout's
    own generated tree, whose policy judges every worktree no grant names.
    Its digest is read before anything else and again after, so the preview
    describes one set of bytes, and acceptance takes exactly those.
    """
    source = evaluator_source(Path(existing.checkout), runtime)
    digest = policy_snapshot_digest(source)
    snapshot = Path(existing.snapshot) if existing.snapshot else None
    judging = (
        snapshot
        if snapshot is not None and snapshot.is_dir()
        else evaluator_source(root, runtime)
    )
    adapter = TypeAdapter(JsonObject)
    accepting = adapter.validate_python(
        policy_data_literals(source / "runtime" / "policy_data.py")
    )
    held = adapter.validate_python(
        policy_data_literals(judging / "runtime" / "policy_data.py")
    )
    data = "runtime/policy_data.py"
    theirs = {
        item.relative_to(source).as_posix(): item.read_bytes()
        for item in policy_snapshot_files(source)
    }
    ours = {
        item.relative_to(judging).as_posix(): item.read_bytes()
        for item in policy_snapshot_files(judging)
    }
    if policy_snapshot_digest(source) != digest:
        raise ValueError(f"{source} changed while it was read; run the refresh again")
    changes = [
        constant_change(name, held, accepting)
        for name in dict.fromkeys([*accepting, *held])
    ]
    return PolicyPreview(
        checkout=existing.checkout,
        runtime=runtime,
        digest=digest,
        judging=str(judging),
        changes=[change for change in changes if change.removed or change.added],
        code=[
            *[
                f"{name}: {'changed' if name in ours else 'added'}"
                for name, content in theirs.items()
                if name != data and (name not in ours or ours[name] != content)
            ],
            *[f"{name}: removed" for name in ours if name not in theirs],
        ],
    )


def refresh_destination_policy(
    root: Path,
    nonce: str,
    repository: Path,
    approve: Callable[[PolicyPreview], bool],
    runtime: PolicyRuntime | None = None,
) -> DestinationPolicy:
    """Replace one accepted snapshot without extending that launch's authority.

    ``root`` is the launch checkout, whose ledger this rewrites and whose
    repository is one of the two authorities a checkout no grant named can be
    reached through; ``runtime`` is read only where the ledger cannot say.

    ``approve`` is shown what accepting would change before anything is
    written. Declined, it raises :class:`RefreshDeclined` with the ledger and
    the snapshot store as they were; approved, it accepts the bytes it was
    shown and no others.
    """
    # lup: ignore[os-environ] — reject an operator-only action inherited by the requesting session
    if os.environ.get(NONCE_VARIABLE):
        raise ValueError(
            "Policy snapshot refresh requires an independent operator terminal outside "
            "the agent session. The requesting session cannot accept replacement policy."
        )
    if not nonce or Path(nonce).name != nonce or nonce in {".", ".."}:
        raise ValueError("The launch nonce must be a single ledger name")
    path = ledger_path(root, nonce)
    adapter = TypeAdapter(dict[str, list[str]])
    captured = path.read_text(encoding="utf-8")
    document = PolicyLaunchLedger.model_validate(adapter.validate_json(captured))
    policies = [
        DestinationPolicy.model_validate_json(row)
        for row in document.destination_policies
    ]
    checkout = str(repository.resolve())
    matches = [row for row in policies if row.checkout == checkout]
    if len(matches) > 1:
        raise ValueError(
            f"Launch {nonce} has no unique explicit policy grant for {checkout}; "
            "changing repository access requires another launch."
        )
    existing = (
        matches[0]
        if matches
        else document.grant_for(repository.resolve(), root.resolve(), runtime)
    )
    if str(repository_layout(repository).common.resolve()) != existing.repository:
        raise ValueError("Destination Git repository identity changed; launch again")
    if not existing.runtime:
        raise ValueError("Launch grant has no runtime identity; launch again")
    if runtime is not None and runtime != existing.runtime:
        raise ValueError(
            f"Launch {nonce} accepted {checkout} for {existing.runtime}; "
            f"--runtime {runtime} names another runtime"
        )
    preview = policy_preview(existing, root.resolve(), existing.runtime)
    if not approve(preview):
        raise RefreshDeclined(checkout)
    accepted = existing.accepted(root.resolve(), existing.runtime, preview.digest)
    if accepted.error:
        raise ValueError(accepted.error)
    document.destination_policies = [
        (accepted if row.checkout == checkout else row).model_dump_json()
        for row in policies
    ] + ([accepted.model_dump_json()] if not matches else [])
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as staged:
        json.dump(document.model_dump(), staged, indent=2)
        replacement = Path(staged.name)
    if path.read_text(encoding="utf-8") != captured:
        replacement.unlink()
        raise ValueError("The launch ledger changed during refresh; read it and retry")
    replacement.replace(path)
    return accepted


def refresh_command(
    root: Path,
    nonce: str,
    repository: Path,
    runtime: PolicyRuntime | None = None,
    yes: bool = False,
) -> None:
    """Show the operator what a refresh changes, and accept it once they agree.

    The preview is printed either way, so what ``--yes`` accepted is on the
    record too; the flag skips only the question.
    """

    def approve(preview: PolicyPreview) -> bool:
        """Show what accepting changes, then take the operator's answer."""
        typer.echo("\n".join(preview.lines()))
        return yes or typer.confirm("Accept this policy for the launch?")

    try:
        accepted = refresh_destination_policy(root, nonce, repository, approve, runtime)
    except RefreshDeclined:
        typer.echo(
            f"Nothing accepted: launch {nonce} judges {repository.resolve()} "
            "as it did before."
        )
        raise typer.Exit(1) from None
    except (OSError, ValueError, ValidationError, sh.ErrorReturnCode) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(
        f"Accepted {accepted.checkout} policy {accepted.digest} for launch {nonce}"
    )
