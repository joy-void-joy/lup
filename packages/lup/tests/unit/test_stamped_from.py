"""Which commit of lup a project was stamped from, read out of git.

The two ways a project comes from lup leave opposite evidence. A clone
carries lup's own commits, so the commit is in its history. A repository made
with GitHub's "Use this template" carries none of them: GitHub copies the
template's files into one fresh root commit, with no parent and no remote
naming the template, and what survives of the commit it copied is the tree.
What is tested is that each is read the way it has to be, in both layouts a
checkout comes in -- a bare repository with its worktree under `tree/main`,
and a plain clone -- and that where no tree matches, the nearest is offered as
the estimate it is.

Every repository is built rather than mocked, because what is read is git's
own history, and a bare repository stands in for the forge. What is stubbed is
`gh`, which is the forge's answer about templates rather than git's.
"""

import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

import lup.devtools.dev.origin as origin
from lup.devtools import sync
from lup.devtools.dev.scaffold import extracted
from lup.devtools.utils import short_sha
from lup.execution.shell import git
from tests.unit.test_ledger_placement import committed, repository
from tests.unit.test_scaffold import wrote

type Layout = Literal["bare", "plain"]


class Forge(BaseModel, frozen=True):
    """lup as the forge holds it, and the commits a test names."""

    repository: Path
    """The bare repository standing in for the forge's."""

    stamped: str
    """The commit a project is made from."""

    tip: str
    """Where main stands after lup moved on past it."""


def lup_on_the_forge(tmp_path: Path) -> Forge:
    """A history that moved on past the commit a project was made from."""
    work = repository(tmp_path / "lup")
    wrote(work, "packages/lup/src/lup/__init__.py", '"""lup."""\n')
    wrote(work, "src/lup_template/serve.py", "serve = 1\n")
    wrote(work, "README.md", "lup\n")
    committed(work, "the scaffold")
    wrote(work, "src/lup_template/serve.py", "serve = 2\n")
    wrote(work, "docs/guide.md", "a guide\n")
    committed(work, "serve two")
    stamped = git.out("-C", str(work), "rev-parse", "HEAD")
    wrote(work, "docs/later.md", "later\n")
    committed(work, "later docs")
    tip = git.out("-C", str(work), "rev-parse", "HEAD")
    bare = tmp_path / "forge" / "lup.git"
    git("clone", "--bare", "--quiet", str(work), str(bare))
    return Forge(repository=bare, stamped=stamped, tip=tip)


def generated(tmp_path: Path, lup: Forge, commit: str) -> Path:
    """What "Use this template" makes of ``commit``: one root commit, its tree.

    The files are the template's at that commit and nothing of its history
    comes along, which is the whole difference from a fork -- so the tree
    the new repository's only commit holds is asserted to be that commit's,
    the one fact the reading rests on.
    """
    work = repository(tmp_path / "generating")
    extracted(lup.repository, commit, work)
    committed(work, "Initial commit")
    assert git.out("-C", str(work), "rev-parse", "HEAD^{tree}") == git.out(
        "-C", str(lup.repository), "rev-parse", f"{commit}^{{tree}}"
    )
    bare = tmp_path / "forge" / "project.git"
    git("clone", "--bare", "--quiet", str(work), str(bare))
    return bare


def checked_out(source: Path, destination: Path, layout: Layout) -> Path:
    """A checkout of ``source``: bare with its worktree at `tree/main`, or plain."""
    match layout:
        case "bare":
            git("clone", "--bare", "--quiet", str(source), str(destination))
            git("-C", str(destination), "worktree", "add", "--quiet", "tree/main")
            return destination / "tree" / "main"
        case "plain":
            git("clone", "--quiet", str(source), str(destination))
            return destination


def renamed(checkout: Path) -> None:
    """The commit initialization makes first, which lup has never seen."""
    wrote(checkout, "src/demo/serve.py", "serve = 2\n")
    committed(checkout, "rename the package")


def root_of(checkout: Path) -> str:
    """The commit a checkout's history starts at."""
    return git.out("-C", str(checkout), "rev-list", "--max-parents=0", "HEAD")


@pytest.mark.parametrize("layout", ["bare", "plain"])
def test_a_generated_repository_is_read_by_the_tree_its_root_commit_holds(
    tmp_path: Path, layout: Layout
) -> None:
    """lup moved on after the copy, and the reading is still the copied commit."""
    lup = lup_on_the_forge(tmp_path)
    project = checked_out(
        generated(tmp_path, lup, lup.stamped), tmp_path / "project", layout
    )
    renamed(project)

    stamp = origin.stamped_from(project, lup.repository)

    assert stamp is not None
    assert stamp == origin.Stamp(
        commit=lup.stamped, evidence="tree", carrier=root_of(project)
    )
    assert stamp.exact()


