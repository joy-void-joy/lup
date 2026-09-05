"""Who answers for an origin no fetch scope names.

The shell family has read a profile declaration about work nothing classified
since `UnjudgedAmbientPolicy` was written -- `ask` keeps it visible, `defer`
hands the long tail to provider-native judgement. Fetch said `ask` in its own
right, so a project that had declared the seamless posture got it on one
surface and not the other: one declaration, two answers.

What is deliberately *not* taken is the rest of the settlement order. The rule
that settles unjudged work inside a boundary does so because every effect the
operation can have is confined there, and the effect of a fetch is a document
entering the agent's context -- which no filesystem or process boundary
bounds. A container is exactly as exposed to what an unlisted origin says as a
bare host is.
"""

from lup.policy.kernel.fetch import decide_fetch
from lup.policy.kernel.rows import UrlScopeRow
from lup.policy.kernel.semantics import UnjudgedAmbient

DOCS = UrlScopeRow(
    scheme="https",
    host="docs.example.test",
    port=None,
    any_port=True,
    include_subdomains=False,
    path_prefix="/",
    reason="declared documentation",
)


POSTURES: tuple[UnjudgedAmbient, ...] = ("ask", "defer")
"""Both answers the declaration admits, so a new one cannot be left untested."""


def verdict(url: str, unjudged: UnjudgedAmbient = "ask"):
    return decide_fetch(url, [DOCS], [], unjudged)


def test_a_declared_scope_is_allowed_whatever_the_profile_says() -> None:
    """The declaration answers first; the posture is only for the long tail."""
    for posture in POSTURES:
        assert verdict("https://docs.example.test/guide", posture).effect == "allow"


def test_an_unlisted_origin_asks_where_the_profile_keeps_it_visible() -> None:
    """The default, and this repository's own answer."""
    settled = verdict("https://elsewhere.test/page")

    assert settled.effect == "ask"
    assert "outside the declared documentation scopes" in settled.reason


def test_an_unlisted_origin_defers_where_the_profile_declared_that() -> None:
    """The seamless posture, reaching the surface it could not reach before.

    Named as provider-native abstention rather than left a bare defer, so the
    reason a runtime is being handed this is on the verdict rather than in
    whoever configured it.
    """
    settled = verdict("https://elsewhere.test/page", "defer")

    assert settled.effect == "defer"
    assert settled.abstention == "provider_native"


def test_a_denied_scope_is_refused_under_either_posture() -> None:
    """A refusal is the project declining to reach that end, not a silence."""
    denied = UrlScopeRow(
        scheme="https",
        host="secrets.test",
        port=None,
        any_port=True,
        include_subdomains=False,
        path_prefix="/",
        reason="never",
    )
    for posture in POSTURES:
        assert (
            decide_fetch("https://secrets.test/x", [DOCS], [denied], posture).effect
            == "deny"
        )
