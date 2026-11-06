"""What a commit brings, judged at the checkpoint where `HEAD` moved to it, whatever the worktree holds."""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.policy.before import Overwrite, before
from lup_dev.policy.checkpoint import (
    CallFinished,
    CallStarted,
    Reply,
    SessionStarted,
    Worktree,
)
from lup_dev.policy.holds import Hold, Response, answer, waiting

if TYPE_CHECKING:
    from conftest import Dying, Kit, Shell

    from lup_dev.policy.store import Store

CORE = Path("src/pkg/core.py")
AGENTS = Path("AGENTS.md")
SESSION = "s1"


def start(kit: Kit, repo: Path) -> None:
    SessionStarted(session=SESSION, cwd=repo).apply(kit.bench)


def begin(kit: Kit, repo: Path, key: str) -> None:
    CallStarted(session=SESSION, cwd=repo, call=key, tool="Bash").apply(kit.bench)


def finish(kit: Kit, repo: Path, key: str) -> Reply:
    return CallFinished(session=SESSION, cwd=repo, call=key, tool="Bash").apply(
        kit.bench
    )


def store(kit: Kit, repo: Path) -> Store:
    return Worktree.at(repo, kit.layout).store


def accepted(kit: Kit, repo: Path, path: Path) -> bytes | None:
    found = store(kit, repo)
    return found.content(found.accepted(), path)


def from_the_index(repo: Path, shell: Shell, path: Path, content: bytes) -> str:
    """Commit `content` at `path` from the index alone, the worktree's file left as it is; return the commit."""
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        input=content,
        capture_output=True,
        check=True,
    ).stdout.decode()
    entry = f"100644,{blob.strip()},{path}"
    shell.git(repo, "update-index", "--add", "--cacheinfo", entry)
    shell.git(repo, "commit", "-q", "-m", "from the index")
    return shell.git(repo, "rev-parse", "HEAD")


def asked(kit: Kit) -> list[Hold]:
    return kit.announced.holds


def on_defaults(kit: Kit, repo: Path, shell: Shell) -> None:
    """Hold `kit` to the project's own defaults, with `AGENTS.md` committed, and start the session."""
    kit.announced.holding_all = False
    (repo / AGENTS).write_text("# Agents\n")
    shell.commit(repo, "the operator's document")
    start(kit, repo)


# What a move brings where nothing in the worktree shows it.


