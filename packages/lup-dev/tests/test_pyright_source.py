"""pyright's source for the engine's build: the release a lock pins, the fetch's commands, and which places a build reads on the host and in a room.

Nothing is fetched: the commands are compared as data, and the places are the
test's own directories.
"""

from pathlib import Path

import pytest

from lup_dev.layout import Layout, PyrightDownloads, PyrightLayout, RoomPaths
from lup_dev.pyright_source import Fetching, PyrightSourceError, Sources, pinned
from lup_dev.settings import LupDevSettings


def lock(root: Path, *versions: str) -> Path:
    """A `uv.lock` at `root` pinning pyright at each of `versions`, beside another package."""
    pins = "".join(
        f'[[package]]\nname = "pyright"\nversion = "{each}"\n\n' for each in versions
    )
    path = root / "uv.lock"
    path.write_text(
        f'version = 1\n\n{pins}[[package]]\nname = "ruff"\nversion = "0.16.10"\n'
    )
    return path


def scratch(tmp_path: Path) -> Layout:
    """lup's places, under the test's own directory."""
    return Layout(
        state=tmp_path / "state",
        cache=tmp_path / "cache" / "lup",
        data=tmp_path / "data" / "lup",
    )


def whole(place: PyrightLayout, release: str) -> None:
    """Keep `release` whole at `place`, marked as a fetch leaves it."""
    place.release(release).mkdir(parents=True)
    place.installed(release).write_text(f"{release}\n")


# The release


def test_the_release_is_the_one_the_lock_pins(tmp_path: Path) -> None:
    assert pinned(lock(tmp_path, "1.1.414")) == "1.1.414"


@pytest.mark.parametrize(
    ("versions", "said"),
    [
        pytest.param([], "pins pyright 0 times", id="none"),
        pytest.param(["1.1.414", "1.1.415"], "pins pyright 2 times", id="two"),
        pytest.param(["1.1.414; rm -rf ~"], "isn't a plain version", id="a-command"),
        pytest.param(["--upload-pack=x"], "isn't a plain version", id="an-option"),
        pytest.param(["v1.1.414"], "isn't a plain version", id="not-as-written"),
        pytest.param(["1.1.414/.."], "isn't a plain version", id="a-path"),
    ],
)
def test_a_lock_pinning_no_one_plain_release_is_refused(
    tmp_path: Path, versions: list[str], said: str
) -> None:
    with pytest.raises(PyrightSourceError, match=said):
        pinned(lock(tmp_path, *versions))


def test_a_missing_lock_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PyrightSourceError, match=r"there's no `uv\.lock`"):
        pinned(tmp_path / "uv.lock")


# The fetch


def test_the_clone_is_the_release_s_tag_alone(tmp_path: Path) -> None:
    assert Fetching(release="1.1.414").clone(tmp_path / "1.1.414") == [
        "git",
        "clone",
        "--quiet",
        "--depth",
        "1",
        "--branch",
        "1.1.414",
        "https://github.com/microsoft/pyright",
        str(tmp_path / "1.1.414"),
    ]


def test_the_install_is_pnpm_s_from_the_lockfile_with_downloads_kept_apart() -> None:
    downloads = PyrightDownloads(home=Path("/d"))
    assert Fetching(release="1.1.414").install(downloads) == [
        "env",
        "XDG_DATA_HOME=/d/data",
        "XDG_CACHE_HOME=/d/cache",
        "XDG_STATE_HOME=/d/state",
        "pnpm",
        "install",
        "--frozen-lockfile",
        "--filter",
        "pyright-internal",
    ]


# Where it's read


def test_the_host_reads_its_own_cache_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LUP_ROOM_PYRIGHT", raising=False)
    layout = scratch(tmp_path)

    sources = Sources.of(LupDevSettings(), layout)

    assert sources == Sources(fetched=layout.pyright_source)
    assert sources.fetched.home == tmp_path / "cache" / "lup" / "pyright"


def test_a_room_reads_its_image_s_then_its_project_s_rooms_never_the_host_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = scratch(tmp_path)
    rooms = layout.rooms(tmp_path / "proj.git").pyright
    for name, value in Sources.room(rooms).items():
        monkeypatch.setenv(name, value)

    sources = Sources.of(LupDevSettings(), layout)

    assert sources == Sources(
        kept=PyrightLayout(home=RoomPaths().pyright), fetched=rooms
    )


def test_the_image_s_copy_is_found_first_then_the_fetched_one(tmp_path: Path) -> None:
    image = PyrightLayout(home=tmp_path / "image")
    rooms = PyrightLayout(home=tmp_path / "rooms")
    sources = Sources(kept=image, fetched=rooms)
    whole(image, "1.1.414")
    whole(rooms, "1.1.414")
    whole(rooms, "1.1.415")

    assert sources.found("1.1.414") == image.release("1.1.414")
    assert sources.found("1.1.415") == rooms.release("1.1.415")
    assert sources.found("1.1.416") is None


def test_a_release_not_marked_whole_isn_t_found(tmp_path: Path) -> None:
    rooms = PyrightLayout(home=tmp_path / "rooms")
    rooms.release("1.1.414").mkdir(parents=True)

    assert Sources(fetched=rooms).found("1.1.414") is None


def test_a_room_s_fetch_says_what_its_image_carries_and_where_it_fetches(
    tmp_path: Path,
) -> None:
    image = PyrightLayout(home=tmp_path / "image")
    rooms = PyrightLayout(home=tmp_path / "rooms")
    whole(image, "1.1.414")
    image.partial("1.1.413").mkdir()

    said = Sources(kept=image, fetched=rooms).why("1.1.415")

    assert said.startswith(
        "the room's image carries pyright 1.1.414, and `uv.lock` pins 1.1.415: "
        f"fetching it into the project's rooms' own directory, {rooms.release('1.1.415')}"
    )
    assert Sources(fetched=rooms).why("1.1.415") == (
        f"fetching pyright 1.1.415 into {rooms.release('1.1.415')}"
    )
