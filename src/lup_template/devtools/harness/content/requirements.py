"""The external programs this repository needs, and what going without costs.

Every entry is exercised rather than looked for, and only one refuses: this
is a framework, and the machines it has to open on include a CI runner with
no desktop, a laptop with no container runtime, and a corporate box where the
daemon is somebody else's. A preflight that refused on any of those would be
a preflight nobody could run.

What each entry buys is the sentence at the top of a session's scrollback. An
agent inside cannot discover that it has no container except by `py eval`
reporting something about a socket -- so the absent capability is stated
where it will be read, before anything depends on it.

The two axes are worth reading together, because either alone misreports.
*Where* says who is expected to have it: a container runtime is the host's
and must never be the image's, a TypeScript toolchain is the image's and the
host has no reason to carry one. *Absence* says what going without costs,
down to a grade that is only worth saying to somebody setting a machine up.
Between them, a laptop with no bun and no clipboard is told nothing at all at
launch, which is correct -- neither is a fault of that machine.
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
    SupplementaryGroup,
)

CONTAINER = Requirement(
    capability="container runtime",
    purpose="the sandbox `py eval` computes in, and multi-worker resolve",
    # Host, and never the image. A container holding a runtime socket can
    # start a sibling with the whole host bind-mounted, which is a total
    # escape -- so the agent image carries no client and the resolver stays
    # a host-side supervisor spawning siblings.
    where="host",
    # Asking the daemon its own version, rather than asking PATH whether a
    # client exists. The two answers came apart for a whole evening once: a
    # profile exported DOCKER_HOST at a podman socket on a host where podman
    # was not installed, so every client redirected to a path that could not
    # exist and reported that it could not reach the daemon -- which reads as
    # a stopped service and sends the reader to restart the wrong thing.
    exercise=Run(command=["docker", "info", "--format", "{{.ServerVersion}}"]),
    absence=LostCapability(
        capability="`py eval` and multi-worker resolve",
    ),
    diagnoses=[
        EnvironmentRedirect(variable="DOCKER_HOST"),
        SupplementaryGroup(group="docker"),
    ],
    # Nothing, and emphatically so. A container holding a docker socket can
    # start a sibling with the whole host bind-mounted, which is a total
    # escape -- so the agent image must never carry a client, and the
    # resolver stays a host-side supervisor spawning siblings.
    install=[],
)
"""Reaching the daemon, which is weaker than the property that matters.

What a session actually needs is that an expression evaluates inside a
container, and a daemon that answers can still be one whose image cannot
import this project. Exercising that far would mean pulling and starting a
container on every launch, which is a cost no preflight should impose, so the
gap is stated rather than closed: this proves the endpoint, and the first
`py eval` proves the rest.
"""

GITHUB = Requirement(
    capability="gh",
    purpose="pull requests, issues, and the friction reports the loop files",
    where="both",
    exercise=Run(command=["gh", "auth", "status"]),
    absence=LostCapability(
        capability="opening pull requests and filing issues from a session"
    ),
    install=["gh"],
)
"""Exercised as *authenticated*, not as installed.

`gh --version` passes on a machine that has never logged in, and every
command that matters then fails one at a time with an authentication error
several steps from setup.
"""

UV = Requirement(
    capability="uv",
    purpose="every command in this project, which is invoked through it",
    where="both",
    exercise=Run(command=["uv", "--version"]),
    absence=RefusedLaunch(
        because=(
            "nothing in this project runs without uv, so a session opened "
            "here would fail at its first command with a message about that "
            "command rather than about the toolchain"
        )
    ),
    # The base image is an astral uv image, so uv arrives with it rather
    # than through a package manager that does not carry it anyway.
    install=[],
)
"""The one entry that refuses, and it refuses for the reason the others do not.

Its absence is not a smaller session -- it is a session where every command
fails, each in the vocabulary of whatever was being attempted. That is the
shape this whole manifest exists to prevent, so it is worth one refusal.
"""

CLIPBOARD = Requirement(
    capability="clipboard",
    purpose="handing a printed launch command straight to the shell that runs it",
    # Host, and advisory. It matters in exactly one moment -- a person running
    # `worktree create` by hand and wanting the follow-up command ready to
    # paste -- and in none of the sessions afterwards, where the agent moves
    # itself and never touches a clipboard. Said once where somebody can act
    # on it; silent at every launch, where it would only teach people to skip
    # the line above it.
    where="host",
    # Which spelling a machine has is a fact about its desktop, not about this
    # project. Naming only `xclip` -- which one caller still does -- reports
    # "no clipboard" on every Wayland session that has a working one.
    exercise=AnyOf(
        alternatives=[
            Run(command=["wl-copy", "--version"]),
            Run(command=["xclip", "-version"]),
            Run(command=["xsel", "--version"]),
            Run(command=["pbcopy"]),
        ]
    ),
    absence=Advisory(improves="copying a launch command to the clipboard"),
)

BUN = Requirement(
    capability="bun",
    purpose="running and bundling this project's TypeScript",
    # Image, not host. Nothing outside the container runs it, so exercising it
    # here would report a perfectly good machine broken for lacking a
    # toolchain it was never meant to carry.
    where="image",
    exercise=Run(command=["bun", "--version"]),
    absence=LostCapability(capability="the TypeScript toolchain"),
    install=["bun"],
)
"""Declared and, until the image declaration exists, unverified.

An image-side requirement is checked where it is needed, and there is not yet
an image to check it in -- so what this buys today is the package list a
build will be assembled from, and the honest statement that nothing has
exercised it. Recorded rather than quietly assumed.
"""

TYPESCRIPT = Requirement(
    capability="typescript",
    purpose="type-checking this project's TypeScript before it runs",
    where="image",
    # Reached through bun rather than as a global binary: a project's compiler
    # version is a property of the project, and a globally installed `tsc`
    # type-checks against whatever version somebody last installed.
    exercise=Run(command=["bunx", "tsc", "--version"], expect="Version"),
    absence=LostCapability(capability="type-checking TypeScript"),
    install=["typescript"],
)

MANIFEST = Manifest(
    requirements=[UV, CONTAINER, GITHUB, BUN, TYPESCRIPT, CLIPBOARD],
)
"""Ordered by how early a session notices the absence, not by importance.

Deliberately short. A first draft also declared ripgrep, and exercising it
refuted the declaration twice over: this project never invokes `rg` -- only
the policy vocabulary judges it, which is a rule about what an *agent* may
run -- and on the machine that raised the finding `rg` is a shell function
rather than an executable, so `command -v` would have called it present
while nothing spawned could reach it. A manifest that invents prerequisites
refuses machines that were fine, which is the failure it exists to prevent
pointed the other way.
"""
