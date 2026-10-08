"""A file tool's write, judged before it lands."""

from pathlib import Path
from typing import TYPE_CHECKING

from lup_dev.policy.before import Overwrite, Replacement, before
from lup_dev.policy.checkpoint import Session, SessionStarted
from lup_dev.policy.store import read_model
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.policy.worktrees import Place, place

if TYPE_CHECKING:
    from conftest import Kit, Shell

CORE = Path("src/pkg/core.py")


def replace(
    repo: Path, old: str, new: str, *, path: Path = CORE, everywhere: bool = False
) -> Replacement:
    return Replacement(
        call="e1",
        tool="Edit",
        path=repo / path,
        old=old,
        new=new,
        everywhere=everywhere,
    )


def test_a_replacement_applies_as_the_tool_does() -> None:
    once = Replacement(call="1", tool="t", path=Path("/a"), old="x", new="y")
    assert once.content("axb") == "ayb"
    assert once.content("axbx") is None
    everywhere = Replacement(
        call="1", tool="t", path=Path("/a"), old="x", new="y", everywhere=True
    )
    assert everywhere.content("axbx") == "ayby"
    assert once.content("abc") is None
    assert (
        Replacement(call="1", tool="t", path=Path("/a"), old="", new="new").content(
            None
        )
        == "new"
    )


def test_an_allowed_edit_is_remembered_until_its_call_finishes(
    kit: Kit, repo: Path
) -> None:
    decision = before(
        kit.bench, replace(repo, "return x\n", "return x + 1\n"), "s1", repo
    )
    assert decision.outcome == "allow"
    assert decision.reason == ""
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [
        (pending.call, pending.path, pending.asked) for pending in session.pending
    ] == [("e1", CORE, False)]


def test_an_edit_with_a_finding_is_refused_before_it_touches_the_file(
    kit: Kit, repo: Path
) -> None:
    original = (repo / CORE).read_text()
    decision = before(
        kit.bench, replace(repo, "return x\n", "return x  # BAD regex\n"), "s1", repo
    )
    assert decision.outcome == "refuse"
    saved = repo / ".lup/saved/1/src/pkg/core.py"
    assert decision.reason.startswith(
        "lup refused 1 file. It is unchanged; your version is saved.\n\n"
        f"{repo}/src/pkg/core.py (saved at {saved})\n"
    )
    assert (
        "Fix these lines in the saved copy, then move it into place:\n"
        f"  mv {saved} {repo}/src/pkg/core.py" in decision.reason
    )
    assert (repo / CORE).read_text() == original
    assert "# BAD regex" in (repo / ".lup" / "saved" / "1" / CORE).read_text()


def test_a_refused_new_file_comes_back_through_a_write(kit: Kit, repo: Path) -> None:
    write = Overwrite(
        call="w1",
        tool="Write",
        path=repo / "src" / "pkg" / "new.py",
        text="x = 1  # BAD regex\n",
    )
    decision = before(kit.bench, write, "s1", repo)
    assert decision.outcome == "refuse"
    assert "write the file again with your file tool" in decision.reason
    assert not (repo / "src" / "pkg" / "new.py").exists()


def test_a_whole_write_over_an_existing_file_asks(kit: Kit, repo: Path) -> None:
    write = Overwrite(
        call="w1", tool="Write", path=repo / CORE, text=(repo / CORE).read_text() + "\n"
    )
    decision = before(kit.bench, write, "s1", repo)
    assert decision.outcome == "ask"
    assert (
        decision.reason
        == f"lup asks: the write replaces the whole of {repo}/src/pkg/core.py"
    )


def test_writes_outside_the_repository_arent_judged(
    kit: Kit, repo: Path, tmp_path: Path
) -> None:
    write = Overwrite(
        call="w1", tool="Write", path=tmp_path / "elsewhere.py", text="x = 1\n"
    )
    assert before(kit.bench, write, "s1", repo).outcome is None


def test_writes_in_another_repository_arent_judged(
    kit: Kit, repo: Path, tmp_path: Path, shell: Shell
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    shell.git(other, "init", "-q")
    write = Overwrite(
        call="w1", tool="Write", path=other / "x.py", text="x = 1  # BAD regex\n"
    )
    assert before(kit.bench, write, "s1", repo).outcome is None


def test_where_a_path_is(repo: Path, linked: Path, bare: Path, tmp_path: Path) -> None:
    common = repo / ".git"
    assert place(repo / CORE) == Place(repository=common, worktree=repo, path=CORE)
    assert place(linked / "src" / "new" / "deep.py") == Place(
        repository=common, worktree=linked, path=Path("src/new/deep.py")
    )
    assert place(common / "config") == Place(
        repository=common, worktree=None, path=Path("config")
    )
    assert place(bare / "tree" / "next.py") == Place(
        repository=bare, worktree=None, path=Path("tree/next.py")
    )
    assert place(tmp_path / "nowhere.py") is None


def test_a_replacement_the_tool_would_refuse_is_allowed(kit: Kit, repo: Path) -> None:
    assert (
        before(kit.bench, replace(repo, "not there", "x"), "s1", repo).outcome
        == "allow"
    )


def test_the_edit_is_judged_against_the_accepted_state(kit: Kit, repo: Path) -> None:
    SessionStarted(session="s1", cwd=repo).apply(kit.bench)
    (repo / "src" / "pkg" / "sneaked.py").write_text(
        '"""Made by a command not yet judged."""\n'
    )
    edit = replace(repo, "Made by", "Written by", path=Path("src/pkg/sneaked.py"))
    decision = before(kit.bench, edit, "s1", repo)
    assert decision.reason == (
        f"lup asks: {repo}/src/pkg/sneaked.py is a new production file"
    )


def test_each_edit_is_logged(kit: Kit, repo: Path) -> None:
    before(
        kit.bench, replace(repo, "return x\n", "return x  # BAD regex\n"), "s1", repo
    )
    [verdict] = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (verdict.tool, verdict.outcome, verdict.session) == ("Edit", "refuse", "s1")
    assert (verdict.worktree, verdict.path) == (repo, CORE)
