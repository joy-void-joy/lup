"""Behavior tests for what the origin remote's credential probe found.

The probe answers with a refusal two readers spend differently: a command
reporting to a person asks whether remote operations can proceed at all,
where the base-freshness reading asks for words to put in front of somebody
whose fetch just failed. Those come apart exactly once -- on a host that was
never reached -- and that is what is under test, because a diagnosis is only
worth having if it is worth acting on.

These run the real `ssh`, against a destination that cannot exist: RFC 2606
reserves `.invalid`, so no name resolves and nothing here reaches a network.
"""

from lup.devtools.dev.remote_auth import remote_auth_refusal

UNREACHABLE = "git@nowhere.invalid:org/repo.git"


def test_a_host_that_was_never_reached_diagnoses_nothing() -> None:
    """Nobody offline is helped by being told to load a key.

    The refusal that brought this about was a real one, and the fix for it
    names an identity to `ssh-add`. Saying that to a machine on a train
    sends its reader after a key that was never the problem -- and this
    probe is a second command, which can fail to reach a host the fetch it
    is explaining reached fine. So the advice is held for the case that
    identifies a credential, and the fetch keeps the floor for the rest.
    """
    refusal = remote_auth_refusal(UNREACHABLE)

    assert refusal.diagnoses() == ""
    assert not refusal.credential


def test_a_host_that_was_never_reached_still_stops_remote_operations() -> None:
    """The other reader's question, whose answer is the opposite one.

    Nothing to say about a credential is not nothing to say: a push has the
    same host to reach, so the complaint stands even where the diagnosis
    does not.
    """
    assert remote_auth_refusal(UNREACHABLE).complaint


def test_a_remote_with_no_credential_to_fail_has_no_complaint() -> None:
    """A local path is a directory, not a machine with a key on it."""
    assert remote_auth_refusal("/srv/git/repo.git").complaint == ""
    assert remote_auth_refusal("").complaint == ""
