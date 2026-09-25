"""Accept destination repository policy bytes under one launch's explicit grants."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypeGuard, get_args

import sh
from pydantic import BaseModel

from lup.execution.shell import git
from lup.policy.assets.host import (
    contents_digest,
    policy_snapshot_contents,
    policy_snapshot_digest,
)
from lup.sandbox.rail import AccessibleRoot, Lease, repository_layout, sibling_worktrees

PolicyRuntime = Literal["claude", "codex"]
"""A native runtime a checkout generates a destination evaluator for.

Closed rather than any string, because the name is spelled into a path --
``.{runtime}/plugins`` beneath the checkout -- and a string arriving from a
command line or a ledger could spell a directory outside it. Declared as a
plain alias because the command line takes it as a choice, and the CLI library
reads a ``Literal`` but not a ``type`` statement wrapping one.
"""


def policy_runtime(name: str) -> TypeGuard[PolicyRuntime]:
    """Whether a name is one of the runtimes a destination evaluator exists for."""
    return name in get_args(PolicyRuntime)


def evaluator_source(checkout: Path, runtime: PolicyRuntime) -> Path:
    """The one generated tree holding a checkout's evaluator for a runtime.

    Refused, saying what to do, where there is not exactly one, and where the
    one there is is not the checkout's own: a tree resolving outside the
    checkout, or reached through a symlink inside it, holds bytes the checkout
    does not, and accepting it would run them as the checkout's policy.
    """
    candidates = list(
        (checkout / f".{runtime}" / "plugins").glob(
            "*/hooks/scripts/policy_evaluator.py"
        )
    )
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one generated {runtime} destination policy evaluator "
            f"in {checkout}; found {len(candidates)}. Run "
            "`uv run lup-devtools harness generate all` there, then refresh "
            "this launch's accepted policy snapshot."
        )
    source = candidates[0].parent.parent
    if not source.resolve().is_relative_to(checkout.resolve()):
        raise ValueError(
            f"Destination policy source {source} resolves to {source.resolve()}, "
            f"outside {checkout}; only a tree the checkout itself holds is accepted"
        )
    if any(path.is_symlink() for path in [source, *source.parents]):
        raise ValueError(f"Destination policy source has a symlink: {source}")
    return source


def captured_policy(source: Path) -> dict[str, bytes]:
    """One evaluator's files as bytes held in memory, read so they describe one state.

    Everything after this reads the held bytes and never the checkout again:
    what is hashed, what is shown and what is written as the snapshot are one
    set of bytes. Read twice and compared, so a tree caught mid-write is
    refused rather than held as a mixture no generation wrote.
    """
    first = policy_snapshot_contents(source)
    if policy_snapshot_contents(source) != first:
        raise ValueError(f"{source} changed while it was read; run the refresh again")
    return first


class DestinationPolicy(BaseModel, frozen=True, extra="forbid"):
    """A checkout and evaluator the operator's launch explicitly made reachable."""

    protocol: Literal[1] = 1
    runtime: PolicyRuntime | Literal[""] = ""
    repository: str
    checkout: str
    writable_roots: list[str]
    read_only_roots: list[str]
    source: str = ""
    snapshot: str = ""
    digest: str = ""
    error: str = ""

    def accepted(
        self, root: Path, runtime: str, shown: dict[str, bytes] | None = None
    ) -> "DestinationPolicy":
        """Write held source bytes into a content-addressed launch snapshot.

        ``runtime`` arrives from a launch or a ledger, and it is spelled into
        the path the evaluator is looked for at, so a name that is not a
        runtime is refused before anything is read.

        ``shown`` is the bytes an operator was shown, where they were: those
        are what the snapshot is written from, and the checkout is not read
        again, so no change made after the showing -- nor one made and undone
        -- can put other bytes in its place. Unshown, the source is captured
        once here, the same way.
        """
        if not policy_runtime(runtime):
            return self.model_copy(
                update={
                    "error": (
                        f"{runtime!r} is not a runtime a destination policy is "
                        f"generated for; name one of {', '.join(get_args(PolicyRuntime))}"
                    )
                }
            )
        try:
            source = evaluator_source(Path(self.checkout), runtime)
        except ValueError as error:
            return self.model_copy(update={"error": str(error), "runtime": runtime})
        try:
            contents = captured_policy(source) if shown is None else shown
            digest = contents_digest(contents)
            destination = root / ".lup" / "policy-snapshots" / digest
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                with TemporaryDirectory(
                    prefix=".accept-", dir=destination.parent
                ) as area:
                    staged = Path(area) / "revision"
                    for name, content in contents.items():
                        copied = staged / name
                        copied.parent.mkdir(parents=True, exist_ok=True)
                        copied.write_bytes(content)
                    if policy_snapshot_digest(staged) != digest:
                        raise ValueError(
                            f"The snapshot of {source} did not keep the bytes held"
                        )
                    try:
                        staged.rename(destination)
                    except OSError:
                        if not destination.is_dir():
                            raise
            if policy_snapshot_digest(destination) != digest:
                raise ValueError(
                    f"Accepted destination snapshot is corrupt: {destination}"
                )
        except (OSError, ValueError) as error:
            return self.model_copy(
                update={"source": str(source), "error": str(error), "runtime": runtime}
            )
        return self.model_copy(
            update={
                "source": str(source),
                "runtime": runtime,
                "snapshot": str(destination),
                "digest": digest,
                "error": "",
            }
        )


