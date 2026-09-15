"""What the device lease holds still, measured where a container would refuse.

A device reaches a container through one name and one registry, and every
assertion here is about the two staying honest: a name the engine would refuse
is refused earlier and in words, a device no spec registers is withheld rather
than handed over, and what was granted is what the argv and the ledger say.
"""

import json
from pathlib import Path

import pytest
import typer
from pydantic import ValidationError

from lup.devtools.harness.contained import record_boundary
from lup.devtools.harness.launch import declared_devices
from lup.harness.devices import (
    Device,
    DeviceLease,
    DeviceRegistry,
    lease_devices,
    registered_devices,
)
from lup.harness.egress import SessionEgress
from lup.harness.image import Podman
from lup.harness.requirements import Manifest
from lup.harness.toolchain import device_requirement, for_host
from lup.policy.assets.host import boundary_description
from lup.sandbox.rail import Lease


def registry(root: Path) -> Path:
    """One CDI spec directory with an NVIDIA spec in it, as the toolkit writes one."""
    directory = root / "etc" / "cdi"
    directory.mkdir(parents=True)
    (directory / "nvidia.yaml").write_text(
        "cdiVersion: 0.5.0\n"
        "kind: nvidia.com/gpu\n"
        "devices:\n"
        "- name: '0'\n"
        "  containerEdits:\n"
        "    deviceNodes:\n"
        "    - path: /dev/nvidia0\n"
        "- name: all\n"
        "  containerEdits:\n"
        "    deviceNodes:\n"
        "    - path: /dev/nvidia0\n"
        "containerEdits:\n"
        "  env:\n"
        "  - NVIDIA_VISIBLE_DEVICES=void\n"
    )
    return directory


@pytest.mark.parametrize(
    "name",
    [
        "nvidia.com/gpu=all",
        "nvidia.com/gpu=0",
        "nvidia.com/gpu=1:0",
        "nvidia.com/gpu=GPU-3f2c9a1e-7b4d-4c2a-9e1f-0a1b2c3d4e5f",
        "amd.com/gpu=all",
    ],
)
def test_a_device_is_named_the_way_the_specification_names_it(name: str) -> None:
    """Every spelling a vendor's toolkit registers is one the launcher takes."""
    assert Device(name=name).arguments() == ["--device", name]


@pytest.mark.parametrize(
    "name", ["all", "nvidia.com/gpu", "/dev/nvidia0", "nvidia.com/gpu=", "gpu=all"]
)
def test_a_name_the_engine_would_refuse_is_refused_at_declaration(name: str) -> None:
    """The engine refuses a whole container over a malformed name; this refuses the name."""
    with pytest.raises(ValidationError):
        Device(name=name)


def test_a_flag_naming_no_device_is_refused_in_the_launchers_words() -> None:
    """The value typed is named, with the shape it should have had."""
    with pytest.raises(typer.BadParameter, match="'all'.*nvidia.com/gpu=all"):
        declared_devices(["nvidia.com/gpu=0", "all"])


def test_declared_devices_keep_the_order_they_were_typed_in() -> None:
    assert [item.name for item in declared_devices(["a.com/x=1", "b.com/y=2"])] == [
        "a.com/x=1",
        "b.com/y=2",
    ]


def test_the_registry_reads_both_spellings_across_both_directories(
    tmp_path: Path,
) -> None:
    """A toolkit writes YAML by default and JSON on request; both engines read both."""
    static = registry(tmp_path)
    generated = tmp_path / "run" / "cdi"
    generated.mkdir(parents=True)
    (generated / "example.json").write_text(
        json.dumps(
            {
                "cdiVersion": "0.5.0",
                "kind": "example.com/accelerator",
                "devices": [{"name": "x", "containerEdits": {}}],
            }
        )
    )
    found = registered_devices([static, generated])

    assert found.names == [
        "nvidia.com/gpu=0",
        "nvidia.com/gpu=all",
        "example.com/accelerator=x",
    ]
    assert found.unreadable == []
    assert found.searched == [static, generated]


def test_a_directory_that_is_not_there_is_searched_and_answers_nothing(
    tmp_path: Path,
) -> None:
    """A host with no toolkit installed is an ordinary host, not a broken one."""
    found = registered_devices([tmp_path / "absent"])

    assert found.names == []
    assert found.searched == [tmp_path / "absent"]


