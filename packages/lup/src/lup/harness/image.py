"""The image an agent session runs in, rendered from what the project declares.

An image assembled by hand beside a manifest can disagree with it, and the
disagreement surfaces late: the session opens, and the toolchain the manifest
promised is absent, and the absence reads as whatever the missing program says
about itself. So the package list is not written here. It comes off
:meth:`Manifest.packages`, the same roster the preflight exercises, which is
what makes "declared" and "installed" one fact instead of two that agree until
somebody edits one.

What this module adds to that roster is everything a package list cannot say:
which layer each part belongs to, so a ``uv add`` costs a sync rather than a
rebuild; which paths stay container-private, so the host's tooling and the
container's do not fight over one ``.venv``; which directories outlive the
container, so a rebuild does not re-download the world; and which identity the
process runs under, so bind-mounted files do not land root-owned on the host.

Three fields answer things that were measured rather than reasoned, against
Claude Code 2.1.237 on rootless podman 6.1.0, and each records its measurement
where the field is declared: ``inner_sandbox``, ``trusted_projects``, and the
same-path mounting that :func:`run_arguments` refuses to spell any other way.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import sh
from pydantic import BaseModel, Field

from lup.harness.browser import BrowserBridge
from lup.harness.credential import GitAccess, GitIdentity, RemoteRewrite
from lup.harness.egress import SessionEgress
from lup.harness.environment import NON_INTERACTIVE_SHELL_ENV
from lup.harness.requirements import Manifest, Package, PackageManager
from lup.harness.terminal import TerminalHandoff
from lup.types import EnvVars, JsonObject


class CacheVolume(BaseModel, frozen=True):
    """A directory whose contents outlive the container that filled it.

    Named volumes rather than bind mounts, because these hold artifacts built
    against the *image's* libc and interpreter. A host cache bound into a
    container mixes wheels compiled for two platforms into one directory, and
    the resulting failure names a package rather than the mount that broke it.
    """

    name: str = Field(description="Volume name, unique to this project")
    path: str = Field(description="Absolute path the volume is mounted at")
    variable: str = Field(
        default="",
        description=(
            "Environment variable that points its tool at this path. Empty "
            "when the tool already defaults here and naming it would only "
            "add a second place the path is written"
        ),
    )
    because: str = Field(
        default="",
        description=(
            "What made this necessary. A boundary answered by widening its "
            "own declaration teaches an agent that every wall is answered by "
            "widening it, and volumes then accrete with nothing removing "
            "one -- each perfectly defensible when written and nobody "
            "afterwards able to say whether it is still earning its place. "
            "Empty is accepted and reported, because refusing it would make "
            "the honest answer -- 'I do not remember' -- unwritable"
        ),
    )

    def environment(self) -> EnvVars:
        """The variable pointing this volume's tool at it, where there is one."""
        return {self.variable: self.path} if self.variable else {}

    def mount_arguments(self) -> list[str]:
        """The run arguments that attach this volume."""
        return ["-v", f"{self.name}:{self.path}"]


class Registry(BaseModel, frozen=True):
    """A manager that installs by registry name, and the command that drives it.

    Declared rather than hardcoded in the renderer so a project may swap the
    tool without forking it -- and so the roster of managers that install
    something *verifiable* is one list, which is what the rendering iterates.
    A manager absent from this list installs nothing by registry, which is the
    correct treatment of ``script``.
    """

    manager: PackageManager = Field(description="Which manager this drives")
    command: str = Field(description="The install command, taking names as arguments")


class ContainerEngine(BaseModel, frozen=True):
    """How one container runtime spells the identity a session runs under.

    The base carries the portable spelling and each engine adds only what is
    its own, because the difference is not cosmetic: a bind mount carries uid
    numbers rather than names, so an engine that remaps them writes files the
    host user cannot read back. Measured -- ``--userns=keep-id`` is podman's
    word for "do not remap", and Docker 29.7.2 refuses it outright with
    ``--userns: invalid USER mode``, so a launcher that spelled one engine's
    requirement unconditionally could not start under the other.

    The spelling is the *client's*, because the client is what accepts or
    rejects a flag: a Docker CLI refuses ``--userns=keep-id`` before the
    daemon ever sees it, whatever the daemon happens to be. Which engine is
    *behind* that client is a second question, and :class:`ContainerClient`
    is where the two are held together -- a Docker CLI pointed at a podman
    socket by ``DOCKER_HOST`` is a real configuration, and it is one no
    spelling can rescue, because the flag podman needs is the flag this
    client refuses to send.
    """

    binary: str = Field(description="The executable that starts a container")

    def identity_arguments(self, uid: int, gid: int) -> list[str]:
        """Run the session as this uid and gid, in the words this engine takes."""
        return ["--user", f"{uid}:{gid}"]


class Docker(ContainerEngine, frozen=True):
    """Docker, which maps container uids to host uids without being told.

    A rootless Docker install maps the host user onto container root through
    its own userns, which this does not attempt to correct: the remedy there
    is ``--userns=host`` or a daemon-side mapping, both of which are postures
    an operator chooses rather than facts a launcher can read off the client.
    """

    binary: str = "docker"


class Podman(ContainerEngine, frozen=True):
    """Podman, which remaps into the subuid range unless told to keep the id."""

    binary: str = "podman"

    def identity_arguments(self, uid: int, gid: int) -> list[str]:
        """The portable spelling, plus podman's word for leaving the id alone."""
        return [*super().identity_arguments(uid, gid), "--userns=keep-id"]


