"""A file tool's write, judged before it lands."""

from pathlib import Path
from typing import TYPE_CHECKING

from lup_dev.inbox.store import ChangedFile, Text
from lup_dev.policy.before import Decision, Overwrite, Replacement, before
from lup_dev.policy.checkpoint import Session, SessionStarted
from lup_dev.policy.holds import Holds, Response
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.policy.worktrees import Place, place
from lup_dev.stored import read_model

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


def test_an_edit_with_a_finding_is_allowed_and_remembered_for_its_checkpoint(
    kit: Kit, repo: Path
) -> None:
    decision = before(
        kit.bench, replace(repo, "return x\n", "return x  # BAD regex\n"), "s1", repo
    )
    assert decision.outcome == "allow"
    assert decision.reason == ""
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [pending.path for pending in session.pending] == [CORE]
    assert not (repo / ".lup" / "saved").exists()


def test_a_write_that_asks_is_held_for_the_operator_and_let_through_on_a_yes(
    kit: Kit, repo: Path
) -> None:
    was = (repo / CORE).read_text()
    write = Overwrite(call="w1", tool="Write", path=repo / CORE, text=was + "\n")
    decision = before(kit.bench, write, "s1", repo)
    [hold] = kit.announced.holds
    assert kit.announced.files == [
        [ChangedFile(path=CORE, before=Text(text=was), after=Text(text=was + "\n"))]
    ]
    assert decision == Decision(outcome="allow")
    assert [each.asks for each in hold.files] == [
        [f"the write replaces the whole of {repo}/src/pkg/core.py"]
    ]
    assert hold.diff.startswith("--- a/src/pkg/core.py\n+++ b/src/pkg/core.py\n")
    assert kit.announced.runtimes == ["asking"]
    assert (hold.call, hold.agent) == ("w1", None)
    session = read_model(kit.layout.store(repo).session("s1"), Session)
    assert session is not None
    assert [(each.path, each.asked) for each in session.pending] == [(CORE, True)]


def test_a_held_write_declined_never_lands_its_version_saved_the_comment_told(
    kit: Kit, repo: Path
) -> None:
    kit.announced.answering = Response(approved=False, comment="use the other module")
    original = (repo / CORE).read_text()
    write = Overwrite(call="w1", tool="Write", path=repo / CORE, text=original + "\n")
    decision = before(kit.bench, write, "s1", repo)
    saved = repo / ".lup/saved/1/src/pkg/core.py"
    assert decision.outcome == "deny"
    assert decision.reason == (
        "lup refused 1 file. It is unchanged; your version is saved.\n\n"
        f"{repo}/src/pkg/core.py (saved at {saved})\n"
        "  The operator declined it: use the other module"
    )
    assert saved.read_text() == original + "\n"
    assert (repo / CORE).read_text() == original


def test_a_held_write_left_unanswered_is_denied_and_its_hold_stays_open(
    kit: Kit, repo: Path
) -> None:
    kit.announced.answering = None
    write = Overwrite(
        call="w1", tool="Write", path=repo / CORE, text=(repo / CORE).read_text() + "\n"
    )
    decision = before(kit.bench, write, "s1", repo)
    [hold] = kit.announced.holds
    assert decision.outcome == "deny"
    assert "Nobody answered in time" in decision.reason
    kept = Holds(layout=kit.layout.store(repo)).get(hold.key)
    assert kept is not None
    assert kept.abandoned


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
    before(kit.bench, edit, "s1", repo)
    [hold] = kit.announced.holds
    assert [each.asks for each in hold.files] == [
        [f"{repo}/src/pkg/sneaked.py is a new production file"]
    ]


def test_each_edit_is_logged(kit: Kit, repo: Path) -> None:
    before(
        kit.bench, replace(repo, "return x\n", "return x  # BAD regex\n"), "s1", repo
    )
    [verdict] = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (verdict.tool, verdict.outcome, verdict.session) == ("Edit", "allow", "s1")
    assert verdict.reasons == ["regex"]
    assert (verdict.worktree, verdict.path) == (repo, CORE)
