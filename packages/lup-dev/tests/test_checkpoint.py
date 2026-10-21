"""The checkpoint: when it runs, what it judges, and what it does about it."""

import inspect
import json
from annotationlib import Format
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from filelock import FileLock, Timeout

from lup.programs import run
from lup_dev import Project
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.codescan.contract import Due, FileReport, Finding, Position, Span
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Drop
from lup_dev.declaration.resolve import Declaration, Selected
from lup_dev.declaration.runner import Plain, Prefixed
from lup_dev.inbox.store import Asked, ChangedFile, Reading, Text
from lup_dev.launch.session import hooked
from lup_dev.policy.before import Decision, Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    Call,
    CallFinished,
    CallStarted,
    ConversationEnded,
    Pending,
    Reply,
    Running,
    Session,
    SessionStarted,
    TurnEnded,
    TurnStarted,
    Worktree,
    over,
)
from lup_dev.policy.holds import Holds, Response, answer, waiting
from lup_dev.policy.importers import Conversation, ImportersPass
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.private.withheld import Held, Withheld, kept
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


def held(kit: Kit, deciding: Callable[[], Decision]) -> bool:
    """Judge a file tool's write, and say whether it was held for the operator and let through on the yes the kit gives."""
    count = len(kit.announced.holds)
    decision = deciding()
    return decision.outcome == "allow" and len(kit.announced.holds) == count + 1


def last_asks(kit: Kit) -> list[str]:
    """Return what the latest hold put before the operator asks, each file's asks in turn."""
    return [ask for each in kit.announced.holds[-1].files for ask in each.asks]


def log(kit: Kit, repo: Path) -> VerdictLog:
    return worktree(kit, repo).verdicts(kit.layout)


