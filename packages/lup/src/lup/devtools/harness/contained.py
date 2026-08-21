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

import hashlib
import json
import os
from collections import deque
from contextlib import nullcontext
from pathlib import Path

import sh
import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text

from lup.harness.credential import remote_rewrites
from lup.harness.egress import SessionEgress
from lup.harness.image import ContainerEngine, Image, detected_client
from lup.harness.notice import Notice
from lup.harness.requirements import Manifest
from lup.runtime.login import ProviderLogin
from lup.sandbox.attribution import WRITE_REFUSAL_MARKERS
from lup.sandbox.rail import Lease, lease_for


def image_tag(dockerfile: str) -> str:
    """The image a declaration answers to, named for the declaration itself.

    Two worktrees share a layer exactly when they would build the same thing,
    and get separate ones exactly when they would not -- derived rather than
    assumed. The assumption is what the alternatives cost. Naming the image
    after the *worktree* pays a full build per checkout, which is hundreds of
    packages times however many are open. Naming it after the *repository*
    rests on every worktree declaring the same toolchain, which is true right
    up until a branch edits the image declaration -- and then the two rebuild
    over each other on every switch, because :func:`image_matches` compares
    the declaration digest and each finds the other's.

    Twelve hex characters, for the reason a short object hash is enough to
    name a commit: this is a handle for a thing already in the store, not a
    security claim, and the full digest is on the image's own label.
    """
    return f"lup-agent:{declaration_digest(dockerfile)[:12]}"


def checkout_tag(root: Path) -> str:
    """The readable name this checkout's latest image also answers to.

    A second tag on the same image, moved to whatever this checkout last
    built or reused. It earns its place twice over. An image list showing
    only digests is one nobody can read, and -- the load-bearing half -- the
    preflight has to name the image it probes, while the digest is computed
    *from* the manifest that preflight is part of. A name that does not
    depend on the declaration is the only one that can be stated inside it.

    Moved even when the build is skipped, or a checkout that reused another's
    image would have no tag of its own and its probe would ask after nothing.
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


# lup: ignore[constant-declaration] — an identity this repository defines, not a
# judgement: the writer and the reader have to name the same key or neither works
DECLARATION_LABEL = "lup.declaration"
"""The label carrying the digest of the Dockerfile an image was built from."""


def declaration_digest(dockerfile: str) -> str:
    """What this declaration hashes to, for comparing an image against it."""
    return hashlib.sha256(dockerfile.encode("utf-8")).hexdigest()


def image_matches(tag: str, dockerfile: str, engine: ContainerEngine) -> bool:
    """Whether this tag exists *and* was built from this declaration.

    Presence alone was the question for a while, and it is the wrong one: an
    image is built once and the declaration goes on changing, so every later
    edit -- a pinned CLI, a package, the entrypoint -- was a change that
    landed in the repository and never in the thing a session actually ran
    in. Nothing reported it, because from the outside a stale image and a
    current one are one tag.

    The digest is a label rather than a file beside the image, so it travels
    with what it describes and cannot be left behind by a `rmi`. An image
    carrying no label at all is one built before this existed, and is treated
    as stale: rebuilding costs a build, and trusting it costs a session
    running in something nobody can identify.
    """
    try:
        labelled = sh.Command(engine.binary)(
            "image",
            "inspect",
            "--format",
            f'{{{{index .Config.Labels "{DECLARATION_LABEL}"}}}}',
            tag,
        )
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return False
    return str(labelled).strip() == declaration_digest(dockerfile)


# lup: ignore[constant-declaration] — an identity this repository defines, not a
# judgement: the tag functions above spell it and the sweep below matches on it,
# so a caller free to differ would be a caller whose prune found nothing
IMAGE_PREFIX = "lup-agent:"
"""What every image this project builds is named under.

