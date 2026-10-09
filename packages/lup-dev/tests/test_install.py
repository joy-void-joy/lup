"""Installing the judge: the review of its source, the answer, and the record."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.catalog.gate import Step
from lup_dev.install import (
    Answer,
    Approval,
    ChangedFile,
    Declined,
    Installed,
    Installer,
    InstallError,
    LineComment,
    Review,
    Reviewer,
    Terminal,
    Toolchain,
    Unchanged,
    Uv,
)
from lup_dev.layout import CheckoutLayout, Layout
from lup_dev.policy.store import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable

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

    def __init__(
        self, answer: Answer, *, meanwhile: Callable[[], None] | None = None
    ) -> None:
        self.given = answer
        self.meanwhile = meanwhile
        self.seen: list[Review] = []

    def answer(self, review: Review) -> Answer:
        self.seen.append(review)
        if self.meanwhile is not None:
            self.meanwhile()
        return self.given


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
    answer: Answer | None = None,
    runtimes: list[FakeRuntime] | None = None,
    meanwhile: Callable[[], None] | None = None,
) -> Installer:
    return Installer(
        checkout=checkout,
        layout=kit.layout,
        toolchain=Recording(),
        reviewer=Answering(answer or Answer(approved=True), meanwhile=meanwhile),
        clock=kit.clock,
        runtimes=list(runtimes or []),
    )


def asked(installing: Installer) -> list[Review]:
    assert isinstance(installing.reviewer, Answering)
    return installing.reviewer.seen


def seen(installing: Installer) -> Review:
    [review] = asked(installing)
    return review


def recording(installing: Installer) -> Recording:
    assert isinstance(installing.toolchain, Recording)
    return installing.toolchain


def changed(review: Review) -> dict[str, ChangedFile]:
    return {str(each.path): each for each in review.files}


def test_the_first_install_shows_every_file_the_judge_carries_whole(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    installing = installer(checkout, kit)
    outcome = installing.install()
    review = seen(installing)
    assert review.since is None
    assert sorted(changed(review)) == [
        "packages/lup-dev/checker/build.py",
        "packages/lup-dev/pyproject.toml",
        "packages/lup-dev/src/lup_dev/__init__.py",
        "packages/lup/pyproject.toml",
        "packages/lup/src/lup/__init__.py",
        "uv.lock",
    ]
    environment = changed(review)["packages/lup-dev/src/lup_dev/__init__.py"]
    assert environment.before is None
    assert environment.after == '"""The environment."""\n'
    assert environment.kind() == "created"
    assert review.shortstat == "6 files changed, 9 insertions(+)"
    assert "whole, since no copy was approved yet" in review.heading()
    assert recording(installing).built == [checkout]
    assert recording(installing).installed == [checkout]
    head = shell.git(checkout, "rev-parse", "HEAD")
    approval = Approval(commit=head, time=kit.clock.now(), checkout=checkout)
    assert outcome == Installed(
        approval=approval, since=None, answer=Answer(approved=True)
    )
    assert installing.approved() == approval


def test_a_refresh_shows_each_changed_file_whole_on_both_sides(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    installer(checkout, kit).install()
    first = shell.git(checkout, "rev-parse", "HEAD")
    (checkout / "packages/lup-dev/src/lup_dev/__init__.py").write_text(
        '"""Changed."""\n'
    )
    (checkout / "packages/lup-dev/src/lup_dev/made.py").write_text('"""Made."""\n')
    (checkout / "uv.lock").unlink()
    (checkout / "docs/note.md").write_text("# Changed\n")
    shell.commit(checkout, "second")
    installing = installer(checkout, kit)
    installing.install()
    review = seen(installing)
    assert review.since == first
    files = changed(review)
    assert sorted(files) == [
        "packages/lup-dev/src/lup_dev/__init__.py",
        "packages/lup-dev/src/lup_dev/made.py",
        "uv.lock",
    ]
    modified = files["packages/lup-dev/src/lup_dev/__init__.py"]
    assert modified.before == '"""The environment."""\n'
    assert modified.after == '"""Changed."""\n'
    assert modified.kind() == "modified"
    assert files["packages/lup-dev/src/lup_dev/made.py"].kind() == "created"
    assert files["uv.lock"].before == "version = 1\n"
    assert files["uv.lock"].after is None
    assert files["uv.lock"].kind() == "deleted"
    assert review.shortstat == "3 files changed, 2 insertions(+), 2 deletions(-)"
    assert review.heading() == (
        f"The judge at {review.commit}: its source since {first}, the commit you "
        f"approved last: {review.shortstat}."
    )


def test_a_rename_is_a_deletion_and_a_creation(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    installer(checkout, kit).install()
    shell.git(
        checkout,
        "mv",
        "packages/lup-dev/src/lup_dev/__init__.py",
        "packages/lup-dev/src/lup_dev/moved.py",
    )
    shell.commit(checkout, "rename")
    installing = installer(checkout, kit)
    installing.install()
    files = changed(seen(installing))
    assert files["packages/lup-dev/src/lup_dev/__init__.py"].kind() == "deleted"
    assert files["packages/lup-dev/src/lup_dev/moved.py"].kind() == "created"


def test_nothing_changed_stops_before_building_or_asking(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    approved = installer(checkout, kit).install()
    first = shell.git(checkout, "rev-parse", "HEAD")
    (checkout / "docs/note.md").write_text("# Changed\n")
    shell.commit(checkout, "docs only")
    head = shell.git(checkout, "rev-parse", "HEAD")
    installing = installer(checkout, kit)
    outcome = installing.install()
    assert outcome == Unchanged(commit=head, since=first)
    assert outcome.report() == (
        f"Nothing the judge carries changed between {first}, the commit you approved "
        f"last, and {head}: nothing to review or install."
    )
    assert asked(installing) == []
    assert recording(installing).built == []
    assert recording(installing).installed == []
    assert isinstance(approved, Installed)
    assert installing.approved() == approved.approval


def test_a_declined_copy_isnt_installed_and_the_approved_one_stays(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    approved = installer(checkout, kit).install()
    first = shell.git(checkout, "rev-parse", "HEAD")
    (checkout / "packages/lup/src/lup/__init__.py").write_text('"""Changed."""\n')
    shell.commit(checkout, "second")
    head = shell.git(checkout, "rev-parse", "HEAD")
    comment = LineComment(
        path=Path("packages/lup/src/lup/__init__.py"),
        first=1,
        last=1,
        side="before",
        note="keep this",
    )
    answer = Answer(approved=False, note="not yet", comments=[comment])
    installing = installer(checkout, kit, answer=answer)
    outcome = installing.install()
    assert outcome == Declined(commit=head, since=first, answer=answer)
    assert outcome.report().splitlines() == [
        (
            f"Declined: the judge at {head} isn't installed, and the copy installed "
            "before keeps judging."
        ),
        "Your note:",
        "    not yet",
        "Your line comments:",
        f"  packages/lup/src/lup/__init__.py:1 (before, at {first}): keep this",
    ]
    assert recording(installing).built == [checkout]
    assert recording(installing).installed == []
    assert isinstance(approved, Installed)
    assert installing.approved() == approved.approval


def test_an_installed_report_carries_the_note_and_comments(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    comment = LineComment(
        path=Path("a.py"), first=3, last=5, side="after", note="tidy\nthis"
    )
    answer = Answer(approved=True, note="fine\n\nby me", comments=[comment])
    outcome = installer(checkout, kit, answer=answer).install()
    head = shell.git(checkout, "rev-parse", "HEAD")
    assert outcome.report().splitlines() == [
        f"Installed the judge at {head}; it judges from here on.",
        "Your note:",
        "    fine",
        "",
        "    by me",
        "Your line comments:",
        "  a.py:3-5 (after): tidy",
        "    this",
    ]


def test_head_moving_during_the_review_refuses_the_install(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    def landed() -> None:
        (checkout / "packages/lup/src/lup/__init__.py").write_text('"""Landed."""\n')
        shell.commit(checkout, "a branch landed")

    installing = installer(checkout, kit, meanwhile=landed)
    with pytest.raises(InstallError, match=r"moved from \w+ to \w+ during the review"):
        installing.install()
    assert recording(installing).installed == []
    assert installing.approved() is None


def test_judge_source_changed_during_the_review_refuses_the_install(
    checkout: Path, kit: Kit
) -> None:
    def edited() -> None:
        (checkout / "packages/lup/src/lup/__init__.py").write_text('"""Edited."""\n')

    installing = installer(checkout, kit, meanwhile=edited)
    with pytest.raises(InstallError, match="changes not committed"):
        installing.install()
    assert recording(installing).installed == []


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
    assert isinstance(installer(checkout, kit).install(), Installed)


def test_a_file_that_isnt_text_refuses_the_review(
    checkout: Path, kit: Kit, shell: Shell
) -> None:
    (checkout / "packages/lup-dev/src/lup_dev/blob.bin").write_bytes(b"\xff\xfe\x00")
    shell.commit(checkout, "binary")
    installing = installer(checkout, kit)
    with pytest.raises(InstallError, match=r"blob\.bin isn't UTF-8 text"):
        installing.install()
    assert asked(installing) == []


def test_an_agent_doesnt_approve_its_own_judge(
    checkout: Path, kit: Kit, runtimes: list[FakeRuntime]
) -> None:
    runtimes[0].within = True
    installing = installer(checkout, kit, runtimes=runtimes)
    with pytest.raises(InstallError, match="inside a first session"):
        installing.install()
    assert recording(installing).built == []


def test_an_approved_commit_gone_from_the_repository_shows_everything(
    checkout: Path, kit: Kit
) -> None:
    gone = Approval(commit="0" * 40, time=kit.clock.now(), checkout=checkout)
    write_model(kit.layout.approval, gone)
    installing = installer(checkout, kit)
    installing.install()
    assert seen(installing).since is None
    assert "packages/lup/src/lup/__init__.py" in changed(seen(installing))


def test_the_terminal_shows_each_file_under_its_own_header_coloured(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    questions: list[str] = []

    def confirm(question: str, *, default: bool) -> bool:
        questions.append(question)
        return default

    monkeypatch.setattr("typer.confirm", confirm)
    before = "".join(f"line {number}\n" for number in range(1, 11))
    after = before.replace("line 5\n", "line five\n")
    review = Review(
        since="a" * 40,
        commit="b" * 40,
        files=[
            ChangedFile(path=Path("src/edited.py"), before=before, after=after),
            ChangedFile(path=Path("src/made.py"), before=None, after="made\n"),
            ChangedFile(path=Path("src/same.py"), before="same\n", after="same\n"),
        ],
        shortstat="3 files changed, 2 insertions(+), 1 deletion(-)",
    )
    answer = Terminal().answer(review)
    shown = capsys.readouterr().out
    assert answer == Answer(approved=False)
    assert questions == [f"Install the judge at {'b' * 40} as the one that runs?"]
    assert "src/edited.py  modified  +1 -1" in shown
    assert "src/made.py  created  +1 -0" in shown
    assert "Its text is unchanged." in shown
    assert "@@ -2,7 +2,7 @@" in shown
    assert "\x1b[31m-line 5" in shown
    assert "\x1b[32m+line five" in shown
    assert " line 4" in shown
    assert " line 1\n" not in shown
    assert shown.index("src/edited.py") < shown.index("src/made.py")


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


def test_the_review_waits_in_the_checkout_under_the_approved_commit() -> None:
    layout = CheckoutLayout(root=Path("/work/lup"))
    assert layout.install_review("abc") == Path("/work/lup/.lup/install-review/abc")
    assert layout.install_review(None) == Path("/work/lup/.lup/install-review/whole")


@pytest.mark.parametrize("arguments", [["install"], ["install", "--in-terminal"]])
def test_lup_dev_install_says_so_in_one_line_when_nothing_changed(
    checkout: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shell: Shell,
    arguments: list[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("LUP_INTERIM_REVIEW_LEGACY_CHECKOUT", str(tmp_path / "none"))
    head = shell.git(checkout, "rev-parse", "HEAD")
    layout = Layout(state=tmp_path / "xdg" / "lup")
    approval = Approval(
        commit=head, time=datetime(2026, 10, 1, tzinfo=UTC), checkout=checkout
    )
    write_model(layout.approval, approval)
    monkeypatch.chdir(checkout)
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        (
            f"Nothing the judge carries changed between {head}, the commit you "
            f"approved last, and {head}: nothing to review or install."
        )
    ]
    assert read_model(layout.approval, Approval) == approval


def test_lup_dev_install_refuses_inside_a_session(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.chdir(checkout)
    result = CliRunner().invoke(cli.app, ["install"])
    assert isinstance(result.exception, InstallError)
    assert not Layout(state=tmp_path / "xdg" / "lup").approval.exists()
