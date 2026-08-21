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
from pathlib import Path

import sh
from pydantic import BaseModel, Field

from lup.harness.requirements import Manifest, Package, PackageManager
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

    Detected from the *client*, never the server. This is not a distinction
    without a difference: a Docker CLI pointed at a podman socket is a real
    configuration, and the flag is rejected by the client before the daemon
    ever sees it, so asking the daemon what it is answers the wrong question.
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


def detected_engine(
    candidates: tuple[str, ...] = ("docker", "podman"),
) -> ContainerEngine | None:
    """Which container client this host has, identified by what it calls itself.

    The version string rather than the file name, because the name is not
    reliable evidence: the ``podman-docker`` package installs a ``docker``
    that is podman, and it needs podman's identity spelling despite answering
    to the other name. Asking it who it is gets that right, where trusting
    the spelling of the path would hand podman Docker's arguments.

    ``None`` when no candidate answers, which is a real answer rather than an
    error: a host without a container client can still open an unconfined
    session, and refusing here would take that away from everyone who never
    asked for the boundary.
    """
    for name in candidates:
        try:
            reported = str(sh.Command(name)("--version"))
        except (sh.CommandNotFound, sh.ErrorReturnCode):
            continue
        return (
            Podman(binary=name) if "podman" in reported.lower() else Docker(binary=name)
        )
    return None


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
            "uv",
            "nodejs",
        ],
        description=(
            "Packages every image gets regardless of the manifest -- what a "
            "shell session needs to be usable at all, as against what this "
            "particular project's work needs. ``uv`` and ``nodejs`` are here "
            "because the registry managers stand on them: a package declared "
            "for ``uv`` or ``bun`` cannot install if the tool that installs "
            "it was itself left to a shell script"
        ),
    )
    inner_sandbox: list[str] = Field(
        default=["bubblewrap", "socat"],
        description=(
            "What the runtime's own sandbox needs in order to run inside "
            "this one. Measured: without these the CLI prints 'Sandbox "
            "disabled ... Commands will run WITHOUT sandboxing' and "
            "continues. Under a real container boundary that warning is "
            "true and harmless, which is exactly the problem -- a boundary "
            "warning that fires every launch on purpose is one operators "
            "learn to skip, and the next one will be real. Installing them "
            "keeps the inner boundary and silences a cry of wolf. Emptying "
            "this field is a posture a project may take, and it should then "
            "turn the runtime's sandbox off by name rather than leave it "
            "failing loudly"
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
    claude_version: str = Field(
        default="2.1.237",
        description=(
            "Pinned rather than latest, so a rebuild is a decision. The "
            "install lands in a layer the run mounts read-only, which is "
            "what stops a self-update from silently making the image "
            "disagree with this field"
        ),
    )
    registry_bin: str = Field(
        default="/root/.bun/bin",
        description=(
            "Where the registry managers put globally installed executables. "
            "On PATH as a directory, because linking each tool by name is a "
            "list that goes stale the moment a package is added -- which it "
            "did, leaving `tsc` installed and unreachable"
        ),
    )
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
    caches: list[CacheVolume] = Field(
        default=[
            CacheVolume(name="lup-uv", path="/cache/uv", variable="UV_CACHE_DIR"),
            CacheVolume(name="lup-npm", path="/cache/npm", variable="npm_config_cache"),
            CacheVolume(name="lup-ruff", path="/cache/ruff", variable="RUFF_CACHE_DIR"),
        ],
        description="Directories that outlive the container, to bound rebuild cost",
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
        """Everything the image installs: baseline, inner sandbox, then declared.

        Deduplicated with declaration order kept, so a rebuild does not
        invalidate a layer because two lists mentioned one package. The
        baseline is spelled as bare names, which parse as distribution
        packages -- correct for every one of them, and the reason the short
        spelling exists.
        """
        return list(
            dict.fromkeys(
                [
                    *(Package(name=name) for name in self.baseline),
                    *(Package(name=name) for name in self.inner_sandbox),
                    *manifest.packages(),
                ]
            )
        )

    def obtained_by(self, manifest: Manifest, manager: PackageManager) -> list[Package]:
        """The packages one ecosystem is responsible for, in declaration order."""
        return [item for item in self.packages(manifest) if item.manager == manager]

    def environment(self) -> EnvVars:
        """Every variable the image bakes in, cache pointers included."""
        return {
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
        exported = "\n".join(
            f"ENV {name}={value}" for name, value in self.environment().items()
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
{registry_layers}{script_layer}
# The CLI, from the registry at a pinned version rather than an install
# script, so what lands is what this declaration names and the layer the run
# mounts read-only cannot be rewritten by a self-update.
RUN bun add -g @anthropic-ai/claude-code@{self.claude_version}

# Everything bun installs globally lands here, so the directory goes on PATH
# rather than each tool being linked one at a time. Measured: linking only the
# CLI left `tsc` installed and unreachable, which reads as a failed install.
ENV PATH={self.registry_bin}:$PATH

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
config="${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}"
mkdir -p "$config"
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
exec "$@"
ENTRY
RUN chmod +x /usr/local/bin/lup-entrypoint
ENTRYPOINT ["/usr/local/bin/lup-entrypoint"]

# The identity the session runs as. Supplied at build time from the host's own
# uid/gid, because a bind mount carries numbers rather than names: a container
# that ran as its own root would leave root-owned files in the host checkout.
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID agent 2>/dev/null || true \\
    && useradd -u $UID -g $GID -m -s /bin/bash agent 2>/dev/null || true \\
    && mkdir -p {self.project_environment} {" ".join(c.path for c in self.caches)} \\
    && chown -R $UID:$GID {self.project_environment} \\
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
        """
        return [
            *engine.identity_arguments(uid, gid),
            "-w",
            str(checkout),
            *[
                argument
                for cache in self.caches
                for argument in cache.mount_arguments()
            ],
            *[
                argument
                for name, value in self.environment().items()
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
        return ["-v", f"{config_home / 'ide'}:/cfg/ide:rw"]

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
