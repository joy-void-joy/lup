"""Who answers for an origin no fetch scope names.

The shell family has read a profile declaration about work nothing classified
since `UnjudgedAmbientPolicy` was written -- `ask` keeps it visible, `defer`
hands the long tail to provider-native judgement. Fetch said `ask` in its own
right, so a project that had declared the seamless posture got it on one
surface and not the other: one declaration, two answers.

Both spellings of reaching an origin, because there are two: `WebFetch` asks
the fetch policy directly, and `curl` asks it from inside the shell
classifier. Answering from the profile on one and from a constant on the
other is the same defect one layer down.

What is deliberately *not* taken is the rest of the settlement order. The rule
that settles unjudged work inside a boundary does so because every effect the
operation can have is confined there, and the effect of a fetch is a document
entering the agent's context -- which no filesystem or process boundary
bounds. A container is exactly as exposed to what an unlisted origin says as a
bare host is. What keeps that rule away from a deferred fetch is the order:
`ProviderNative` settles the abstention before `ContainedEffects` is read.
"""

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.fetch import decide_fetch
from lup.policy.kernel.rows import ShellRuleRow, UrlScopeRow
from lup.policy.kernel.semantics import UnjudgedAmbient
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary

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


def curled(command: str, unjudged: UnjudgedAmbient) -> KernelDecision:
    """One curl, judged the way a session judges it, under one posture."""
    rows: list[ShellRuleRow] = erase_shell_rules(default_vocabulary())
    return decide_shell(
        command,
        rows,
        [DOCS],
        [],
        unjudged_ambient=unjudged,
    )


def test_curl_answers_from_the_same_declaration_webfetch_does() -> None:
    """The second spelling of reaching an origin, which read a constant.

    `curl` asks the fetch policy from inside the shell classifier, so the
    declaration had to reach it through the segment context. Until it did, a
    profile that had declared the seamless posture got it for `WebFetch` and
    an approval question for the identical URL spelled as a command.
    """
    assert curled("curl https://elsewhere.test/page", "ask").effect == "ask"
    assert curled("curl https://elsewhere.test/page", "defer").effect == "defer"


def test_a_deferred_curl_is_not_rewritten_by_the_contained_reading() -> None:
    """The ordering this rests on, asserted rather than assumed.

    `ProviderNative` is read before `ContainedEffects`, so a deliberate
    handoff survives a boundary rather than being turned into an allow by a
    rule whose argument -- every effect is confined here -- is the one thing
    untrue of reading a document into context.
    """
    settled = decide_shell(
        "curl https://elsewhere.test/page",
        erase_shell_rules(default_vocabulary()),
        [DOCS],
        [],
        contained=True,
        inside_placement=True,
        unjudged_ambient="defer",
    )

    assert settled.effect == "defer"
    assert "confined" not in settled.reason


def test_a_declared_origin_is_still_allowed_however_it_is_spelled() -> None:
    for posture in POSTURES:
        assert curled("curl https://docs.example.test/guide", posture).effect == "allow"
