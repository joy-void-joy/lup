"""Accept changed destination policy bytes for a live, already granted launch."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import typer
import sh
from pydantic import BaseModel, TypeAdapter, ValidationError

from lup.devtools.harness.preflight import NONCE_VARIABLE, ledger_path
from lup.execution.shell import git
from lup.policy.snapshots import DestinationPolicy, RepositoryPolicyAuthority
from lup.sandbox.rail import repository_layout


class PolicyLaunchLedger(BaseModel, extra="allow"):
    """The grant field plus boundary measurements preserved without reinterpretation."""

    destination_policies: list[str] = []
    destination_authorities: list[str] = []
    writable_roots: list[str] = []
    read_only_roots: list[str] = []
    runtime: list[str] = []

    def grant_for(
        self, checkout: Path, launch: Path, runtime: str = ""
    ) -> DestinationPolicy:
        """A checkout no grant named, reached through an authority the launch holds.

        Two authorities reach one. An explicitly mounted writable bare
        repository covers the worktrees beneath that mount. The launch
        checkout's own repository covers every worktree of it: the lease that
        opens a session mounts that repository's shared directory writable, so
        a worktree the session cuts there is one it could already write, and
        whose edits were already judged as that repository's code, by the
        policy the session launched with. Accepting it changes which of that
        repository's generated policies judges those edits and nothing about
        what the launch may write -- which is why, under either authority, the
        deepest measured root over the checkout has to hold it writable.

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
        mounted = [
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
        match sorted({*self.runtime, *mounted} - {""}), runtime:
            case [], "":
                raise ValueError(
                    "This launch recorded no runtime; name the one it opened with "
                    "--runtime claude or --runtime codex"
                )
            case [], named:
                launched = named
            case [recorded], named if named in ("", recorded):
                launched = recorded
            case [recorded], named:
                raise ValueError(
                    f"This launch opened {recorded}; --runtime {named} names another runtime"
                )
            case recorded, _:
                raise ValueError(
                    f"This launch's grants name more than one runtime ({', '.join(recorded)}); "
                    "changing repository access requires another launch"
                )
        return DestinationPolicy(
            repository=repository,
            checkout=str(checkout),
            runtime=launched,
            writable_roots=[str(checkout)],
            read_only_roots=self.read_only_roots,
        )


def refresh_destination_policy(
    root: Path, nonce: str, repository: Path, runtime: str = ""
) -> DestinationPolicy:
    """Replace one accepted snapshot without extending that launch's authority.

    ``root`` is the launch checkout, whose ledger this rewrites and whose
    repository is one of the two authorities a checkout no grant named can be
    reached through; ``runtime`` is read only where the ledger cannot say.
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
    if runtime and runtime != existing.runtime:
        raise ValueError(
            f"Launch {nonce} accepted {checkout} for {existing.runtime}; "
            f"--runtime {runtime} names another runtime"
        )
    accepted = existing.accepted(root.resolve(), existing.runtime)
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
    root: Path, nonce: str, repository: Path, runtime: str = ""
) -> None:
    """Report the exact destination revision accepted by the operator."""
    try:
        accepted = refresh_destination_policy(root, nonce, repository, runtime)
    except (OSError, ValueError, ValidationError, sh.ErrorReturnCode) as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(
        f"Accepted {accepted.checkout} policy {accepted.digest} for launch {nonce}"
    )
