"""Which posture one launch opens its session under, and where each part came from.

Every setting a launch resolves reaches it from up to four places, each
overriding the one after it: the launch's own flags, the mode it was
launched in, this machine's ``sync.json.local``, and the project's own
declaration. A mode outranks the machine because it is chosen by name for
this launch, and a flag outranks the mode because it is typed for this one
launch alone. The value alone is not enough to report: an operator reading
``Network: host`` needs to know whether they asked for it a moment ago or a
file they forgot about did, so every setting travels with its origin and the
banner says both.

The network and the memory limit shape the container, so they apply to a
contained launch and are said as such. The permission settings shape the
runtime, and a value that stops a runtime asking or confining —
:func:`~lup.harness.posture.unconfining` — applies from a declared layer
only inside the container: a launch on the host leaves a machine default
naming one behind, and refuses a mode naming one before it opens anything.
"""

from typing import Literal

import typer
from pydantic import BaseModel, ValidationError

from lup.devtools.sync import SessionDefaults
from lup.harness.image import ContainerPrivileges, Image, MemoryLimit
from lup.harness.models import Harness, SessionMode
from lup.harness.notice import Notice
from lup.harness.posture import (
    ClaudePermissionMode,
    CodexApprovalPolicy,
    CodexSandboxMode,
    unconfining,
)
from lup.sandbox.models import NetworkMode

type Origin = Literal["flag", "mode", "machine", "project"]
"""Which of the four layers a setting was taken from."""


def origin_said(origin: Origin, flag: str) -> str:
    """Where a setting came from, in the words a banner line ends on."""
    match origin:
        case "flag":
            return f"from {flag}"
        case "mode":
            return "from the mode"
        case "machine":
            return "from sync.json.local"
        case "project":
            return "declared by the project"


class Chosen[T](BaseModel, frozen=True):
    """One setting's value, and the layer that supplied it."""

    value: T
    origin: Origin

    def said(self, flag: str) -> str:
        """Where this came from, as the banner says it."""
        return origin_said(self.origin, flag)


def chosen[T](
    flag: T | None, mode: T | None, machine: T | None, project: T | None = None
) -> Chosen[T] | None:
    """The first layer that says anything: flag, mode, machine, then project."""
    if flag is not None:
        return Chosen[T](value=flag, origin="flag")
    if mode is not None:
        return Chosen[T](value=mode, origin="mode")
    if machine is not None:
        return Chosen[T](value=machine, origin="machine")
    if project is not None:
        return Chosen[T](value=project, origin="project")
    return None


def settled[T](
    flag: T | None, mode: T | None, machine: T | None, project: T
) -> Chosen[T]:
    """The first layer that says anything, where the project always says something."""
    return chosen(flag, mode, machine, None) or Chosen[T](
        value=project, origin="project"
    )


def memory_limit(spelled: str, where: str) -> MemoryLimit:
    """A limit written as text, parsed, or refused in the words of where it was."""
    try:
        return MemoryLimit.model_validate(spelled)
    except ValidationError as error:
        raise typer.BadParameter(
            f"{where}: {spelled!r} is not a memory limit — write an amount "
            "such as 12g or 512m, or a share such as 75%"
        ) from error


class LaunchOverrides(BaseModel, frozen=True):
    """What one launcher invocation's own flags asked for, and nothing else."""

    network: NetworkMode | None = None
    memory: MemoryLimit | None = None
    permission_mode: ClaudePermissionMode | None = None
    approval_policy: CodexApprovalPolicy | None = None
    sandbox_mode: CodexSandboxMode | None = None
    services: dict[str, int] = {}


class SettingOrigins(BaseModel, frozen=True):
    """Where a container's network and memory limit came from, for its banner.

    Apart from the settings because the container's builder reads the
    resolved image and needs only the half of the answer a banner line ends
    on. A worker's container, built with no launch around it, takes the
    default: everything it runs under was declared by the project.
    """

    network: Origin = "project"
    memory: Origin = "project"
    services: Origin = "project"
    privileges: Origin = "project"


