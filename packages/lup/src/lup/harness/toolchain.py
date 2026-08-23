"""Requirements lup offers, at defaults a project is expected to overrule.

The same split the shell vocabulary makes. :mod:`lup.harness.requirements` is
the mechanism -- what a requirement is, how it is exercised, what absence
costs -- and this is the batteries: one constructor per external program lup
has an opinion about, each parameterised at the points where the opinion is
really a guess.

Every guess is a parameter with a default rather than a value written into
the body, because the same program is needed differently by different
projects. What a container image installs to satisfy a toolchain depends on
that image's base; which group grants a daemon socket depends on how the
daemon was installed; whether a capability is wanted on the host, in the
image, or both is the composing project's answer and not this module's. A
project takes the constructors it wants, passes what it differs on, and
writes its own :class:`~lup.harness.requirements.Requirement` for anything
lup never heard of -- which is the whole of the extension story, exactly as
it is for shell rules.
"""

from pathlib import Path

from lup.devtools.clipboard import clipboard_probes
from lup.harness.requirements import (
    Advisory,
    AnyOf,
    EnvironmentRedirect,
    LostCapability,
    Manifest,
    RefusedLaunch,
    Requirement,
    Run,
    Side,
    SupplementaryGroup,
)


def uv_requirement(
    where: Side = "both",
    install: list[str] = [],
) -> Requirement:
    """The package manager every command in a lup project is invoked through.

    The one requirement offered here that refuses rather than degrades. Its
    absence is not a smaller session, it is a session where every command
    fails in the vocabulary of whatever was being attempted -- which is the
    shape the whole manifest exists to prevent, and so worth one refusal.

    ``install`` is empty because the images lup builds start from a base that
    ships uv. A project whose base does not says so here.
    """
    return Requirement(
        capability="uv",
        purpose="every command in this project, which is invoked through it",
        where=where,
        exercise=Run(command=["uv", "--version"]),
        absence=RefusedLaunch(
            because=(
                "nothing in this project runs without uv, so a session opened "
                "here would fail at its first command with a message about "
                "that command rather than about the toolchain"
            )
        ),
        install=install,
    )


def container_requirement(
    where: Side = "host",
    install: list[str] = [],
    socket_variable: str = "DOCKER_HOST",
    socket_group: str = "docker",
    lost: str = "sandboxed evaluation and multi-worker resolve",
) -> Requirement:
    """A reachable container daemon, exercised by asking it its own version.

    Asking the daemon rather than asking PATH for a client. The two answers
    came apart for an entire evening once: a profile exported a socket
    variable pointing at a runtime that was not installed, so every client
    redirected to a path that could not exist and reported that it could not
    reach the daemon -- which reads as a stopped service and sends the reader
    to restart the wrong thing.

    ``where`` defaults to the host and ``install`` to nothing, and both
    defaults are load-bearing rather than merely conservative: a container
    holding a daemon socket can start a sibling with the whole host
    bind-mounted, which is a total escape. A project that means to put a
    runtime inside its image is overruling a security property and should
    have to say so.

    What this does *not* prove is that an expression evaluates inside a
    container -- a daemon that answers can still be one whose image cannot
    import the project. Exercising that far would mean pulling and starting a
    container on every launch, which is a cost no preflight should impose, so
    the gap is stated rather than closed.
    """
    return Requirement(
        capability="container runtime",
        purpose="the sandbox code evaluation runs in, and multi-worker resolve",
        where=where,
        exercise=Run(command=["docker", "info", "--format", "{{.ServerVersion}}"]),
        absence=LostCapability(capability=lost),
        diagnoses=[
            EnvironmentRedirect(variable=socket_variable),
            SupplementaryGroup(group=socket_group),
        ],
        install=install,
    )


def same_path_mount_requirement(
    where: Side = "host",
    install: list[str] = [],
    image: str = "docker.io/library/busybox:latest",
    probe: Path = Path("/tmp/lup-same-path-probe"),
    witness: str = "pyproject.toml",
) -> Requirement:
    """Whether this host can bind-mount a directory at its own absolute path.

    The prerequisite the worktree rail rests on, and one that has already been
    found false. A linked worktree's `.git` is a file holding an *absolute*
    `gitdir:` pointer, so a container that mounted the tree anywhere else
    would hold a checkout pointing at a path that does not exist there --
    same-path mounting is forced rather than preferred, and where it does not
    work the rail does not work.

    How this is asked matters more than that it is asked, and the first
    version got it wrong in the direction that manufactures findings. Asking
    ``test -d`` about the mounted directory answered *false* on rootless
    podman for every worktree this rail leases -- which reads exactly like an
    absent mount, and is not one. Reading a file through the same mount, in
    the same container, succeeded: the mount was present and `stat` on the
    mount point was simply not answerable under that user-namespace mapping.
    A presence check had answered a different question than the one asked,
    and its wrong answer was shaped like a real defect.

    So the exercise reads a file across the boundary. That cannot succeed
    unless the mount both happened and carried content, and it cannot fail
    for a reason that has nothing to do with mounting.

    ``probe`` should be pointed at a directory the project actually leases
    rather than left at its default, and ``witness`` at a file that exists
    inside it. A probe aimed somewhere else answers about somewhere else.

    Checked at setup rather than at every launch, because it starts a
    container. That is a statement about the probe's cost and not about the
    requirement's importance -- which is why the two are separate fields.
    """
    return Requirement(
        capability="same-path bind mounts",
        purpose="the worktree rail, which confines a worker by mounting",
        where=where,
        checked="setup",
        # Read a file that only exists on the host side, rather than asking
        # whether the directory is there. Asking about the directory is what a
        # first draft did, and it can pass without the mount having happened
        # at all: the container creates an empty directory at any mount target
        # it was given, so `test -d` answers yes about a directory the mount
        # left behind. Reading a file through it cannot.
        exercise=Run(
            command=[
                "docker",
                "run",
                "--rm",
                "-v",
                f"{probe}:{probe}:ro",
                image,
                "cat",
                str(probe / witness),
            ]
        ),
        absence=LostCapability(
            capability="the worktree rail, and so multi-worker resolve"
        ),
        install=install,
    )


