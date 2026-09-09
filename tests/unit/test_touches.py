"""What each session is holding, from the typed writer to the compiled hook.

The fold, the roster-scoped expiry, and the approval a foreign claim earns are
three layers in three processes that share no import, so each is exercised
against what the layer beneath it actually wrote rather than against a fixture
shaped like it.
"""

import json
from pathlib import Path

import sh

from lup.coordination.identity import mint_member_id
from lup.coordination.policy import peer_policy
from lup.coordination.repository import RepositoryPeers
from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.peers import decide_foreign_claim, settled_with_claim
from lup.policy.peer_policy import erase_peer_policy
from lup.types import JsonObject
from tests.unit.repos import commit_file, initialized_repo

DISPATCHER = Path(".claude/plugins/lup/hooks/scripts/policy.py")

DECLARED = erase_peer_policy(peer_policy())
"""The row this repository actually compiles, rather than a fixture beside it."""


def joined(work: Path, hooks: Path) -> RepositoryPeers:
    """A throwaway repository whose roster the real writer opened."""
    initialized_repo(work, hooks)
    return RepositoryPeers(work)


def decide(payload: object, member: str) -> JsonObject:
    """Run the generated dispatcher as one member of the roster."""
    return json.loads(
        str(
            sh.Command("python3")(
                "-I",
                "-S",
                str(DISPATCHER),
                _in=json.dumps(payload),
                _env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": str(Path.home()),
                    "LUP_COORDINATION_MEMBER": member,
                },
            )
        )
    )


def edit_payload(path: Path, old: str, new: str, cwd: Path) -> JsonObject:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
        "cwd": str(cwd),
    }


def test_a_touch_is_found_by_the_path_a_write_would_land_on(tmp_path: Path) -> None:
    work = tmp_path / "work"
    peers = joined(work, tmp_path / "hooks")
    member = mint_member_id()
    peers.join(member, work, cli_name="feat-rewriting")
    peers.touches.touched(
        peers.address("feat-rewriting") or peers.join(member, work),
        work / "src" / "a.py",
        "abc",
    )
    covering = peers.holding(work / "src" / "a.py")
    assert [holder.id for claim in covering for holder in claim.holders] == [member]


def test_a_lock_covers_everything_beneath_its_prefix(tmp_path: Path) -> None:
    work = tmp_path / "work"
    peers = joined(work, tmp_path / "hooks")
    member = mint_member_id()
    peers.join(member, work, cli_name="feat-rewriting")
    peers.lock(member, work / "src")
    assert peers.holding(work / "src" / "deep" / "a.py")
    assert not peers.holding(work / "other" / "a.py")


def test_a_release_by_somebody_who_never_held_it_says_nothing(tmp_path: Path) -> None:
    """Otherwise one session unlocks another's work by asking."""
    work = tmp_path / "work"
    peers = joined(work, tmp_path / "hooks")
    holder, stranger = mint_member_id(), mint_member_id()
    peers.join(holder, work, cli_name="feat-rewriting")
    peers.join(stranger, work, cli_name="feat-transducer")
    peers.lock(holder, work / "src")
    peers.release(stranger, work / "src")
    assert peers.holding(work / "src" / "a.py")
    peers.release(holder, work / "src")
    assert not peers.holding(work / "src" / "a.py")


def test_a_claim_expires_with_the_session_holding_it(tmp_path: Path) -> None:
    """No timeout to tune, and nobody left to remember a release."""
    work = tmp_path / "work"
    peers = joined(work, tmp_path / "hooks")
    member = mint_member_id()
    peers.join(member, work, cli_name="feat-rewriting")
    peers.lock(member, work / "src")
    assert peers.holding(work / "src" / "a.py")
    peers.leave(member, summary="landed")
    assert not peers.holding(work / "src" / "a.py")


def test_an_edit_under_another_session_s_claim_asks_and_names_the_holder(
    tmp_path: Path,
) -> None:
    """The whole point: the failure this stops is finding out at merge time."""
    work = tmp_path / "work"
    git = initialized_repo(work, tmp_path / "hooks")
    commit_file(git, work, "a.py", "value = 1\n", "seed the file under claim")
    peers = RepositoryPeers(work)
    holder, mine = mint_member_id(), mint_member_id()
    peers.join(holder, work, cli_name="feat-rewriting")
    peers.join(mine, work, cli_name="feat-transducer")
    peers.lock(holder, work)
    decision = decide(edit_payload(work / "a.py", "value = 1", "value = 2", work), mine)
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "ask"
    assert "feat-rewriting" in str(specific["permissionDecisionReason"])


def test_a_session_is_not_asked_about_a_path_it_holds_itself(tmp_path: Path) -> None:
    """A session meeting its own claim on every edit would be asked about its own work."""
    work = tmp_path / "work"
    git = initialized_repo(work, tmp_path / "hooks")
    commit_file(git, work, "a.py", "value = 1\n", "seed the file under claim")
    peers = RepositoryPeers(work)
    mine = mint_member_id()
    peers.join(mine, work, cli_name="feat-transducer")
    peers.lock(mine, work)
    decision = decide(edit_payload(work / "a.py", "value = 1", "value = 2", work), mine)
    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert "feat-transducer" not in str(specific["permissionDecisionReason"])


def test_a_written_file_is_claimed_by_the_session_that_named_it(
    tmp_path: Path,
) -> None:
    """The tier that admits no contest, because the call said which file."""
    work = tmp_path / "work"
    git = initialized_repo(work, tmp_path / "hooks")
    commit_file(git, work, "a.py", "value = 1\n", "seed the file under claim")
    peers = RepositoryPeers(work)
    mine = mint_member_id()
    peers.join(mine, work, cli_name="feat-transducer")
    decide(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(work / "a.py")},
            "cwd": str(work),
        },
        mine,
    )
    assert [
        holder.id for claim in peers.holding(work / "a.py") for holder in claim.holders
    ] == [mine]


def test_a_project_declaring_no_roster_holds_nothing_against_an_edit() -> None:
    """Declining coordination must not put a question in front of every write."""
    verdict = KernelDecision("allow", "small safe edit")
    assert decide_foreign_claim("/tmp/a.py", ["feat-rewriting"], None) is None
    assert settled_with_claim(verdict, None) is verdict


def test_a_quiet_path_cannot_weaken_what_the_edit_gates_decided() -> None:
    """The claim family has no positive authority, only a question to add."""
    refused = KernelDecision("deny", "the anti-pattern table refuses this")
    assert settled_with_claim(refused, None) is refused
    assert DECLARED is not None
    settled = settled_with_claim(
        refused, decide_foreign_claim("/tmp/a.py", ["feat-rewriting"], DECLARED)
    )
    assert settled.effect == "deny"


def test_a_held_path_turns_an_allowed_edit_into_a_question() -> None:
    """And the reason carries both halves, because one approval answers both."""
    assert DECLARED is not None
    settled = settled_with_claim(
        KernelDecision("allow", "small safe edit"),
        decide_foreign_claim("/tmp/a.py", ["feat-rewriting"], DECLARED),
    ).placed(escapable=True)
    assert settled.effect == "ask"
    assert "feat-rewriting" in settled.reason