def test_a_protected_file_committed_from_the_index_is_asked_about_at_its_commit(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    begin(kit, repo, "c1")
    commit = from_the_index(repo, shell, AGENTS, b"# Agents\nmore\n")
    told = finish(kit, repo, "c1").context
    [hold] = asked(kit)
    assert hold.commit == commit
    assert [each.path for each in hold.files] == [AGENTS]
    assert "more" in hold.diff
    assert f"HEAD moved to {commit}" in told
    assert (repo / AGENTS).read_text() == "# Agents\n"
    assert accepted(kit, repo, AGENTS) == b"# Agents\n"
    # Asked once: brought into the worktree, it's what the operator was asked about.
    begin(kit, repo, "c2")
    shell.git(repo, "checkout", "HEAD", "--", str(AGENTS))
    finish(kit, repo, "c2")
    assert len(asked(kit)) == 1
    assert accepted(kit, repo, AGENTS) == b"# Agents\nmore\n"


def test_a_production_file_committed_from_the_index_is_told_as_a_commit_s(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    begin(kit, repo, "c1")
    from_the_index(repo, shell, CORE, b"x = 1  # BAD regex\n")
    told = finish(kit, repo, "c1").context
    assert asked(kit) == []
    assert f"{repo / CORE}:1:8 - regex" in told


def test_a_protected_file_a_commit_alone_deletes_is_asked_about_at_its_commit(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    begin(kit, repo, "c1")
    shell.git(repo, "rm", "-q", "--cached", str(AGENTS))
    shell.git(repo, "commit", "-q", "-m", "out of the index")
    finish(kit, repo, "c1")
    [hold] = asked(kit)
    assert [(each.path, each.blob) for each in hold.files] == [(AGENTS, "")]
    assert (repo / AGENTS).read_text() == "# Agents\n"


# A commit under an open hold.


def held(kit: Kit, repo: Path, shell: Shell, dying: Dying, content: str) -> str:
    """Hold a write to `AGENTS.md` of `content`, its call's process ending as it waits; return the hold's key."""
    on_defaults(kit, repo, shell)
    begin(kit, repo, "c1")
    (repo / AGENTS).write_text(content)
    dying.at_next_wait(kit.clock)
    with pytest.raises(dying.died):
        finish(kit, repo, "c1")
    [hold] = waiting(kit.layout)
    return hold.key


def test_the_version_held_committed_adds_no_item(
    holding_kit: Kit, repo: Path, shell: Shell, dying: Dying
) -> None:
    kit = holding_kit
    held(kit, repo, shell, dying, "# Agents\nheld\n")
    begin(kit, repo, "c2")
    shell.commit(repo, "the file held")
    assert finish(kit, repo, "c2").context == ""
    assert len(asked(kit)) == 1


@pytest.mark.parametrize(
    "back",
    [
        ["checkout", "HEAD", "--", str(AGENTS)],
        ["reset", "--hard", "-q", "HEAD"],
        ["restore", "--source=HEAD", "--", str(AGENTS)],
    ],
)
def test_a_version_declined_that_a_commit_holds_asks_again_if_it_comes_back(
    holding_kit: Kit, repo: Path, shell: Shell, dying: Dying, back: list[str]
) -> None:
    kit = holding_kit
    key = held(kit, repo, shell, dying, "# Agents\nheld\n")
    begin(kit, repo, "c2")
    shell.commit(repo, "the file held")
    finish(kit, repo, "c2")
    answer(kit.layout, key, Response(approved=False), [], kit.clock)
    begin(kit, repo, "c3")
    told = finish(kit, repo, "c3").context
    head = shell.git(repo, "rev-parse", "HEAD")
    assert (repo / AGENTS).read_text() == "# Agents\n"
    assert accepted(kit, repo, AGENTS) == b"# Agents\n"
    assert head[:12] in told
    begin(kit, repo, "c4")
    shell.git(repo, *back)
    kit.announced.answering = Response(approved=False)
    finish(kit, repo, "c4")
    [_, again] = asked(kit)
    assert [each.path for each in again.files] == [AGENTS]
    assert (repo / AGENTS).read_text() == "# Agents\n"


def test_a_version_declined_then_approved_stays_approved_if_it_comes_back(
    holding_kit: Kit, repo: Path, shell: Shell, dying: Dying
) -> None:
    kit = holding_kit
    key = held(kit, repo, shell, dying, "# Agents\nheld\n")
    begin(kit, repo, "c2")
    shell.commit(repo, "the file held")
    finish(kit, repo, "c2")
    answer(kit.layout, key, Response(approved=False), [], kit.clock)
    begin(kit, repo, "c3")
    finish(kit, repo, "c3")
    begin(kit, repo, "c4")
    shell.git(repo, "checkout", "HEAD", "--", str(AGENTS))
    kit.announced.answering = Response(approved=True)
    finish(kit, repo, "c4")
    assert len(asked(kit)) == 2
    # Taken away and brought back, each from history: the operator's latest answer stands.
    begin(kit, repo, "c5")
    shell.git(repo, "checkout", "HEAD~1", "--", str(AGENTS))
    finish(kit, repo, "c5")
    begin(kit, repo, "c6")
    shell.git(repo, "checkout", "HEAD", "--", str(AGENTS))
    finish(kit, repo, "c6")
    assert len(asked(kit)) == 2
    assert accepted(kit, repo, AGENTS) == b"# Agents\nheld\n"


def test_another_version_committed_under_a_hold_is_asked_about_at_its_commit_and_no_approval_of_the_first_covers_it(
    holding_kit: Kit, repo: Path, shell: Shell, dying: Dying
) -> None:
    kit = holding_kit
    key = held(kit, repo, shell, dying, "# Agents\nshown\n")
    begin(kit, repo, "c2")
    (repo / AGENTS).write_text("# Agents\nanother\n")
    shell.commit(repo, "another version")
    finish(kit, repo, "c2")
    head = shell.git(repo, "rev-parse", "HEAD")
    [_, second] = asked(kit)
    assert second.commit == head
    assert "another" in second.diff
    # What's shown is approved; what's committed has its own answer still to come.
    answer(kit.layout, key, Response(approved=True), [], kit.clock)
    begin(kit, repo, "c3")
    told = finish(kit, repo, "c3").context
    assert "It isn't in place" in told
    open_holds = [each.key for each in waiting(kit.layout)]
    assert open_holds == [second.key]


def test_another_version_committed_under_a_hold_and_declined_asks_again_if_it_stays(
    holding_kit: Kit, repo: Path, shell: Shell, dying: Dying
) -> None:
    kit = holding_kit
    key = held(kit, repo, shell, dying, "# Agents\nshown\n")
    begin(kit, repo, "c2")
    (repo / AGENTS).write_text("# Agents\nanother\n")
    shell.commit(repo, "another version")
    finish(kit, repo, "c2")
    [_, second] = asked(kit)
    answer(kit.layout, second.key, Response(approved=False), [], kit.clock)
    answer(kit.layout, key, Response(approved=True), [], kit.clock)
    begin(kit, repo, "c3")
    kit.announced.answering = Response(approved=False)
    finish(kit, repo, "c3")
    [_, _, third] = asked(kit)
    assert [each.path for each in third.files] == [AGENTS]
    assert third.commit is None
    assert (repo / AGENTS).read_text() == "# Agents\n"


def test_an_approved_version_committed_asks_nothing_and_another_committed_with_it_does(
    holding_kit: Kit, repo: Path, shell: Shell, dying: Dying
) -> None:
    kit = holding_kit
    key = held(kit, repo, shell, dying, "# Agents\nshown\n")
    answer(kit.layout, key, Response(approved=True), [], kit.clock)
    begin(kit, repo, "c2")
    shell.git(repo, "add", str(AGENTS))
    shell.git(repo, "commit", "-q", "-m", "the version approved")
    finish(kit, repo, "c2")
    assert len(asked(kit)) == 1
    begin(kit, repo, "c3")
    commit = from_the_index(repo, shell, AGENTS, b"# Agents\nnever shown\n")
    finish(kit, repo, "c3")
    [_, second] = asked(kit)
    assert second.commit == commit


# Ordinary work asks nothing new.


def ordinary(kit: Kit, told: str, flags: int = 0) -> None:
    """Say what ordinary work leaves: nothing asked, and no move told."""
    assert asked(kit) == []
    assert len(kit.flags.asked) == flags
    assert "HEAD moved" not in told


def edited(kit: Kit, repo: Path, content: str = "# More\n") -> None:
    """Write a file nothing asks about, accepted at its call's checkpoint."""
    begin(kit, repo, "edit")
    (repo / "README.md").write_text(content)
    assert finish(kit, repo, "edit").context == ""


def test_a_commit_of_what_was_accepted_asks_nothing(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    edited(kit, repo)
    begin(kit, repo, "c1")
    shell.commit(repo, "what was accepted")
    told = finish(kit, repo, "c1").context
    assert told == ""
    ordinary(kit, told)


def test_a_commit_of_what_was_approved_asks_nothing(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    kit.announced.answering = Response(approved=True)
    begin(kit, repo, "c1")
    (repo / AGENTS).write_text("# Agents\nmore\n")
    finish(kit, repo, "c1")
    assert len(asked(kit)) == 1
    begin(kit, repo, "c2")
    shell.commit(repo, "what was approved")
    assert finish(kit, repo, "c2").context == ""
    assert len(asked(kit)) == 1


def test_a_commit_of_a_file_tool_s_write_asks_nothing_more(
    kit: Kit, repo: Path, shell: Shell
) -> None:
    kit.announced.holding_all = False
    (repo / AGENTS).write_text("# Agents\n")
    shell.commit(repo, "the operator's document")
    start(kit, repo)
    write = Overwrite(call="w1", tool="Write", path=repo / AGENTS, text="# Agents\nw\n")
    CallStarted(session=SESSION, cwd=repo, call="w1", tool="Write").apply(kit.bench)
    assert before(kit.bench, write, SESSION, repo).outcome == "allow"
    (repo / AGENTS).write_text(write.text)
    CallFinished(session=SESSION, cwd=repo, call="w1", tool="Write").apply(kit.bench)
    assert len(asked(kit)) == 1
    begin(kit, repo, "c1")
    shell.commit(repo, "the file tool's write")
    assert finish(kit, repo, "c1").context == ""
    assert len(asked(kit)) == 1


@pytest.mark.parametrize(
    "command",
    [
        ["commit", "-q", "--amend", "-m", "said otherwise"],
        ["commit", "-q", "--allow-empty", "-m", "nothing"],
        ["switch", "-q", "-c", "beside"],
        ["branch", "beside"],
        ["tag", "marked"],
        ["reset", "--soft", "-q", "HEAD~1"],
        ["revert", "--no-edit", "HEAD"],
        ["reset", "--hard", "-q", "HEAD~1"],
        ["checkout", "-q", "--detach", "HEAD~1"],
    ],
)
def test_a_move_through_what_s_already_in_the_history_asks_nothing(
    holding_kit: Kit, repo: Path, shell: Shell, command: list[str]
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    edited(kit, repo)
    shell.commit(repo, "the edit")
    begin(kit, repo, "seen")
    finish(kit, repo, "seen")
    begin(kit, repo, "c1")
    shell.git(repo, *command)
    told = finish(kit, repo, "c1").context
    ordinary(kit, told)


def test_a_branch_made_merged_rebased_and_left_asks_nothing(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    begin(kit, repo, "c1")
    shell.git(repo, "switch", "-q", "-c", "side")
    assert finish(kit, repo, "c1").context == ""
    edited(kit, repo, "# On the side\n")
    begin(kit, repo, "c2")
    shell.commit(repo, "on the side")
    assert finish(kit, repo, "c2").context == ""
    begin(kit, repo, "c3")
    shell.git(repo, "switch", "-q", "main")
    assert finish(kit, repo, "c3").context == ""
    begin(kit, repo, "c4")
    (repo / "docs.md").write_text("# On main\n")
    finish(kit, repo, "c4")
    begin(kit, repo, "c5")
    shell.commit(repo, "on main")
    assert finish(kit, repo, "c5").context == ""
    begin(kit, repo, "c6")
    shell.git(repo, "switch", "-q", "side")
    assert finish(kit, repo, "c6").context == ""
    begin(kit, repo, "c7")
    shell.git(repo, "rebase", "-q", "main")
    told = finish(kit, repo, "c7").context
    ordinary(kit, told)
    begin(kit, repo, "c8")
    shell.git(repo, "switch", "-q", "main")
    finish(kit, repo, "c8")
    begin(kit, repo, "c9")
    shell.git(repo, "merge", "-q", "--no-ff", "--no-edit", "side")
    told = finish(kit, repo, "c9").context
    ordinary(kit, told)


def forge_ahead(repo: Path, tmp_path: Path, shell: Shell, name: str) -> None:
    """Give `repo` a remote `origin`, a commit on its `main` the repository doesn't hold yet, changing `name`."""
    forge = tmp_path / "forge.git"
    shell.git(tmp_path, "clone", "-q", "--bare", str(repo), str(forge))
    shell.git(repo, "remote", "add", "origin", str(forge))
    other = tmp_path / "elsewhere"
    shell.git(tmp_path, "clone", "-q", str(forge), str(other))
    shell.git(other, "config", "user.email", "test@example.com")
    shell.git(other, "config", "user.name", "Test")
    (other / name).write_text("# From the remote\n")
    shell.commit(other, "from the remote")
    shell.git(other, "push", "-q", "origin", "main")


def test_a_pull_asks_nothing(
    holding_kit: Kit, repo: Path, tmp_path: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    forge_ahead(repo, tmp_path, shell, "README.md")
    begin(kit, repo, "c1")
    shell.git(repo, "pull", "-q", "--ff-only", "origin", "main")
    told = finish(kit, repo, "c1").context
    ordinary(kit, told)


def test_a_protected_file_a_pull_brings_asks_nothing(
    holding_kit: Kit, repo: Path, tmp_path: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    forge_ahead(repo, tmp_path, shell, str(AGENTS))
    begin(kit, repo, "c1")
    shell.git(repo, "pull", "-q", "--ff-only", "origin", "main")
    told = finish(kit, repo, "c1").context
    ordinary(kit, told)


def test_a_soft_reset_to_what_the_remote_holds_asks_nothing(
    holding_kit: Kit, repo: Path, tmp_path: Path, shell: Shell
) -> None:
    """`HEAD` moves with the worktree left as it was: the remote's commit holds what it brings."""
    kit = holding_kit
    on_defaults(kit, repo, shell)
    forge_ahead(repo, tmp_path, shell, str(AGENTS))
    begin(kit, repo, "c1")
    shell.git(repo, "fetch", "-q", "origin")
    shell.git(repo, "reset", "--soft", "-q", "origin/main")
    told = finish(kit, repo, "c1").context
    ordinary(kit, told)
    assert (repo / AGENTS).read_text() == "# Agents\n"


def test_a_commit_of_part_of_a_file_holds_nothing_where_its_role_asks_nothing(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    """What's staged apart has no version the judge saw, as `lup-dev stage` makes one: told as a commit's, and no hold."""
    kit = holding_kit
    on_defaults(kit, repo, shell)
    readme = repo / "README.md"
    begin(kit, repo, "c1")
    readme.write_text("# Work\none\ntwo\n")
    assert finish(kit, repo, "c1").context == ""
    begin(kit, repo, "c2")
    from_the_index(repo, shell, Path("README.md"), b"# Work\none\n")
    told = finish(kit, repo, "c2").context
    assert asked(kit) == []
    assert kit.flags.asked == []
    assert told == ""
    assert readme.read_text() == "# Work\none\ntwo\n"
    begin(kit, repo, "c3")
    shell.commit(repo, "the rest")
    assert finish(kit, repo, "c3").context == ""
    assert asked(kit) == []


def test_a_commit_of_part_of_a_production_file_asks_what_it_adds_and_holds_nothing(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    """Judged as what the commit changes, so what it leaves out isn't read as removed."""
    kit = holding_kit
    on_defaults(kit, repo, shell)
    was = (repo / CORE).read_text()
    begin(kit, repo, "c1")
    (repo / CORE).write_text(
        f"{was}\n\ndef first() -> int:\n    return 1\n\n\ndef second() -> int:\n    return 2\n"
    )
    finish(kit, repo, "c1")
    flagged = len(kit.flags.asked)
    begin(kit, repo, "c2")
    part = f"{was}\n\ndef first() -> int:\n    return 1\n"
    from_the_index(repo, shell, CORE, part.encode())
    finish(kit, repo, "c2")
    assert asked(kit) == []
    [_, *new] = kit.flags.asked[flagged - 1 :]
    assert [str(each.file.path) for each in new] == [str(CORE)]
    assert all(
        ask.api is None or ask.api.name == "first"
        for each in new
        for ask in (each.file.reading.asks if each.file.reading else [])
    )
    assert accepted(kit, repo, CORE) == (repo / CORE).read_bytes()


def test_a_commit_of_part_of_a_protected_file_is_a_version_they_haven_t_seen_and_asks(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    kit = holding_kit
    on_defaults(kit, repo, shell)
    kit.announced.answering = Response(approved=True)
    begin(kit, repo, "c1")
    (repo / AGENTS).write_text("# Agents\none\ntwo\n")
    finish(kit, repo, "c1")
    begin(kit, repo, "c2")
    commit = from_the_index(repo, shell, AGENTS, b"# Agents\none\n")
    finish(kit, repo, "c2")
    [_, second] = asked(kit)
    assert second.commit == commit
    assert (repo / AGENTS).read_text() == "# Agents\none\ntwo\n"


def test_a_commit_changing_a_file_the_repository_ignores_is_read_as_a_commit_s(
    holding_kit: Kit, repo: Path, shell: Shell
) -> None:
    """No snapshot holds what git ignores, so a commit is the only place its content shows."""
    kit = holding_kit
    on_defaults(kit, repo, shell)
    (repo / ".gitignore").write_text(".venv/\n.lup/\nforced.py\n")
    (repo / "forced.py").write_text("x = 1\n")
    shell.git(repo, "add", "-f", "forced.py", ".gitignore")
    shell.git(repo, "commit", "-q", "-m", "forced")
    begin(kit, repo, "seen")
    kit.announced.answering = Response(approved=True)
    finish(kit, repo, "seen")
    holds = len(asked(kit))
    begin(kit, repo, "c1")
    (repo / "forced.py").write_text("x = 2  # BAD regex\n")
    shell.git(repo, "add", "-f", "forced.py")
    shell.git(repo, "commit", "-q", "-m", "changed")
    told = finish(kit, repo, "c1").context
    assert len(asked(kit)) == holds
    assert f"{repo / 'forced.py'}:1:8 - regex" in told