def reported_version(name: str) -> str:
    """What one container client says when asked who it is.

    Separated from the detection so a caller can answer for a client that is
    not installed here -- which is what makes the ``podman-docker`` case
    testable on a machine that does not have it.
    """
    return str(sh.Command(name)("--version"))


def reported_server(name: str) -> str:
    """What the engine *behind* one client says it is, in its own components.

    A separate question from :func:`reported_version`, and asked separately
    because the two disagree on a real host: ``DOCKER_HOST`` pointed at a
    podman socket leaves a Docker CLI reporting Docker while every container
    it starts is podman's. The components list is what carries the name --
    podman answers with a ``Podman Engine`` entry where Docker answers with
    ``Engine`` and ``containerd`` -- and the version number alone does not,
    which is why this asks for the list rather than the shorter field.

    Unlike the client probe this one reaches a daemon, so it fails whenever
    nothing is listening. That failure is not an error here: a client with no
    running daemon is undrivable for reasons this question cannot improve on,
    and the caller reads the absence as an unknown server.
    """
    return str(sh.Command(name)("version", "--format", "{{json .Server.Components}}"))


type EngineFlavor = Literal["docker", "podman", "unknown"]
"""Which of the two engines something is, or that it did not say."""


def flavor_of(reported: str) -> EngineFlavor:
    """Read an engine's own words for which of the two it is."""
    return "podman" if "podman" in reported.lower() else "docker"


class ContainerClient(BaseModel, frozen=True):
    """One container client on this host, and the engine actually behind it.

    Both halves, because either alone gets a real host wrong. The client
    decides which flags are *sendable*: the ``podman-docker`` package installs
    a ``docker`` that is podman and takes podman's arguments despite the name,
    which is why nothing here trusts the spelling of a path. The server
    decides what those flags will *mean*: ``DOCKER_HOST`` pointing a genuine
    Docker CLI at a podman socket is an ordinary developer setup, and the
    containers it starts are podman's however the client answers.

    Measured on such a host, and the reason this class exists rather than a
    bare engine: podman remaps uids unless told ``--userns=keep-id``, the
    Docker CLI rejects that flag outright, and the session's own bind-mounted
    checkout is therefore read-only to it -- ``touch: Permission denied`` on
    the tree it was opened to work on. No spelling fixes that, because the
    one word that would is the word this client will not carry.
    """

    binary: str = Field(description="The executable that starts a container")
    client: EngineFlavor = Field(description="What the CLI says it is")
    server: EngineFlavor = Field(
        default="unknown",
        description=(
            "What answers on that CLI's socket. ``unknown`` when nothing "
            "answered, which is not treated as a mismatch: a daemon that is "
            "down is a different problem with its own message, and guessing "
            "at a mismatch would name the wrong one"
        ),
    )

    def engine(self) -> ContainerEngine:
        """The identity spelling this *client* accepts, whatever runs behind it."""
        return (
            Podman(binary=self.binary)
            if self.client == "podman"
            else Docker(binary=self.binary)
        )

    def drives_its_server(self) -> bool:
        """Whether this client can express what the engine behind it requires."""
        return not (self.client == "docker" and self.server == "podman")

    def consequence(self) -> str:
        """What a session started through this client would lose, for a refusal."""
        return (
            f"`{self.binary}` is a Docker client driving a podman engine, which "
            "podman needs `--userns=keep-id` to do without remapping uids -- and "
            "a Docker client rejects that flag before the daemon sees it, so the "
            "session's own checkout would be read-only to it. Install podman's "
            "own CLI, or unset DOCKER_HOST to reach a Docker daemon, or open the "
            "session with --unsandboxed to run on the host under the semantic "
            "policy alone."
        )


def detected_client(
    candidates: tuple[str, ...] = ("docker", "podman"),
    ask: Callable[[str], str] = reported_version,
    ask_server: Callable[[str], str] = reported_server,
) -> ContainerClient | None:
    """Which client this host should drive its containers through.

    Every candidate is asked rather than the first one that answers being
    taken, because "answers" and "can do the job" came apart on a real host:
    a Docker CLI pointed at podman answers first and cannot start a usable
    session, while the podman CLI sitting beside it can. Preferring a client
    that matches its own server picks the second without anyone having to
    know the first was there.

    A mismatched client is still returned when it is the only one, so the
    caller can refuse in that client's own terms rather than reporting a
    host with no container runtime -- which would be false, and would send
    an operator to install what they already have.

    ``None`` when no candidate answers at all, which is a real answer rather
    than an error: a host without a container client can still open an
    unconfined session, and refusing here would take that away from everyone
    who never asked for the boundary.
    """

    def probed(name: str) -> ContainerClient | None:
        try:
            reported = ask(name)
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            return None
        try:
            behind = flavor_of(ask_server(name))
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            behind = "unknown"
        return ContainerClient(binary=name, client=flavor_of(reported), server=behind)

    answered = [found for name in candidates if (found := probed(name)) is not None]
    return next(
        (found for found in answered if found.drives_its_server()),
        answered[0] if answered else None,
    )


