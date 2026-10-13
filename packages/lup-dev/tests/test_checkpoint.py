"""The checkpoint: when it runs, what it judges, and what it does about it."""

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sh
from filelock import FileLock

from lup_dev import Project
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.codescan.contract import FileReport, Finding, Position, Span
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Drop
from lup_dev.declaration.resolve import Declaration, Selected
from lup_dev.declaration.runner import Plain, Prefixed
from lup_dev.policy.before import Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    Reply,
    Session,
    SessionStarted,
    TurnEnded,
    Worktree,
)
from lup_dev.policy.holds import Holds, Response, answer, waiting
from lup_dev.policy.importers import Conversation, ImportersPass
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import FakeRuntime, Kit, Shell

CORE = Path("src/pkg/core.py")
SESSION = "s1"


def start(kit: Kit, repo: Path, session: str = SESSION) -> None:
    SessionStarted(session=session, cwd=repo).apply(kit.bench)


def call(
    kit: Kit, repo: Path, key: str, *, tool: str = "Bash", agent: str = ""
) -> None:
    CallStarted(
        session=SESSION,
        agent=agent,
        cwd=repo,
        call=key,
        tool=tool,
        spawns=tool == "Agent",
    ).apply(kit.bench)


def call_for(session: str, kit: Kit, repo: Path, key: str) -> None:
    """A shell call another session makes."""
    CallStarted(session=session, cwd=repo, call=key, tool="Bash").apply(kit.bench)


def finish(
    kit: Kit, repo: Path, key: str, *, agent: str = "", session: str = SESSION
) -> Reply:
    return CallFinished(session=session, agent=agent, cwd=repo, call=key).apply(
        kit.bench
    )


def end(
    kit: Kit, repo: Path, session: str = SESSION, *, after_block: bool = False
) -> Reply:
    return TurnEnded(session=session, cwd=repo, after_block=after_block).apply(
        kit.bench
    )


def subagent_ends(kit: Kit, repo: Path, agent: str) -> Reply:
    return ConversationEnded(session=SESSION, agent=agent, cwd=repo).apply(kit.bench)


def worktree(kit: Kit, repo: Path) -> Worktree:
    return Worktree.at(repo, kit.layout)


def session(kit: Kit, repo: Path) -> Session:
    found = read_model(worktree(kit, repo).store.layout.session(SESSION), Session)
    assert found is not None
    return found


def shell_write(kit: Kit, repo: Path, key: str, path: Path, content: str) -> Reply:
    """A shell call that writes `path`, judged when it finishes."""
    call(kit, repo, key)
    (repo / path).write_text(content)
    return finish(kit, repo, key)


def log(kit: Kit, repo: Path) -> VerdictLog:
    return worktree(kit, repo).verdicts(kit.layout)


