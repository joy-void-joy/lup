"""Each package manager lup knows: its package, and the user-level settings keeping the package age, from the project's own files."""

import os
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest

from lup_dev import Uv
from lup_dev.declaration.package_managers import PACKAGE_MANAGERS
from lup_dev.declaration.package_managers.manager import HomeSettings, Ungated
from lup_dev.declaration.package_managers.npm import NpmManager
from lup_dev.declaration.package_managers.pnpm import PnpmManager
from lup_dev.declaration.package_managers.uv import UvManager

THREE_DAYS = timedelta(days=3)


def settings(answer: HomeSettings | Ungated) -> HomeSettings:
    assert isinstance(answer, HomeSettings), answer
    return answer


def test_lup_knows_npm_and_uv_by_the_packages_bringing_them() -> None:
    assert [each.package for each in PACKAGE_MANAGERS] == ["npm", "pnpm", "uv"]
    assert [each.package for each in Uv.requirements] == [UvManager.package]


@pytest.mark.parametrize(
    ("age", "line"),
    [
        pytest.param(THREE_DAYS, "min-release-age=3.0", id="days"),
        pytest.param(timedelta(hours=36), "min-release-age=1.5", id="a-fraction"),
        pytest.param(timedelta(0), "min-release-age=0.0", id="none"),
    ],
)
def test_npm_keeps_the_age_in_days_in_its_npmrc_whatever_the_project(
    tmp_path: Path, age: timedelta, line: str
) -> None:
    written = settings(NpmManager().aged(tmp_path, age))
    assert written.path == Path(".npmrc")
    assert written.text.splitlines()[1:] == [line]


@pytest.mark.parametrize(
    ("age", "line"),
    [
        pytest.param(THREE_DAYS, "minimumReleaseAge: 4320", id="days"),
        pytest.param(timedelta(seconds=90), "minimumReleaseAge: 2", id="rounded-up"),
        pytest.param(timedelta(0), "minimumReleaseAge: 0", id="none"),
    ],
)
def test_pnpm_keeps_the_age_in_minutes_in_its_config_whatever_the_project(
    tmp_path: Path, age: timedelta, line: str
) -> None:
    written = settings(PnpmManager().aged(tmp_path, age))
    assert written.path == Path(".config/pnpm/config.yaml")
    assert written.text.splitlines()[1:] == [line]


def installed_at(root: Path, times: dict[Path, int]) -> None:
    """Write each of a workspace's files at `root`, last changed at its time, in seconds."""
    for path, seconds in times.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("")
        os.utime(root / path, (seconds, seconds))


@pytest.mark.parametrize(
    ("times", "stale"),
    [
        pytest.param({PnpmManager.lockfile: 1}, True, id="never-installed"),
        pytest.param(
            {
                PnpmManager.lockfile: 1,
                PnpmManager.workspace: 1,
                PnpmManager.installed: 2,
            },
            False,
            id="installed-after-both",
        ),
        pytest.param(
            {PnpmManager.lockfile: 1, PnpmManager.installed: 1},
            False,
            id="installed-as-it-changed",
        ),
        pytest.param(
            {
                PnpmManager.lockfile: 3,
                PnpmManager.workspace: 1,
                PnpmManager.installed: 2,
            },
            True,
            id="lockfile-changed-since",
        ),
        pytest.param(
            {
                PnpmManager.lockfile: 1,
                PnpmManager.workspace: 3,
                PnpmManager.installed: 2,
            },
            True,
            id="settings-changed-since",
        ),
    ],
)
def test_a_pnpm_workspace_is_stale_where_installed_before_its_lockfile_or_settings(
    tmp_path: Path, times: dict[Path, int], *, stale: bool
) -> None:
    installed_at(tmp_path, times)
    assert PnpmManager().stale(tmp_path) is stale


@pytest.mark.parametrize(
    ("files", "sets"),
    [
        pytest.param({}, False, id="no-settings"),
        pytest.param(
            {"pyproject.toml": '[project]\nname = "p"\n'}, False, id="no-tool-uv"
        ),
        pytest.param(
            {"pyproject.toml": "[tool.uv]\npackage = false\n"},
            False,
            id="tool-uv-without",
        ),
        pytest.param(
            {"pyproject.toml": '[tool.uv]\nexclude-newer = "3 days"\n'},
            True,
            id="tool-uv",
        ),
        pytest.param(
            {"uv.toml": 'exclude-newer = "2026-10-01T00:00:00Z"\n'}, True, id="uv-toml"
        ),
        pytest.param(
            {
                "uv.toml": 'exclude-newer = "1 week"\n',
                "pyproject.toml": "[tool.uv]\npackage = false\n",
            },
            True,
            id="uv-toml-over-tool-uv-without",
        ),
        pytest.param(
            {
                "uv.toml": "native-tls = true\n",
                "pyproject.toml": '[tool.uv]\nexclude-newer = "3 days"\n',
            },
            False,
            id="uv-toml-hiding-tool-uv",
        ),
    ],
)
def test_uv_gets_its_settings_only_where_the_project_sets_its_own_exclude_newer(
    tmp_path: Path, files: dict[str, str], *, sets: bool
) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    answer = UvManager().aged(tmp_path, THREE_DAYS)
    assert isinstance(answer, HomeSettings) is sets


@pytest.mark.parametrize(
    ("age", "span"),
    [
        pytest.param(THREE_DAYS, "P3D", id="days"),
        pytest.param(timedelta(hours=36), "P1DT12H", id="hours"),
        pytest.param(timedelta(days=7, minutes=30), "P7DT30M", id="minutes"),
    ],
)
def test_uv_keeps_the_age_as_an_iso_duration_in_its_user_level_uv_toml(
    tmp_path: Path, age: timedelta, span: str
) -> None:
    (tmp_path / "uv.toml").write_text('exclude-newer = "3 days"\n')
    written = settings(UvManager().aged(tmp_path, age))
    assert written.path == Path(".config/uv/uv.toml")
    assert tomllib.loads(written.text) == {"exclude-newer": span}


def test_uv_says_why_it_gets_none_naming_the_setting_to_add(tmp_path: Path) -> None:
    assert UvManager().aged(tmp_path, timedelta(hours=36)) == Ungated(
        why=(
            "This project sets no `exclude-newer` of its own for uv (its "
            "`uv.toml`, else its `pyproject.toml`'s `[tool.uv]`), so the room gets "
            "none at the user level, which would have uv relock a `uv.lock` "
            "resolved without it. `uvx`, `uv tool` and `uv pip` there install "
            'packages of any age. Add `exclude-newer = "P1DT12H"` to `[tool.uv]` '
            "to gate them, and the project's own `uv run`."
        )
    )