class Image(BaseModel, frozen=True):
    """The container image and the run it is started with, declared together.

    One model rather than two, because the pair is only correct jointly. A
    ``UV_PROJECT_ENVIRONMENT`` baked into the image and a volume list supplied
    at run time have to name the same paths, and the way that stays true is
    that one declaration answers both.
    """

    base: str = Field(
        default="archlinux:base",
        description=(
            "Base image, chosen for what its archive carries rather than for "
            "size. Measured against Debian stable: ``gh``, ``bun`` and ``uv`` "
            "are all absent there, so each would have to be fetched by a "
            "shell line the build executes unverified -- three holes opened "
            "in the boundary this harness exists to close. Every one of them "
            "is a signed package here, checked before it unpacks"
        ),
    )
    snapshot: str = Field(
        default="2026/08/20",
        description=(
            "Archive snapshot the distribution is pinned to, as YYYY/MM/DD. "
            "A rolling distribution is the cost of the archive above, and "
            "this is what pays it: the build resolves against "
            "archive.archlinux.org rather than today's mirrors, so rebuilding "
            "in six months installs the same versions rather than whatever "
            "has landed since. Bumping the date is a decision somebody makes "
            "and reviews, which is the property a floating base tag cannot "
            "offer because it never appears in a diff"
        ),
    )
    baseline: list[str] = Field(
        default=[
            "ca-certificates",
            "curl",
            "git",
            "jq",
            "less",
            "openssh",
            "procps-ng",
            "ripgrep",
            "fd",
            "python",
            "uv",
            "nodejs",
        ],
        description=(
            "Packages every image gets regardless of the manifest -- what a "
            "shell session needs to be usable at all, as against what this "
            "particular project's work needs. ``uv`` and ``nodejs`` are here "
            "because the registry managers stand on them: a package declared "
            "for ``uv`` or ``bun`` cannot install if the tool that installs "
            "it was itself left to a shell script. ``python`` is here for the "
            "permission dispatcher, which a native CLI starts as a bare "
            "``python3`` deliberately outside any virtual environment, so the "
            "interpreter ``uv`` manages is the one interpreter it may not "
            "use: an image carrying only that one has no policy at all"
        ),
    )
    inner_sandbox: list[str] = Field(
        default=[],
        description=(
            "What the runtime's own sandbox needs in order to run inside "
            "this one. Empty, because the launcher turns that sandbox off by "
            "name for a contained session rather than leaving it to fail, "
            "which is the posture this field's own earlier reasoning named "
            "as the alternative to filling it. Filling it was tried and "
            "measured on both halves of the claim. The false half: "
            "bubblewrap cannot mount a fresh ``/proc`` in an unprivileged "
            "container -- ``Can't mount proc on /newroot/proc: Operation not "
            "permitted`` -- so the inner boundary did not stand up. The true "
            "half: their presence silenced the CLI's 'Commands will run "
            "WITHOUT sandboxing' notice, so two packages bought quiet about "
            "a boundary that was not there, which is the cry of wolf they "
            "were installed to prevent, moved rather than stopped. A project "
            "that means to keep the inner sandbox fills this and sets the "
            "runtime's own nested-sandbox option, and should read what that "
            "option costs before it does"
        ),
    )
    project_environment: str = Field(
        default="/opt/lup/venv",
        description=(
            "``UV_PROJECT_ENVIRONMENT``, deliberately outside the mounted "
            "tree. A `.venv` inside the checkout is shared with the host "
            "through the bind mount, so host tooling and container tooling "
            "overwrite each other's interpreter paths. Container-private is "
            "the fix, and it holds under a contained-Bash architecture too"
        ),
    )
    agent_clis: list[Package] = Field(
        default=[
            Package(name="@anthropic-ai/claude-code", manager="bun", version="2.1.237"),
            Package(name="@openai/codex", manager="bun", version="0.149.0"),
        ],
        description=(
            "The agent runtimes this image carries, each pinned rather than "
            "latest so a rebuild is a decision. Every runtime the harness "
            "launches belongs here: a contained launch runs `<cli>` inside "
            "the container, so a runtime missing from this list builds an "
            "image, starts a proxy, and then fails with `not found` on the "
            "one program the session existed to run -- which is what "
            "happened to Codex while the list was one hardcoded line. The "
            "installs land in a layer the run mounts read-only, which is "
            "what stops a self-update from silently making the image "
            "disagree with this declaration"
        ),
    )
    terminal: TerminalHandoff = Field(
        default=TerminalHandoff(),
        description=(
            "Which facts about the operator's terminal cross into the "
            "session, and the editors the image carries so that the ones "
            "naming a program name one that is there. Held on the image "
            "rather than beside the launch for the same reason the mounts "
            "are: the editor list is a layer this image builds, and the "
            "variable pointing at it is only correct if the two agree"
        ),
    )
    config_home: str = Field(
        default="/cfg",
        description=(
            "Where the runtime's configuration home sits inside the "
            "container. Container-private rather than the host's, because "
            "that directory holds the credential store and the session state "
            "of every project the operator has open, none of which this "
            "session has any business reading. What has to cross is named "
            "one file at a time. Which variable points a CLI at it is that "
            "runtime's own word and arrives from its login declaration"
        ),
    )
    browser: BrowserBridge = Field(
        default=BrowserBridge(),
        description=(
            "How a sign-in URL reaches a browser on the operator's machine, "
            "which is the one thing a contained session cannot finish alone. "
            "Declared beside the egress because it is the same subject read "
            "the other way round: that says what may leave, and this is the "
            "single narrow thing that may -- a URL, on a known sign-in "
            "address, and nothing back"
        ),
    )
    credential_seed: str = Field(
        default="/opt/lup/credential-seed",
        description=(
            "Where the host's stored login is offered to the entrypoint, "
            "outside the config home rather than over it. The host file used "
            "to be bind-mounted read-only at the exact path the CLI keeps a "
            "login, which read as working -- a session started signed in -- "
            "and was not: that file is written back to, both when a login "
            "completes and when an expiring token is renewed, and a "
            "read-only mount refused both. It also shadowed whatever the "
            "config volume held, so a login made inside was invisible the "
            "next launch. Offered here instead, and copied in once"
        ),
    )
    registry_root: str = Field(
        default="/opt/bun",
        description=(
            "``BUN_INSTALL``: where bun keeps what it installs globally. "
            "Outside any home directory, because the build installs as root "
            "and the session runs as the host's uid -- and root's home is "
            "mode 750, so a global toolchain left there is installed into a "
            "directory the session user cannot enter. The build owns this "
            "path to the session's uid for the same reason"
        ),
    )

    def registry_bin(self) -> str:
        """Where globally installed executables land, for PATH.

        A directory on PATH rather than each tool linked by name: a list of
        names goes stale the moment a package is added, which it did, leaving
        `tsc` installed and unreachable.
        """
        return f"{self.registry_root}/bin"

    registries: list[Registry] = Field(
        default=[
            Registry(manager="bun", command="bun add -g"),
            Registry(manager="uv", command="uv tool install"),
        ],
        description=(
            "The managers that install by registry name, in the order their "
            "layers are built. ``script`` is deliberately absent: a manager "
            "listed here installs something whose version was pinned and "
            "whose integrity the lockfile recorded, and a shell line is "
            "neither"
        ),
    )
    forge: GitAccess = Field(
        default=GitAccess(),
        description=(
            "How this session reaches a remote, and what its commits claim. "
            "Part of this declaration for the same reason the egress is: the "
            "credential the container is given and the rewrite that makes it "
            "reachable are one fact, and a launcher holding half of it is "
            "how a session ends up with a token and an ssh remote it cannot "
            "use the token on"
        ),
    )
    egress: SessionEgress = Field(
        default=SessionEgress(),
        description=(
            "How the session reaches the network. Part of this declaration "
            "rather than the launcher's because the network the session "
            "attaches to and the proxy the environment points at are one "
            "fact spelled twice, and a launcher holding half of it is how a "
            "session ends up on an internal network with no way out of it"
        ),
    )
    caches: list[CacheVolume] = Field(
        default=[
            CacheVolume(
                name="lup-uv",
                path="/cache/uv",
                variable="UV_CACHE_DIR",
                because="a `uv sync` at every container start, re-downloading "
                "the whole dependency tree without it",
            ),
            CacheVolume(
                name="lup-bun",
                path="/cache/bun",
                variable="BUN_INSTALL_CACHE_DIR",
                because="`bunx tsc` and any `bun add` at container start, "
                "re-fetching every package without it",
            ),
            CacheVolume(
                name="lup-ruff",
                path="/cache/ruff",
                variable="RUFF_CACHE_DIR",
                because="ruff re-analysing every file on each check otherwise",
            ),
        ],
        description="Directories that outlive the container, to bound rebuild cost",
    )
    published_ports: list[int] = Field(
        default=[],
        description=(
            "Ports the session's container publishes to the host, so a human "
            "can open what the agent is serving. Empty by default, because "
            "publishing is the one hole in a container's surface that faces "
            "the operator's own machine and most projects serve nothing. A "
            "project doing frontend work names its dev ports here and gets "
            "them; the agent's own `curl localhost:<port>` needs nothing "
            "from this list, because that traffic never leaves the container"
        ),
    )
    pids_limit: int = Field(
        default=4096,
        description=(
            "How many processes the session may hold, spelled rather than "
            "left to the engine's default for the reason the egress proxy "
            "spells its own: a bound a reader can see in the argv is a bound "
            "somebody can argue with, where an absent flag is a bound nobody "
            "knows the value of. Measured, and the reason this is not "
            "optional -- a Docker CLI driving a podman engine is given "
            "``pids.max=1`` when the flag is absent, and a container that may "
            "hold one process cannot fork, so the entrypoint dies on its "
            "first `mkdir` with `fork: Resource temporarily unavailable` and "
            "nothing in the message names a limit. 4096 because a session "
            "runs a toolchain rather than one program: a `uv sync`, a test "
            "run and a language server are each many processes, and the "
            "number is a runaway backstop rather than a budget"
        ),
    )
    trusted_projects: list[Path] = Field(
        default=[],
        description=(
            "Checkout paths trusted *in addition to* the one the container is "
            "started against, which the entrypoint adds on its own. Normally "
            "empty, and worth understanding before filling: a fresh config "
            "home starts every workspace untrusted, and an untrusted "
            "workspace has its `permissions.allow` entries *ignored* with a "
            "notice rather than an error -- 'Ignoring 10 permissions.allow "
            "entries ... this workspace has not been trusted'. So a container "
            "that starts clean each time starts with the policy those entries "
            "encode silently switched off. Measured, and the reason the "
            "entrypoint seeds at all. What does *not* belong here is a list "
            "built by enumerating sibling directories: that bakes host paths "
            "into a portable image and rebuilds the layer whenever one "
            "appears"
        ),
    )

    def packages(self, manifest: Manifest) -> list[Package]:
        """Everything the image installs: baseline, editors, then declared.

        Deduplicated with declaration order kept, so a rebuild does not
        invalidate a layer because two lists mentioned one package. The
        baseline is spelled as bare names, which parse as distribution
        packages -- correct for every one of them, and the reason the short
        spelling exists.

        The editors come off the terminal handoff rather than being listed in
        the baseline, so that the list an image installs and the list a launch
        matches an ``EDITOR`` against are one list. Written twice, they come
        apart in the direction that is hardest to see: the launch forwards a
        name it believes is carried, the layer never installed it, and the
        operator's editor fails to open with the runtime blamed for it.
        """
        return list(
            dict.fromkeys(
                [
                    *(Package(name=name) for name in self.baseline),
                    *(Package(name=name) for name in self.inner_sandbox),
                    *self.terminal.packages(),
                    *manifest.packages(),
                ]
            )
        )

    def obtained_by(self, manifest: Manifest, manager: PackageManager) -> list[Package]:
        """The packages one ecosystem is responsible for, in declaration order."""
        return [item for item in self.packages(manifest) if item.manager == manager]

    def environment(self) -> EnvVars:
        """Every variable the image bakes in, cache pointers included.

        :data:`~lup.harness.environment.NON_INTERACTIVE_SHELL_ENV` first, and
        baked rather than passed, because a container is a spawn point like
        any other and was the one that got missed: the launch and resolver
        flows merged these at every place they start a command, and a session
        inside the image started with none of them. What that cost is a
        credential prompt with no terminal to answer it -- the failure the
        whole forge design exists to head off, reintroduced at the one spot
        nothing was measuring. Baked, so anything that starts this image gets
        it: a probe and a one-off ``run`` are as unattended as a session.

        ``LUP_CONTAINED`` is how the policy inside learns there is a boundary
        under it. Baked into the image rather than passed at run time because
        it is a fact about where the process is, not a posture a caller
        chooses: a session that could switch it off from the outside would be
        telling the policy to relax with nothing underneath.

        ``LANG`` is baked at the handoff's fallback and overwritten at run
        time by whatever the operator's terminal answered. Both, because the
        two cover different callers: a launch carries the operator's own
        locale across, and anything that starts this image directly -- a
        probe, a one-off ``run`` -- still gets UTF-8 rather than the ASCII an
        unset ``LANG`` means.
        """
        return {
            **NON_INTERACTIVE_SHELL_ENV,
            **self.browser.environment(),
            "LUP_CONTAINED": "1",
            "LANG": self.terminal.fallback_locale,
            "UV_PROJECT_ENVIRONMENT": self.project_environment,
            "UV_LINK_MODE": "copy",
            **{
                name: value
                for cache in self.caches
                for name, value in cache.environment().items()
            },
        }

    def dockerfile(self, manifest: Manifest) -> str:
        """Render the image as a Dockerfile.

        Layered by how often each part changes: the OS toolchain is baked in
        and rebuilt when the manifest changes, the pinned CLI sits above it,
        and the project's own dependencies are installed at container *start*
        into a cache volume rather than copied in. That last choice is what
        makes ``uv add`` cost a sync instead of a rebuild, and it is also why
        no ``COPY`` of the project appears here -- the checkout arrives as a
        mount, at its own absolute path, for the reason
        ``same_path_mount_requirement`` explains.
        """
        installed = " \\\n        ".join(
            item.name for item in self.obtained_by(manifest, "pacman")
        )
        generated = self.terminal.generated()
        locales = (
            "\n# The locales the terminal handoff carries, compiled so that an\n"
            "# operator's own `LANG` names one that exists here. A forwarded\n"
            "# locale glibc cannot find is answered by falling back to ASCII and\n"
            "# warning once per program, which costs a session its box drawing\n"
            "# and blames neither the image nor the launch.\n"
            "RUN printf '%s\\n' \\\n        "
            + " \\\n        ".join(f"'{item.line()}'" for item in generated)
            + " >> /etc/locale.gen \\\n    && locale-gen\n"
            if generated
            else ""
        )
        registry_layers = "".join(
            f"\n# The {registry.manager} half of the toolchain, "
            f"pinned and integrity-checked.\n"
            f"RUN {registry.command} "
            f"{' '.join(item.requested() for item in obtained)}\n"
            for registry in self.registries
            if (obtained := self.obtained_by(manifest, registry.manager))
        )
        script_layer = "".join(
            f"\n# {item.name}: installed by an unverified shell line, which the\n"
            f"# package-install-script rule refuses. Present because it was declared.\n"
            f"RUN {item.command}\n"
            for item in self.obtained_by(manifest, "script")
        )
        agent_clis = " ".join(item.requested() for item in self.agent_clis)
        opening = self.browser.script(self.egress.shares_host_loopback())
        # Quoted, because `ENV name=value` takes whitespace as separating
        # *more* pairs: an unquoted `GIT_SSH_COMMAND=ssh -o BatchMode=yes`
        # makes `-o` a name with no value and the whole file unparseable.
        # JSON is the quoting, since its escapes are the ones this parser
        # reads and nothing here wants shell expansion -- `PATH`, which does,
        # is written literally a few lines up.
        exported = "\n".join(
            f"ENV {name}={json.dumps(value)}"
            for name, value in self.environment().items()
        )
        volumes = "\n".join(f"VOLUME {cache.path}" for cache in self.caches)
        seed = json.dumps(self.seed_configuration(), indent=2)
        return f"""\
# Generated from the project's Manifest. Edit the declaration, not this file.
FROM {self.base}

# Pin the archive before anything resolves against it, so every layer below
# sees one snapshot rather than whichever mirror answered first.
RUN printf '%s\\n' \\
        'Server=https://archive.archlinux.org/repos/{self.snapshot}/$repo/os/$arch' \\
        > /etc/pacman.d/mirrorlist \\
    && pacman -Syu --noconfirm

# The OS toolchain, from the same roster the host preflight exercises. Signed
# by the distribution and verified before it unpacks.
RUN pacman -S --noconfirm --needed \\
        {installed} \\
    && pacman -Scc --noconfirm
{locales}
# Where the registry manager installs, declared before it installs anything.
# Outside any home directory: this build runs as root and the session runs as
# the host's uid, and root's home is mode 750 -- so a global toolchain left
# there is installed into a directory the session cannot enter, which reads
# as the tool having failed to install rather than as a permission.
#
# On PATH as a directory rather than each tool linked by name, because a list
# of names goes stale the moment a package is added -- which it did, leaving
# `tsc` installed and unreachable.
ENV BUN_INSTALL={self.registry_root}
ENV PATH={self.registry_bin()}:$PATH
{registry_layers}{script_layer}
# Every agent runtime the harness launches, from the registry at a pinned
# version rather than an install script, so what lands is what the
# declaration names and the layer the run mounts read-only cannot be
# rewritten by a self-update.
RUN bun add -g {agent_clis}

# Trust, seeded where a fresh config home will find it. A workspace this
# image was built for is one the operator already decided to run, but an
# unseeded config home does not know that: it discards the declared
# `permissions.allow` with a notice and continues, so the policy is off and
# nothing failed. Seeded at start rather than baked into the config home,
# because that directory is a mount and a mount hides whatever the image put
# beneath it.
COPY <<'SEED' /opt/lup/trust-seed.json
{seed}
SEED
COPY <<'ENTRY' /usr/local/bin/lup-entrypoint
#!/bin/sh
set -e
config={self.config_home}
mkdir -p "$config"
# Said here because here is where the evidence is. A config volume filled
# under one user-namespace mapping and mounted under another belongs to a uid
# this session is not, and the shell's own report of that is `Permission
# denied` on a path -- which names neither the volume nor the mapping, and
# reads as a broken image. Nothing on the host can ask this reliably: the
# volume's directory is not always stat-able from outside, so a launcher's
# check would be silent exactly when it mattered.
if [ ! -w "$config" ]; then
  echo "lup: $config is not writable by uid $(id -u)." >&2
  echo "lup: the volume mounted there was filled by a different uid, which" >&2
  echo "lup: happens when this project's container engine or its user" >&2
  echo "lup: namespace mapping changed since the volume was created." >&2
  echo "lup: remove that volume and the next launch recreates it." >&2
  exit 1
fi
if [ ! -f "$config/.claude.json" ]; then
  # The checkout this container was started against is the one the operator
  # chose when they wrote the mount and the workdir, so it is trusted here
  # rather than enumerated at build time. Building the list from a directory
  # listing was tried: it baked thirty-one host paths into the image, granted
  # trust to directories that were not checkouts, and rebuilt the layer every
  # time a worktree appeared or went.
  jq --arg here "$PWD" \\
     '.projects[$here] = {{"hasTrustDialogAccepted": true}}' \\
     /opt/lup/trust-seed.json > "$config/.claude.json"
fi
# The stored login, copied in rather than mounted over the path it lives at.
# Only when the config home holds none that could still reach an account,
# which is what keeps the two directions from fighting: a login usable in here
# is never overwritten by the host's, and the host's file is never written by
# anything in here. After the copy this container owns its credential
# outright, so `/login` completes and an expiring token renews -- neither of
# which a read-only mount allowed.
#
# "Usable" rather than "present" because the config home outlives the
# credential in it. The volume is keyed on the repository and kept, the copy
# ages on its own schedule, and a home left alone past the refresh
# credential's life holds a file that is a login by every test except the one
# that matters. Read as present, it suppresses the seed and the session opens
# demanding a sign-in -- and a sign-in is the one thing this boundary cannot
# finish, because the callback comes back to a loopback address that only
# exists inside. So the seed answers the question the failure actually turns
# on, and nothing is lost by replacing a credential no request will be
# answered for: it is not a login for its own account either.
#
# What decides that is the runtime's, and arrives per launch beside the
# filename. A runtime declaring no test is taken at its word rather than
# guessed at -- it keeps the older present-or-absent rule, and a launch that
# cannot renew what it holds falls back to the printed URL.
#
# The copy replaces the file whole, which is the unit it always was, so
# whatever else the runtime keeps beside the login in there goes with it --
# Claude Code stores its MCP authorizations in this same file, and they come
# back as the host's rather than surviving as this home's. That is the price
# of the seed being a copy, and it is paid only for a home whose login had
# already stopped working.
#
# The filename is the runtime's own word and arrives per launch, because one
# image starts every runtime the harness declares and they do not agree on it.
# `-s` rather than `-f`, and a removal before the copy, because every config
# home that predates this holds an empty file at exactly this path: it was the
# mount point the old read-only bind needed, so the engine created it, and it
# belongs to the remapped uid that created it. A presence test would read that
# as a login and seed nothing, and a copy over it would be refused for the
# ownership -- the directory is ours and the file is not, so it is removed
# rather than written through. An empty credential is not a login by anyone's
# definition, so nothing is lost by replacing one.
usable() {{
  [ -s "$1" ] || return 1
  [ -n "$LUP_CREDENTIAL_RENEWABLE" ] || return 0
  jq -e "$LUP_CREDENTIAL_RENEWABLE" "$1" >/dev/null 2>&1
}}
seed={self.credential_seed}
stored="$config/$LUP_CREDENTIAL_NAME"
if [ -n "$LUP_CREDENTIAL_NAME" ] && usable "$seed" && ! usable "$stored"; then
  if [ -s "$stored" ]; then
    echo "lup: the login in this config home can no longer be renewed," >&2
    echo "lup: so it was replaced by the host's, which still can." >&2
  fi
  rm -f "$stored"
  cp "$seed" "$stored"
  chmod 600 "$stored"
fi
exec "$@"
ENTRY
RUN chmod +x /usr/local/bin/lup-entrypoint
ENTRYPOINT ["/usr/local/bin/lup-entrypoint"]

# What `BROWSER` names, so a sign-in inside can reach a browser outside. The
# pipe it writes to is mounted per launch; with nothing mounted the script
# prints the URL and returns, which is what the flow falls back to.
COPY <<'OPEN' {self.browser.opener}
{opening}
OPEN
RUN chmod +x {self.browser.opener}

# The identity the session runs as. Supplied at build time from the host's own
# uid/gid, because a bind mount carries numbers rather than names: a container
# that ran as its own root would leave root-owned files in the host checkout.
#
# Every directory the build wrote to as root and the session has to reach is
# handed over here, the registry root included. Leaving that one out is how a
# pinned toolchain ends up installed and unreachable, reported by whatever
# tried to run it rather than by the layer that misplaced it.
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID agent 2>/dev/null || true \\
    && useradd -u $UID -g $GID -m -s /bin/bash agent 2>/dev/null || true \\
    && mkdir -p {self.project_environment} {self.registry_root} \\
        {" ".join(c.path for c in self.caches)} \\
    && chown -R $UID:$GID {self.project_environment} {self.registry_root} \\
        {" ".join(c.path for c in self.caches)}

{exported}

{volumes}

USER $UID:$GID
"""

    def run_arguments(
        self,
        checkout: Path,
        uid: int,
        gid: int,
        engine: ContainerEngine = Docker(),
        proxy_address: str = "",
    ) -> list[str]:
        """The run arguments a session is started with, mounts excluded.

        The checkout is mounted at its own absolute path and cannot be mounted
        anywhere else: a linked worktree's ``.git`` is a file holding an
        absolute ``gitdir:`` pointer, so a tree mounted elsewhere is a checkout
        pointing at a path that does not exist. The rail's own mount topology
        supplies the list; this supplies everything around it.

        The identity is the ``engine``'s to spell rather than this method's,
        because the two runtimes disagree about it in a way that is fatal
        rather than cosmetic -- see :class:`ContainerEngine`. Docker is the
        default because it is the one an adopter is likeliest to have, and it
        is a default rather than an assumption: a caller that detected podman
        passes it and gets podman's spelling.

        The egress environment is passed here rather than baked into the
        image, unlike everything in :meth:`environment`. Which network a
        session runs on is a posture, and baking it would mean an operator
        who flipped the mode paid a distribution rebuild to change one
        variable -- where the paths and the project environment really are
        facts about what was built.

        ``proxy_address`` is where the proxy sits on that network, which a
        caller reads back after starting it. It cannot be anything this
        declaration holds -- it is assigned when the container joins -- and
        the earlier attempt to avoid needing it, by addressing the proxy
        under a DNS alias, is what put a resolver on the internal network and
        left the proxy unable to resolve anything at all.

        ``--init`` is what makes the bound beside it survivable, and the two
        are one subject. Without it PID 1 is the agent runtime, which does not
        reap: every child a session orphans -- a ``git`` the runtime spawned
        and stopped waiting on, a worker thread's helper -- is reparented to
        it and stays a zombie for the life of the container, so the process
        table fills monotonically and never drains. Measured in a session a
        few hours old: 4,045 zombies against a limit of 4,096, of which 3,933
        were ``[git] <defunct>``.

        What that costs is not a message about processes. It is
        ``RuntimeError: can't start new thread`` and ``fork: Resource
        temporarily unavailable`` scattered through a suite -- 94 failures and
        151 errors in one run -- which reads exactly like the change under
        test having broken something, and cost a whole bisection of a change
        that was fine. Both engines take the flag and put a real reaper at PID
        1, so the class stops existing rather than being watched for.
        """
        return [
            *engine.identity_arguments(uid, gid),
            *self.egress.attachment_arguments(checkout.name),
            "--init",
            "--pids-limit",
            str(self.pids_limit),
            *[
                argument
                for port in self.published_ports
                for argument in ("-p", f"{port}:{port}")
            ],
            "-w",
            str(checkout),
            *[
                argument
                for cache in self.caches
                for argument in cache.mount_arguments()
            ],
            *[
                argument
                for name, value in (
                    self.environment() | self.egress.environment(proxy_address)
                ).items()
                for argument in ("-e", f"{name}={value}")
            ],
        ]

    def ide_bridge(self, config_home: Path) -> list[str]:
        """Mount the host's IDE lockfile directory into the container's config.

        The editor extension finds a running session by reading lockfiles under
        ``CLAUDE_CONFIG_DIR/ide``. With the CLI in a container and the editor on
        the host, that directory is on the wrong side and ``/ide`` stops
        working. Bridging the one directory is narrower than sharing the config
        home, which holds the credential store.
        """
        return ["-v", f"{config_home / 'ide'}:{self.config_home}/ide:rw"]

    def session_arguments(
        self,
        *,
        tag: str,
        checkout: Path,
        uid: int,
        gid: int,
        writable: Mapping[Path, str],
        read_only: Mapping[Path, str],
        state_volume: str,
        config_home_env: str,
        credential_file: str = ".credentials.json",
        credential_renewable: str = "",
        credential: Path | None = None,
        host_config_home: Path | None = None,
        engine: ContainerEngine = Docker(),
        forge_token: str = "",
        rewrites: list[RemoteRewrite] | None = None,
        identity: GitIdentity | None = None,
        browser_directory: Path | None = None,
        terminal: EnvVars | None = None,
        interactive: bool = True,
        proxy_address: str = "",
    ) -> list[str]:
        """The whole argv that opens one agent session inside a container.

        Assembled here rather than at the launcher because every part of it
        has to agree with a part of the image: the config home the entrypoint
        seeds, the caches the build chowned, the environment the layers
        baked. A launcher that spelled these itself would be a second
        declaration of the same facts, free to drift from this one.

        ``state_volume`` carries the config home across launches. A container
        that started clean each time would re-seed trust every launch, and --
        measured -- an unseeded config home discards the workspace's declared
        ``permissions.allow`` with a notice rather than an error, so the
        policy would be off with nothing having failed.

        ``credential`` is offered read-only at :attr:`credential_seed` and
        copied into the config home by the entrypoint when that home holds
        none that could still be renewed -- ``credential_renewable`` is the
        runtime's own test for that, and an empty one keeps the older rule of
        seeding only an absent login. It used to be mounted read-only at the
        path the CLI keeps a login, which looked right and was not: the CLI writes that file back
        both when a login completes and when it renews an expiring token, so
        a read-only mount meant `/login` could not finish inside the boundary
        and a long session could not renew what it started with. The mount
        also shadowed the config volume's own copy, so a login made in here
        was gone by the next launch.

        The agent can read the credential either way, which is not a leak
        this could close: an agent that can open a session can reach whatever
        opens one. The scope is the boundary, not the secrecy. What the copy
        does close is the other direction -- nothing in here writes the
        host's file -- at the cost of the two diverging, which is what makes
        signing in as somebody else inside possible at all.

        ``terminal`` is what :meth:`TerminalHandoff.for_host` answered on this
        machine, passed rather than resolved here for the reason every host
        fact in this file is passed: the declaration is hashed, and a
        ``TERM`` read inside it would report a generated tree stale for having
        been checked from a different terminal.

        ``interactive`` is what a probe turns off. The same argv has to open a
        session and carry an exercise, because an exercise that ran through a
        differently-assembled argv would verify a container no session opens
        -- but a probe's output is captured rather than shown, and ``-it``
        against a pipe fails on the terminal it was promised.
        """
        mounts = [
            argument
            for host, inside in writable.items()
            for argument in ("-v", f"{host}:{inside}:rw")
        ] + [
            argument
            for host, inside in read_only.items()
            for argument in ("-v", f"{host}:{inside}:ro")
        ]
        seeded = (
            [
                "-v",
                f"{credential}:{self.credential_seed}:ro",
                "-e",
                f"LUP_CREDENTIAL_NAME={credential_file}",
                "-e",
                f"LUP_CREDENTIAL_RENEWABLE={credential_renewable}",
            ]
            if credential is not None
            else []
        )
        bridged = (
            self.ide_bridge(host_config_home) if host_config_home is not None else []
        )
        opening = (
            ["-v", f"{browser_directory}:{self.browser.inside}:rw"]
            if browser_directory is not None
            else []
        )
        # The forge configuration is passed rather than baked, and passed
        # here rather than through `run_arguments`, because it is the one
        # part of the run that is neither an image fact nor a posture: it is
        # a secret and a resolution of *this host's* remotes, and neither
        # belongs in a layer anybody could pull.
        reaching = self.forge.environment(forge_token, rewrites or [], identity) | (
            terminal or {}
        )
        return [
            engine.binary,
            "run",
            "--rm",
            *(["-it"] if interactive else []),
            "-v",
            f"{state_volume}:{self.config_home}",
            "-e",
            f"{config_home_env}={self.config_home}",
            *self.run_arguments(checkout, uid, gid, engine, proxy_address),
            *[
                argument
                for name, value in reaching.items()
                for argument in ("-e", f"{name}={value}")
            ],
            *mounts,
            *seeded,
            *bridged,
            *opening,
            tag,
        ]

    def seed_configuration(self) -> JsonObject:
        """The container-side ``.claude.json`` a fresh config home starts from.

        Without this the workspace is untrusted and its declared permissions
        are discarded with a notice. Seeding is the whole fix, and it belongs
        beside the image rather than in a launch script because the paths it
        names are the paths the mount table names.
        """
        return {
            "hasCompletedOnboarding": True,
            "projects": {
                str(project): {"hasTrustDialogAccepted": True}
                for project in self.trusted_projects
            },
        }