def test_a_write_with_a_finding_is_put_back_and_saved(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    original = (repo / CORE).read_text()
    mine = original + "y = 2  # BAD regex\n"
    reply = shell_write(kit, repo, "c1", CORE, mine)
    assert reply.context.startswith(
        "lup refused 1 file. It is unchanged; your version is saved."
    )
    assert f"{repo}/src/pkg/core.py:11:8 - regex: regex fires here" in reply.context
    saved = repo / ".lup/saved/1/src/pkg/core.py"
    assert f"mv {saved} {repo}/src/pkg/core.py" in reply.context
    assert (repo / CORE).read_text() == original
    assert (repo / ".lup" / "saved" / "1" / CORE).read_text() == mine


def test_the_put_back_file_isnt_judged_again(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    shell_write(
        kit, repo, "c1", CORE, (repo / CORE).read_text() + "y = 2  # BAD regex\n"
    )
    call(kit, repo, "c2")
    assert finish(kit, repo, "c2").context == ""


def test_an_allowed_write_becomes_the_accepted_state(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    changed = (repo / CORE).read_text().replace("return x", "return x + 1")
    assert shell_write(kit, repo, "c1", CORE, changed).context == ""
    store = worktree(kit, repo).store
    assert store.content(store.accepted(), CORE) == changed.encode()
    assert session(kit, repo).touched == {"": [CORE]}


def test_no_checkpoint_while_another_call_runs(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    call(kit, repo, "c2")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(kit, repo, "c1").context == ""
    assert "# BAD regex" in (repo / CORE).read_text()
    assert finish(kit, repo, "c2").context.startswith("lup refused 1 file.")


def test_parallel_calls_are_judged_together(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    call(kit, repo, "c2")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    (repo / "README.md").write_text("# Changed\n")
    finish(kit, repo, "c2")
    reply = finish(kit, repo, "c1")
    assert reply.context.startswith("lup refused 1 file.")
    assert (repo / "README.md").read_text() == "# Changed\n"


def test_a_finish_with_no_start_leaves_the_running_calls_alone(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(kit, repo, "ghost").context == ""
    assert finish(kit, repo, "c1").context.startswith("lup refused 1 file.")


def test_a_call_that_never_finishes_is_cleared_when_the_turn_ends(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "lost")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    reply = end(kit, repo)
    assert reply.block.startswith("lup refused 1 file.")
    call(kit, repo, "c2")
    assert finish(kit, repo, "c2").context == ""


def running(kit: Kit, repo: Path) -> list[str]:
    return [each.key for each in worktree(kit, repo).running().calls]


def test_a_turns_end_clears_only_its_own_sessions_calls(kit: Kit, repo: Path) -> None:
    start(kit, repo, "other")
    start(kit, repo)
    call_for("other", kit, repo, "o1")
    call(kit, repo, "lost")
    end(kit, repo)
    assert running(kit, repo) == ["o1"]


def test_another_sessions_call_doesnt_hold_back_a_checkpoint(
    kit: Kit, repo: Path
) -> None:
    """A call no hook will finish (a configuration hooking only `PreToolUse`, a
    session that crashed) mustn't keep every session's checkpoints from running."""
    start(kit, repo, "other")
    start(kit, repo)
    call_for("other", kit, repo, "o1")
    reply = shell_write(
        kit, repo, "c1", CORE, (repo / CORE).read_text() + "y = 2  # BAD regex\n"
    )
    assert reply.context.startswith("lup refused 1 file.")
    assert "# BAD regex" not in (repo / CORE).read_text()
    assert running(kit, repo) == ["o1"]


def test_a_session_starting_accepts_the_worktree_whatever_another_session_runs(
    kit: Kit, repo: Path
) -> None:
    """What changed before a session's first call is accepted, even while another
    session's call runs: that session's write in progress then goes unjudged, the
    price of not waiting on another session's calls."""
    start(kit, repo, "other")
    call_for("other", kit, repo, "o1")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    start(kit, repo)
    call(kit, repo, "c1")
    assert finish(kit, repo, "c1").context == ""
    assert finish(kit, repo, "o1", session="other").context == ""
    assert "# BAD regex" in (repo / CORE).read_text()


def test_a_new_file_through_the_shell_comes_back_through_the_file_tools(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    reply = shell_write(kit, repo, "c1", Path("src/pkg/new.py"), '"""New."""\n')
    assert (
        "Made through the shell, so it comes back through your file tools"
        in reply.context
    )
    assert "src/pkg/new.py is a new production file" in reply.context
    assert not (repo / "src" / "pkg" / "new.py").exists()
    assert (repo / ".lup" / "saved" / "1" / "src" / "pkg" / "new.py").exists()


def test_tests_docs_and_scratch_through_the_shell_are_allowed(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / "tests" / "test_new.py").write_text("x = 1  # BAD regex\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("# Note\n")
    (repo / "tmp").mkdir()
    (repo / "tmp" / "try.py").write_text("x = 1  # BAD regex\n")
    assert finish(kit, repo, "c1").context == ""


def test_content_committed_elsewhere_isnt_judged(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    shell.git(repo, "checkout", "-q", "-b", "other")
    (repo / CORE).write_text("x = 1  # BAD regex\n")
    shell.commit(repo, "other")
    shell.git(repo, "checkout", "-q", "main")
    start(kit, repo)
    call(kit, repo, "c1")
    shell.git(repo, "checkout", "-q", "other")
    assert finish(kit, repo, "c1").context == ""
    assert (repo / CORE).read_text() == "x = 1  # BAD regex\n"


def test_a_write_committed_in_the_same_call_is_judged_once_as_the_commits(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / CORE).write_text("x = 1  # BAD regex\n")
    shell.commit(repo, "sneak it in")
    told = finish(kit, repo, "c1").context
    head = shell.git(repo, "rev-parse", "HEAD")
    assert told.startswith(f"HEAD moved to {head} in {repo}, bringing content")
    assert f"{repo}/src/pkg/core.py:1:8 - regex: regex fires here" in told
    assert "fail the gate: fix them in a later commit" in told
    assert (repo / CORE).read_text() == "x = 1  # BAD regex\n"
    assert shell.git(repo, "status", "--porcelain") == ""
    [verdict] = log(kit, repo).read()
    assert (verdict.tool, verdict.session, verdict.outcome) == ("move", None, "refuse")
    call(kit, repo, "c2")
    assert finish(kit, repo, "c2").context == ""


def test_a_module_committed_through_the_shell_stays_and_asks_the_operator_after(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    start(kit, repo)
    new = repo / "src" / "pkg" / "new.py"
    call(kit, repo, "c1")
    new.write_text('"""New."""\n')
    shell.commit(repo, "a module through the shell")
    told = finish(kit, repo, "c1").context
    assert f"asks: {new} is a new production file" in told
    [hold] = waiting(kit.layout)
    assert told.endswith(f"(hold {hold.key}, `lup-dev holds`).")
    assert hold.commit == shell.git(repo, "rev-parse", "HEAD")
    assert new.read_text() == '"""New."""\n'
    call(kit, repo, "c2")
    shell.git(repo, "restore", "src/pkg/new.py")
    assert finish(kit, repo, "c2").context == ""
    assert [each.key for each in waiting(kit.layout)] == [hold.key]


def test_a_moves_hold_is_answered_after_the_fact(
    kit: Kit, repo: Path, shell: Shell, runtimes: list[FakeRuntime]
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    shell.commit(repo, "a module through the shell")
    finish(kit, repo, "c1")
    [hold] = waiting(kit.layout)
    answer(
        kit.layout,
        hold.key,
        Response(approved=False, comment="not this module"),
        list(runtimes),
        kit.clock,
    )
    [verdict] = [each for each in log(kit, repo).read() if each.tool == "move"]
    assert (verdict.outcome, verdict.answer, verdict.session) == (
        "hold",
        "declined",
        None,
    )
    call(kit, repo, "c2")
    told = finish(kit, repo, "c2").context
    assert told.startswith(
        f"The operator declined what commit {hold.commit} brought to "
        f"{repo}/src/pkg/new.py: not this module. Nothing was changed"
    )
    assert (repo / "src" / "pkg" / "new.py").exists()
    call(kit, repo, "c3")
    assert finish(kit, repo, "c3").context == ""


def test_a_file_changed_after_its_commit_is_judged_against_heads_content(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    committed = (repo / CORE).read_text().replace("return x", "return x + 1")
    (repo / CORE).write_text(committed)
    shell.commit(repo, "a commit")
    mine = committed + "y = 2  # BAD regex\n"
    (repo / CORE).write_text(mine)
    told = finish(kit, repo, "c1").context
    assert told.startswith("lup refused 1 file.")
    assert "HEAD moved" not in told
    assert (repo / CORE).read_text() == committed
    assert (repo / ".lup" / "saved" / "1" / CORE).read_text() == mine
    store = worktree(kit, repo).store
    assert store.content(store.accepted(), CORE) == committed.encode()


def test_a_clean_merge_of_a_file_both_sides_changed_is_set_aside(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "feature")
    (repo / CORE).write_text(
        (repo / CORE).read_text() + "\n\nclass Adapter:\n    pass\n"
    )
    shell.commit(repo, "feature: a class")
    shell.git(repo, "switch", "-q", "main")
    (repo / CORE).write_text(
        (repo / CORE).read_text().replace('"""Core."""', '"""Core, on main."""')
    )
    shell.commit(repo, "main: its docstring")
    start(kit, repo)
    call(kit, repo, "c1")
    shell.git(repo, "merge", "-q", "--no-edit", "feature")
    assert finish(kit, repo, "c1").context == ""
    assert shell.git(repo, "status", "--porcelain") == ""
    assert log(kit, repo).read() == []


def test_a_merge_in_progress_sets_aside_what_git_merged_cleanly(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "feature")
    (repo / CORE).write_text(
        (repo / CORE).read_text() + "\n\nclass Adapter:\n    pass\n"
    )
    (repo / "README.md").write_text("# Feature\n")
    shell.commit(repo, "feature")
    shell.git(repo, "switch", "-q", "main")
    (repo / CORE).write_text(
        (repo / CORE).read_text().replace('"""Core."""', '"""Core, on main."""')
    )
    (repo / "README.md").write_text("# Main\n")
    shell.commit(repo, "main")
    start(kit, repo)
    call(kit, repo, "c1")
    sh.git("merge", "-q", "--no-edit", "feature", _cwd=str(repo), _ok_code=[1])
    assert finish(kit, repo, "c1").context == ""
    [verdict] = log(kit, repo).read()
    assert (verdict.path, verdict.role) == (Path("README.md"), "docs")


def test_a_branch_judged_in_another_worktree_merges_unjudged(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    start(kit, repo)
    edit = Replacement(
        call="e1",
        tool="Edit",
        path=linked / CORE,
        old="    return x\n",
        new="    return x\n\n\nclass Adapter:\n    pass\n",
    )
    assert before(kit.bench, edit, SESSION, repo).outcome == "ask"
    call(kit, repo, "e1", tool="Edit")
    (linked / CORE).write_text(edit.content((linked / CORE).read_text()) or "")
    finish(kit, repo, "e1")
    call(kit, linked, "c1")
    shell.commit(linked, "feature: a class")
    assert finish(kit, linked, "c1").context == ""
    call(kit, repo, "c2")
    (repo / CORE).write_text(
        (repo / CORE).read_text().replace('"""Core."""', '"""Core, on main."""')
    )
    shell.commit(repo, "main: its docstring")
    assert finish(kit, repo, "c2").context == ""
    call(kit, repo, "c3")
    shell.git(repo, "merge", "-q", "--no-edit", "feat")
    assert finish(kit, repo, "c3").context == ""
    assert shell.git(repo, "status", "--porcelain") == ""


def test_work_between_sessions_is_accepted_unjudged(kit: Kit, repo: Path) -> None:
    start(kit, repo, "first")
    TurnEnded(session="first", cwd=repo).apply(kit.bench)
    (repo / CORE).write_text("x = 1  # BAD regex\n")
    start(kit, repo, SESSION)
    call(kit, repo, "c1")
    assert finish(kit, repo, "c1").context == ""


def test_an_edit_judged_before_it_lands_is_accepted_as_judged(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    added = "\n\nclass Room:\n    pass\n"
    edit = Replacement(
        call="e1",
        tool="Edit",
        path=repo / CORE,
        old="    return x\n",
        new="    return x\n" + added,
    )
    decision = before(kit.bench, edit, SESSION, repo)
    assert decision.outcome == "ask"
    assert decision.reason == f"lup asks: {repo}/src/pkg/core.py adds the class `Room`"
    call(kit, repo, "e1", tool="Edit")
    (repo / CORE).write_text(edit.content((repo / CORE).read_text()) or "")
    assert finish(kit, repo, "e1").context == ""
    assert session(kit, repo).approved == [CORE]
    [verdict] = log(kit, repo).read()
    assert (verdict.outcome, verdict.answer, verdict.reasons) == (
        "ask",
        "approved",
        ["public-api"],
    )


def test_an_approval_covers_the_path_for_the_rest_of_the_session(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    write = Overwrite(
        call="w1",
        tool="Write",
        path=repo / "src" / "pkg" / "new.py",
        text='"""New."""\n',
    )
    assert before(kit.bench, write, SESSION, repo).outcome == "ask"
    call(kit, repo, "w1", tool="Write")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    finish(kit, repo, "w1")
    again = Overwrite(
        call="w2",
        tool="Write",
        path=repo / "src" / "pkg" / "new.py",
        text='"""New."""\nx = 1\n',
    )
    assert before(kit.bench, again, SESSION, repo).outcome == "allow"


def test_a_subagents_spawn_isnt_a_running_call(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    call(kit, repo, "spawn", tool="Agent")
    call(kit, repo, "c1", agent="sub")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(kit, repo, "c1", agent="sub").context.startswith(
        "lup refused 1 file."
    )


def test_a_report_waits_for_the_other_conversations_that_ran_calls(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "a1", agent="a")
    call(kit, repo, "b1", agent="b")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(kit, repo, "a1", agent="a").context == ""
    told = finish(kit, repo, "b1", agent="b").context
    assert told.startswith("lup refused 1 file.")
    call(kit, repo, "a2", agent="a")
    assert finish(kit, repo, "a2", agent="a").context == told


HOOK = Path(".claude/hooks/check.py")


def protected_module(repo: Path, shell: Shell) -> None:
    (repo / HOOK).parent.mkdir(parents=True)
    (repo / HOOK).write_text((repo / CORE).read_text())
    shell.commit(repo, "a protected module")


def test_a_protected_modules_finding_is_refused_through_the_shell(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    protected_module(repo, shell)
    start(kit, repo)
    original = (repo / HOOK).read_text()
    reply = shell_write(kit, repo, "c1", HOOK, original + "y = 2  # BAD regex\n")
    assert reply.context.startswith("lup refused 1 file.")
    assert ".claude/hooks/check.py:11:8 - regex: regex fires here" in reply.context
    assert "Made through the shell" not in reply.context
    assert (repo / HOOK).read_text() == original


def test_a_clean_change_to_a_protected_module_asks_through_the_file_tools(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    protected_module(repo, shell)
    start(kit, repo)
    changed = (repo / HOOK).read_text().replace("return x", "return x + 1")
    reply = shell_write(kit, repo, "c1", HOOK, changed)
    assert "Made through the shell, so it comes back through your file tools" in (
        reply.context
    )
    assert ".claude/hooks/check.py is a protected path" in reply.context


def test_a_protected_modules_type_errors_keep_the_turn_from_ending(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    protected_module(repo, shell)
    start(kit, repo)
    broken = (repo / HOOK).read_text() + "y: int = 'a'  # TYPE\n"
    edit = Overwrite(call="w1", tool="Write", path=repo / HOOK, text=broken)
    assert before(kit.bench, edit, SESSION, repo).outcome == "ask"
    call(kit, repo, "w1", tool="Write")
    (repo / HOOK).write_text(broken)
    finish(kit, repo, "w1")
    assert end(kit, repo).block.startswith("lup won't end the turn yet")


def test_type_errors_are_information_and_keep_the_turn_from_ending(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    broken = (repo / CORE).read_text() + "y: int = 'a'  # TYPE\n"
    reply = shell_write(kit, repo, "c1", CORE, broken)
    assert "Type errors and ruff's findings in the files changed" in reply.context
    assert (repo / CORE).read_text() == broken
    assert end(kit, repo).block.startswith("lup won't end the turn yet")
    shell_write(kit, repo, "c2", CORE, broken.replace("  # TYPE", ""))
    assert end(kit, repo).block == ""


def subagent_breaks_core(kit: Kit, repo: Path, agent: str = "worker") -> None:
    """A subagent's shell call leaves a type error in `CORE`, judged as it finishes."""
    call(kit, repo, f"{agent}-1", agent=agent)
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    finish(kit, repo, f"{agent}-1", agent=agent)


def both_break_core(kit: Kit, repo: Path, agent: str = "worker") -> None:
    """A shell write lands at a checkpoint where the session's and a subagent's calls
    both finished: the checkpoint can't tell whose it is."""
    call(kit, repo, "own-1")
    call(kit, repo, f"{agent}-1", agent=agent)
    (repo / CORE).write_text((repo / CORE).read_text() + "y: int = 'a'  # TYPE\n")
    finish(kit, repo, "own-1")
    finish(kit, repo, f"{agent}-1", agent=agent)


def test_the_sessions_turns_end_ignores_a_subagents_files_once_it_stopped(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    subagent_breaks_core(kit, repo)
    assert end(kit, repo) == Reply()
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert end(kit, repo) == Reply()
    mine = Path("tests/test_core.py")
    shell_write(kit, repo, "c1", mine, "z: str = 1  # TYPE\n")
    block = end(kit, repo).block
    assert block.startswith("lup won't end the turn yet")
    assert f"{repo}/tests/test_core.py:1:" in block
    assert "core.py:11" not in block


def test_a_subagents_end_doesnt_hold_on_its_files(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    subagent_breaks_core(kit, repo)
    checks = len(kit.engine.checked)
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert len(kit.engine.checked) == checks
    assert kit.engine.importers_asked == []
    assert end(kit, repo) == Reply()
    assert kit.engine.importers_asked == [[CORE]]


def test_a_shell_write_no_checkpoint_can_attribute_goes_to_every_participant(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    both_break_core(kit, repo)
    assert session(kit, repo).touched == {"": [CORE], "worker": [CORE]}
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert end(kit, repo).block.startswith("lup won't end the turn yet")


def test_a_file_tools_write_goes_to_the_conversation_that_made_it(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    new = repo / "src" / "pkg" / "new.py"
    text = '"""New."""\nz: str = 1  # TYPE\n'
    write = Overwrite(call="w1", tool="Write", path=new, text=text)
    assert before(kit.bench, write, SESSION, repo).outcome == "ask"
    call(kit, repo, "c1")
    call(kit, repo, "w1", tool="Write", agent="worker")
    new.write_text(text)
    finish(kit, repo, "c1")
    finish(kit, repo, "w1", agent="worker")
    assert session(kit, repo).touched == {"worker": [Path("src/pkg/new.py")]}
    told = end(kit, repo).block
    assert told.startswith("Type errors and ruff's findings in the files changed")
    assert "lup won't end the turn yet" not in told
    assert end(kit, repo) == Reply()
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert end(kit, repo) == Reply()


def test_a_subagent_is_at_work_until_its_end_lets_it_go(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    both_break_core(kit, repo)
    call(kit, repo, "worker-lost", agent="worker")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    first = subagent_ends(kit, repo, "worker").block
    assert first.startswith("lup refused 1 file.")
    assert "lup won't end the turn yet" not in first
    mailed = end(kit, repo).block
    assert "lup won't end the turn yet" not in mailed
    working = end(kit, repo)
    assert working.block == ""
    assert working.note.startswith(
        "A subagent of this session at work touched these files too"
    )
    assert f"{repo}/src/pkg/core.py:11:" in working.note
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert end(kit, repo).block.startswith("lup won't end the turn yet")


def test_a_turns_end_leaves_a_subagents_call_in_flight_to_its_finish(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "w1", agent="worker")
    new = repo / "src" / "pkg" / "new.py"
    new.write_text('"""New."""\n')
    assert end(kit, repo) == Reply()
    assert new.exists()
    told = finish(kit, repo, "w1", agent="worker").context
    assert told.startswith("lup refused 1 file.")
    assert "Made through the shell" in told


def test_a_subagents_file_tool_write_landed_before_its_call_finished_stays(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    new = repo / "src" / "pkg" / "new.py"
    write = Overwrite(call="w1", tool="Write", path=new, text='"""New."""\n')
    assert before(kit.bench, write, SESSION, repo).outcome == "ask"
    call(kit, repo, "w1", tool="Write", agent="worker")
    new.write_text('"""New."""\n')
    assert end(kit, repo) == Reply()
    assert finish(kit, repo, "w1", agent="worker").context == ""
    assert new.read_text() == '"""New."""\n'


def test_what_the_turns_end_must_tell_still_blocks_while_a_subagent_works(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    both_break_core(kit, repo)
    call(kit, repo, "lost")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    block = end(kit, repo).block
    assert block.startswith("lup refused 1 file.")
    assert "A subagent of this session at work touched these files too" in block
    assert "lup won't end the turn yet" not in block


def test_the_same_findings_after_a_block_let_the_turn_end_saying_so(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    broken = (repo / CORE).read_text() + "y: int = 'a'  # TYPE\n"
    shell_write(kit, repo, "c1", CORE, broken)
    first = end(kit, repo).block
    assert first.startswith("lup won't end the turn yet")
    let = end(kit, repo, after_block=True)
    assert let.block == ""
    assert let.note.startswith("lup held the turn's end on these just before")
    assert f"{repo}/src/pkg/core.py:11:" in let.note
    assert end(kit, repo).block == first


def test_different_findings_after_a_block_block_again(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    broken = (repo / CORE).read_text() + "y: int = 'a'  # TYPE\n"
    shell_write(kit, repo, "c1", CORE, broken)
    end(kit, repo)
    shell_write(kit, repo, "c2", CORE, broken + "z: str = 1  # TYPE\n")
    again = end(kit, repo, after_block=True).block
    assert again.startswith("lup won't end the turn yet")
    assert end(kit, repo, after_block=True).note.startswith("lup held the turn's end")


def test_a_session_starting_again_forgets_its_subagents(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    both_break_core(kit, repo)
    assert "lup won't end the turn yet" not in end(kit, repo).block
    start(kit, repo)
    assert end(kit, repo).block.startswith("lup won't end the turn yet")


def test_an_importers_state_an_earlier_judge_stored_reads_as_no_ones(
    kit: Kit, repo: Path
) -> None:
    layout = kit.layout.store(repo)
    layout.home.mkdir(parents=True)
    report = importer_error(Path("src/pkg/user.py"))
    layout.importers.write_text(
        json.dumps({"pending": [], "found": [report.model_dump(mode="json")]})
    )
    found = ImportersPass(layout=layout, root=repo).collect()
    assert (found.reports, found.writers) == ([report], [])


def test_a_finding_ruff_fixes_safely_neither_informs_nor_holds_the_turn(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    fixable = (repo / CORE).read_text() + "import os  # FIXABLE F401\n"
    assert shell_write(kit, repo, "c1", CORE, fixable).context == ""
    assert end(kit, repo) == Reply()


def test_removed_committed_notes_are_listed_once_at_turn_end(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    (repo / CORE).write_text(
        (repo / CORE).read_text() + "# lup: the limit is the provider's\n"
    )
    shell.commit(repo, "note")
    start(kit, repo)
    reply = shell_write(
        kit,
        repo,
        "c1",
        CORE,
        (repo / CORE)
        .read_text()
        .replace("# lup: the limit is the provider's\n", "z = 3\n"),
    )
    assert "Notes present when the session started were removed" in reply.context
    first = end(kit, repo).block
    assert "src/pkg/core.py: # lup: the limit is the provider's" in first
    assert end(kit, repo).block == ""


def test_every_judgement_is_logged(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    shell_write(
        kit, repo, "c1", CORE, (repo / CORE).read_text() + "y = 2  # BAD regex\n"
    )
    [verdict] = log(kit, repo).read()
    assert (verdict.tool, verdict.runtime, verdict.outcome, verdict.reasons) == (
        "checkpoint",
        "asking",
        "refuse",
        ["regex"],
    )


def held_file(holding_kit: Kit, repo: Path) -> Path:
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch")
    new = repo / "src" / "pkg" / "new.py"
    new.write_text('"""New."""\n')
    return new


def answer_on_sleep(kit: Kit, response: Response) -> None:
    def answer() -> None:
        [hold] = waiting(kit.layout)
        Holds(layout=kit.layout.store(hold.worktree)).answer(
            hold.key, response, kit.clock
        )

    kit.clock.on_sleep.append(answer)


def test_an_ask_is_held_until_the_operator_approves(
    holding_kit: Kit, repo: Path
) -> None:
    new = held_file(holding_kit, repo)
    answer_on_sleep(holding_kit, Response(approved=True, comment="good name"))
    reply = finish(holding_kit, repo, "p1")
    assert (
        f"The operator approved the held change to {repo}/src/pkg/new.py: good name"
        in reply.context
    )
    assert new.read_text() == '"""New."""\n'
    store = worktree(holding_kit, repo).store
    assert store.content(store.accepted(), Path("src/pkg/new.py")) == b'"""New."""\n'
    answers = [
        verdict.answer
        for verdict in log(holding_kit, repo).read()
        if verdict.outcome == "hold"
    ]
    assert answers == ["approved"]


def test_a_declined_hold_is_put_back_with_the_comment(
    holding_kit: Kit, repo: Path
) -> None:
    new = held_file(holding_kit, repo)
    answer_on_sleep(
        holding_kit, Response(approved=False, comment="use the existing module")
    )
    reply = finish(holding_kit, repo, "p1")
    assert "The operator declined it: use the existing module" in reply.context
    assert not new.exists()
    assert (repo / ".lup" / "saved" / "1" / "src" / "pkg" / "new.py").exists()


def test_an_unanswered_hold_is_put_back_and_stays_open(
    holding_kit: Kit, repo: Path
) -> None:
    new = held_file(holding_kit, repo)

    def wait_a_day() -> None:
        holding_kit.clock.time += timedelta(hours=25)

    holding_kit.clock.on_sleep.append(wait_a_day)
    reply = finish(holding_kit, repo, "p1")
    assert "Nobody answered in time; the hold stays open" in reply.context
    assert not new.exists()
    [hold] = waiting(holding_kit.layout)
    assert hold.abandoned
    answer(holding_kit.layout, hold.key, Response(approved=True), [], holding_kit.clock)
    [verdict] = log(holding_kit, repo).read()
    assert (verdict.outcome, verdict.answer) == ("hold", "approved")
    call(holding_kit, repo, "p2")
    late = finish(holding_kit, repo, "p2").context
    assert (
        "After the hold timed out, the operator approved the change to "
        f"{repo}/src/pkg/new.py. Your version was saved" in late
    )
    assert session(holding_kit, repo).approved == [Path("src/pkg/new.py")]


def test_a_refusal_on_a_holding_runtime_isnt_held(holding_kit: Kit, repo: Path) -> None:
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(holding_kit, repo, "p1").context.startswith("lup refused 1 file.")
    assert waiting(holding_kit.layout) == []


PYPROJECT = Path("pyproject.toml")


def decline_on_sleep(kit: Kit, meanwhile: Callable[[], None]) -> None:
    """While the hold waits, run what another session does, then decline it."""

    def then_decline() -> None:
        meanwhile()
        [hold] = waiting(kit.layout)
        Holds(layout=kit.layout.store(hold.worktree)).answer(
            hold.key, Response(approved=False, comment="not now"), kit.clock
        )

    kit.clock.on_sleep.append(then_decline)


def test_a_held_file_is_left_to_its_hold_by_a_session_starting_meanwhile(
    holding_kit: Kit, repo: Path
) -> None:
    """A session starting in the worktree while a hold waits accepts the rest as it
    stands, but not the held file, and its checkpoints and turn's end leave it
    alone: the operator's decline still puts it back. Seen live on 2026-10-13: a
    Codex session's edit to `pyproject.toml` stayed after the decline, two Claude
    sessions having started in its worktree while it waited."""
    kit = holding_kit
    original = (repo / PYPROJECT).read_text()
    start(kit, repo)
    call(kit, repo, "p1", tool="apply_patch")
    (repo / PYPROJECT).write_text(original + "# a dependency\n")
    heard: list[Reply] = []
    accepted: list[bytes | None] = []

    def other_session() -> None:
        start(kit, repo, "other")
        store = worktree(kit, repo).store
        accepted.append(store.content(store.accepted(), PYPROJECT))
        accepted.append(store.content(store.started("other"), PYPROJECT))
        call_for("other", kit, repo, "o1")
        (repo / "README.md").write_text("# Other\n")
        heard.append(finish(kit, repo, "o1", session="other"))
        heard.append(end(kit, repo, "other"))
        accepted.append(store.content(store.accepted(), PYPROJECT))

    decline_on_sleep(kit, other_session)
    reply = finish(kit, repo, "p1")
    assert "The operator declined it: not now" in reply.context
    assert (repo / PYPROJECT).read_text() == original
    assert (repo / ".lup/saved/1/pyproject.toml").read_text().endswith(
        "# a dependency\n"
    )
    assert accepted == [original.encode()] * 3
    assert heard == [Reply(), Reply()]
    store = worktree(kit, repo).store
    assert store.content(store.accepted(), Path("README.md")) == b"# Other\n"


def test_another_sessions_turns_end_doesnt_hold_on_a_held_file(
    holding_kit: Kit, repo: Path
) -> None:
    """What's in a held file is nobody's until the operator answers, so another
    session that touched it before doesn't hold its turn's end on it."""
    kit = holding_kit
    start(kit, repo, "other")
    call_for("other", kit, repo, "o1")
    mine = (repo / CORE).read_text().replace("return x", "return x + 1")
    (repo / CORE).write_text(mine)
    assert finish(kit, repo, "o1", session="other").context == ""
    start(kit, repo)
    call(kit, repo, "p1", tool="apply_patch")
    (repo / CORE).write_text(mine + "\n\nclass Extra:  # TYPE\n    pass\n")
    ends: list[Reply] = []
    decline_on_sleep(kit, lambda: ends.append(end(kit, repo, "other")))
    assert "The operator declined it" in finish(kit, repo, "p1").context
    assert ends == [Reply()]
    assert (repo / CORE).read_text() == mine


def importer_error(path: Path) -> FileReport:
    place = Position(line=1, column=1)
    finding = Finding(
        path=path,
        span=Span(start=place, end=place),
        owner="pyright",
        rule="reportCallIssue",
        message="wrong arguments",
    )
    return FileReport(path=path, findings=[finding])


OWN = Conversation(session=SESSION, agent="")
WORKER = Conversation(session=SESSION, agent="worker")


def test_the_importers_pass_runs_once_with_everything_requested(
    kit: Kit, repo: Path
) -> None:
    importers = ImportersPass(layout=kit.layout.store(repo), root=repo)
    held = FileLock(kit.layout.store(repo).importers_run)
    with held:
        importers.request([Path("a.py")], [OWN], kit.spawner)
        importers.request([Path("b.py")], [WORKER], kit.spawner)
        assert kit.spawner.spawned == []
        importers.run(kit.engine, Plain())
        assert kit.engine.importers_asked == []
    importers.run(kit.engine, Plain())
    assert kit.engine.importers_asked == [[Path("a.py"), Path("b.py")]]
    assert kit.engine.runners == [Plain()]
    assert importers.collect().writers == [OWN, WORKER]
    assert importers.collect().writers == []


def test_an_idle_request_starts_one_pass(kit: Kit, repo: Path) -> None:
    importers = ImportersPass(layout=kit.layout.store(repo), root=repo)
    importers.request([Path("a.py")], [OWN], kit.spawner)
    assert kit.spawner.spawned == [repo]


USER = Path("src/pkg/user.py")


def user_with_an_error(kit: Kit, repo: Path) -> None:
    """`USER` imports `CORE` and has a type error, which the pass reports."""
    kit.engine.importer_reports = [importer_error(USER)]
    (repo / USER).write_text("from pkg.core import helper\nhelper('a')  # TYPE\n")


def test_the_turns_end_waits_for_the_pass_and_reports_its_errors(
    kit: Kit, repo: Path
) -> None:
    user_with_an_error(kit, repo)
    start(kit, repo)
    shell_write(
        kit,
        repo,
        "c1",
        CORE,
        (repo / CORE).read_text().replace("return x", "return x + 1"),
    )
    assert kit.spawner.spawned == [repo]
    block = end(kit, repo).block
    assert kit.engine.importers_asked == [[CORE]]
    assert f"{repo}/src/pkg/user.py:2:14 - reportGeneralTypeIssues" in block
    assert session(kit, repo).watched == {"": [USER]}


def test_the_importers_errors_go_to_the_conversation_whose_change_they_follow(
    kit: Kit, repo: Path
) -> None:
    user_with_an_error(kit, repo)
    start(kit, repo)
    call(kit, repo, "w1", agent="worker")
    (repo / CORE).write_text(
        (repo / CORE).read_text().replace("return x", "return x + 1")
    )
    finish(kit, repo, "w1", agent="worker")
    assert end(kit, repo) == Reply()
    assert session(kit, repo).watched == {"worker": [USER]}
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert end(kit, repo) == Reply()


def test_the_importers_errors_go_to_the_session_whose_change_they_follow(
    kit: Kit, repo: Path
) -> None:
    user_with_an_error(kit, repo)
    start(kit, repo, "other")
    start(kit, repo)
    CallStarted(session="other", cwd=repo, call="o1", tool="Bash").apply(kit.bench)
    (repo / CORE).write_text(
        (repo / CORE).read_text().replace("return x", "return x + 1")
    )
    finish(kit, repo, "o1", session="other")
    assert end(kit, repo) == Reply()
    other = worktree(kit, repo).recorded("other")
    assert other is not None
    assert other.watched == {"": [USER]}
    assert end(kit, repo, "other").block.startswith("lup won't end the turn yet")


def bad(root: Path) -> None:
    (root / CORE).write_text((root / CORE).read_text() + "y = 2  # BAD regex\n")


def test_a_worktree_the_session_moves_into_is_judged(
    kit: Kit, repo: Path, linked: Path
) -> None:
    start(kit, repo)
    call(kit, linked, "c1")
    bad(linked)
    told = finish(kit, linked, "c1").context
    assert told.startswith("lup refused 1 file.")
    assert f"{linked}/src/pkg/core.py:11:8 - regex" in told
    assert "# BAD" not in (linked / CORE).read_text()
    assert (linked / ".lup" / "saved" / "1" / CORE).exists()


def test_a_call_counts_in_every_worktree_its_session_holds(
    kit: Kit, repo: Path, linked: Path
) -> None:
    start(kit, repo)
    call(kit, linked, "c1")
    finish(kit, linked, "c1")
    call(kit, repo, "c2")
    bad(linked)
    call(kit, linked, "c3")
    assert finish(kit, linked, "c3").context == ""
    assert finish(kit, repo, "c2").context.startswith("lup refused 1 file.")


def test_a_shell_write_where_the_session_never_went_isnt_judged(
    kit: Kit, repo: Path, linked: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    bad(linked)
    assert finish(kit, repo, "c1").context == ""
    assert "# BAD regex" in (linked / CORE).read_text()


def test_a_worktree_removed_since_is_no_longer_held(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    start(kit, repo)
    call(kit, linked, "c1")
    finish(kit, linked, "c1")
    shell.git(repo, "worktree", "remove", str(linked))
    call(kit, repo, "c2")
    bad(repo)
    assert finish(kit, repo, "c2").context.startswith("lup refused 1 file.")
    assert end(kit, repo).block == ""


def test_the_turns_end_runs_in_every_worktree_the_session_holds(
    kit: Kit, repo: Path, linked: Path
) -> None:
    start(kit, repo)
    call(kit, linked, "c1")
    finish(kit, linked, "c1")
    call(kit, repo, "lost")
    bad(linked)
    bad(repo)
    block = end(kit, repo).block
    assert block.startswith("lup refused 2 files.")
    assert f"{repo}/src/pkg/core.py (saved at" in block
    assert f"{linked}/src/pkg/core.py (saved at" in block


def test_every_worktree_is_judged_by_the_integration_branchs_declaration(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    declare(linked, PROTECTING_NOTHING)
    shell.commit(linked, "feat: protect nothing")
    start(kit, repo)
    asked = before(kit.bench, core_edit(linked), SESSION, repo)
    assert asked.outcome == "ask"
    assert asked.reason == (
        f"lup asks: {linked}/src/pkg/core.py is a protected path (src/pkg/core.py)"
    )
    assert Worktree.at(linked, kit.layout).roles.protecting(CORE) is None


def test_the_integration_branchs_declaration_changes_when_committed(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    (repo / "lup_project.py").write_text(PROTECTING_NOTHING)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "ask"
    shell.commit(repo, "dev: protect nothing")
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


def test_without_the_integration_branch_a_worktree_is_judged_by_its_head(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "main: protect the core")
    (repo / "lup_project.py").write_text(PROTECTING_NOTHING)
    start(kit, repo)
    assert before(kit.bench, core_edit(repo), SESSION, repo).outcome == "ask"


def approve(kit: Kit, repo: Path, commit: str) -> None:
    """Record `commit` as the one the operator approved, as trust on launch does."""
    approval = Approval(
        commit=commit,
        fingerprint="approved",
        paths=[Path("lup_project.py")],
        tool=ReleaseTool(name="lup-dev", version="0.4.0", registry="index", pins={}),
        time=kit.clock.now(),
    )
    write_model(kit.layout.approved(repo / ".git"), approval)


def test_the_approved_commits_declaration_judges_not_the_tip(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    approve(kit, repo, shell.git(repo, "rev-parse", "HEAD"))
    declare(repo, PROTECTING_NOTHING)
    shell.commit(repo, "dev: protect nothing, not approved yet")
    start(kit, repo)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "ask"
    approve(kit, repo, shell.git(repo, "rev-parse", "HEAD"))
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


def test_an_approved_commit_gone_from_the_repository_has_the_stand_in(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "ask"
    gone = "0" * 40
    approve(kit, repo, gone)
    stood_in = before(kit.bench, core_edit(linked), SESSION, repo)
    assert stood_in.outcome == "ask"
    call(kit, linked, "c1")
    (linked / "README.md").write_text("# Changed\n")
    told = finish(kit, linked, "c1").context
    assert (
        f"lup can't load the project's declaration at {gone}: the commit approved "
        f"last, {gone}, isn't in the repository" in told
    )


def test_an_approved_commit_gone_with_nothing_kept_fails(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    approve(kit, repo, "0" * 40)
    start(kit, repo)
    with pytest.raises(ProjectError, match="isn't in the repository"):
        before(kit.bench, core_edit(repo), SESSION, repo)


def test_only_the_latest_commits_declaration_stays_exported(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    before(kit.bench, core_edit(repo), SESSION, repo)
    (repo / "lup_project.py").write_text(PROTECTING_NOTHING)
    shell.commit(repo, "dev: protect nothing")
    before(kit.bench, core_edit(repo), SESSION, repo)
    head = shell.git(repo, "rev-parse", "HEAD")
    exports = kit.layout.exported(repo / ".git", head).parent
    assert [each.name for each in exports.iterdir()] == [head]
    assert not (repo / "__pycache__").exists()


def test_an_approval_covers_a_path_in_its_worktree_only(
    kit: Kit, repo: Path, linked: Path
) -> None:
    start(kit, repo)

    def write(root: Path, key: str) -> Overwrite:
        return Overwrite(
            call=key, tool="Write", path=root / "src/pkg/new.py", text='"""New."""\n'
        )

    assert before(kit.bench, write(repo, "w1"), SESSION, repo).outcome == "ask"
    call(kit, repo, "w1", tool="Write")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    finish(kit, repo, "w1")
    assert before(kit.bench, write(repo, "w2"), SESSION, repo).outcome == "allow"
    assert before(kit.bench, write(linked, "w3"), SESSION, repo).outcome == "ask"


def test_a_session_started_in_a_bare_repositorys_directory_is_judged(
    kit: Kit, bare: Path
) -> None:
    main = bare / "tree" / "main"
    start(kit, bare / "tree")
    edit = Replacement(
        call="e1",
        tool="Edit",
        path=main / CORE,
        old="return x\n",
        new="return x  # BAD regex\n",
    )
    assert before(kit.bench, edit, SESSION, bare / "tree").outcome == "refuse"
    call(kit, bare, "c1")
    bad(main)
    assert finish(kit, bare, "c1").context.startswith("lup refused 1 file.")


def test_a_write_in_the_repositorys_git_directory_asks(kit: Kit, bare: Path) -> None:
    main = bare / "tree" / "main"
    start(kit, main)
    hook = Overwrite(
        call="w1", tool="Write", path=bare / "hooks" / "pre-commit", text="#!/bin/sh\n"
    )
    decision = before(kit.bench, hook, SESSION, main)
    assert decision.outcome == "ask"
    assert decision.reason == (
        f"lup asks: {bare}/hooks/pre-commit is in the repository's git directory, "
        "which runs outside the agent's reach"
    )
    [verdict] = VerdictLog(path=kit.layout.verdicts(bare)).read()
    assert (verdict.worktree, verdict.path) == (bare, Path("hooks/pre-commit"))


def test_a_repository_nested_in_a_worktree_is_another_repository(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    nested = repo / "vendor" / "lib"
    nested.mkdir(parents=True)
    shell.git(nested, "init", "-q", "-b", "main")
    shell.git(nested, "config", "user.email", "test@example.com")
    shell.git(nested, "config", "user.name", "Test")
    (nested / "x.py").write_text("x = 1\n")
    shell.commit(nested, "nested")
    start(kit, repo)
    write = Overwrite(
        call="w1", tool="Write", path=nested / "x.py", text="x = 1  # BAD regex\n"
    )
    assert before(kit.bench, write, SESSION, repo).outcome is None


PROTECTING_CORE = '''
from lup_dev import Module, Modules, Paths, Project


class Guard(Module):
    """The project's own module, protecting its core."""

    name = "guard"

    paths: Paths = Paths.of(protected=["src/pkg/core.py"])


project = Project(modules=Modules.default().add(Guard()))
'''
"""A declaration holding a module of the project's own, which JSON can't bring back."""

PROTECTING_NOTHING = "from lup_dev import Project\nproject = Project()\n"


def declare(root: Path, declaration: str) -> None:
    (root / "lup_project.py").write_text(declaration)


def core_edit(root: Path) -> Replacement:
    return Replacement(
        call="e1", tool="Edit", path=root / CORE, old="return x\n", new="return x + 1\n"
    )


def test_the_last_declaration_that_loaded_stands_in_for_one_that_cant(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    loaded = shell.git(repo, "rev-parse", "HEAD")
    start(kit, repo)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "ask"
    (repo / "lup_project.py").write_text(
        "from lup_dev import Unheard\n" + PROTECTING_CORE
    )
    shell.commit(repo, "dev: a name the judge lacks")
    broken = shell.git(repo, "rev-parse", "HEAD")
    stood_in = before(kit.bench, core_edit(linked), SESSION, repo)
    assert stood_in.outcome == "ask"
    assert "is a protected path (src/pkg/core.py)" in stood_in.reason
    call(kit, linked, "c1")
    (linked / "README.md").write_text("# Changed\n")
    told = finish(kit, linked, "c1").context
    assert f"lup can't load the project's declaration at {broken}: " in told
    assert f"from commit {loaded}, until one loads" in told
    call(kit, linked, "c2")
    (linked / "README.md").write_text("# Changed again\n")
    assert "can't load" not in finish(kit, linked, "c2").context


def test_a_declaration_that_doesnt_resolve_has_the_same_stand_in(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "ask"
    (repo / "lup_project.py").write_text(
        PROTECTING_CORE.replace(".add(Guard())", '.add(Guard()).drop("ledger")')
    )
    shell.commit(repo, "dev: drop a module that isn't there")
    stood_in = before(kit.bench, core_edit(linked), SESSION, repo)
    assert stood_in.outcome == "ask"
    assert "is a protected path (src/pkg/core.py)" in stood_in.reason


def test_with_no_declaration_kept_one_that_cant_load_fails(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    declare(repo, "from lup_dev import Unheard\n")
    shell.commit(repo, "a name the judge lacks")
    start(kit, repo)
    with pytest.raises(ProjectError, match="Unheard"):
        before(kit.bench, core_edit(repo), SESSION, repo)


def test_the_gate_reads_the_worktree_as_it_stands_with_no_stand_in(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    before(kit.bench, core_edit(linked), SESSION, repo)
    declare(linked, "from lup_dev import Unheard\n")
    with pytest.raises(ProjectError):
        _ = Worktree.at(linked, kit.layout).declaration


def dropping(rule: str) -> str:
    """Return a declaration whose `CodeRules` drops `rule` from lup's default."""
    return (
        "from lup_dev import CodeRules, Modules, Project, Rules\n"
        "project = Project(\n"
        f"    modules=Modules.default().edit(CodeRules(rules=Rules().drop({rule!r}))),\n"
        ")\n"
    )


def dropped(selected: list[Selected]) -> list[str]:
    [code_rules] = selected
    return [
        name
        for operation in code_rules.rules.operations
        if isinstance(operation, Drop)
        for name in operation.names
    ]


def test_every_check_sends_the_integration_branchs_rule_selection(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    (repo / "lup_project.py").write_text(dropping("regex"))
    shell.commit(repo, "dev: drop regex")
    (linked / "lup_project.py").write_text(dropping("tuple-shape"))
    start(kit, repo)
    before(kit.bench, core_edit(linked), SESSION, repo)
    call(kit, linked, "c1")
    (linked / CORE).write_text((linked / CORE).read_text() + "# TYPE\n")
    finish(kit, linked, "c1")
    end(kit, repo)
    assert kit.engine.selections
    for selected in kit.engine.selections:
        assert dropped(selected) == ["runtime-mention", "regex"]
    assert dropped(Worktree.at(linked, kit.layout).declaration.rules) == [
        "runtime-mention",
        "tuple-shape",
    ]


def test_a_stand_in_declaration_sends_its_own_rule_selection(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    (repo / "lup_project.py").write_text(dropping("regex"))
    shell.commit(repo, "dev: drop regex")
    start(kit, repo)
    before(kit.bench, core_edit(linked), SESSION, repo)
    (repo / "lup_project.py").write_text(
        "from lup_dev import Unheard\n" + dropping("tuple-shape")
    )
    shell.commit(repo, "dev: a name the judge lacks")
    kit.engine.selections.clear()
    before(kit.bench, core_edit(linked), SESSION, repo)
    assert kit.engine.selections
    for selected in kit.engine.selections:
        assert dropped(selected) == ["runtime-mention", "regex"]


PLAIN = (
    "from lup_dev import Modules, Plain, Project, Python\n"
    "project = Project(modules=Modules.default().edit(Python(runner=Plain())))\n"
)
"""A declaration whose tools run as the `PATH` finds them."""

POETRY = '''
from pathlib import Path

from lup_dev import Modules, Project, Python, RoomNeeds, Runner, Tools


class Poetry(Runner):
    """The project's own runner, a class the judge's kept data can't bring back."""

    def command(self, tool: list[str]) -> list[str]:
        return ["poetry", "run", *tool]

    def judging(self, tool: list[str]) -> list[str]:
        return ["poetry", "run", *tool]

    def environment(self) -> list[str]:
        return ["poetry.lock"]

    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        return RoomNeeds()


project = Project(modules=Modules.default().edit(Python(runner=Poetry())))
'''


def test_the_engine_and_ruff_run_with_the_integration_branchs_runner(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    (repo / "lup_project.py").write_text(PLAIN)
    shell.commit(repo, "dev: no uv")
    start(kit, repo)
    before(kit.bench, core_edit(linked), SESSION, repo)
    call(kit, linked, "c1")
    (linked / CORE).write_text((linked / CORE).read_text() + "# TYPE\n")
    finish(kit, linked, "c1")
    end(kit, repo)
    plain = Prefixed.of(Plain())
    assert kit.engine.runners
    assert kit.linter.runners
    assert all(each == plain for each in [*kit.engine.runners, *kit.linter.runners])


def test_a_stand_in_declaration_runs_the_tools_with_its_runners_commands(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    (repo / "lup_project.py").write_text(POETRY)
    shell.commit(repo, "dev: poetry")
    start(kit, repo)
    before(kit.bench, core_edit(linked), SESSION, repo)
    (repo / "lup_project.py").write_text("from lup_dev import Unheard\n" + POETRY)
    shell.commit(repo, "dev: a name the judge lacks")
    kit.engine.runners.clear()
    kit.linter.runners.clear()
    before(kit.bench, core_edit(linked), SESSION, repo)
    ran = [*kit.engine.runners, *kit.linter.runners]
    assert ran
    for runner in ran:
        assert runner.judging(["ruff"]) == ["poetry", "run", "ruff"]
        assert runner.environment() == ["poetry.lock"]


def test_before_the_first_commit_the_defaults_rule_selection_judges(
    kit: Kit, tmp_path: Path, shell: Shell
) -> None:
    root = tmp_path / "fresh"
    (root / "src" / "pkg").mkdir(parents=True)
    shell.git(root, "init", "-q", "-b", "main")
    (root / "lup_project.py").write_text(dropping("regex"))
    judged = Worktree.of(root, root / ".git", kit.bench.services).declaration
    assert judged.rules == Declaration.of(Project()).rules
