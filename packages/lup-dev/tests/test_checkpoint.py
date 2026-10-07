"""The checkpoint: when it runs, what it judges, and what it does about it."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock

from lup_dev.before import Overwrite, Replacement, before
from lup_dev.changes import read_model
from lup_dev.checker import FileReport, Finding, Position, Span
from lup_dev.checkpoint import (
    CallFinished,
    CallStarted,
    ImportersPass,
    Reply,
    Session,
    SessionStarted,
    TurnEnded,
    Worktree,
)
from lup_dev.holds import Holds, Response, waiting

if TYPE_CHECKING:
    from conftest import Kit, Shell

    from lup_dev.verdicts import VerdictLog

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


def finish(kit: Kit, repo: Path, key: str, *, agent: str = "") -> Reply:
    return CallFinished(session=SESSION, agent=agent, cwd=repo, call=key).apply(
        kit.bench
    )


def end(kit: Kit, repo: Path) -> Reply:
    return TurnEnded(session=SESSION, cwd=repo).apply(kit.bench)


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
    assert "src/pkg/core.py:11:8 - regex: regex fires here" in reply.context
    assert "mv .lup/saved/1/src/pkg/core.py src/pkg/core.py" in reply.context
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


def test_a_write_committed_in_the_same_call_is_judged(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    start(kit, repo)
    call(kit, repo, "c1")
    (repo / CORE).write_text("x = 1  # BAD regex\n")
    shell.commit(repo, "sneak it in")
    assert finish(kit, repo, "c1").context.startswith("lup refused 1 file.")


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
    assert decision.reason == "lup asks: src/pkg/core.py adds the class `Room`"
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
        "The operator approved the held change to src/pkg/new.py: good name"
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
    Holds(layout=holding_kit.layout.store(repo)).answer(
        hold.key, Response(approved=True), holding_kit.clock
    )
    call(holding_kit, repo, "p2")
    late = finish(holding_kit, repo, "p2").context
    assert (
        "After the hold timed out, the operator approved the change to src/pkg/new.py"
        in late
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
    assert "src/pkg/user.py:1:1 - reportCallIssue: wrong arguments" in block
