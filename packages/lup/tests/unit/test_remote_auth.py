"""Two questions about one remote, and why asking one for both fails.

A forwarded ssh agent answers for the transport and says nothing about the
forge API, so a session can push all day and be unable to open the request
describing what it pushed. These hold the split to the case that motivated
it: an ssh remote, perfectly reachable, on a session whose forge client holds
no credential at all.
"""

import pytest
import sh

from lup.devtools.dev import remote_auth

SSH_REMOTE = "git@github.com:acme/widget.git"


class StubGit:
    """Just enough git to answer where origin points."""

    def __init__(self, remote: str) -> None:
        self.remote = remote

    def out(self, *arguments: str) -> str:
        """What `git remote get-url origin` prints."""
        return self.remote


class StubForgeClient:
    """A forge client holding nothing, which is how a logged-out one behaves.

    It records what it was asked, because half of what these tests check is
    that it was asked at all -- the defect was a probe that reported ready
    having consulted nothing, and only the call log tells that from a probe
    that asked and was answered.
    """

    def __init__(self) -> None:
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, *arguments: str, **keywords: object) -> str:
        self.asked.append(arguments)
        raise sh.CommandNotFound("gh")


def test_an_ssh_remote_reaches_the_forge_client_for_the_api_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe that was never run on the remotes that most needed it.

    Dispatching on the remote's scheme sent every ssh remote to the transport
    arm, so the client was asked only where git already spoke https -- which
    is the one case where a failure would have surfaced anyway.
    """
    client = StubForgeClient()
    monkeypatch.setattr(remote_auth, "git", StubGit(SSH_REMOTE))
    monkeypatch.setattr(remote_auth, "gh", client)

    assert remote_auth.check_forge_api() is False
    assert client.asked == [("auth", "status")]


def test_the_transport_probe_still_declines_to_ask_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correct on its own terms, and exactly why it could not answer for the API.

    This is the shape the module's promise broke on: a key that works, a
    client that holds nothing, and one probe reporting ready for both.
    """
    client = StubForgeClient()

    def reachable(destination: str, remote_url: str) -> remote_auth.RemoteRefusal:
        """An ssh destination that answers, which a forwarded agent's does."""
        return remote_auth.RemoteRefusal()

    monkeypatch.setattr(remote_auth, "git", StubGit(SSH_REMOTE))
    monkeypatch.setattr(remote_auth, "gh", client)
    monkeypatch.setattr(remote_auth, "ssh_auth_refusal", reachable)

    assert remote_auth.check_remote_auth() is True
    assert client.asked == []


def test_the_refusal_names_both_places_a_credential_comes_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host and a contained session are fixed differently, and both read this.

    Naming only the sign-in sends whoever is inside a container after the one
    remedy that does not outlive it.
    """
    monkeypatch.setattr(remote_auth, "gh", StubForgeClient())

    refusal = remote_auth.gh_auth_refusal(SSH_REMOTE)

    assert refusal.credential is True
    assert "gh auth login" in refusal.complaint
    assert "LUP_GIT_TOKEN" in refusal.complaint
    assert "token_source" in refusal.complaint