@pytest.mark.parametrize("layout", ["bare", "plain"])
def test_a_clone_is_read_by_the_newest_commit_it_shares(
    tmp_path: Path, layout: Layout
) -> None:
    """Cloned before lup moved on, with the project's own commit on top."""
    lup = lup_on_the_forge(tmp_path)
    project = checked_out(lup.repository, tmp_path / "project", layout)
    git("-C", str(project), "reset", "--quiet", "--hard", lup.stamped)
    renamed(project)

    stamp = origin.stamped_from(project, lup.repository)

    assert stamp == origin.Stamp(
        commit=lup.stamped, evidence="history", carrier=lup.stamped
    )


def test_a_root_commit_amended_after_generation_reads_as_the_nearest(
    tmp_path: Path,
) -> None:
    """The copy with its guide corrected: no commit holds that tree exactly.

    The commit after the copied one differs from it only under `docs/` as
    well, so the top-level pass reads the two alike -- and what picks the
    copy out is the second pass, counting the files that differ.
    """
    lup = lup_on_the_forge(tmp_path)
    work = repository(tmp_path / "generating")
    extracted(lup.repository, lup.stamped, work)
    wrote(work, "docs/guide.md", "a corrected guide\n")
    committed(work, "Initial commit")

    stamp = origin.stamped_from(work, lup.repository)

    assert stamp is not None
    assert stamp == origin.Stamp(
        commit=lup.stamped,
        evidence="nearest",
        carrier=root_of(work),
        differing=1,
    )
    assert not stamp.exact()
    assert "an estimate" in stamp.explained()


def test_a_repository_sharing_nothing_with_upstream_reads_as_nothing(
    tmp_path: Path,
) -> None:
    lup = lup_on_the_forge(tmp_path)
    work = repository(tmp_path / "unrelated")
    wrote(work, "notes.txt", "nothing of lup's\n")
    committed(work, "unrelated")

    assert origin.stamped_from(work, lup.repository) is None


class Gh:
    """`gh`, answering which template a repository was generated from."""

    def __init__(self, template: str | None) -> None:
        self.template = template

    def out(self, *args: str) -> str:
        document = (
            {"template_repository": {"clone_url": self.template}}
            if self.template is not None
            else {"template_repository": None}
        )
        return json.dumps(document)


def registered(
    checkout: Path,
    lup: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str | None,
) -> None:
    """The shipped registration naming the forge's lup, and the forge answering.

    The checkout's origin is named on a forge, as a clone of the project's own
    repository is, so the template is asked for rather than guessed.
    """
    (checkout / "sync.json").write_text(
        json.dumps({"projects": [{"name": "lup", "url": str(lup.repository)}]})
    )
    git("-C", str(checkout), "remote", "set-url", "origin", "git@github.com:a/b.git")
    monkeypatch.setattr(sync, "project_root", lambda: checkout)
    monkeypatch.setattr(sync, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(origin, "resolved_host", lambda alias: alias)
    monkeypatch.setattr(origin, "gh", Gh(template))


@pytest.mark.parametrize("layout", ["bare", "plain"])
def test_the_report_names_the_base_and_the_branches_holding_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    layout: Layout,
) -> None:
    """Fetched through the registration, as a first launch would clone it."""
    lup = lup_on_the_forge(tmp_path)
    project = checked_out(
        generated(tmp_path, lup, lup.stamped), tmp_path / "project", layout
    )
    registered(project, lup, tmp_path, monkeypatch, str(lup.repository))

    assert origin.report_base(project, "lup")

    printed = capsys.readouterr().out
    assert f"Base: {lup.stamped}  serve two" in printed
    assert f"main (default): 1 commit(s) past it, at {short_sha(lup.tip)}" in printed


@pytest.mark.parametrize("layout", ["bare", "plain"])
def test_a_clone_of_lup_itself_is_reported_from_its_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    layout: Layout,
) -> None:
    """Generated from no template, so the registration is read as it stands."""
    lup = lup_on_the_forge(tmp_path)
    project = checked_out(lup.repository, tmp_path / "project", layout)
    renamed(project)
    registered(project, lup, tmp_path, monkeypatch, None)

    assert origin.report_base(project, "lup")

    printed = capsys.readouterr().out
    assert f"Base: {lup.tip}  later docs" in printed
    assert "main (default): stands at it" in printed


def test_a_template_other_than_the_registration_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The base is a commit of the template, so the registration has to name it."""
    lup = lup_on_the_forge(tmp_path)
    project = checked_out(
        generated(tmp_path, lup, lup.stamped), tmp_path / "project", "plain"
    )
    registered(project, lup, tmp_path, monkeypatch, "https://github.com/a/fork.git")

    assert not origin.report_base(project, "lup")

    assert "dev init upstream" in capsys.readouterr().out
    assert not (tmp_path / "cache").exists()
