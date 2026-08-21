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

from pathlib import Path

import sh
import typer

from lup.harness.image import ContainerEngine, Image, detected_engine
from lup.harness.requirements import Manifest
from lup.runtime.login import ProviderLogin
from lup.sandbox.rail import lease_for


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
    lease = lease_for(root, human_owned)
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
    )