def github_requirement(
    where: Side = "both",
    install: list[str] = ["gh"],
) -> Requirement:
    """The GitHub CLI, exercised as *authenticated* rather than as installed.

    `gh --version` passes on a machine that has never logged in, and every
    command that matters then fails one at a time with an authentication
    error several steps from the setup that would fix it.
    """
    return Requirement(
        capability="gh",
        purpose="pull requests, issues, and the friction reports the loop files",
        where=where,
        exercise=Run(command=["gh", "auth", "status"]),
        absence=LostCapability(
            capability="opening pull requests and filing issues from a session"
        ),
        install=install,
    )


def bun_requirement(
    where: Side = "image",
    install: list[str] = ["bun"],
) -> Requirement:
    """The JavaScript runtime and package manager, wanted inside the image.

    ``where`` defaults to the image because a host that will only ever run
    this toolchain inside a container is not a host with a problem, and
    exercising it there would report one. A project doing JavaScript work
    directly on the host passes ``both``.
    """
    return Requirement(
        capability="bun",
        purpose="running and bundling this project's TypeScript",
        where=where,
        exercise=Run(command=["bun", "--version"]),
        absence=LostCapability(capability="the JavaScript toolchain"),
        install=install,
    )


def typescript_requirement(
    where: Side = "image",
    install: list[str] = ["typescript"],
) -> Requirement:
    """The TypeScript compiler, reached through the package runner.

    Through `bunx` rather than as a global binary: a project's compiler
    version is a property of that project, and a globally installed `tsc`
    checks against whatever version somebody last installed anywhere.
    """
    return Requirement(
        capability="typescript",
        purpose="type-checking this project's TypeScript before it runs",
        where=where,
        exercise=Run(command=["bunx", "tsc", "--version"], expect="Version"),
        absence=LostCapability(capability="type-checking TypeScript"),
        install=install,
    )


def clipboard_requirement(
    where: Side = "host",
    install: list[str] = [],
) -> Requirement:
    """Any one of the clipboard clients a desktop might have, as an advisory.

    Advisory because it matters in exactly one moment -- somebody running a
    command by hand and wanting the follow-up ready to paste -- and in none
    of the sessions afterwards, where an agent moves itself and never touches
    a clipboard. Said once to whoever is setting a machine up; silent at
    every launch, where it would only teach people to skip the line above it.

    The spellings come off :func:`~lup.devtools.clipboard.clipboard_probes`
    rather than being listed here, because which one a machine has is a fact
    about its desktop rather than about any project -- and because a list
    written twice comes apart. It already had: this named four backends
    including Wayland while the code that reached for a clipboard tried four
    that did not, so a Wayland machine was told it had a clipboard and then
    silently failed to use it.

    Each probe is a *read*. A write would destroy whatever the operator had
    on their clipboard to establish something they never asked about, and a
    ``--version`` proves nothing: `wl-copy --version` succeeds with no
    compositor running and `xclip -version` succeeds with no `DISPLAY`, which
    is exactly the machine where pasting does nothing.
    """
    return Requirement(
        capability="clipboard",
        purpose="handing a printed command straight to the shell that runs it",
        where=where,
        checked="setup",
        exercise=AnyOf(
            alternatives=[Run(command=probe) for probe in clipboard_probes()]
        ),
        absence=Advisory(improves="copying a command to the clipboard"),
        install=install,
    )


def default_manifest() -> Manifest:
    """Every requirement at its offered default -- the batteries-included roster.

    A project with no opinion yet composes this and gets a preflight that
    says true things; one that has an opinion replaces the entries it differs
    on rather than this call. Deliberately carries no JavaScript toolchain:
    most projects on lup have none, and a manifest that invents a
    prerequisite refuses machines that were fine.
    """
    return Manifest(
        requirements=[
            uv_requirement(),
            container_requirement(),
            github_requirement(),
            clipboard_requirement(),
        ]
    )
