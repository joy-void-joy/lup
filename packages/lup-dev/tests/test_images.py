"""The room's image: its definition byte for byte, and a build through a scripted podman.

No test runs podman: each podman command is answered by the script, and the build's
time passes on the test's clock.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup.programs import Ran
from lup.rooms.container import Image
from lup.rooms.engine import ContainerError, Podman, Process
from lup_dev import Core, Modules, Packages
from lup_dev.catalog.room import RoomBase
from lup_dev.declaration.kinds import Package
from lup_dev.declaration.project import Project
from lup_dev.declaration.resolve import resolve
from lup_dev.launch.images import Build, ImageError, build, definition, fetched
from lup_dev.layout import PyrightLayout
from lup_dev.pyright_source import Fetching

if TYPE_CHECKING:
    from conftest import FakeClock

IMAGE = Image(definition="FROM archlinux\n", project="/srv/lup.git")
OLDER = "localhost/lup-room:0123"


def test_the_definition_installs_every_package_from_the_pinned_day() -> None:
    base = RoomBase(
        image="docker.io/library/archlinux:base-20260105.0.1@sha256:abc",
        snapshot=date(2026, 1, 5),
    )
    packages = [
        Package(name="git", why="version control"),
        Package(name="noto-fonts-cjk", why="pages set Japanese text"),
        Package(name="libc++", why="a name pacman takes as it is"),
    ]

    assert definition(packages, base) == (
        "FROM docker.io/library/archlinux:base-20260105.0.1@sha256:abc\n"
        "RUN echo 'Server = https://archive.archlinux.org/repos/2026/01/05/$repo/os/$arch'"
        " > /etc/pacman.d/mirrorlist \\\n"
        "    && pacman -Syu --noconfirm --needed -- git noto-fonts-cjk libc++ \\\n"
        "    && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \\\n"
        "    && locale-gen \\\n"
        "    && rm -rf /var/cache/pacman/pkg/*\n"
    )


def test_with_man_db_the_man_pages_are_kept_the_base_s_extracted_and_indexed() -> None:
    packages = [
        Package(name="git", why="version control"),
        Package(name="man-db", why="reads a manual"),
    ]

    assert definition(packages, RoomBase()) == (
        f"FROM {RoomBase().image}\n"
        "RUN echo 'Server = https://archive.archlinux.org/repos/2026/08/15/$repo/os/$arch'"
        " > /etc/pacman.d/mirrorlist \\\n"
        "    && echo 'NoExtract = !usr/share/man/man*' >> /etc/pacman.conf \\\n"
        "    && pacman -Syu --noconfirm --needed -- git man-db \\\n"
        "    && missing=$(pacman -Qkq"
        """ | awk '$2 ~ "^/usr/share/man/man" { print $1 }' | sort -u) \\\n"""
        "    && pacman -Sw --noconfirm -- $missing \\\n"
        "    && pacman -Sp --print-format /var/cache/pacman/pkg/%f -- $missing"
        " | xargs -I {} bsdtar -xf {} -C / 'usr/share/man/man*' \\\n"
        "    && mandb --quiet \\\n"
        "    && echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen \\\n"
        "    && locale-gen \\\n"
        "    && rm -rf /var/cache/pacman/pkg/*\n"
    )


def test_the_man_pages_steps_follow_the_install_and_precede_the_cache_s_end() -> None:
    text = definition([Package(name="man-db", why="reads a manual")], RoomBase())
    steps = [line.strip().removeprefix("&& ") for line in text.splitlines()[1:]]

    order = ["echo 'NoExtract", "pacman -Syu", "missing=", "mandb", "rm -rf"]
    places = [
        next(at for at, step in enumerate(steps) if step.startswith(each))
        for each in order
    ]
    assert places == sorted(places)


def test_the_default_modules_packages_are_installed() -> None:
    packages = resolve(Project()).packages
    text = definition(packages, RoomBase())
    installing = next(line for line in text.splitlines() if "pacman -Syu" in line)

    for each in packages:
        assert f" {each.name} " in f"{installing} "
    assert "nodejs" in installing
    assert "uv" in installing
    assert "mandb --quiet" in text


def test_a_room_without_man_db_keeps_no_man_pages() -> None:
    project = Project(
        modules=Modules.default().edit(
            Core(
                packages=Packages()
                .drop("man-db", why="nobody reads them here")
                .drop("man-pages", why="nor these")
            )
        )
    )
    text = definition(resolve(project).packages, RoomBase())

    assert "NoExtract" not in text
    assert "mandb" not in text
    assert "bsdtar" not in text


def test_a_name_the_shell_would_read_is_quoted() -> None:
    text = definition([Package(name="a b;rm", why="hostile")], RoomBase())
    assert "-- 'a b;rm' \\" in text


TOOLS = [
    Package(name="git", why="clones pyright's source"),
    Package(name="pnpm", why="installs pyright's dependencies"),
]


def test_pyright_s_source_is_a_step_of_its_own_after_the_packages() -> None:
    fetching = Fetching(release="1.1.414", age=timedelta(days=3))

    text = definition(TOOLS, RoomBase(), fetching)

    assert text == definition(TOOLS, RoomBase()) + fetched(fetching)
    assert [line.split()[0] for line in text.splitlines() if line[0] != " "] == [
        "FROM",
        "RUN",
        "RUN",
    ]


def test_another_release_changes_pyright_s_step_alone() -> None:
    one = definition(TOOLS, RoomBase(), Fetching(release="1.1.414")).split("RUN ")
    other = definition(TOOLS, RoomBase(), Fetching(release="1.1.415")).split("RUN ")

    assert one[:2] == other[:2]
    assert one[2] != other[2]


def test_pyright_s_step_installs_in_a_home_of_its_own_under_the_package_age() -> None:
    place = PyrightLayout(home=Path("/opt/lup/pyright"))
    fetching = Fetching(release="1.1.414", age=timedelta(hours=36))

    text = fetched(fetching, place)

    steps = text.removeprefix("RUN ").removesuffix("\n").split(" \\\n    && ")
    home = place.downloads("1.1.414").home
    assert steps[2:4] == [
        f"mkdir -p {home}/.config/pnpm",
        (
            "printf '%s\\n' '# lup'\"'\"'s package age, from the declaration'\"'\"'s "
            "`Core.package_age`: a project'\"'\"'s own `pnpm-workspace.yaml` outranks it.' "
            f"'minimumReleaseAge: 2160' > {home}/.config/pnpm/config.yaml"
        ),
    ]
    install = fetching.install(place.downloads("1.1.414"))
    assert steps[4] == f"HOME={home} {' '.join(install)}"
    assert steps[5:] == [
        f"rm -rf {home}",
        "echo 1.1.414 > /opt/lup/pyright/1.1.414/.lup-installed",
    ]


def test_a_room_not_building_the_engine_carries_no_pyright() -> None:
    assert "pyright" not in definition(resolve(Project()).packages, RoomBase())


class Script:
    """Answers podman's commands as a build sees them, each recorded."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        exists: bool,
        listed: list[dict[str, object]],
        removal: int = 0,
    ) -> None:
        self.clock = clock
        self.exists = exists
        self.listed = listed
        self.removal = removal
        self.commands: list[list[str]] = []

    def __call__(self, process: Process) -> Ran:
        arguments = process.arguments[1:]
        self.commands.append(arguments)
        match arguments:
            case ["image", "exists", *_]:
                return Ran(command=process.arguments, status=0 if self.exists else 1)
            case ["build", *_]:
                self.clock.sleep(50)
                return Ran(command=process.arguments, status=0)
            case ["images", *_]:
                return Ran(
                    command=process.arguments,
                    status=0,
                    output=json.dumps(self.listed).encode(),
                )
            case ["image", "rm", *_]:
                return Ran(command=process.arguments, status=self.removal)
            case _:
                pytest.fail(f"podman asked {arguments}")


