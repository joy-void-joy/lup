"""URL scope matching for the fetch policy."""

import urllib.parse

from .decision import KernelDecision
from .rows import UrlScopeRow
from .semantics import UnjudgedAmbient


def host_matches_scope(hostname: str, expected_host: str, subdomains: bool) -> bool:
    """Match a host exactly, or beneath a scope that opted into subdomains.

    The leading dot is required so a scope for ``githubusercontent.com``
    covers ``raw.githubusercontent.com`` without also covering a
    lookalike registration like ``evilgithubusercontent.com``.
    """
    return hostname == expected_host or (
        subdomains and hostname.endswith(f".{expected_host}")
    )


def url_matches_scope(
    scheme: str,
    hostname: str,
    port: int | None,
    path: str,
    scope: UrlScopeRow,
) -> bool:
    """Compare parsed URL components with one primitive scope row."""
    return (
        scheme == scope["scheme"]
        and host_matches_scope(hostname, scope["host"], scope["include_subdomains"])
        and (scope["any_port"] or port == scope["port"])
        and path.startswith(scope["path_prefix"])
    )


def decide_fetch(
    url: str,
    allowed_scopes: list[UrlScopeRow],
    denied_scopes: list[UrlScopeRow],
    unjudged_ambient: UnjudgedAmbient = "ask",
) -> KernelDecision:
    """Deny matching scopes first, allow declared scopes, and ask otherwise.

    The last of those is the profile's answer rather than this function's.
    An origin no scope names is the fetch surface's version of a command the
    vocabulary has no row for, and the shell has read a declaration about
    that since :class:`~lup.policy.kernel.settlement.UnjudgedAmbientPolicy`
    was written: ``ask`` keeps unjudged work visible, ``defer`` hands the
    long tail to provider-native judgement. This said ``ask`` in its own
    right, which made a profile that had declared the seamless posture get
    it on one surface and not the other -- one declaration, two answers.

    Only that half is taken. The rest of the settlement order is not
    consulted here, and the reason is specific to fetch: the rule that
    settles unjudged work inside a boundary does so because every effect the
    operation can have is confined there, and the effect of a fetch is a
    document entering the agent's context. No filesystem or process boundary
    bounds that. A container is exactly as exposed to what an unlisted origin
    says as a bare host is, so containment is not an argument for reading
    one.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return KernelDecision("ask", "malformed URL requires approval")
    if not parsed.scheme or hostname is None:
        return KernelDecision("ask", "malformed URL requires approval")
    denied = next(
        (
            scope
            for scope in denied_scopes
            if url_matches_scope(parsed.scheme, hostname, port, parsed.path, scope)
        ),
        None,
    )
    if denied is not None:
        return KernelDecision("deny", denied["reason"] or "URL is denied")
    allowed = next(
        (
            scope
            for scope in allowed_scopes
            if url_matches_scope(parsed.scheme, hostname, port, parsed.path, scope)
        ),
        None,
    )
    if allowed is not None:
        return KernelDecision("allow", allowed["reason"])
    outside = "URL is outside the declared documentation scopes"
    if unjudged_ambient == "defer":
        return KernelDecision("defer", outside, abstention="provider_native")
    return KernelDecision("ask", outside)
