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

from pathlib import Path

from lup.devtools.clipboard import clipboard_probes
from lup.harness.image import ContainerEngine, Docker, detected_client
from lup.harness.requirements import (
    Advisory,
    AnyOf,
    EnvironmentRedirect,
    Exercise,
    HostFacts,
    LostCapability,
    Manifest,
    MountProbe,
    Package,
    RefusedLaunch,
    Requirement,
    Run,
    Side,
    SupplementaryGroup,
)


def uv_requirement(
    where: Side = "both",
    install: list[Package] = [],
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


def for_host(
    manifest: Manifest, engine: ContainerEngine, checkout: Path | None = None
) -> Manifest:
    """This manifest with every client-carried exercise pointed at ``engine``.

    The split this exists for: *which capability is required* is a
    declaration, hashed into the ownership digest and identical on every
    machine, while *which program carries the exercise out* is a fact about
    the machine in front of you. Folding the second into the first reported
    generated artifacts as stale for having a different container client --
    measured moving twice on one machine, minutes apart, when a stale podman
    pid file was cleaned up between the runs.

    It matters which client, which is why this exists at all rather than the
    declaration simply being right: ``DOCKER_HOST`` pointing a genuine Docker
    CLI at a podman socket leaves that CLI answering first, and
    :func:`~lup.harness.image.detected_client` refuses it -- podman needs
    ``--userns=keep-id`` and a Docker client rejects the flag before the
    daemon sees it -- while the podman CLI beside it is what a session opens
    through. Exercising the refused one verifies a boundary no session uses.

    ``checkout`` is the second such fact and arrives the same way. A probe
    aimed at where this tree actually sits cannot have that path in the
    declaration: measured, the ownership digest moved between two worktrees
    of one commit, so every checkout but the one that generated last read its
    own committed tree as stale -- for having been checked out somewhere
    else. What is declared is the shape; this is where a machine answers it.
    """
    facts = HostFacts(client=engine.binary, checkout=checkout or Path())
    return Manifest(
        requirements=[
            requirement.model_copy(
                update={"exercise": resolved_exercise(requirement, facts)}
            )
            for requirement in manifest.requirements
        ]
    )


def resolved_exercise(requirement: Requirement, facts: HostFacts) -> Exercise:
    """One requirement's exercise with everything this machine has to supply.

    Two resolutions rather than one, because they answer different questions.
    ``by_client`` is the *requirement's* claim that the client carries the
    exercise out, and only some requirements make it; :meth:`Exercise.given`
    is each exercise shape answering for whatever else it could not name, and
    every shape answers it -- with "nothing" where a command is already
    portable.
    """
    exercise = (
        requirement.exercise.pointed_at(facts.client)
        if requirement.by_client
        else requirement.exercise
    )
    return exercise.given(facts)


def container_client(fallback: str = "docker") -> ContainerEngine:
    """Which client a container exercise should run through — the launcher's.

    Asked rather than spelled, because the two answers come apart on an
    ordinary host: ``DOCKER_HOST`` pointing a genuine Docker CLI at a podman
    socket leaves that CLI answering first, and
    :func:`~lup.harness.image.detected_client` refuses it as undrivable --
    podman needs ``--userns=keep-id`` and a Docker client rejects the flag
    before the daemon sees it -- while the podman CLI beside it is what a
    session actually opens through. A manifest exercising the refused client
    verifies a boundary no session uses: it can pass where the launch fails
    and fail where the launch would have worked, which is the one thing a
    declare-and-verify manifest must not do.

    The engine rather than the binary, because the client decides more than
    which program is spawned: what the daemon behind it is *asked* is spelled
    per engine too, and `podman info --format '{{.ServerVersion}}'` fails with
    *can't evaluate field ServerVersion* -- which a preflight reports as the
    runtime being unavailable on a host where it is running fine.

    ``fallback`` is what a host with no client at all gets. A name rather than
    an absence, so the exercise still fails in that program's own words --
    ``docker: not found`` says more than an empty command could.
    """
    found = detected_client()
    return found.engine() if found is not None else Docker(binary=fallback)


def container_requirement(
    where: Side = "host",
    install: list[Package] = [],
    socket_variable: str = "DOCKER_HOST",
    socket_group: str = "docker",
    lost: str = "sandboxed evaluation and multi-worker resolve",
    client: str = "docker",
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
        by_client=True,
        purpose="the sandbox code evaluation runs in, and multi-worker resolve",
        where=where,
        # Bare `info` rather than a formatted field, because the report is
        # shaped per engine and the query is not: `podman info --format
        # '{{.ServerVersion}}'` answers *can't evaluate field ServerVersion*,
        # which a preflight reports as the runtime being unavailable on a
        # machine where it is running fine. Both engines fail `info` when the
        # daemon is unreachable, which is the whole of what this asks.
        exercise=Run(command=[client, "info"]),
        absence=LostCapability(capability=lost),
        diagnoses=[
            EnvironmentRedirect(variable=socket_variable),
            SupplementaryGroup(group=socket_group),
        ],
        install=install,
    )


def same_path_mount_requirement(
    where: Side = "host",
    install: list[Package] = [],
    image: str = "docker.io/library/busybox:latest",
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

    Which directory it is aimed at is not written here, and that is the
    second thing this got wrong. Spelling the checkout put an absolute host
    path into a declaration the ownership digest hashes, and the digest then
    moved between two worktrees of one commit -- so every checkout but the
    last one to generate read its own committed tree as stale, for a fact
    about where somebody had put it. :class:`MountProbe` declares the shape
    and :func:`for_host` aims it, which is the same split the container
    client already goes through.

    ``witness`` names a file the probed directory is known to hold. A probe
    whose witness is absent answers about the witness rather than the mount.

    Checked at setup rather than at every launch, because it starts a
    container. That is a statement about the probe's cost and not about the
    requirement's importance -- which is why the two are separate fields.
    """
    return Requirement(
        capability="same-path bind mounts",
        purpose="the worktree rail, which confines a worker by mounting",
        where=where,
        checked="setup",
        exercise=MountProbe(image=image, witness=witness),
        absence=LostCapability(
            capability="the worktree rail, and so multi-worker resolve"
        ),
        install=install,
    )


def github_requirement(
    where: Side = "both",
    install: list[Package] = [Package(name="github-cli")],
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


def bubblewrap_requirement(
    where: Side = "host",
    install: list[Package] = [Package(name="bubblewrap")],
) -> Requirement:
    """The unprivileged confinement a runtime's own Linux sandbox is built on.

    Exercised rather than looked up on PATH, because the two answers differ
    exactly where it matters: a confinement binary that is installed and
    cannot start a namespace on this kernel is present and useless, and a
    launcher that vouched for it on presence alone would tell every
    dispatcher downstream to relax into a boundary that is not there.
    """
    return Requirement(
        capability="bwrap",
        purpose="the OS boundary an uncontained session's runtime confines with",
        where=where,
        exercise=Run(command=["bwrap", "--version"]),
        absence=LostCapability(capability="OS confinement"),
        install=install,
    )


def socat_requirement(
    where: Side = "host",
    install: list[Package] = [Package(name="socat")],
) -> Requirement:
    """The relay that carries a sandboxed command's traffic to its proxy.

    ``-V`` rather than ``--version``, which socat does not have: asked the
    long way it prints ``E unknown option "--version"`` and exits 1. A prober
    that spelled one flag for every program it checked read that as a broken
    socat on every host in the world, and the OS boundary was reported
    unavailable on machines where it was installed and working -- which is
    the whole argument for a probe travelling with the program it probes
    rather than with the code that calls for it.
    """
    return Requirement(
        capability="socat",
        purpose="the OS boundary an uncontained session's runtime confines with",
        where=where,
        exercise=Run(command=["socat", "-V"]),
        absence=LostCapability(capability="OS confinement"),
        install=install,
    )


def bun_requirement(
    where: Side = "image",
    install: list[Package] = [Package(name="bun")],
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
    install: list[Package] = [Package(name="typescript", manager="bun")],
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
    install: list[Package] = [],
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


def agent_session_requirement(
    where: Side = "image",
    install: list[Package] = [],
    runtime: str = "claude",
) -> Requirement:
    """Whether an agent session actually runs inside the image, not merely opens.

    The question the whole contained-agent architecture rests on, and one that
    every cheaper probe answers wrongly. ``claude --version`` passes in an
    image where no session can authenticate; a config home that accepts a
    ``mkdir`` proves the filesystem and nothing about whether the runtime will
    use it; and ``claude plugin validate`` was measured reporting a plugin
    path *missing* through a bind mount that was demonstrably there -- the
    same rootless-podman misreport ``same_path_mount_requirement`` exists to
    route around.

    So the exercise runs a real turn and requires its answer back. That cannot
    pass without the image, the mount, the relocated config home, the
    credential store, the egress proxy and the model endpoint all working
    together, and it cannot fail for a reason unrelated to any of them.

    The list in that sentence is what the declaration used to *claim*. Spelled
    out as its own ``run``, this exercise carried no mount, no config home, no
    credential and no network -- so it started a bare container on the
    engine's default bridge, where the proxy this architecture routes through
    does not stand between anything. It could pass on a host whose sessions
    could not open, which is the one thing a declare-and-verify manifest must
    not do, and it is the reason the first contained session met a DNS
    failure that no preflight had been in a position to see.

    Declared image-side now, which is what makes it true: an image-side
    exercise is carried out behind the argv a session opens with, so every
    part of the boundary the sentence above names is in the path. Nothing here
    spells a client or a tag, and that is the same fix a second time -- both
    were host facts sitting in a declaration the ownership digest hashes.

    Its absence refuses rather than degrades, because an architecture whose
    sessions do not run is not a degraded architecture.
    """
    return Requirement(
        capability="contained agent session",
        purpose="running agents, workers and reviewers inside the boundary",
        where=where,
        checked="setup",
        exercise=Run(
            command=[runtime, "-p", "Reply with exactly: SESSION_OK"],
            expect="SESSION_OK",
        ),
        absence=RefusedLaunch(
            because=(
                "the boundary is claimed but no session can run behind it, so "
                "the work would silently proceed on the host instead"
            )
        ),
        install=install,
    )


def proxy_reachable_requirement(
    where: Side = "image",
    install: list[Package] = [],
) -> Requirement:
    """Whether the session can open a connection to the proxy it was given.

    The first component of a filtered egress, and the one whose failure is
    least recognisable. A session on an internal network reaches the world
    only through the proxy, so a proxy it cannot open a socket to means every
    request fails before anything is sent.

    Asked of ``$HTTPS_PROXY`` rather than of a spelled address, and that
    keeps two things true at once. The address is assigned when the proxy
    joins the network, so a declaration naming one would be a fact about a
    machine sitting in something the ownership digest hashes. And what the
    session was *pointed at* is the right subject anyway: a probe that
    reached the proxy by some other route would verify a path no session
    takes, which is the mistake the contained-session exercise already made
    once.

    Squid answers a direct request with a status of its own, so any HTTP code
    proves the socket opened. Being refused is a correct answer here.

    This used to ask whether a DNS alias resolved, and that question could be
    answered yes by a network whose resolver then refused every public name
    the proxy needed -- measured, and the reason the alias is gone.

    ``at_launch`` because it is one of two places in the image roster where a
    container start is worth paying for on the way in. A session that opens
    without this cannot do anything, and it does not fail on the way in: it
    opens, looks entirely healthy, and blames the operator's network for
    every request afterwards.
    """
    return Requirement(
        capability="session reaches its proxy",
        at_launch=True,
        purpose="reaching anything at all from inside a filtered session",
        where=where,
        exercise=Run(
            command=[
                "sh",
                "-c",
                "curl --silent --show-error --max-time 15 --output /dev/null "
                '--write-out "%{http_code}" "$HTTPS_PROXY"',
            ]
        ),
        absence=RefusedLaunch(
            because=(
                "a filtered session sends everything to the proxy it was "
                "pointed at, so nothing in it can reach the network — and the "
                "runtime reports that as the operator's own internet being "
                "down. `harness egress --down` removes the network and the "
                "proxy so the next launch rebuilds the pair; `--unsandboxed` "
                "opens on the host under the semantic policy alone"
            )
        ),
        install=install,
    )


def proxy_tunnels_requirement(
    where: Side = "image",
    install: list[Package] = [],
    destination: str = "https://api.anthropic.com/",
) -> Requirement:
    """Whether a request actually reaches the public internet through the proxy.

    The second component, and the end-to-end one. Reaching the proxy proves a
    socket; this proves the tunnel -- that the proxy accepted a ``CONNECT``,
    that it could resolve the destination on its own side, and that its
    bridged network really does reach out.

    Through ``curl``'s reading of the proxy variables rather than an explicit
    ``-x``, deliberately. Those variables are what every other client in the
    session reads, so a probe that bypassed them would prove the proxy works
    while saying nothing about whether anything is pointed at it -- which is
    exactly the half that was broken.

    The destination is the API the session exists to reach. A generic
    connectivity host would answer a question nobody has: an allowlist that
    admits the wider internet and not this one is a working boundary and a
    session that cannot do anything.

    ``at_launch`` for the reason the reachability probe above is, and the two
    are separate because they fail separately and send a reader to different
    places: a proxy that cannot be reached is its attachment to this network,
    and one that is reached and carries nothing is the proxy itself, or what
    it was configured to allow.
    """
    return Requirement(
        capability="egress proxy tunnels out",
        at_launch=True,
        purpose="every model call, package install and documentation fetch",
        where=where,
        # `-o /dev/null` with the code written out: any HTTP status proves the
        # tunnel stood up, and the body does not. An unauthenticated 401 from
        # the API is a complete success for this question, so matching on
        # content here would refuse a working boundary.
        exercise=Run(
            command=[
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "30",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                destination,
            ]
        ),
        absence=RefusedLaunch(
            because=(
                "the session is on a network with no gateway and the one "
                "process bridged out of it is not carrying its traffic, so "
                "every model call fails. The rendered policy is at "
                "`tmp/egress.conf` and the proxy's own log says which rule "
                "refused; `harness egress --down` rebuilds the pair, and "
                "`--unsandboxed` opens without an egress boundary at all"
            )
        ),
        install=install,
    )


def metadata_refused_requirement(
    where: Side = "image",
    install: list[Package] = [],
    endpoint: str = "http://169.254.169.254/",
    status: str = "403",
) -> Requirement:
    """Whether the boundary still refuses what it exists to refuse.

    The third component, and the only one that fails *closed*: the two above
    ask whether the session can reach the world, and this asks whether it
    still cannot reach the places a compromised one would head for. Both
    questions have to be live, because the natural repair for the first --
    widen, bridge, turn the filtering off -- passes it by removing the
    boundary, and nothing else here would notice.

    The cloud metadata endpoint stands for the whole denied set. It is the
    destination with the highest payoff and the lowest effort: an unauthenticated
    HTTP GET that hands out instance credentials, on an address every cloud
    answers on. If this one is refused, the private-range rules the proxy
    compiles are in force.

    Matching a *status* rather than the proxy's error page. The status is
    protocol; the page is a build's English, and a probe that read it would
    start failing on a proxy upgrade that changed nothing about the boundary.
    """
    return Requirement(
        capability="metadata endpoint refused",
        purpose="the half of the boundary that keeps a session out of the host's cloud",
        where=where,
        checked="setup",
        exercise=Run(
            command=[
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "30",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                endpoint,
            ],
            expect=status,
        ),
        absence=RefusedLaunch(
            because=(
                "the egress boundary is not refusing the cloud metadata "
                "endpoint, so a session in this container can read whatever "
                "credentials the host's instance role holds. This one is not "
                "answered by widening anything: the denials are compiled "
                "from `EgressPolicy` into `tmp/egress.conf`, and a proxy "
                "running an older render of it is the likeliest cause"
            )
        ),
        install=install,
    )


def terminal_handoff_requirement(
    where: Side = "image",
    install: list[Package] = [],
) -> Requirement:
    """Whether the operator's terminal actually arrived inside the container.

    Three facts in one exercise because they fail together and are fixed
    together: they are the same handoff, and splitting them would start three
    containers to answer one question.

    Each of the three was measured absent on the first contained session.
    ``COLORTERM`` unset is 24-bit colour collapsing to sixteen, with the
    engine's own placeholder ``TERM`` making a truecolour terminal
    indistinguishable from a teletype. An ``EDITOR`` naming nothing runnable
    is the open-in-editor binding doing nothing when pressed -- and an
    ``EDITOR`` that is merely *unset* is the same silence, which is why this
    checks that it runs rather than that it is written. A ``LANG`` naming a
    locale nobody generated is glibc falling back to ASCII, one warning per
    program.

    The exercise prints what it found before it checks it, so a failure
    reports the values rather than only the verdict. Which of the three is
    wrong is the whole of what a reader needs, and re-running by hand inside
    a container is not a step anybody should have to take to learn it.
    """
    return Requirement(
        capability="terminal handoff",
        purpose="colour, the open-in-editor binding, and UTF-8 output",
        where=where,
        checked="setup",
        exercise=Run(
            command=[
                "sh",
                "-c",
                'printf "TERM=%s COLORTERM=%s EDITOR=%s LANG=%s\n" '
                '"$TERM" "$COLORTERM" "$EDITOR" "$LANG"; '
                '[ -n "$COLORTERM" ] || { '
                'echo "COLORTERM did not cross, so colour is 16 not 16m" >&2; '
                "exit 1; }; "
                'command -v "$EDITOR" >/dev/null || { '
                'echo "EDITOR=$EDITOR names nothing runnable here" >&2; '
                "exit 1; }; "
                'LC_ALL="$LANG" locale >/dev/null 2>&1 || { '
                'echo "LANG=$LANG was never generated in this image" >&2; '
                "exit 1; }",
            ]
        ),
        absence=Advisory(
            improves="colour depth, the open-in-editor binding, and UTF-8 output"
        ),
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