def stored(name: str, ident: str, size: int, containers: int) -> dict[str, object]:
    return {
        "Id": ident,
        "Names": [name],
        "Size": size,
        "Containers": containers,
        "Created": 1791846953,
    }


def test_a_build_is_recorded_and_the_unused_older_images_go(
    tmp_path: Path, clock: FakeClock
) -> None:
    script = Script(
        clock,
        exists=False,
        listed=[
            stored(IMAGE.tag, "new", 1_640_000_000, 0),
            stored(OLDER, "old-unused", 1_500_000_000, 0),
            stored("localhost/lup-room:4567", "old-running", 1_500_000_000, 1),
        ],
    )
    record = tmp_path / "state" / "rooms" / "builds.jsonl"

    built = build(IMAGE, Podman(execute=script), clock, record)

    expected = Build(
        tag=IMAGE.tag,
        project="/srv/lup.git",
        finished=datetime(2026, 10, 1, 12, 0, 50, tzinfo=UTC),
        duration=timedelta(seconds=50),
        size=1_640_000_000,
    )
    assert built == expected
    assert [
        Build.model_validate_json(line) for line in record.read_text().splitlines()
    ] == [expected]
    assert [command[:2] for command in script.commands] == [
        ["image", "exists"],
        ["build", "--tag"],
        ["images", "--filter"],
        ["image", "rm"],
    ]
    assert script.commands[-1] == ["image", "rm", "old-unused"]


def test_each_build_adds_a_line(tmp_path: Path, clock: FakeClock) -> None:
    record = tmp_path / "builds.jsonl"
    for _ in range(2):
        script = Script(clock, exists=False, listed=[stored(IMAGE.tag, "new", 1, 0)])
        build(IMAGE, Podman(execute=script), clock, record)

    assert len(record.read_text().splitlines()) == 2


def test_an_image_already_built_costs_one_question(
    tmp_path: Path, clock: FakeClock
) -> None:
    script = Script(clock, exists=True, listed=[])
    record = tmp_path / "builds.jsonl"

    assert build(IMAGE, Podman(execute=script), clock, record) is None
    assert script.commands == [["image", "exists", IMAGE.tag]]
    assert not record.exists()


def test_a_build_podman_doesnt_list_is_refused(
    tmp_path: Path, clock: FakeClock
) -> None:
    script = Script(clock, exists=False, listed=[stored(OLDER, "old", 1, 0)])

    with pytest.raises(ImageError, match="doesn't list it"):
        build(IMAGE, Podman(execute=script), clock, tmp_path / "builds.jsonl")


def test_an_older_image_podman_wont_remove_is_said(
    tmp_path: Path, clock: FakeClock
) -> None:
    script = Script(
        clock,
        exists=False,
        listed=[stored(IMAGE.tag, "new", 1, 0), stored(OLDER, "old", 1, 0)],
        removal=2,
    )
    record = tmp_path / "builds.jsonl"

    with pytest.raises(ContainerError, match="couldn't remove the image old"):
        build(IMAGE, Podman(execute=script), clock, record)
    assert len(record.read_text().splitlines()) == 1