def test_a_spec_that_will_not_parse_is_reported_rather_than_skipped(
    tmp_path: Path,
) -> None:
    """A file the engine cannot read is a file it refuses a device over."""
    directory = registry(tmp_path)
    (directory / "broken.yaml").write_text("kind: [unterminated\n")
    (directory / "listless.yaml").write_text("- just\n- a list\n")
    found = registered_devices([directory])

    assert found.names == ["nvidia.com/gpu=0", "nvidia.com/gpu=all"]
    assert [item.path.name for item in found.unreadable] == [
        "broken.yaml",
        "listless.yaml",
    ]
    assert all(item.reason for item in found.unreadable)


def test_a_declared_device_no_spec_registers_is_withheld_with_the_registry_named() -> (
    None
):
    """Handed to the engine, the name refuses the whole container; here it is one line."""
    leased = lease_devices(
        [Device(name="nvidia.com/gpu=all")],
        DeviceRegistry(names=[], searched=[Path("/etc/cdi"), Path("/var/run/cdi")]),
    )

    assert leased.granted == []
    assert [item.device.name for item in leased.withheld] == ["nvidia.com/gpu=all"]
    assert leased.withheld[0].reason == (
        "no CDI spec under /etc/cdi or /var/run/cdi registers it"
    )


def test_the_image_and_the_flag_naming_one_device_grant_it_once() -> None:
    """Two people asking for one GPU is one flag, not two the engine has to settle."""
    gpu = Device(name="nvidia.com/gpu=all")
    leased = lease_devices([gpu, gpu], DeviceRegistry(names=[gpu.name]))

    assert leased.granted == [gpu]


def test_a_lease_grants_in_declaration_order_and_withholds_the_rest() -> None:
    leased = lease_devices(
        [Device(name="a.com/x=1"), Device(name="b.com/y=2"), Device(name="a.com/x=3")],
        DeviceRegistry(names=["a.com/x=3", "a.com/x=1"]),
    )

    assert [item.name for item in leased.granted] == ["a.com/x=1", "a.com/x=3"]
    assert [item.device.name for item in leased.withheld] == ["b.com/y=2"]


def test_a_lease_says_nothing_when_nothing_was_declared() -> None:
    """A line saying no device was asked for grows the opening block for nobody."""
    assert DeviceLease().notices() == []


def test_a_grant_is_said_at_boundary_weight() -> None:
    said = lease_devices(
        [Device(name="nvidia.com/gpu=all")],
        DeviceRegistry(names=["nvidia.com/gpu=all"]),
    ).notices()

    assert [item.urgency for item in said] == ["boundary"]
    assert "nvidia.com/gpu=all" in said[0].text


def test_a_withheld_device_names_the_command_that_registers_it() -> None:
    """The fix is the operator's and made once on the machine, so the notice spells it."""
    said = lease_devices(
        [Device(name="nvidia.com/gpu=all")],
        DeviceRegistry(names=[], searched=[Path("/etc/cdi")]),
    ).notices()

    assert [item.urgency for item in said] == ["warning", "warning"]
    assert "withheld" in said[0].text
    assert "nvidia-ctk cdi generate" in said[1].text
    assert said[1].indent == 1


def test_the_boundary_ledger_records_the_granted_devices(tmp_path: Path) -> None:
    """A run's provenance is this file, and it has to say what the container held."""
    gpu = Device(name="nvidia.com/gpu=all")
    record_boundary(
        Lease(),
        SessionEgress(),
        tmp_path,
        lease_devices([gpu], DeviceRegistry(names=[gpu.name])),
    )

    assert boundary_description(tmp_path)["devices"] == ["nvidia.com/gpu=all"]


def test_the_boundary_ledger_records_no_device_where_none_was_granted(
    tmp_path: Path,
) -> None:
    """An absent grant is an empty list rather than an absent key, so a reader can tell."""
    record_boundary(Lease(), SessionEgress(), tmp_path)

    assert boundary_description(tmp_path)["devices"] == []


def test_a_device_requirement_proves_the_device_inside_a_container_the_client_starts() -> (
    None
):
    """The probe is carried by whichever engine this host answered with."""
    aimed = for_host(
        Manifest(
            requirements=[
                device_requirement(
                    Device(name="nvidia.com/gpu=all"),
                    witness=["nvidia-smi", "-L"],
                    purpose="the search core's population proposers",
                )
            ]
        ),
        Podman(),
    )
    exercise = aimed.requirements[0].exercise

    assert aimed.requirements[0].checked == "setup"
    assert exercise.programs() == ["podman"]
    assert isinstance(exercise.model_dump()["command"], list)
    assert exercise.model_dump()["command"][:5] == [
        "podman",
        "run",
        "--rm",
        "--device",
        "nvidia.com/gpu=all",
    ]
    assert exercise.model_dump()["command"][-2:] == ["nvidia-smi", "-L"]