An identity rather than a judgement: the tag functions above spell it and the
sweep below has to match them, so a caller free to differ would be a caller
whose prune found nothing.
"""


def superseded_images(engine: ContainerEngine, keep: str) -> list[str]:
    """The digest tags no checkout is pointing at any more.

    Content-addressing is what lets two checkouts share a layer, and the cost
    it comes with is that editing the declaration leaves the old image
    standing rather than replacing it under one name. These are big -- a full
    Arch base and a package set -- so something has to name what is finished.

    A digest tag is finished when no readable checkout tag sits on the same
    image. That is the whole test, and it is deliberately not "older than":
    a checkout nobody has opened for a month still runs the image its tag
    points at, and time says nothing about that.

    ``keep`` is the tag this checkout would build right now, held back
    whether or not anything is tagged onto it yet -- a sweep run between a
    declaration edit and the next launch would otherwise delete the image
    that launch is about to reuse.
    """
    try:
        listed = sh.Command(engine.binary)(
            "images", "--format", "{{.ID}} {{.Repository}}:{{.Tag}}"
        )
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return []
    return finished_tags(str(listed), keep)


def finished_tags(listing: str, keep: str) -> list[str]:
    """Read one engine's image listing down to the tags nothing points at.

    Split from the call that fetches the listing because this is the half
    that decides what gets deleted, and a sweep whose selection cannot be
    exercised without a container runtime is one nobody should be asked to
    trust. The listing is one ``<id> <repository>:<tag>`` per line, which is
    the format the caller asks for.

    A digest tag is recognized by its shape -- the prefix plus twelve hex
    characters -- rather than by parsing, because that is what
    :func:`image_tag` produces and a checkout name of that exact length
    would have to be twelve characters of hex to collide.
    """
    rows = [line.split() for line in listing.splitlines()]
    # Sliced at the prefix rather than split on "/", because the registry a
    # listing prepends is not a path and the tag is not its last segment: the
    # name this project builds under starts where the prefix does, and
    # everything before it is whichever store the image happens to sit in.
    named = [
        (row[0], row[1][row[1].index(IMAGE_PREFIX) :])
        for row in rows
        if len(row) == 2 and IMAGE_PREFIX in row[1]
    ]
    beside = {
        identifier: [tag for other, tag in named if other == identifier]
        for identifier, _ in named
    }
    return sorted(
        tag
        for tags in beside.values()
        for tag in tags
        if tag != keep
        and len(tag) == len(IMAGE_PREFIX) + 12
        and not any(len(other) != len(tag) for other in tags)
    )


def retire_images(tags: list[str], engine: ContainerEngine) -> list[str]:
    """Remove each named image, reporting the ones that actually went.

    One call per tag rather than one call for all of them, because a single
    failure -- an image a stopped container still references -- would take
    the whole sweep down with it and leave the operator no better off.
    """
    gone: list[str] = []
    for tag in tags:
        try:
            sh.Command(engine.binary)("rmi", tag)
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            continue
        gone.append(tag)
    return gone


def name_for_checkout(tag: str, readable: str, engine: ContainerEngine) -> None:
    """Point this checkout's readable name at the image it will actually run.

    Idempotent, and silent about its own failure: the tag is a convenience
    for whoever reads an image list and the name the preflight probes, and
    neither is worth refusing a launch over. The session runs the digest tag
    regardless, which is the one that has to be right.
    """
    try:
        sh.Command(engine.binary)("tag", tag, readable)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return


def running(name: str, engine: ContainerEngine) -> bool:
    """Whether a container by this name is up, asked of the engine.

    Asked rather than remembered, for the same reason :func:`image_matches`
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
    client = detected_client()
    if client is None:
        Notice(
            text="No container client answered, so nothing of this is running.",
            urgency="warning",
        ).say()
        return
    for argv in egress.teardown_arguments(project) if down else []:
        # Every exit code is acceptable here and nowhere else: removing a
        # container that is already gone reports an error naming exactly the
        # absence this call was asked to produce.
        sh.Command(client.binary)(*argv, _ok_code=list(range(256)))
    if down:
        Notice(text="Removed.", urgency="ready").say()
        return
    for notice in egress.notice(project):
        notice.say()


