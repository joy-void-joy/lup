"""The filtered sandbox's egress policy and the proxy rules it compiles to."""

from lup.sandbox.egress import EgressPolicy


def rule_order(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.startswith("http_access")]


def test_the_permissive_posture_allows_what_it_has_not_denied() -> None:
    rendered = EgressPolicy().render()

    assert rule_order(rendered)[-1] == "http_access allow all"


def test_naming_domains_flips_the_posture_to_refuse_by_default() -> None:
    rendered = EgressPolicy(allowed_domains=[".pypi.org"]).render()

    assert "acl allowed_domains dstdomain .pypi.org" in rendered
    assert rule_order(rendered)[-2:] == [
        "http_access allow allowed_domains",
        "http_access deny all",
    ]


def test_destination_denials_precede_any_allow() -> None:
    # Load-bearing rather than cosmetic: a permitted hostname can resolve to a
    # private address, and an allowlist consulted first would wave it through.
    order = rule_order(EgressPolicy(allowed_domains=[".pypi.org"]).render())

    assert order.index("http_access deny forbidden_destinations") < order.index(
        "http_access allow allowed_domains"
    )


def test_cloud_metadata_is_refused_by_address_not_only_by_name() -> None:
    # The address rule is what holds, because a caller asking numerically
    # never consults a name list.
    rendered = EgressPolicy().render()

    assert "acl forbidden_destinations dst 169.254.0.0/16" in rendered
    assert "metadata.google.internal" in rendered


def test_the_ipv6_analogues_are_refused_too() -> None:
    rendered = EgressPolicy().render()

    for private in ("fc00::/7", "fe80::/10", "::1/128"):
        assert f"acl forbidden_destinations dst {private}" in rendered


def test_ports_are_allowlisted_and_tunnels_narrower_still() -> None:
    rendered = EgressPolicy().render()

    assert "http_access deny !Safe_ports" in rendered
    assert "http_access deny CONNECT !SSL_ports" in rendered
    assert "acl SSL_ports port 443" in rendered
    assert "acl Safe_ports port 22" not in rendered


def test_a_caller_may_narrow_the_reachable_ports() -> None:
    rendered = EgressPolicy(allowed_ports=(443,), tunnel_ports=(443,)).render()

    assert "acl Safe_ports port 80" not in rendered
    assert "acl Safe_ports port 443" in rendered


def test_nothing_is_cached_between_runs() -> None:
    assert "cache deny all" in EgressPolicy().render()


def test_no_dstdomain_list_holds_a_name_another_entry_already_covers() -> None:
    # Squid refuses such a list *fatally*, so this is the boundary being there
    # at all rather than tidiness: the proxy exits, its container removes
    # itself, and the session downstream sees a proxy name that will not
    # resolve. Asserted over both lists, since both render as `dstdomain`.
    rendered = EgressPolicy(allowed_domains=[".example.com", "example.com"]).render()

    declared = [line for line in rendered.splitlines() if line.startswith("acl ")]
    assert "acl allowed_domains dstdomain .example.com" in declared
    assert "localhost" not in rendered.replace(".localhost", "")


def test_the_covered_entry_is_dropped_and_the_covering_one_kept() -> None:
    # The direction matters: a leading dot matches the apex too, so dropping
    # the dotted form would keep the narrower half and lose every subdomain.
    policy = EgressPolicy()

    assert policy.distinct([".local", "local", "foo.local"]) == [".local"]
    assert policy.distinct(["local"]) == ["local"]


def test_the_icmp_helper_is_off_because_the_proxy_has_no_net_raw() -> None:
    # It needs NET_RAW, which the proxy deliberately does not have. Left on it
    # dies at startup on `Unable to open any ICMP sockets`, which reads as
    # squid failing rather than a helper it does not need.
    assert "pinger_enable off" in EgressPolicy().render()
