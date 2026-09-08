"""The population nobody assembled: every session working in one repository.

Written against the failures that make a repository roster useless without
being visibly broken — a name that stops resolving the moment its session
renames, a description that still says what somebody was doing an hour ago,
and a store that comes into being because a process mentioned it.
"""

from pathlib import Path

import pytest

from lup.coordination.identity import (
    MEMBER_ENV,
    MemberNames,
    derived_cli_name,
    mint_member_id,
    session_member_id,
)
from lup.coordination.peer_tools import create_peer_tools
from lup.coordination.repository import RepositoryPeers
from lup.coordination.roster import Delivery
from lup.coordination.store import coordination_root


def joined(
    root: Path, name: str, worktree: str = "tree"
) -> tuple[RepositoryPeers, str]:
    """One repository's peers, with a session already on the roster."""
    peers = RepositoryPeers(root)
    member = mint_member_id()
    peers.join(member, root / worktree, cli_name=name)
    return peers, member


def test_the_store_is_shared_by_every_worktree_of_one_repository(
    tmp_path: Path,
) -> None:
    """Derived from the shared git directory, so no worktree owns the roster."""
    (tmp_path / ".git").mkdir()

    assert coordination_root(tmp_path) == tmp_path / ".git" / "lup" / "coordination"


def test_mentioning_the_roster_does_not_create_it(tmp_path: Path) -> None:
    """Opening a cohort writes, so a session assembling its tools must not."""
    RepositoryPeers(tmp_path)

    assert not coordination_root(tmp_path).exists()


def test_a_session_is_reached_by_its_name_and_by_its_id(tmp_path: Path) -> None:
    """One resolution, so a spelling one surface accepts the next does not reject."""
    peers, member = joined(tmp_path, "reviewer")

    by_name = peers.address("reviewer")
    by_id = peers.address(member)

    assert by_name is not None
    assert by_name == by_id


def test_a_name_written_down_before_a_rename_still_reaches_its_session(
    tmp_path: Path,
) -> None:
    """There is no error a sender could be shown: the name was right when read."""
    peers, member = joined(tmp_path, "reviewer")

    peers.rename(member, "merger")

    assert peers.address("reviewer") == peers.address("merger")
    assert peers.names.current(member) == "merger"


def test_a_reused_name_reaches_whoever_claimed_it_last(tmp_path: Path) -> None:
    """A name is a handle, and handles get reused after they are released."""
    peers, first = joined(tmp_path, "reviewer")
    second = mint_member_id()
    peers.join(second, tmp_path / "other", cli_name="worker")

    peers.rename(second, "reviewer")

    found = peers.address("reviewer")
    assert found is not None and found.id == second
    assert found.id != first


def test_a_listing_says_what_each_session_is_doing_now(tmp_path: Path) -> None:
    """A task is what a member arrived for; a description is where it has got to."""
    peers, member = joined(tmp_path, "reviewer")

    peers.describe(member, "reading the merge for dropped code")

    [view] = peers.listing()
    assert view.doing == "reading the merge for dropped code"
    assert view.address == "reviewer"


def test_a_session_that_never_described_itself_falls_back_to_its_task(
    tmp_path: Path,
) -> None:
    """Silence about the work is not silence about the purpose."""
    peers, _member = joined(tmp_path, "reviewer", worktree="feature")

    [view] = peers.listing()

    assert view.doing.endswith("feature")


def test_a_session_that_left_is_still_listed_and_says_so(tmp_path: Path) -> None:
    """Whether the peer you wrote to is still there is what a listing answers."""
    peers, member = joined(tmp_path, "reviewer")

    peers.leave(member, summary="landed it")

    [view] = peers.listing()
    assert not view.member.running
    assert view.member.summary == "landed it"


def test_a_message_to_nobody_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """Each surface renders "nobody answers to that" in its own words."""
    peers, _member = joined(tmp_path, "reviewer")

    assert peers.send("nobody", "hello") is None


def test_mail_reaches_a_peer_and_is_taken_once(tmp_path: Path) -> None:
    """The durable record: it waits in the file until somebody reads it."""
    peers, member = joined(tmp_path, "reviewer")

    peers.send("reviewer", "the base moved under you")

    assert [item.text for item in peers.waiting(member).messages] == [
        "the base moved under you"
    ]
    assert len(peers.take(member).messages) == 1
    assert peers.waiting(member).messages == []


def test_a_repository_peer_reads_when_it_looks(tmp_path: Path) -> None:
    """Nothing wakes a session nobody is holding, and the roster says so."""
    peers, member = joined(tmp_path, "reviewer")

    [view] = peers.listing()

    assert view.member.delivery is Delivery.MAILBOX
    assert view.member.worktree.endswith("tree")
    assert view.member.actor.id == member


def test_a_session_with_no_name_is_called_after_its_worktree(tmp_path: Path) -> None:
    """The one fact a session has before it has done anything."""
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()

    peers.join(member, tmp_path / "feat-coordination")

    assert peers.names.current(member) == "feat-coordination"
    assert derived_cli_name(tmp_path / "feat-coordination") == "feat-coordination"


def test_a_launcher_that_minted_an_id_outranks_the_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher set it where an agent's own shell call cannot reach."""
    monkeypatch.setenv(MEMBER_ENV, "proven")

    assert session_member_id("runtime-session") == "proven"


def test_a_session_nobody_launched_answers_to_its_own_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full peer that cannot prove who started it is still a peer."""
    monkeypatch.delenv(MEMBER_ENV, raising=False)

    assert session_member_id("runtime-session") == "runtime-session"
    assert session_member_id() == ""


def test_renames_are_a_record_rather_than_a_field(tmp_path: Path) -> None:
    """Every naming is kept, which is what lets an old one go on resolving."""
    names = MemberNames(tmp_path / "names.jsonl")
    names.rename("one", "first")
    names.rename("one", "second")

    assert [record.cli_name for record in names.named()] == ["first", "second"]
    assert names.resolve("first") == "one"
    assert names.current("one") == "second"


async def test_a_session_using_its_tools_is_on_the_roster(tmp_path: Path) -> None:
    """A verb puts its session on the roster before it does anything else.

    Nothing else could: a description names a member the fold has never seen
    and is dropped, and a peer looking for who is working here reads a roster
    this session is absent from. Joining on every call rather than once is
    what lets a tool server answer without knowing whether it is the first.
    """
    peers = RepositoryPeers(tmp_path)
    tools = {
        tool.name: tool
        for tool in create_peer_tools(peers, "abc123", tmp_path / "feat-thing")
    }

    await tools["coordination_describe"].handler({"description": "rewriting the guard"})

    [listed] = peers.listing()
    assert listed.member.actor.id == "abc123"
    assert listed.doing == "rewriting the guard"
    assert listed.member.delivery == Delivery.INBOX


async def test_joining_twice_leaves_one_member(tmp_path: Path) -> None:
    """Idempotent, because every verb calls it and a session takes many."""
    peers = RepositoryPeers(tmp_path)
    tools = {
        tool.name: tool
        for tool in create_peer_tools(peers, "abc123", tmp_path / "feat-thing")
    }

    await tools["coordination_peers"].handler({})
    await tools["coordination_peers"].handler({})

    assert len(peers.listing()) == 1