def network_present(name: str, engine: ContainerEngine) -> bool:
    """Whether this network exists, asked of the engine rather than guessed."""
    try:
        sh.Command(engine.binary)("network", "inspect", name)
    except (sh.CommandNotFound, sh.ErrorReturnCode):
        return False
    return True


def build_image(
    image: Image,
    manifest: Manifest,
    tag: str,
    engine: ContainerEngine,
    root: Path,
    shown: int = 4,
) -> None:
    """Build this project's image from the declaration, in the open.

    The Dockerfile is written into the checkout's scratch directory rather
    than piped in, so an operator who wants to know what was built can read
    the file the build actually used instead of reconstructing it.

    Every line the build writes is kept, and the terminal shows the last
    ``shown`` of them in place. The distinction matters more than it looks:
    the *file* is complete, so nothing a reader might need was thrown away,
    and the *display* is a window onto it rather than a shortened copy. A
    cold build here is hundreds of package lines, and putting them in the
    scrollback buries whatever the launch said before them -- which is
    exactly the boundary report a session most needs to have read.

    Two lines are printed before anything runs, because a build with a live
    region and no header is a session that appears to have stopped: what is
    being built, and where its full output is being written.
    """
    scratch = root / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    dockerfile = scratch / "agent.Dockerfile"
    rendered = image.dockerfile(manifest)
    dockerfile.write_text(rendered)
    log = scratch / "agent-build.log"
    argv = [
        "build",
        "-t",
        tag,
        "--label",
        f"{DECLARATION_LABEL}={declaration_digest(rendered)}",
        "-f",
        str(dockerfile),
        "--build-arg",
        f"UID={root.stat().st_uid}",
        "--build-arg",
        f"GID={root.stat().st_gid}",
        str(scratch),
    ]
    Notice(text=f"Building {tag} from {dockerfile}", urgency="progress").say()
    Notice(text=f"Its output: {log}", urgency="artifact").say()
    console = Console()
    recent: deque[str] = deque(maxlen=shown)
    with log.open("w", encoding="utf-8") as handle:
        # Transient, so the window closes when the build does and the
        # scrollback keeps the two header lines rather than a frozen tail of
        # whatever the last layer happened to say. Off entirely where there
        # is no terminal to redraw -- a CI log is a file, and a file wants
        # every line in order, which is what the handle already gets.
        live = Live(console=console, transient=True) if console.is_terminal else None

        def record(chunk: str) -> None:
            """Keep every line, and show the last few."""
            handle.write(chunk)
            spoken = chunk.rstrip()
            if not spoken or live is None:
                return
            recent.append(spoken)
            live.update(Text("\n".join(recent), style="dim"))

        try:
            with live or nullcontext():
                sh.Command(engine.binary)(
                    *argv, _out=record, _err_to_out=True, _out_bufsize=1
                )
        except sh.ErrorReturnCode as error:
            for line in recent:
                typer.echo(line)
            raise typer.BadParameter(
                f"Could not build {tag} from {dockerfile}. The declaration is "
                f"in the project's Image; {log} holds every line of the build, "
                "and its last ones say which layer failed."
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

    A client that answers and cannot drive the engine behind it is refused
    the same way and in different words, because the two failures send an
    operator to opposite places: one to install a runtime, the other to stop
    pointing the one they have at somebody else's socket.
    """
    if engine is not None:
        client = engine
    else:
        found = detected_client()
        if found is None:
            raise typer.BadParameter(
                "No container client answered, so this session cannot be "
                "contained. Install docker or podman, or open the session with "
                "--unsandboxed to run on the host under the semantic policy alone."
            )
        if not found.drives_its_server():
            raise typer.BadParameter(found.consequence())
        client = found.engine()
    rendered = image.dockerfile(manifest)
    tag = image_tag(rendered)
    if not image_matches(tag, rendered, client):
        build_image(image, manifest, tag, client, root)
    name_for_checkout(tag, checkout_tag(root), client)
    start_egress(image.egress, root.name, client, root)
    for notice in image.egress.notice(root.name):
        notice.say()
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
    for notice in image.forge.notice(token, rewrites):
        notice.say()
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
