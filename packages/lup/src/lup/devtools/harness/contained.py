"""Opening a native session inside the container the project declares.

The launcher's other half. :mod:`lup.harness.image` says what a container is
and how it starts; this says how a *launch* reaches one -- which image tag
this checkout answers to, whether it has been built, and what the lease under
the session mounts.

Why the checkout is a mount rather than a copy, and why it is mounted at its
own absolute path: a linked worktree's ``.git`` is a file holding an absolute
``gitdir:`` pointer into the repository's common directory, so a tree that
appeared anywhere else inside the container would be a checkout pointing at a
path that does not exist. :func:`lup.sandbox.rail.same_path` is the rule, and
this module is one of the two callers that has to honour it.

What this deliberately does not do is fall back to an uncontained launch when
the boundary cannot be built. A boundary that quietly is not there is the one
failure mode the design forbids, so a caller that asked to be contained and
cannot be gets a refusal naming what was missing, and the operator decides.
"""

import json
import os
from pathlib import Path

import sh
import typer

from lup.harness.credential import remote_rewrites
from lup.harness.egress import SessionEgress
from lup.harness.image import ContainerEngine, Image, detected_engine
from lup.harness.requirements import Manifest
from lup.runtime.login import ProviderLogin
from lup.sandbox.attribution import WRITE_REFUSAL_MARKERS
from lup.sandbox.rail import Lease, lease_for


def image_tag(root: Path) -> str:
    """The image this checkout answers to.

    Named for the repository rather than the worktree, because every worktree
    of one repository declares the same toolchain and building a layer per
    branch would pay the whole build cost for a name.
    """
    return f"lup-agent:{root.name}"


def state_volume_name(root: Path) -> str:
    """The volume carrying this project's container-side config home.

    Per repository for the same reason as the tag, and separate from the
    caches because it holds decisions rather than artifacts: the trust a
    fresh config home would otherwise discard, and the session state a
    ``--continue`` reopens.
    """
    return f"lup-cfg-{root.name}"


def image_present(tag: str, engine: ContainerEngine) -> bool:
    """Whether this tag already exists, asked of the engine rather than guessed."""
    try:
        sh.Command(engine.binary)("image", "inspect", tag)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return False
    return True


def running(name: str, engine: ContainerEngine) -> bool:
    """Whether a container by this name is up, asked of the engine.

    Asked rather than remembered, for the same reason :func:`image_present`
    is: the operator may have removed it between launches, another checkout
    of the same repository may have brought it up, and a launcher that kept
    its own record of either would be reading a file instead of the truth.
    """
    try:
        state = sh.Command(engine.binary)(
            "inspect", "--format", "{{.State.Running}}", name
        )
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return False
    return str(state).strip() == "true"


def start_egress(
    egress: SessionEgress, project: str, engine: ContainerEngine, root: Path
) -> None:
    """Bring up the internal network and the proxy bridged out of it.

    Idempotent, and idempotent one piece at a time rather than as a whole:
    the network can outlive a proxy the operator stopped, and a run that
    treated the pair as one fact would leave a session attached to a network
    with nothing on the far side of it -- which is the failure mode the
    filtered posture exists to avoid, arrived at by the launcher itself.

    The rendered configuration is written into the checkout's scratch
    directory rather than piped in, for the reason :func:`build_image` writes
    the Dockerfile there: what the proxy is enforcing should be readable as a
    file rather than reconstructed from a declaration and a memory of which
    version was running.
    """
    if not egress.filtered():
        return
    client = sh.Command(engine.binary)
    if not network_present(egress.network_name(project), engine):
        client(*egress.network_arguments(project))
    if running(egress.proxy_name(project), engine):
        return
    scratch = root / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    configuration = scratch / "egress.conf"
    configuration.write_text(egress.enforced().render())
    try:
        client(*egress.proxy_arguments(project, configuration))
        client(*egress.connect_arguments(project))
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter(
            f"Could not start {egress.proxy_name(project)}, so this session "
            "would open on an internal network with no way out of it. The "
            "policy it was given is at "
            f"{configuration}; open the session with --unsandboxed, or "
            "declare `mode='bridge'` on the image's egress to run without "
            "an egress boundary."
        ) from error


