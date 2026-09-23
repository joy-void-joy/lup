"""A session named for its work, decided in the half both runtimes ship.

Everything a runtime's naming hook does besides asking a model is decided in
:mod:`lup.coordination.bare.naming`: whether a prompt asks, what an answer may
be, how a name is settled against the live sessions' names, and when the
runtime is given the roster's name. Each is asserted here over a store the
typed writers produced, so the half a bare interpreter runs agrees with the
library by construction rather than by a pin.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from lup.channels.models import utc_now
from lup.coordination.bare import naming
from lup.coordination.bare.naming import Arrival, Naming, Titling
from lup.coordination.bare.store import (
    Member,
    current_name,
    member_of,
    session_actor,
    stamped,
)
from lup.coordination.identity import NameTakenError, mint_member_id
from lup.coordination.repository import RepositoryPeers
from lup.coordination.wake import WakePath


def declared(attempts: int = 3, deadline_seconds: float = 20.0) -> Naming:
    """The naming declaration as a hook reads it, with what a test varies."""
    return Naming(
        model="sonnet",
        effort="low",
        instruction="Name the work.",
        attempts=attempts,
        deadline_seconds=deadline_seconds,
        longest=48,
    )


def joined(
    peers: RepositoryPeers, worktree: Path, name: str, wake: WakePath = WakePath()
) -> str:
    """One session on the roster under *name*, and the id it answers to."""
    member = mint_member_id()
    peers.join(member, worktree, cli_name=name, wake=wake)
    return member


def arrival(worktree: Path) -> Arrival:
    """A prompt from the root session working in *worktree*."""
    return Arrival(
        session_id="root-session",
        cwd=str(worktree),
        prompt="Rename sessions after their work",
    )


def strangers(worktree: Path) -> list[Arrival]:
    """Prompts carrying the member's id that are not its root session's own."""
    return [
        Arrival(session_id="root-session", cwd=str(worktree), agent_id="child"),
        Arrival(session_id="root-session", cwd=str(worktree), agent_type="reviewer"),
        Arrival(session_id="another-session", cwd=str(worktree)),
        Arrival(session_id="root-session", cwd="/somewhere/else"),
    ]


def owned(peers: RepositoryPeers, member: str, worktree: Path) -> Member:
    """The member as its own root session's prompt finds it."""
    found = naming.owning(peers.root, member, arrival(worktree))
    assert found is not None
    return found


def test_a_session_answering_only_to_the_name_it_joined_with_is_due(
    tmp_path: Path,
) -> None:
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    found = owned(peers, member, tmp_path)

    assert naming.due(found, naming.looked(peers.root, member, found), declared(), None)


def test_a_renamed_session_is_never_named_over(tmp_path: Path) -> None:
    """A second name is somebody's choice, whoever made it."""
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    peers.rename(member, "chosen")
    found = owned(peers, member, tmp_path)

    assert not naming.due(
        found, naming.looked(peers.root, member, found), declared(), None
    )


@pytest.mark.parametrize(
    ("shown", "asks"),
    [
        (None, True),
        ("", True),
        ("dev", True),
        ("somebody-chose-this", False),
    ],
)
def test_a_title_somebody_set_in_the_chrome_stops_the_ask(
    tmp_path: Path, shown: str | None, asks: bool
) -> None:
    """Nothing reported, nothing set, or the default itself leaves the ask owed."""
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    found = owned(peers, member, tmp_path)

    assert (
        naming.due(found, naming.looked(peers.root, member, found), declared(), shown)
        is asks
    )