class GrantedCheckout(BaseModel, frozen=True):
    """The exact directory grant and the Git worktree that owns it."""

    checkout: Path
    scope: Path
    writable: bool


class RepositoryPolicyAuthority(BaseModel, frozen=True, extra="forbid"):
    """An explicitly mounted bare repository's scope for later worktree acceptance."""

    repository: str
    root: str
    runtime: PolicyRuntime


def destination_authorities(
    accessible: list[AccessibleRoot], runtime: str
) -> list[RepositoryPolicyAuthority]:
    """Retain original explicit repository roots, never mounts inferred from Git.

    None for a launch whose runtime generates no destination evaluator: every
    row would name a tree a refresh could never accept.
    """
    if not policy_runtime(runtime):
        return []

    def authority(declared: AccessibleRoot) -> RepositoryPolicyAuthority | None:
        if not declared.writable or not declared.path.is_dir():
            return None
        try:
            bare = git.out(
                "-C", str(declared.path), "rev-parse", "--is-bare-repository"
            ).strip()
            if bare != "true":
                return None
            layout = repository_layout(declared.path)
        except sh.ErrorReturnCode:
            return None
        return RepositoryPolicyAuthority(
            repository=str(layout.common.resolve()),
            root=str(declared.path.resolve()),
            runtime=runtime,
        )

    return [row for declared in accessible if (row := authority(declared)) is not None]


def granted_checkouts(root: AccessibleRoot) -> list[GrantedCheckout]:
    """Resolve a named directory through Git, without scanning unrelated children."""
    path = root.path.resolve()
    if not path.is_dir():
        return []
    try:
        layout = repository_layout(path)
        bare = git.out("-C", str(path), "rev-parse", "--is-bare-repository").strip()
        if bare == "true":
            return [
                GrantedCheckout(
                    checkout=checkout.resolve(),
                    scope=checkout.resolve(),
                    writable=root.writable,
                )
                for checkout in sibling_worktrees(path)
                if (checkout / ".git").exists()
                and repository_layout(checkout).common.resolve()
                == layout.common.resolve()
            ]
        checkout = Path(
            git.out("-C", str(path), "rev-parse", "--show-toplevel").strip()
        ).resolve()
        return [GrantedCheckout(checkout=checkout, scope=path, writable=root.writable)]
    except sh.ErrorReturnCode:
        return []


def accept_destination_policies(
    root: Path,
    accessible: list[AccessibleRoot],
    lease: Lease,
    runtime: str,
) -> list[DestinationPolicy]:
    """Record exact repository identities separately from broad execution mounts."""
    grants = [grant for declared in accessible for grant in granted_checkouts(declared)]
    return [
        DestinationPolicy(
            repository=str(repository_layout(checkout).common.resolve()),
            checkout=str(checkout),
            writable_roots=sorted(
                {
                    str(grant.scope)
                    for grant in grants
                    if grant.checkout == checkout and grant.writable
                }
            ),
            read_only_roots=sorted(
                {
                    *[
                        str(grant.scope)
                        for grant in grants
                        if grant.checkout == checkout
                        and not grant.writable
                        and not any(
                            other.checkout == checkout
                            and other.scope == grant.scope
                            and other.writable
                            for other in grants
                        )
                    ],
                    *[str(path.resolve()) for path in lease.read_only],
                }
            ),
        ).accepted(root.resolve(), runtime)
        for checkout in sorted({grant.checkout for grant in grants})
    ]
