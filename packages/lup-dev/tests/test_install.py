"""Installing the judge: the review of its source, the approval, and the record."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.catalog.gate import Step
from lup_dev.install import (
    Approval,
    Installer,
    InstallError,
    Review,
    Reviewer,
    Toolchain,
    Uv,
)
from lup_dev.layout import Layout
from lup_dev.policy.store import write_model

if TYPE_CHECKING:
    from conftest import FakeRuntime, Kit, Shell

SOURCE = {
    "packages/lup/pyproject.toml": "[project]\nname = 'lup'\n",
    "packages/lup/src/lup/__init__.py": '"""The library."""\n',
    "packages/lup-dev/pyproject.toml": "[project]\nname = 'lup-dev'\n",
    "packages/lup-dev/src/lup_dev/__init__.py": '"""The environment."""\n',
    "packages/lup-dev/checker/build.py": (
        "from pathlib import Path\nPath('built').write_text('yes')\n"
    ),
    "packages/lup-dev/tests/test_a.py": "def test_a():\n    pass\n",
    "docs/note.md": "# Note\n",
    "uv.lock": "version = 1\n",
}


class Recording(Toolchain):
    """Records what it was asked to build and install."""

    built: list[Path] = []
    installed: list[Path] = []

    def build(self, checkout: Path) -> None:
        self.built.append(checkout)

    def install(self, checkout: Path) -> None:
        self.installed.append(checkout)


class Answering(Reviewer):
    """Answers every review the same way, keeping what it was shown."""

    def __init__(self, *, answer: bool) -> None:
        self.answer = answer
        self.seen: list[Review] = []

    def approves(self, review: Review) -> bool:
        self.seen.append(review)
        return self.answer


@pytest.fixture
def checkout(tmp_path: Path, shell: Shell) -> Path:
    root = tmp_path / "lup"
    for name, content in SOURCE.items():
        file = root / Path(name)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    shell.git(root, "init", "-q", "-b", "dev")
    shell.git(root, "config", "user.email", "test@example.com")
    shell.git(root, "config", "user.name", "Test")
    shell.git(root, "config", "commit.gpgsign", "false")
    shell.commit(root, "first")
    return root


def installer(
    checkout: Path,
    kit: Kit,
    *,
    answer: bool = True,
    runtimes: list[FakeRuntime] | None = None,
) -> Installer:
    return Installer(
        checkout=checkout,
        layout=kit.layout,
        toolchain=Recording(),
        reviewer=Answering(answer=answer),
        clock=kit.clock,
        runtimes=list(runtimes or []),
    )


def seen(installing: Installer) -> Review:
    assert isinstance(installing.reviewer, Answering)
    [review] = installing.reviewer.seen
    return review


def recording(installing: Installer) -> Recording:
    assert isinstance(installing.toolchain, Recording)
    return installing.toolchain


def test_the_first_install_shows_all_the_judge_carries(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    installing = installer(checkout, kit)
    approval = installing.install()
    review = seen(installing)
    assert review.since is None
    for carried in [
        "packages/lup/pyproject.toml",
        "packages/lup/src/lup/__init__.py",
        "packages/lup-dev/src/lup_dev/__init__.py",
        "packages/lup-dev/checker/build.py",
        "uv.lock",
    ]:
        assert carried in review.stat, carried
    assert "tests/test_a.py" not in review.stat
    assert "docs/note.md" not in review.stat
    assert '+"""The environment."""' in review.diff
    assert recording(installing).built == [checkout]
    assert recording(installing).installed == [checkout]
    head = shell.git(checkout, "rev-parse", "HEAD")
    assert approval == Approval(commit=head, time=kit.clock.now(), checkout=checkout)
    assert installing.approved() == approval


def test_a_refresh_shows_only_what_changed_since_the_approved_commit(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    installer(checkout, kit).install()
    first = shell.git(checkout, "rev-parse", "HEAD")
    (checkout / "packages/lup-dev/src/lup_dev/__init__.py").write_text(
        '"""Changed."""\n'
    )
    (checkout / "docs/note.md").write_text("# Changed\n")
    shell.commit(checkout, "second")
    installing = installer(checkout, kit)
    installing.install()
    review = seen(installing)
    assert review.since == first
    assert "packages/lup-dev/src/lup_dev/__init__.py" in review.stat
    assert "docs/note.md" not in review.stat
    assert review.text().startswith(
        f"The judge at {review.commit}: its source since {first}"
    )


def test_an_unchanged_judge_says_so(checkout: Path, kit: Kit, shell: Shell) -> None:
    installer(checkout, kit).install()
    (checkout / "docs/note.md").write_text("# Changed\n")
    shell.commit(checkout, "docs only")
    installing = installer(checkout, kit)
    installing.install()
    assert "Its source hasn't changed." in seen(installing).text()


def test_a_declined_copy_isnt_installed_and_the_approved_one_stays(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    approved = installer(checkout, kit).install()
    (checkout / "packages/lup/src/lup/__init__.py").write_text('"""Changed."""\n')
    shell.commit(checkout, "second")
    installing = installer(checkout, kit, answer=False)
    assert installing.install() is None
    assert recording(installing).built == [checkout]
    assert recording(installing).installed == []
    assert installing.approved() == approved


@pytest.mark.parametrize(
    "change",
    ["packages/lup-dev/src/lup_dev/__init__.py", "packages/lup-dev/src/lup_dev/new.py"],
)
def test_uncommitted_judge_source_is_refused(
    checkout: Path, kit: Kit, change: str
) -> None:
    (checkout / change).write_text("x = 1\n")
    installing = installer(checkout, kit)
    with pytest.raises(InstallError, match="changes not committed"):
        installing.install()
    assert recording(installing).built == []


def test_uncommitted_changes_elsewhere_dont_matter(checkout: Path, kit: Kit) -> None:
    (checkout / "docs/note.md").write_text("# Draft\n")
    assert installer(checkout, kit).install() is not None


def test_an_agent_doesnt_approve_its_own_judge(
    checkout: Path, kit: Kit, runtimes: list[FakeRuntime]
) -> None:
    runtimes[0].within = True
    installing = installer(checkout, kit, runtimes=runtimes)
    with pytest.raises(InstallError, match="inside a first session"):
        installing.install()
    assert recording(installing).built == []


def test_an_approved_commit_no_longer_known_shows_everything(
    checkout: Path, kit: Kit
) -> None:
    gone = Approval(commit="0" * 40, time=kit.clock.now(), checkout=checkout)
    write_model(kit.layout.approval, gone)
    installing = installer(checkout, kit)
    installing.install()
    assert seen(installing).since is None
    assert "packages/lup/src/lup/__init__.py" in seen(installing).stat


def test_uv_installs_a_copy_with_the_locks_versions(
    checkout: Path, tmp_path: Path
) -> None:
    log = tmp_path / "uv.log"
    fake = tmp_path / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--output-file" ]; then echo "pydantic==2.13.5" > "$2"; fi\n'
        f'  if [ "$1" = "--constraints" ]; then cat "$2" >> "{log}"; fi\n'
        "  shift\n"
        "done\n"
    )
    fake.chmod(0o755)
    Uv(executable=str(fake)).install(checkout)
    export, install, constraints = log.read_text().splitlines()
    assert export.startswith(
        "export --package lup-dev --no-dev --no-emit-workspace --no-hashes --frozen "
        "--format requirements-txt --quiet --output-file "
    )
    assert install.startswith("tool install --force --constraints ")
    assert install.endswith(str(checkout / "packages" / "lup-dev"))
    assert constraints == "pydantic==2.13.5"


def test_the_installer_builds_the_engine_as_the_gate_does() -> None:
    assert Uv().engine.name == "engine"
    assert Uv().engine.command[-1] == "packages/lup-dev/checker/build.py"


def test_uv_runs_the_engines_build_step(checkout: Path) -> None:
    build = [sys.executable, "packages/lup-dev/checker/build.py"]
    Uv(engine=Step(name="engine", command=build)).build(checkout)
    assert (checkout / "built").read_text() == "yes"


def test_lup_dev_install_refuses_inside_a_session(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.chdir(checkout)
    result = CliRunner().invoke(cli.app, ["install"])
    assert isinstance(result.exception, InstallError)
    assert not Layout(state=tmp_path / "xdg" / "lup").approval.exists()
