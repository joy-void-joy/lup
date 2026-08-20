# lup: ignore[empty-collection]
# Every empty list here is a default *parameter* -- the point a project
# overrules -- and not a collection this module goes on to append to.
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

    Four spellings, because which one a machine has is a fact about its
    desktop rather than about any project. Naming only `xclip` reports "no
    clipboard" on every Wayland session that has a working one.
    """
    return Requirement(
        capability="clipboard",
        purpose="handing a printed command straight to the shell that runs it",
        where=where,
        exercise=AnyOf(
            alternatives=[
                Run(command=["wl-copy", "--version"]),
                Run(command=["xclip", "-version"]),
                Run(command=["xsel", "--version"]),
                Run(command=["pbcopy"]),
            ]
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
