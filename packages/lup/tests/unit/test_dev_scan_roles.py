"""Development scans stop at roots whose purpose is retained data."""

from pathlib import Path

import pytest

from lup.devtools.dev import antipatterns, boundaries
from lup.devtools.project import DevProject
from lup.policy.kernel.rows import PathRoleRow


class GitListing:
    """The file inventory both scans receive from Git."""

    def lines(self, *_args: str) -> list[str]:
        return ["src/app.py", "notes/jobs/generated.py"]

    def __call__(self, *_args: str) -> str:
        return "src/app.py\nnotes/jobs/generated.py\n"


@pytest.fixture
def data_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DevProject:
    (tmp_path / "src").mkdir()
    (tmp_path / "notes/jobs").mkdir(parents=True)
    (tmp_path / "src/app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "notes/jobs/generated.py").write_text(
        "payload = 'large'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    listing = GitListing()
    monkeypatch.setattr(antipatterns, "git", listing)
    monkeypatch.setattr(boundaries, "git", listing)
    return DevProject(
        package="app",
        path_roles=[PathRoleRow(root="notes", role="data")],
    )


def test_antipatterns_skip_data_roots(data_project: DevProject) -> None:
    assert [item.rel for item in antipatterns.scanned_files(data_project)] == [
        "src/app.py"
    ]


def test_boundaries_skip_data_roots(data_project: DevProject) -> None:
    assert [item.rel for item in boundaries.tracked_python_sources(data_project)] == [
        "src/app.py"
    ]