def test_asking_stops_once_the_declared_attempts_are_spent(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    found = owned(peers, member, tmp_path)
    titling = naming.looked(peers.root, member, found)
    for _ in range(2):
        titling = naming.concluded(
            peers.root, member, naming.asking(peers.root, member, titling), ""
        )

    assert naming.due(found, titling, declared(attempts=3), None)
    assert not naming.due(found, titling, declared(attempts=2), None)


def test_an_ask_under_way_is_not_started_again_until_its_deadline_passes(
    tmp_path: Path,
) -> None:
    """A slow ask settles the name either way; one that died stops counting."""
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    found = owned(peers, member, tmp_path)
    started = utc_now()
    titling = Titling(attempts=1, asked=stamped(started), pushed="dev")

    assert not naming.due(
        found, titling, declared(), None, now=started + timedelta(seconds=5)
    )
    assert naming.due(
        found, titling, declared(), None, now=started + timedelta(seconds=21)
    )


def test_a_name_a_live_session_answers_to_is_numbered_past(tmp_path: Path) -> None:
    """The typed rename refuses the name; the hook, which nobody chose for, numbers it."""
    peers = RepositoryPeers(tmp_path)
    joined(peers, tmp_path, "auth-refactor")
    member = joined(peers, tmp_path, "dev")

    with pytest.raises(NameTakenError):
        peers.rename(member, "auth-refactor")
    taken = naming.settled(peers.root, member, "auth-refactor")

    assert taken == "auth-refactor-2"
    found = member_of(peers.root, session_actor(member))
    assert found is not None
    assert current_name(found) == "auth-refactor-2"
    assert peers.address("dev") == peers.address("auth-refactor-2")


def test_a_rename_that_landed_first_is_kept(tmp_path: Path) -> None:
    """Settled against the member as it is under the lock, not as the hook read it."""
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    peers.rename(member, "chosen")

    assert naming.settled(peers.root, member, "session-naming") == ""
    found = member_of(peers.root, session_actor(member))
    assert found is not None
    assert current_name(found) == "chosen"


def test_only_the_members_own_root_session_is_named(tmp_path: Path) -> None:
    """A child carrying its launcher's member id names nothing, as it binds nothing."""
    peers = RepositoryPeers(tmp_path)
    member = joined(
        peers,
        tmp_path,
        "dev",
        wake=WakePath(runtime="claude", handle="/inbox", session="root-session"),
    )

    assert naming.owning(peers.root, member, arrival(tmp_path)) is not None
    assert [
        naming.owning(peers.root, member, stranger) for stranger in strangers(tmp_path)
    ] == [None, None, None, None]


def test_a_session_not_yet_on_the_roster_is_named_later(tmp_path: Path) -> None:
    peers = RepositoryPeers(tmp_path)
    joined(peers, tmp_path, "dev")

    assert naming.owning(peers.root, mint_member_id(), arrival(tmp_path)) is None


def test_the_runtime_is_given_a_roster_rename_once(tmp_path: Path) -> None:
    """The first look takes the launch's name as given; a rename is carried once."""
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    titling = naming.looked(peers.root, member, owned(peers, member, tmp_path))

    assert naming.pending(owned(peers, member, tmp_path), titling) == ""
    peers.rename(member, "chosen")
    assert naming.pending(owned(peers, member, tmp_path), titling) == "chosen"
    titling = naming.concluded(peers.root, member, titling, "chosen")
    assert naming.pending(owned(peers, member, tmp_path), titling) == ""
    assert naming.recalled(peers.root, member) == titling


@pytest.mark.parametrize(
    ("reply", "name"),
    [
        ('{"name": "auth-refactor"}', "auth-refactor"),
        ('{"name": "session-naming-hook-2"}', "session-naming-hook-2"),
        ('{"name": null}', ""),
        ('{"name": "Auth Refactor"}', ""),
        ('{"name": "auth--refactor"}', ""),
        ('{"name": "-auth"}', ""),
        ('{"name": "refactoré"}', ""),
        (json.dumps({"name": "-".join(["word"] * 12)}), ""),
        ('{"title": "auth-refactor"}', ""),
        ("[]", ""),
        ("auth-refactor", ""),
    ],
)
def test_an_answer_names_only_in_the_shape_a_name_takes(reply: str, name: str) -> None:
    """What a person types to reach the session: worktree-shaped, and not too long."""
    assert naming.answered(reply, 48) == name


def test_the_answer_schema_admits_a_name_or_nothing() -> None:
    schema = json.loads(naming.answer_schema())

    assert schema["required"] == ["name"]
    assert schema["properties"]["name"]["type"] == ["string", "null"]
    assert schema["additionalProperties"] is False


def test_a_malformed_declaration_names_nothing(tmp_path: Path) -> None:
    """Checked field by field, so a hook never asks under a deadline it misread."""
    written = tmp_path / "session_naming.json"
    written.write_text(json.dumps({**declared(), "attempts": "3"}))
    assert naming.settings(written) is None

    written.write_text(json.dumps(declared()))
    assert naming.settings(written) == declared()
    assert naming.settings(tmp_path / "absent.json") is None