def record_boundary(lease: Lease, egress: SessionEgress, root: Path) -> None:
    """Write down what this session is confined by, for the gate that explains it.

    The mount table is a launch fact and the dispatcher that has to explain a
    refusal was compiled long before it. Nothing else bridges that: the
    dispatcher runs as a bare script with no way to ask the container runtime
    anything, and a refusal it cannot attribute reaches the agent as
    ``Read-only file system`` -- which is a broken disk, not a boundary, and
    is debugged as one.

    Written on every contained launch rather than once, because a lease
    changes when a sibling worktree appears or goes, and a stale table would
    attribute a refusal to a mount that is no longer there. An uncontained
    launch writes nothing and the reader treats absence as "no boundary to
    speak of", which is exactly what it is.
    """
    ledger = root / ".lup" / "boundary.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "read_only": sorted(lease.read_only.values()),
                "write_refusals": list(WRITE_REFUSAL_MARKERS),
                "allowed_hosts": sorted(item.host for item in egress.admits),
            },
            indent=2,
        )
    )


def report_egress(egress: SessionEgress, root: Path, down: bool) -> None:
    """Say what network boundary this project has, and remove it when asked.

    Removal names each piece separately and tolerates a piece already gone:
    the operator may have stopped the proxy by hand, and a teardown that
    failed on the half already in the state it wanted would leave the other
    half standing while reporting an error.
    """
    project = root.name
    client = detected_engine()
    if client is None:
        typer.echo("No container client answered, so nothing of this is running.")
        return
    for argv in egress.teardown_arguments(project) if down else []:
        # Every exit code is acceptable here and nowhere else: removing a
        # container that is already gone reports an error naming exactly the
        # absence this call was asked to produce.
        sh.Command(client.binary)(*argv, _ok_code=list(range(256)))
    typer.echo("Removed." if down else "\n".join(egress.notice(project)))


def network_present(name: str, engine: ContainerEngine) -> bool:
    """Whether this network exists, asked of the engine rather than guessed."""
    try:
        sh.Command(engine.binary)("network", "inspect", name)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return False
    return True


def build_image(
    image: Image, manifest: Manifest, tag: str, engine: ContainerEngine, root: Path
) -> None:
    """Build this project's image from the declaration, in the open.

    The Dockerfile is written into the checkout's scratch directory rather
    than piped in, so an operator who wants to know what was built can read
    the file the build actually used instead of reconstructing it.
    """
    scratch = root / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    dockerfile = scratch / "agent.Dockerfile"
    dockerfile.write_text(image.dockerfile(manifest))
    typer.echo(f"Building {tag} from {dockerfile}")
    try:
        sh.Command(engine.binary)(
            "build",
            "-t",
            tag,
            "-f",
            str(dockerfile),
            "--build-arg",
            f"UID={root.stat().st_uid}",
            "--build-arg",
            f"GID={root.stat().st_gid}",
            str(scratch),
            _fg=True,
        )
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter(
            f"Could not build {tag} from {dockerfile}. The declaration is in "
            "the project's Image; the build output above says which layer "
            "failed."
        ) from error


def contained_argv(
    image: Image,
    manifest: Manifest,
    root: Path,
    human_owned: list[Path],
    host_config_home: Path | None,
    credential: Path | None,
    login: ProviderLogin,
    engine: ContainerEngine | None = None,
) -> list[str]:
    """The argv that opens a session in this project's container.

    Refuses rather than degrades when no container client answers: a launch
    that asked for the boundary and silently ran without one is exactly the
    failure the boundary exists to make impossible.
    """
    client = engine if engine is not None else detected_engine()
    if client is None:
        raise typer.BadParameter(
            "No container client answered, so this session cannot be "
            "contained. Install docker or podman, or open the session with "
            "--unsandboxed to run on the host under the semantic policy alone."
        )
    tag = image_tag(root)
    if not image_present(tag, client):
        build_image(image, manifest, tag, client, root)
    start_egress(image.egress, root.name, client, root)
    for line in image.egress.notice(root.name):
        typer.echo(line)
    lease = lease_for(root, human_owned)
    record_boundary(lease, image.egress, root)
    # Read on the host and passed in, never resolved inside: the file that
    # answers "where does this remote point" is `.git/config`, which the
    # container can write, so a rewrite decided in there is a rewrite the
    # confined thing chose for itself.
    environ = os.environ  # lup: ignore[os-environ]
    token = (
        environ[image.forge.token_variable]
        if image.forge.token_variable in environ
        else ""
    )
    rewrites = remote_rewrites(root, image.forge.host)
    for line in image.forge.notice(token, rewrites):
        typer.echo(line)
    return image.session_arguments(
        tag=tag,
        checkout=root,
        uid=root.stat().st_uid,
        gid=root.stat().st_gid,
        writable=lease.writable,
        read_only=lease.read_only,
        state_volume=state_volume_name(root),
        config_home_env=login.config_home_env,
        credential_file=login.credentials_file,
        credential=credential,
        host_config_home=host_config_home,
        engine=client,
        forge_token=token,
        rewrites=rewrites,
    )
