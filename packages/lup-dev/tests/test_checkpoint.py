"""The checkpoint: when it runs, what it judges, and what it does about it."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sh
from filelock import FileLock

from lup_dev.codescan.contract import FileReport, Finding, Position, Span
from lup_dev.policy.before import Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    CallFinished,
    CallStarted,
    Reply,
    Session,
    SessionStarted,
    TurnEnded,
    Worktree,
)
from lup_dev.policy.holds import Holds, Response, answer, waiting
from lup_dev.policy.importers import ImportersPass
from lup_dev.policy.store import read_model
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.project import ProjectError

if TYPE_CHECKING:
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


def end(kit: Kit, repo: Path, session: str = SESSION) -> Reply:
    return TurnEnded(session=session, cwd=repo).apply(kit.bench)


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
    assert session(kit, repo).touched == [CORE]


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


def test_a_turns_end_clears_only_its_own_sessions_calls(kit: Kit, repo: Path) -> None:
    start(kit, repo, "other")
    start(kit, repo)
    call_for("other", kit, repo, "o1")
    end(kit, repo)
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    call(kit, repo, "c1")
    assert finish(kit, repo, "c1").context == ""
    assert "# BAD regex" in (repo / CORE).read_text()
    told = finish(kit, repo, "o1", session="other").context
    assert told.startswith("lup refused 1 file.")


def test_a_session_starting_while_another_writes_leaves_that_write_to_be_judged(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo, "other")
    call_for("other", kit, repo, "o1")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    start(kit, repo)
    told = finish(kit, repo, "o1", session="other").context
    assert told.startswith("lup refused 1 file.")


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


def test_the_importers_pass_runs_once_with_everything_requested(
    kit: Kit, repo: Path
) -> None:
    importers = ImportersPass(layout=kit.layout.store(repo), root=repo)
    runner = FileLock(kit.layout.store(repo).importers_run)
    with runner:
        importers.request([Path("a.py")], kit.spawner)
        importers.request([Path("b.py")], kit.spawner)
        assert kit.spawner.spawned == []
        importers.run(kit.engine)
        assert kit.engine.importers_asked == []
    importers.run(kit.engine)
    assert kit.engine.importers_asked == [[Path("a.py"), Path("b.py")]]


def test_an_idle_request_starts_one_pass(kit: Kit, repo: Path) -> None:
    importers = ImportersPass(layout=kit.layout.store(repo), root=repo)
    importers.request([Path("a.py")], kit.spawner)
    assert kit.spawner.spawned == [repo]


def test_the_turns_end_waits_for_the_pass_and_reports_its_errors(
    kit: Kit, repo: Path
) -> None:
    kit.engine.importer_reports = [importer_error(Path("src/pkg/user.py"))]
    (repo / "src" / "pkg" / "user.py").write_text("from pkg.core import helper\n")
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
    assert f"{repo}/src/pkg/user.py:1:1 - reportCallIssue: wrong arguments" in block


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
    declare(linked, "from lup_dev.project import Project\nproject = Project()\n")
    shell.commit(linked, "feat: protect nothing")
    start(kit, repo)
    asked = before(kit.bench, core_edit(linked), SESSION, repo)
    assert asked.outcome == "ask"
    assert asked.reason == (
        f"lup asks: {linked}/src/pkg/core.py is a protected path (src/pkg/core.py)"
    )
    assert (
        Worktree.at(linked, kit.layout).declared.project.protected.matching(CORE)
        is None
    )


def test_the_integration_branchs_declaration_changes_when_committed(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    (repo / "lup_project.py").write_text(
        "from lup_dev.project import Project\nproject = Project()\n"
    )
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "ask"
    shell.commit(repo, "dev: protect nothing")
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


def test_without_the_integration_branch_a_worktree_is_judged_by_its_head(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "main: protect the core")
    (repo / "lup_project.py").write_text(
        "from lup_dev.project import Project\nproject = Project()\n"
    )
    start(kit, repo)
    assert before(kit.bench, core_edit(repo), SESSION, repo).outcome == "ask"


def test_only_the_latest_commits_declaration_stays_exported(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    before(kit.bench, core_edit(repo), SESSION, repo)
    (repo / "lup_project.py").write_text(
        "from lup_dev.project import Project\nproject = Project()\n"
    )
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


PROTECTING_CORE = (
    "from lup_dev.project import Project, Protected\n"
    'project = Project(protected=Protected.default().add("src/pkg/core.py"))\n'
)


def declare(root: Path, declaration: str) -> None:
    (root / "pyproject.toml").write_text(
        '[tool.lup]\nproject = "lup_project:project"\n'
        '[tool.pytest]\ntestpaths = ["tests", "src"]\n'
    )
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
        "from lup_dev.project import Unheard\n" + PROTECTING_CORE
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


def test_with_no_declaration_kept_one_that_cant_load_fails(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    declare(repo, "from lup_dev.project import Unheard\n")
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
    declare(linked, "from lup_dev.project import Unheard\n")
    with pytest.raises(ProjectError):
        _ = Worktree.at(linked, kit.layout).declared