class SessionSettings(BaseModel, frozen=True):
    """Every setting one launch resolved, each carrying the layer it came from."""

    network: Chosen[NetworkMode]
    memory: Chosen[MemoryLimit] | None = None
    permission_mode: Chosen[ClaudePermissionMode] | None = None
    approval_policy: Chosen[CodexApprovalPolicy] | None = None
    sandbox_mode: Chosen[CodexSandboxMode] | None = None
    bash_sandbox: Chosen[bool] | None = None
    privileges: Chosen[ContainerPrivileges] | None = None
    services: Chosen[dict[str, int]] | None = None
    """The host ports named services were moved to, by a machine or a launch.

    One origin for the whole map, the highest layer that moved any of them:
    a launch's flag moves one service and leaves the machine's say about the
    rest standing, so the two are merged rather than one replacing the other.
    """

    @classmethod
    def resolved(
        cls,
        harness: Harness,
        machine: SessionDefaults | None = None,
        flags: LaunchOverrides = LaunchOverrides(),
        mode: SessionMode | None = None,
    ) -> "SessionSettings":
        """Join the four layers: flag, then mode, then machine, then project.

        ``machine`` is what this machine's registry said, passed rather than
        read here, so a probe standing in for a launch hands in the answer
        that launch reads and a test hands in whichever it means. The project
        declares the network and the limit on its image and no permission
        posture at all: a normal session runs on each runtime's own.
        """
        defaults: SessionDefaults = machine or {}
        posture = mode.posture if mode is not None else None
        written = defaults.get("memory")
        machine_memory = (
            memory_limit(written, "sync.json.local session.memory")
            if written is not None
            else None
        )
        network: Chosen[NetworkMode] = settled(
            flags.network,
            mode.network if mode is not None else None,
            defaults.get("network"),
            harness.image.egress.mode,
        )
        return cls(
            network=network,
            memory=chosen(
                flags.memory,
                mode.memory if mode is not None else None,
                machine_memory,
                harness.image.memory,
            ),
            permission_mode=chosen(
                flags.permission_mode,
                posture.permission_mode if posture is not None else None,
                defaults.get("permission_mode"),
            ),
            approval_policy=chosen(
                flags.approval_policy,
                posture.approval_policy if posture is not None else None,
                defaults.get("approval_policy"),
            ),
            sandbox_mode=chosen(
                flags.sandbox_mode,
                posture.sandbox_mode if posture is not None else None,
                defaults.get("sandbox_mode"),
            ),
            bash_sandbox=chosen(
                None, posture.bash_sandbox if posture is not None else None, None
            ),
            privileges=chosen(
                None, mode.privileges if mode is not None else None, None
            ),
            services=moved_services(harness, defaults.get("services", {}), flags),
        )

    def image(self, declared: Image) -> Image:
        """The declared image with this launch's container settings in it.

        Everything downstream reads the image, so resolving onto it once is
        what keeps the proxy, the argv and the probe on one answer rather
        than each consulting the layers again.
        """
        return declared.model_copy(
            update={
                "egress": declared.egress.model_copy(
                    update={"mode": self.network.value}
                ),
                "memory": self.memory.value if self.memory is not None else None,
                "privileges": (
                    self.privileges.value
                    if self.privileges is not None
                    else declared.privileges
                ),
                "services": (
                    declared.services.with_ports(self.services.value)
                    if self.services is not None
                    else declared.services
                ),
            }
        )

    def origins(self) -> SettingOrigins:
        """Where the container's own settings came from."""
        return SettingOrigins(
            network=self.network.origin,
            memory=self.memory.origin if self.memory is not None else "project",
            services=self.services.origin if self.services is not None else "project",
            privileges=(
                self.privileges.origin if self.privileges is not None else "project"
            ),
        )


def moved_services(
    harness: Harness, machine: dict[str, int], flags: LaunchOverrides
) -> Chosen[dict[str, int]] | None:
    """The host ports a machine and a launch moved named services to, merged.

    Checked against the declaration here, before anything is generated, so
    an override naming no declared service stops the launch in the words of
    where it was written rather than reaching a relay that does not exist.
    """
    moved = {**machine, **flags.services}
    if not moved:
        return None
    try:
        harness.image.services.with_ports(moved)
    except ValueError as refusal:
        where = (
            "--host-service" if flags.services else "sync.json.local session.services"
        )
        raise typer.BadParameter(f"{where}: {refusal}") from refusal
    return Chosen[dict[str, int]](
        value=moved, origin="flag" if flags.services else "machine"
    )


def applied[T: str | bool](
    setting: Chosen[T] | None, contained: bool
) -> Chosen[T] | None:
    """A permission setting as this launch applies it, or nothing.

    A flag always stands: somebody typed it for this launch. A declared
    value stands too unless it is one only a container may stand in for and
    the launch is on the host, where nothing else would be there.
    """
    if setting is None or contained or setting.origin == "flag":
        return setting
    return None if unconfining(setting.value) else setting


def permission_notices[T: str | bool](
    setting: Chosen[T] | None, contained: bool, runtime: str, flag: str, noun: str
) -> list[Notice]:
    """What a launch says about one permission setting, applied or left behind."""
    if setting is None:
        return []
    if applied(setting, contained) is None:
        return [
            Notice(
                text=(
                    f"{noun}: {setting.value} ({setting.said(flag)}) applies "
                    f"inside the container only; this host launch keeps "
                    f"{runtime}'s own default"
                ),
                urgency="boundary",
            )
        ]
    return [
        Notice(
            text=f"{noun}: {setting.value} ({setting.said(flag)})",
            urgency="boundary",
        )
    ]
