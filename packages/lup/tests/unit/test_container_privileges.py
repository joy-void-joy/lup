"""What a session may hold inside its container, and where that is decided.

A session holds nothing and gains nothing unless something says otherwise:
the image, a mode, this machine's registry, or a flag, in that order of
precedence from last to first. Administering the container — sudo, and the
file capabilities a package manager uses — is the widening a mode or a
launch asks for; what reaches past the container stays dropped however it is
asked, and a widening is refused on an engine whose container root is the
host's unless the launch accepts that by name.

What only a real container can show is left to one: that ``sudo pacman``
installs a package under the capability set here, and that a mount as the
container's root is refused. The argv that decides both is pinned here.
"""

from pathlib import Path

import pytest
import typer

from lup.devtools.harness.contained import refuse_rootful_widening
from lup.devtools.harness.posture import LaunchOverrides, SessionSettings
from lup.harness.image import ContainerPrivileges, Docker, Image, Podman
from lup.harness.models import Harness, PromptDocument, SessionMode
from lup.harness.requirements import Manifest


def test_a_session_holds_nothing_and_gains_nothing_by_default() -> None:
    arguments = ContainerPrivileges().arguments()

    assert arguments == [
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
    ]


def test_administering_gives_back_the_file_capabilities_and_sudo() -> None:
    """Every one inside both engines' own default set; none that reaches outward."""
    privileges = ContainerPrivileges.administering()
    arguments = privileges.arguments()

    given = [
        arguments[at + 1] for at, word in enumerate(arguments) if word == "--cap-add"
    ]
    assert set(given) >= {
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
        "FSETID",
        "SETUID",
        "SETGID",
        "KILL",
    }
    assert not {"SYS_ADMIN", "NET_ADMIN", "NET_RAW", "SYS_PTRACE", "MKNOD"} & set(given)
    assert "no-new-privileges:true" not in arguments
    assert privileges.sudo


@pytest.mark.parametrize(
    "reaching", ["SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "SYS_TIME"]
)
def test_a_capability_reaching_past_the_container_is_refused(reaching: str) -> None:
    with pytest.raises(ValueError, match="stay dropped"):
        ContainerPrivileges(capabilities=["CHOWN", reaching], new_privileges=True)


def test_sudo_without_new_privileges_is_refused() -> None:
    """sudo is a setuid binary, which no-new-privileges would leave inert."""
    with pytest.raises(ValueError, match="new_privileges"):
        ContainerPrivileges(sudo=True)


def harness(image: Image, *modes: SessionMode) -> Harness:
    return Harness(
        generator_version="0",
        plugins=[],
        guidance=PromptDocument(parts=[]),
        image=image,
        modes=list(modes),
    )


ADMINISTERED = SessionMode(
    name="free",
    description="Making something, the container its only wall.",
    privileges=ContainerPrivileges.administering(),
)


def test_a_mode_asking_for_sudo_needs_an_image_that_installs_it() -> None:
    with pytest.raises(ValueError, match="declare Image\\(sudo=True\\)"):
        harness(Image(), ADMINISTERED)


def test_a_flag_outranks_the_mode_and_the_mode_the_machine() -> None:
    declared = harness(Image(sudo=True), ADMINISTERED)
    mode = declared.mode("free")

    moded = SessionSettings.resolved(declared, {"sudo": False}, LaunchOverrides(), mode)
    machine = SessionSettings.resolved(declared, {"sudo": True})
    flagged = SessionSettings.resolved(
        declared, {"sudo": True}, LaunchOverrides(sudo=False), mode
    )

    assert moded.privileges is not None and moded.privileges.origin == "mode"
    assert moded.image(declared.image).privileges.sudo
    assert machine.privileges is not None and machine.privileges.origin == "machine"
    assert machine.image(declared.image).privileges.sudo
    assert flagged.privileges is not None and flagged.privileges.origin == "flag"
    assert not flagged.image(declared.image).privileges.widened()


def test_a_flag_asking_for_sudo_the_image_lacks_says_where_it_came_from() -> None:
    with pytest.raises(typer.BadParameter, match="from --sudo.*Image\\(sudo=True\\)"):
        SessionSettings.resolved(harness(Image()), None, LaunchOverrides(sudo=True))


def answering(tmp_path: Path, name: str, answer: str) -> Path:
    """A stand-in engine binary that answers ``info`` with one line."""
    binary = tmp_path / name
    binary.write_text(f"#!/bin/sh\nprintf '%s\\n' '{answer}'\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_each_engine_reads_its_own_rootless_answer(tmp_path: Path) -> None:
    rootless_docker = Docker(
        binary=str(
            answering(
                tmp_path, "docker", '["name=seccomp,profile=builtin","name=rootless"]'
            )
        )
    )
    rootful_docker = Docker(
        binary=str(answering(tmp_path, "rootful", '["name=seccomp,profile=builtin"]'))
    )
    rootless_podman = Podman(binary=str(answering(tmp_path, "podman", "true")))

    assert rootless_docker.rootless()
    assert not rootful_docker.rootless()
    assert rootless_podman.rootless()
    assert not Docker(binary=str(tmp_path / "absent")).rootless()


def test_widening_on_a_rootful_engine_is_refused_by_name(tmp_path: Path) -> None:
    rootful = Docker(binary=str(answering(tmp_path, "docker", '["name=seccomp"]')))

    with pytest.raises(typer.BadParameter, match="--allow-rootful-privileges"):
        refuse_rootful_widening(ContainerPrivileges.administering(), rootful, False)
    refuse_rootful_widening(ContainerPrivileges.administering(), rootful, True)
    refuse_rootful_widening(ContainerPrivileges(), rootful, False)


def test_an_image_installing_sudo_keeps_the_proxy_across_it() -> None:
    rendered = Image(sudo=True).dockerfile(Manifest())

    assert "pacman -S --noconfirm --needed sudo" in rendered
    assert "'ALL ALL=(ALL:ALL) NOPASSWD: ALL'" in rendered
    assert "env_keep" in rendered and "HTTPS_PROXY" in rendered
    assert "sudoers" not in Image().dockerfile(Manifest())