def test_a_write_with_a_finding_lands_and_its_finding_is_told(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    mine = (repo / CORE).read_text() + "y = 2  # BAD regex\n"
    reply = shell_write(kit, repo, "c1", CORE, mine)
    assert reply.context.startswith("lup's findings on the lines changed")
    assert f"{repo}/src/pkg/core.py:11:8 - regex: regex fires here" in reply.context
    assert (repo / CORE).read_text() == mine
    assert not (repo / ".lup" / "saved").exists()


def test_a_finding_told_once_isnt_told_again_at_the_next_call(
    kit: Kit, repo: Path
) -> None:
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
    assert finish(kit, repo, "c2").context.startswith(
        "lup's findings on the lines changed"
    )


def test_parallel_calls_are_judged_together(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    call(kit, repo, "c2")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    (repo / "README.md").write_text("# Changed\n")
    finish(kit, repo, "c2")
    reply = finish(kit, repo, "c1")
    assert reply.context.startswith("lup's findings on the lines changed")
    assert (repo / "README.md").read_text() == "# Changed\n"


def taken_elsewhere(made: Callable[[], FileLock]) -> bool:
    """Say whether a thread of its own finds the lock `made` gives taken, trying once."""

    def tried() -> bool:
        lock = made()
        try:
            lock.acquire(timeout=0)
        except Timeout:
            return True
        lock.release()
        return False

    with ThreadPoolExecutor(max_workers=1) as other:
        return other.submit(tried).result(timeout=60)


def waited_for(made: Callable[[], FileLock]) -> bool:
    """Take the lock `made` gives, waiting for it as a hook does, and let it go."""
    with made():
        return True


def test_the_judge_s_locks_exclude_hooks_answered_in_threads_of_one_process(
    kit: Kit, repo: Path
) -> None:
    # The launch's process answers each hook in a thread of its own, where each
    # was a process of its own: a lock one hook holds keeps every other out.
    start(kit, repo)
    opened = worktree(kit, repo)
    index = SessionIndex(layout=kit.layout)

    def sessions() -> FileLock:
        return index.lock(SESSION)

    for made in [opened.lock, opened.calls_lock, sessions]:
        assert not taken_elsewhere(made)
        held = made()
        with ThreadPoolExecutor(max_workers=1) as other:
            with held:
                assert taken_elsewhere(made)
                # A hook waiting for it in another thread isn't refused as a
                # deadlock: it gets the lock once the first lets it go.
                waiting = other.submit(waited_for, made)
            assert waiting.result(timeout=60)
        assert not taken_elsewhere(made)


def test_parallel_hooks_in_threads_of_one_process_are_judged_together(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)

    def started(key: str) -> None:
        call(kit, repo, key)

    with ThreadPoolExecutor(max_workers=2) as hooks:
        list(hooks.map(started, ["c1", "c2"]))
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(kit, repo, "c1").context == ""
    assert finish(kit, repo, "c2").context.startswith(
        "lup's findings on the lines changed"
    )


def test_a_finish_with_no_start_leaves_the_running_calls_alone(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(kit, repo, "ghost").context == ""
    assert finish(kit, repo, "c1").context.startswith(
        "lup's findings on the lines changed"
    )


def test_a_call_that_never_finishes_is_cleared_when_the_turn_ends(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "lost")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    reply = end(kit, repo)
    assert reply.block.startswith("lup won't end the turn yet")
    assert "regex: regex fires here" in reply.block
    call(kit, repo, "c2")
    assert finish(kit, repo, "c2").context == ""


def running(kit: Kit, repo: Path) -> list[str]:
    return [each.key for each in worktree(kit, repo).running().calls]


def test_a_call_that_must_be_over_is_forgotten_when_the_calls_are_kept(
    kit: Kit, repo: Path
) -> None:
    """A call no hook finished, from a session long gone or recorded by a judge
    that kept no start time, is forgotten as the list is next kept; a call
    started within a hook's longest wait stays."""
    start(kit, repo, "gone")
    call_for("gone", kit, repo, "stale")
    store = worktree(kit, repo).store.layout.calls
    kept = read_model(store, Running)
    assert kept is not None
    untimed = Call(key="untimed", session="gone", agent="", tool="Bash")
    write_model(store, Running(calls=[*kept.calls, untimed]))
    kit.clock.sleep(timedelta(hours=25).total_seconds())
    start(kit, repo)
    call(kit, repo, "c1")
    assert running(kit, repo) == ["c1"]
    kit.clock.sleep(timedelta(hours=24).total_seconds())
    call(kit, repo, "c2")
    assert running(kit, repo) == ["c1", "c2"]


def test_a_pending_write_no_end_confirmed_is_forgotten_once_its_call_must_be_over(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)

    def edit(key: str, old: str) -> None:
        change = Replacement(
            call=key, tool="Edit", path=repo / CORE, old=old, new=f"{old}_"
        )
        assert before(kit.bench, change, SESSION, repo).outcome == "allow"

    edit("e1", "def helper")
    record = session(kit, repo)
    untimed = Pending(call="untimed", path=CORE, blob=record.pending[0].blob)
    worktree(kit, repo).keep(
        record.model_copy(update={"pending": [*record.pending, untimed]})
    )
    kit.clock.sleep(timedelta(hours=25).total_seconds())
    edit("e2", "def ask")
    assert [each.call for each in session(kit, repo).pending] == ["e2"]


def test_a_call_lasts_no_longer_than_a_rooms_hook_waits() -> None:
    def default(function: Callable[..., object], name: str) -> object:
        signed = inspect.signature(function, annotation_format=Format.STRING)
        return signed.parameters[name].default

    assert default(over, "lifetime") == default(hooked, "hold")


def test_a_turns_start_clears_the_calls_the_runtime_shows_over(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "lost")
    call(kit, repo, "gone", agent="worker")
    call(kit, repo, "c1")
    TurnStarted(session=SESSION, cwd=repo, over=["lost", "gone"]).apply(kit.bench)
    assert running(kit, repo) == ["c1"]
    bad(repo)
    assert finish(kit, repo, "c1").context.startswith(
        "lup's findings on the lines changed"
    )


def test_a_turns_start_clears_its_conversations_calls_of_another_turn(
    kit: Kit, repo: Path
) -> None:
    """A prompt arriving in a turn carries that turn's id, and leaves its calls."""
    start(kit, repo)
    for key, agent in [("c1", ""), ("w1", "worker")]:
        CallStarted(
            session=SESSION, agent=agent, cwd=repo, call=key, tool="Bash", turn="t1"
        ).apply(kit.bench)
    TurnStarted(session=SESSION, cwd=repo, turn="t1").apply(kit.bench)
    assert running(kit, repo) == ["c1", "w1"]
    TurnStarted(session=SESSION, cwd=repo, turn="t2").apply(kit.bench)
    assert running(kit, repo) == ["w1"]


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
    assert reply.context.startswith("lup's findings on the lines changed")
    assert "# BAD regex" in (repo / CORE).read_text()
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


def test_a_new_file_through_the_shell_is_held_and_lands_on_a_yes(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    reply = shell_write(kit, repo, "c1", Path("src/pkg/new.py"), '"""New."""\n')
    assert reply.context.startswith("The operator approved the held change to")
    assert last_asks(kit) == ["src/pkg/new.py is a new production file"]
    assert (repo / "src" / "pkg" / "new.py").read_text() == '"""New."""\n'


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
    assert (verdict.tool, verdict.session, verdict.outcome) == ("move", None, "allow")
    assert verdict.reasons == ["regex"]
    call(kit, repo, "c2")
    assert finish(kit, repo, "c2").context == ""


def test_a_protected_file_committed_through_the_shell_stays_and_asks_the_operator_after(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    kit.announced.answering = None
    start(kit, repo)
    new = repo / ".github" / "ci.yml"
    new.parent.mkdir()
    call(kit, repo, "c1")
    new.write_text("on: push\n")
    shell.commit(repo, "CI through the shell")
    told = finish(kit, repo, "c1").context
    # The agent reads what it asks under the file's absolute path.
    assert f"{new}\n  asks: .github/ci.yml is a protected path" in told
    [hold] = waiting(kit.layout)
    assert told.endswith(f"in their inbox (hold {hold.key}).")
    assert kit.announced.holds == [hold]
    assert kit.announced.files == [
        [
            ChangedFile(
                path=Path(".github/ci.yml"),
                before=None,
                after=Text(text="on: push\n"),
                reading=Reading(
                    role="protected", asks=[Asked(name="protected", taken="held")]
                ),
            )
        ]
    ]
    assert hold.commit == shell.git(repo, "rev-parse", "HEAD")
    assert new.read_text() == "on: push\n"
    call(kit, repo, "c2")
    shell.git(repo, "restore", ".github/ci.yml")
    assert finish(kit, repo, "c2").context == ""
    assert [each.key for each in waiting(kit.layout)] == [hold.key]


def test_a_moves_hold_is_answered_after_the_fact(
    kit: Kit, repo: Path, shell: Shell, runtimes: list[FakeRuntime]
) -> None:
    kit.announced.answering = None
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / ".github").mkdir()
    (repo / ".github" / "ci.yml").write_text("on: push\n")
    shell.commit(repo, "CI through the shell")
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
        f"{repo}/.github/ci.yml: not this module. Nothing was changed"
    )
    assert (repo / ".github" / "ci.yml").exists()
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
    assert told.startswith("lup's findings on the lines changed")
    assert f"{repo}/src/pkg/core.py:11:8 - regex" in told
    assert "HEAD moved" not in told
    store = worktree(kit, repo).store
    assert store.content(store.accepted(), CORE) == mine.encode()


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
    run("git", "merge", "-q", "--no-edit", "feature", cwd=repo, ok=[1])
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
    assert held(kit, lambda: before(kit.bench, edit, SESSION, repo))
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
    assert held(kit, lambda: before(kit.bench, edit, SESSION, repo))
    assert last_asks(kit) == ["src/pkg/core.py adds the class `Room`"]
    call(kit, repo, "e1", tool="Edit")
    (repo / CORE).write_text(edit.content((repo / CORE).read_text()) or "")
    assert finish(kit, repo, "e1").context == ""
    assert session(kit, repo).approved == [CORE]
    [verdict] = log(kit, repo).read()
    assert (verdict.outcome, verdict.answer, verdict.reasons) == (
        "hold",
        "approved",
        ["public-api"],
    )


def test_a_file_tools_findings_are_told_with_the_call_and_not_again_at_its_finish(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    edit = Replacement(
        call="e1",
        tool="Edit",
        path=repo / CORE,
        old="    return x\n",
        new="    return x  # BAD regex\n",
    )
    decision = before(kit.bench, edit, SESSION, repo)
    assert decision.told.startswith("lup's findings on the lines changed")
    call(kit, repo, "e1", tool="Edit")
    (repo / CORE).write_text(edit.content((repo / CORE).read_text()) or "")
    assert finish(kit, repo, "e1") == Reply()
    store = worktree(kit, repo).store
    assert store.content(store.accepted(), CORE) == (repo / CORE).read_bytes()


def test_a_file_tools_write_to_a_test_is_told_its_type_errors_with_the_call(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    test = repo / "tests" / "test_core.py"
    text = "def test_it():\n    x: int = 'a'  # TYPE\n"
    write = Overwrite(call="w1", tool="Write", path=test, text=text)
    decision = before(kit.bench, write, SESSION, repo)
    assert decision.outcome == "allow"
    assert decision.told.startswith(
        "Type errors and ruff's findings in the files changed"
    )
    assert f"{test}:2:" in decision.told
    call(kit, repo, "w1", tool="Write")
    test.write_text(text)
    assert finish(kit, repo, "w1") == Reply()


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
    assert held(kit, lambda: before(kit.bench, write, SESSION, repo))
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
        "lup's findings on the lines changed"
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
    assert told.startswith("lup's findings on the lines changed")
    call(kit, repo, "a2", agent="a")
    assert finish(kit, repo, "a2", agent="a").context == told


HOOK = Path(".claude/hooks/check.py")


def protected_module(repo: Path, shell: Shell) -> None:
    (repo / HOOK).parent.mkdir(parents=True)
    (repo / HOOK).write_text((repo / CORE).read_text())
    shell.commit(repo, "a protected module")


def test_a_protected_modules_change_through_the_shell_is_held_and_put_back_on_a_no(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    protected_module(repo, shell)
    start(kit, repo)
    kit.announced.answering = Response(approved=False, comment="leave the hook")
    original = (repo / HOOK).read_text()
    reply = shell_write(kit, repo, "c1", HOOK, original + "y = 2  # BAD regex\n")
    assert reply.context.startswith("lup refused 1 file.")
    assert "The operator declined it: leave the hook" in reply.context
    assert (repo / HOOK).read_text() == original


def test_a_clean_change_to_a_protected_module_through_the_shell_is_held(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    protected_module(repo, shell)
    start(kit, repo)
    changed = (repo / HOOK).read_text().replace("return x", "return x + 1")
    reply = shell_write(kit, repo, "c1", HOOK, changed)
    assert reply.context.startswith("The operator approved the held change to")
    assert any(
        ".claude/hooks/check.py is a protected path" in each for each in last_asks(kit)
    )
    assert (repo / HOOK).read_text() == changed


def test_a_protected_modules_type_errors_keep_the_turn_from_ending(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    protected_module(repo, shell)
    start(kit, repo)
    broken = (repo / HOOK).read_text() + "y: int = 'a'  # TYPE\n"
    edit = Overwrite(call="w1", tool="Write", path=repo / HOOK, text=broken)
    assert held(kit, lambda: before(kit.bench, edit, SESSION, repo))
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
    """Its findings are told to the writer with the call, so neither the
    checkpoint after it nor the session's turn's end tells them again."""
    start(kit, repo)
    new = repo / "src" / "pkg" / "new.py"
    text = '"""New."""\nz: str = 1  # TYPE\n'
    write = Overwrite(call="w1", tool="Write", path=new, text=text)
    decision = before(kit.bench, write, SESSION, repo, agent="worker")
    assert decision.told.startswith(
        "Type errors and ruff's findings in the files changed"
    )
    call(kit, repo, "c1")
    call(kit, repo, "w1", tool="Write", agent="worker")
    new.write_text(text)
    assert finish(kit, repo, "c1") == Reply()
    assert finish(kit, repo, "w1", agent="worker") == Reply()
    assert session(kit, repo).touched == {"worker": [Path("src/pkg/new.py")]}
    assert end(kit, repo) == Reply()
    assert subagent_ends(kit, repo, "worker") == Reply()
    assert end(kit, repo) == Reply()


def test_a_subagent_is_at_work_until_its_end_lets_it_go(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    both_break_core(kit, repo)
    call(kit, repo, "worker-lost", agent="worker")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    first = subagent_ends(kit, repo, "worker").block
    assert first.startswith("The operator approved the held change to")
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
    assert told.startswith("The operator approved the held change to")


def test_a_subagents_file_tool_write_landed_before_its_call_finished_stays(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    new = repo / "src" / "pkg" / "new.py"
    write = Overwrite(call="w1", tool="Write", path=new, text='"""New."""\n')
    assert held(kit, lambda: before(kit.bench, write, SESSION, repo))
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
    assert block.startswith("The operator approved the held change to")
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
    assert let.note.startswith("lup held the turn's end once already, and lets it end")
    assert f"{repo}/src/pkg/core.py:11:" in let.note
    # A later turn ends at once: the findings were passed, and haven't changed.
    assert end(kit, repo) == Reply()


def test_an_end_following_a_hold_ends_whatever_is_left(kit: Kit, repo: Path) -> None:
    start(kit, repo)
    broken = (repo / CORE).read_text() + "y: int = 'a'  # TYPE\n"
    shell_write(kit, repo, "c1", CORE, broken)
    end(kit, repo)
    shell_write(kit, repo, "c2", CORE, broken + "z: str = 1  # TYPE\n")
    let = end(kit, repo, after_block=True)
    assert let.block == ""
    assert let.note.startswith("lup held the turn's end once already")
    assert f"{repo}/src/pkg/core.py:12:" in let.note
    assert end(kit, repo) == Reply()


def test_passed_findings_hold_a_later_end_only_where_they_change(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    original = (repo / CORE).read_text()
    broken = original + "y: int = 'a'  # TYPE\n"
    shell_write(kit, repo, "c1", CORE, broken)
    assert end(kit, repo).block.startswith("lup won't end the turn yet")
    end(kit, repo, after_block=True)
    assert end(kit, repo) == Reply()
    shell_write(kit, repo, "c2", CORE, broken + "z: str = 1  # TYPE\n")
    changed = end(kit, repo).block
    assert changed.startswith("lup won't end the turn yet")
    assert f"{repo}/src/pkg/core.py:12:" in changed
    end(kit, repo, after_block=True)
    shell_write(kit, repo, "c3", CORE, original)
    assert end(kit, repo) == Reply()
    shell_write(kit, repo, "c4", CORE, broken)
    assert end(kit, repo).block.startswith("lup won't end the turn yet")


def test_a_session_starting_again_keeps_what_its_turns_passed(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    shell_write(
        kit, repo, "c1", CORE, (repo / CORE).read_text() + "y: int = 'a'  # TYPE\n"
    )
    end(kit, repo)
    end(kit, repo, after_block=True)
    start(kit, repo)
    assert end(kit, repo) == Reply()


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
        "allow",
        ["regex"],
    )


def held_file(holding_kit: Kit, repo: Path) -> Path:
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch")
    new = repo / "src" / "pkg" / "new.py"
    new.write_text('"""New."""\n')
    return new


def test_a_write_flagged_at_the_checkpoint_is_put_before_the_operator_holding_no_one(
    holding_kit: Kit, repo: Path
) -> None:
    holding_kit.announced.holding_all = False
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch", agent="a1")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    assert finish(holding_kit, repo, "p1", agent="a1").context == ""
    assert holding_kit.announced.holds == []
    call(holding_kit, repo, "p2", tool="apply_patch", agent="a1")
    (repo / "src" / "pkg" / "new.py").write_text(
        '"""New."""\n\n\nclass Room:\n    pass\n'
    )
    finish(holding_kit, repo, "p2", agent="a1")
    made, joined = holding_kit.flags.asked
    assert (made.sender.runtime, made.sender.agent, made.call) == (
        "holding",
        "a1",
        "p1",
    )
    assert made.file == ChangedFile(
        path=Path("src/pkg/new.py"),
        before=None,
        after=Text(text='"""New."""\n'),
        reading=Reading(
            role="production", asks=[Asked(name="new-file", taken="flagged")]
        ),
    )
    assert made.flagged.summary == "src/pkg/new.py is a new production file"
    # Joined, the file is judged whole since the item was made.
    assert (joined.joining, joined.call, joined.file.before) == (1, "p2", None)
    assert joined.flagged.summary.splitlines() == [
        "src/pkg/new.py is a new production file",
        "src/pkg/new.py adds the class `Room`",
    ]
    assert joined.file.reading is not None
    assert [each.name for each in joined.file.reading.asks] == [
        "new-file",
        "public-api",
    ]


def test_a_patch_flagging_nothing_refreshes_its_conversations_item_at_the_checkpoint(
    holding_kit: Kit, repo: Path
) -> None:
    holding_kit.announced.holding_all = False
    new = repo / "src" / "pkg" / "new.py"
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch", agent="a1")
    new.write_text('"""New."""\n')
    finish(holding_kit, repo, "p1", agent="a1")
    # A patch to a file no item gathers asks the inbox nothing.
    call(holding_kit, repo, "p2", tool="apply_patch", agent="a1")
    (repo / CORE).write_text((repo / CORE).read_text() + "\nLIMIT = 3\n")
    finish(holding_kit, repo, "p2", agent="a1")
    assert len(holding_kit.flags.shown) == 1
    # One to the item's file refreshes it, its file as it stands, judged whole.
    call(holding_kit, repo, "p3", tool="apply_patch", agent="a1")
    new.write_text('"""New."""\n\nLIMIT = 3\n')
    finish(holding_kit, repo, "p3", agent="a1")
    made, refreshed = holding_kit.flags.asked
    assert (refreshed.joining, refreshed.refreshing, refreshed.call) == (
        1,
        True,
        "p3",
    )
    assert refreshed.file.before is None
    assert refreshed.file.after == Text(text='"""New."""\n\nLIMIT = 3\n')
    assert refreshed.flagged.summary == made.flagged.summary
    # Another conversation's patch to the file asks nothing: the item is a1's.
    call(holding_kit, repo, "p4", tool="apply_patch", agent="a2")
    new.write_text('"""New."""\n\nLIMIT = 4\n')
    finish(holding_kit, repo, "p4", agent="a2")
    assert len(holding_kit.flags.asked) == 2


def test_what_a_move_brought_flagged_is_put_before_the_operator_naming_its_commit(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    shell.commit(repo, "sneak it in")
    finish(kit, repo, "c1")
    head = shell.git(repo, "rev-parse", "HEAD")
    [asked] = kit.flags.asked
    assert asked.flagged.text == (
        f"src/pkg/new.py landed with commit {head}, flagged for the operator's review."
    )
    assert (asked.flagged.commit, asked.sender.agent, asked.call) == (head, None, None)


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
    [hold] = holding_kit.announced.holds
    assert (hold.call, hold.agent) == ("p1", None)
    assert holding_kit.announced.files == [
        [
            ChangedFile(
                path=Path("src/pkg/new.py"),
                before=None,
                after=Text(text='"""New."""\n'),
                reading=Reading(
                    role="production", asks=[Asked(name="new-file", taken="held")]
                ),
            )
        ]
    ]


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


def test_a_finding_on_a_holding_runtime_is_told_not_held(
    holding_kit: Kit, repo: Path
) -> None:
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch")
    (repo / CORE).write_text((repo / CORE).read_text() + "y = 2  # BAD regex\n")
    assert finish(holding_kit, repo, "p1").context.startswith(
        "lup's findings on the lines changed"
    )
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
        (repo / "README.md").write_text("# The operator's\n")
        start(kit, repo, "other")
        store = worktree(kit, repo).store
        accepted.append(store.content(store.accepted(), PYPROJECT))
        accepted.append(store.content(store.started("other"), PYPROJECT))
        call_for("other", kit, repo, "o1")
        (repo / "tests" / "test_other.py").write_text("def test_other(): ...\n")
        heard.append(finish(kit, repo, "o1", session="other"))
        heard.append(end(kit, repo, "other"))
        accepted.append(store.content(store.accepted(), PYPROJECT))

    decline_on_sleep(kit, other_session)
    reply = finish(kit, repo, "p1")
    assert "The operator declined it: not now" in reply.context
    assert (repo / PYPROJECT).read_text() == original
    saved = repo / ".lup" / "saved" / "1" / PYPROJECT
    assert saved.read_text() == original + "# a dependency\n"
    assert accepted == [original.encode()] * 3
    assert heard == [Reply(), Reply()]
    store = worktree(kit, repo).store
    assert store.content(store.accepted(), Path("README.md")) == b"# The operator's\n"
    assert store.content(store.accepted(), Path("tests/test_other.py")) is not None


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
    assert told.startswith("lup's findings on the lines changed")
    assert f"{linked}/src/pkg/core.py:11:8 - regex" in told


def test_a_call_counts_in_every_worktree_its_conversation_works_in(
    kit: Kit, repo: Path, linked: Path
) -> None:
    start(kit, repo)
    call(kit, linked, "c1")
    finish(kit, linked, "c1")
    call(kit, repo, "c2")
    bad(linked)
    call(kit, linked, "c3")
    assert finish(kit, linked, "c3").context == ""
    assert finish(kit, repo, "c2").context.startswith(
        "lup's findings on the lines changed"
    )


def edits_in(
    kit: Kit, cwd: Path, root: Path, key: str, *, agent: str, old: str = "def helper"
) -> None:
    """Conversation `agent` edits `old` in `CORE` in the worktree at `root` with a file tool, its hooks reporting `cwd`, as a subagent's report the session's."""
    edit = Replacement(call=key, tool="Edit", path=root / CORE, old=old, new=f"{old}_")
    before(kit.bench, edit, SESSION, cwd, agent=agent)
    call(kit, cwd, key, tool="Edit", agent=agent)
    (root / CORE).write_text(edit.content((root / CORE).read_text()) or "")
    finish(kit, cwd, key, agent=agent)


def test_a_subagent_busy_in_its_worktree_holds_back_checkpoints_there_alone(
    kit: Kit, repo: Path, linked: Path
) -> None:
    """A worker's hooks report the session's worktree, where its calls start;
    once its file tools wrote in its own, its calls count there alone."""
    start(kit, repo)
    edits_in(kit, repo, linked, "w1", agent="worker")
    call(kit, repo, "w2", agent="worker")
    assert running(kit, repo) == []
    assert running(kit, linked) == ["w2"]
    mine = shell_write(
        kit, repo, "c1", CORE, (repo / CORE).read_text() + "y = 2  # BAD regex\n"
    )
    assert mine.context.startswith("lup's findings on the lines changed")
    edits_in(kit, repo, linked, "r1", agent="reviewer", old="def ask")
    call(kit, repo, "r2", agent="reviewer")
    bad(linked)
    assert finish(kit, repo, "r2", agent="reviewer").context == ""
    worker = finish(kit, repo, "w2", agent="worker").context
    assert f"{linked}/src/pkg/core.py:11:8 - regex" in worker


def test_a_subagent_works_where_its_session_does_until_its_file_tools_write(
    kit: Kit, repo: Path
) -> None:
    start(kit, repo)
    call(kit, repo, "w1", agent="worker")
    reply = shell_write(
        kit, repo, "c1", CORE, (repo / CORE).read_text() + "y = 2  # BAD regex\n"
    )
    assert reply.context == ""
    worker = finish(kit, repo, "w1", agent="worker").context
    assert worker.startswith("lup's findings on the lines changed")


def test_the_turns_end_judges_every_worktree_but_where_anothers_call_runs(
    kit: Kit, repo: Path, linked: Path
) -> None:
    """The session's turn's end leaves a worker's running call alone, and so
    its worktree, whose checkpoint that call's finish runs; elsewhere it runs
    its last checkpoint."""
    start(kit, repo)
    edits_in(kit, repo, linked, "w1", agent="worker")
    call(kit, repo, "w2", agent="worker")
    call(kit, repo, "lost")
    bad(repo)
    bad(linked)
    block = end(kit, repo).block
    assert f"{repo}/src/pkg/core.py:11:8 - regex" in block
    assert str(linked) not in block
    assert running(kit, linked) == ["w2"]
    assert running(kit, repo) == []


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
    assert finish(kit, repo, "c2").context.startswith(
        "lup's findings on the lines changed"
    )
    assert str(linked) not in end(kit, repo).block


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
    assert block.startswith("lup won't end the turn yet")
    assert f"{repo}/src/pkg/core.py:11:8 - regex" in block
    assert f"{linked}/src/pkg/core.py:11:8 - regex" in block


def test_every_worktree_is_judged_by_the_integration_branchs_declaration(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    declare(linked, PROTECTING_NOTHING)
    shell.commit(linked, "feat: protect nothing")
    start(kit, repo)
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    assert last_asks(kit) == ["src/pkg/core.py is a protected path (src/pkg/core.py)"]
    assert [hold.worktree for hold in kit.announced.holds][-1] == linked
    assert Worktree.at(linked, kit.layout).roles.protecting(CORE) is None


def test_the_integration_branchs_declaration_changes_when_committed(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    (repo / "lup_project.py").write_text(PROTECTING_NOTHING)
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    shell.commit(repo, "dev: protect nothing")
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


def test_without_the_integration_branch_a_worktree_is_judged_by_its_head(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "main: protect the core")
    (repo / "lup_project.py").write_text(PROTECTING_NOTHING)
    start(kit, repo)
    assert held(kit, lambda: before(kit.bench, core_edit(repo), SESSION, repo))


def approve(kit: Kit, repo: Path, commit: str, local: str | None = None) -> None:
    """Record `commit`, with the person's own layer `local`, as the operator approved, as trust on launch does."""
    approval = Approval(
        commit=commit,
        fingerprint="approved",
        paths=[Path("lup_project.py")],
        tool=ReleaseTool(name="lup-dev", version="0.4.0", registry="index", pins={}),
        time=kit.clock.now(),
        local=local,
    )
    write_model(kit.layout.approved(repo / ".git"), approval)


LOCAL_PROTECTING_CORE = '''
from lup_dev import Module, Modules, Paths, Project


class Mine(Module):
    """The person's own module, protecting the core for themselves."""

    name = "mine"

    paths: Paths = Paths.of(protected=["src/pkg/core.py"])


project = Project(modules=Modules().add(Mine()))
'''
"""The person's own layer, adding a module of theirs to the project's."""


def test_the_approved_copy_of_the_person_s_layer_judges_not_the_worktree_s(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_NOTHING)
    shell.commit(repo, "dev: protect nothing")
    head = shell.git(repo, "rev-parse", "HEAD")
    approve(kit, repo, head, LOCAL_PROTECTING_CORE)
    (repo / "lup_project.local.py").write_text(
        "from lup_dev import Project\nproject = Project()\n"
    )
    start(kit, repo)
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    approve(kit, repo, head)
    (repo / "lup_project.local.py").write_text(LOCAL_PROTECTING_CORE)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


def test_a_layer_of_the_person_s_a_commit_holds_is_never_read(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_NOTHING)
    (repo / "lup_project.local.py").write_text(LOCAL_PROTECTING_CORE)
    shell.commit(repo, "dev: a layer committed by mistake")
    approve(kit, repo, shell.git(repo, "rev-parse", "HEAD"))
    start(kit, repo)
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


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
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    approve(kit, repo, shell.git(repo, "rev-parse", "HEAD"))
    assert before(kit.bench, core_edit(linked), SESSION, repo).outcome == "allow"


def test_an_approved_commit_gone_from_the_repository_has_the_stand_in(
    kit: Kit, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(repo, "switch", "-q", "-c", "dev")
    declare(repo, PROTECTING_CORE)
    shell.commit(repo, "dev: protect the core")
    start(kit, repo)
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    gone = "0" * 40
    approve(kit, repo, gone)
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
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

    assert held(kit, lambda: before(kit.bench, write(repo, "w1"), SESSION, repo))
    call(kit, repo, "w1", tool="Write")
    (repo / "src" / "pkg" / "new.py").write_text('"""New."""\n')
    finish(kit, repo, "w1")
    assert before(kit.bench, write(repo, "w2"), SESSION, repo).outcome == "allow"
    assert held(kit, lambda: before(kit.bench, write(linked, "w3"), SESSION, repo))


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
    assert before(kit.bench, edit, SESSION, bare / "tree").outcome == "allow"
    call(kit, bare, "c1")
    bad(main)
    assert finish(kit, bare, "c1").context.startswith(
        "lup's findings on the lines changed"
    )


def test_a_session_s_start_tells_what_came_due_and_a_subagent_s_doesn_t(
    kit: Kit, repo: Path
) -> None:
    reminder = Finding(
        path=CORE,
        span=Span(start=Position(line=3, column=1), end=Position(line=3, column=1)),
        owner="lup",
        rule="defer-closed",
        message="issue #12 is closed",
        steer="finish the work here",
        reminder=True,
    )
    write_model(repo / ".git" / "lup" / "due.json", Due(reminders=[reminder]))

    told = SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)
    sub = SessionStarted(session=SESSION, cwd=repo, agent="a1").apply(kit.bench)

    assert told.context == (
        "Work deferred in this repository came due, as the gate last found it (it "
        "doesn't fail the gate):\n- src/pkg/core.py:3: issue #12 is closed; finish "
        "the work here"
    )
    assert sub.context == ""


def test_a_session_s_start_with_nothing_due_tells_nothing(kit: Kit, repo: Path) -> None:
    assert SessionStarted(session=SESSION, cwd=repo).apply(kit.bench).context == ""


def test_a_write_in_the_repositorys_git_directory_asks(kit: Kit, bare: Path) -> None:
    main = bare / "tree" / "main"
    start(kit, main)
    hook = Overwrite(
        call="w1", tool="Write", path=bare / "hooks" / "pre-commit", text="#!/bin/sh\n"
    )
    assert held(kit, lambda: before(kit.bench, hook, SESSION, main))
    assert last_asks(kit) == [
        (
            f"{bare}/hooks/pre-commit is in the repository's git directory, "
            "which runs outside the agent's reach"
        )
    ]
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
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    (repo / "lup_project.py").write_text(
        "from lup_dev import Unheard\n" + PROTECTING_CORE
    )
    shell.commit(repo, "dev: a name the judge lacks")
    broken = shell.git(repo, "rev-parse", "HEAD")
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    assert any("is a protected path (src/pkg/core.py)" in ask for ask in last_asks(kit))
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
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    (repo / "lup_project.py").write_text(
        PROTECTING_CORE.replace(".add(Guard())", '.add(Guard()).drop("ledger")')
    )
    shell.commit(repo, "dev: drop a module that isn't there")
    assert held(kit, lambda: before(kit.bench, core_edit(linked), SESSION, repo))
    assert any("is a protected path (src/pkg/core.py)" in ask for ask in last_asks(kit))


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


# A value never published, told at the checkpoint after the call


def test_a_patch_carrying_a_private_value_lands_its_value_told_after_the_call(
    holding_kit: Kit, repo: Path
) -> None:
    withheld = Withheld(held=[Held(kind="value", text="Kestrel Labs")])
    repository = worktree(holding_kit, repo).repository
    write_model(kept(holding_kit.layout.module_data("private", repository)), withheld)
    holding_kit.announced.holding_all = False
    start(holding_kit, repo)
    call(holding_kit, repo, "p1", tool="apply_patch")
    notes = repo / "docs" / "notes.md"
    notes.parent.mkdir()
    notes.write_text("# Notes\n\nFor Kestrel Labs.\n")
    reply = finish(holding_kit, repo, "p1")
    assert reply.context.startswith("Values never published, on the lines changed")
    assert (
        f"  {repo}/docs/notes.md:3:5 - private: one of the operator's private values"
    ) in reply.context
    assert notes.read_text() == "# Notes\n\nFor Kestrel Labs.\n"
    assert holding_kit.announced.holds == []
    [flagged] = holding_kit.flags.asked
    assert flagged.flagged.summary == (
        "docs/notes.md:3 - one of the operator's private values"
    )
    [verdict] = [
        each
        for each in log(holding_kit, repo).read()
        if each.path == Path("docs/notes.md")
    ]
    assert (verdict.outcome, verdict.reasons) == ("allow", ["private"])
