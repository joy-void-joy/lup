"""A session named for its work, decided in the half both runtimes ship.

Everything a runtime's naming hook does besides asking a model is decided in
:mod:`lup.coordination.bare.naming`: whether a prompt asks, what an answer may
be, how a name is settled against the live sessions' names, and when the
runtime is given the roster's name. Each is asserted here over a store the
typed writers produced, so the half a bare interpreter runs agrees with the
library by construction rather than by a pin.
"""

import json
import time
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
        arguments=["--tools", ""],
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
    titling = Titling(
        attempts=1, asked=stamped(started), pushed="dev", shown="dev", resumed=""
    )

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


def test_a_title_somebody_set_in_the_chrome_is_taken_up_by_the_roster(
    tmp_path: Path,
) -> None:
    """A `/rename`, or a reopened conversation's own title, is the newer choice.

    Taken up over whatever the roster was called, since it was chosen where
    the session is looked at; and once, since the next look finds the chrome
    showing what the roster answers to.
    """
    peers = RepositoryPeers(tmp_path)
    member = joined(peers, tmp_path, "dev")
    peers.rename(member, "chosen-by-a-peer")
    found = owned(peers, member, tmp_path)
    titling = naming.looked(peers.root, member, found)

    assert naming.adoptable(found, titling, "") == ""
    assert naming.adoptable(found, titling, "chosen-by-a-peer") == ""
    assert naming.adoptable(found, titling, "my-own-title") == "my-own-title"
    assert (
        naming.settled(peers.root, member, "my-own-title", over_a_rename=True)
        == "my-own-title"
    )
    titling = naming.concluded(peers.root, member, titling, "my-own-title")
    assert (
        naming.adoptable(owned(peers, member, tmp_path), titling, "my-own-title") == ""
    )


def test_a_title_taken_up_is_numbered_past_a_live_session_that_has_it(
    tmp_path: Path,
) -> None:
    peers = RepositoryPeers(tmp_path)
    joined(peers, tmp_path, "taken")
    member = joined(peers, tmp_path, "dev")

    assert naming.settled(peers.root, member, "taken", over_a_rename=True) == "taken-2"


def test_a_resume_heard_before_the_session_joined_waits_for_its_first_look(
    tmp_path: Path,
) -> None:
    """A runtime reports a resume as the session starts, which can be before
    its tool server has put it on the roster; the first look begins around it.
    """
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    naming.resuming(peers.root, member, "thread-9")
    peers.join(member, tmp_path, cli_name="dev")

    titling = naming.looked(peers.root, member, owned(peers, member, tmp_path))

    assert titling["resumed"] == "thread-9"
    assert titling["pushed"] == "dev"
    assert naming.concluded(peers.root, member, titling, "kept")["resumed"] == ""


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
    written.write_text(json.dumps({**declared(), "arguments": "--tools"}))
    assert naming.settings(written) is None

    written.write_text(json.dumps(declared()))
    assert naming.settings(written) == declared()
    assert naming.settings(tmp_path / "absent.json") is None


def test_the_compiled_declaration_is_read_beside_the_hooks_manifest(
    tmp_path: Path,
) -> None:
    """Outside the runtime directory, whose every file a policy snapshot hashes."""
    host = tmp_path / "hooks" / "runtime" / "session_naming.py"
    host.parent.mkdir(parents=True)
    (tmp_path / "hooks" / "session_naming.json").write_text(json.dumps(declared()))

    assert naming.compiled_for(host) == declared()


def test_the_prompt_reaches_the_model_quoted_as_the_thing_to_name() -> None:
    """Between the markers the declared instruction points at, whole."""
    prompt = "Refactor the roster\n\nand keep every line of this"

    assert naming.request_for(prompt) == f"<request>\n{prompt}\n</request>"


def test_an_ask_that_overruns_its_deadline_is_killed_with_everything_it_started(
    tmp_path: Path,
) -> None:
    """A wrapper killed alone leaves its real binary running; the session goes whole."""
    survivor = tmp_path / "survived"
    started = utc_now()

    assert (
        naming.ran(
            ["sh", "-c", f"(sleep 2; touch {survivor}) & wait"],
            "",
            0.5,
        )
        is None
    )
    assert (utc_now() - started).total_seconds() < 2
    for _ in range(30):
        if survivor.exists():
            break
        time.sleep(0.1)
    assert not survivor.exists()


def test_an_ask_that_answers_in_time_is_read_whole() -> None:
    assert naming.ran(["cat"], '{"name": "auth-refactor"}', 5.0) == (
        '{"name": "auth-refactor"}'
    )
    assert naming.ran(["no-such-program-anywhere"], "", 5.0) is None
