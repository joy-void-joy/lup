"""The counter-pressure on a boundary that answers every refusal by widening.

The failure this exists for is slow and has no natural corrective: each
widening is defensible when it is written, and nobody afterwards can say
whether it is still needed, so the declaration drifts toward a boundary
nobody would have chosen -- one defensible step at a time. What is pinned
here is that the two questions stay answerable, and that neither of them
ever fails a check: an unexercised entry is a question, and a gate that
failed on one would teach people to stop reading the gate.
"""

from lup.devtools.harness.accretion import report, survey
from lup.harness.egress import AllowedHost, SessionEgress
from lup.harness.image import CacheVolume, Image


def test_a_host_admitted_for_no_stated_reason_is_named() -> None:
    """The cheap question, and the one worth asking while somebody remembers.

    An entry with no reason cannot be argued about later, so the argument is
    had now rather than by whoever inherits it.
    """
    image = Image(egress=SessionEgress(admits=[AllowedHost(host="crates.io")]))
    found = survey(image, "feat", reached=[])
    assert [item.entry for item in found] == ["crates.io"]
    assert "nothing says why" in found[0].finding


def test_a_host_the_proxy_has_never_been_asked_for_is_named() -> None:
    """Evidence rather than inference: the proxy records what it was asked."""
    image = Image(
        egress=SessionEgress(
            admits=[
                AllowedHost(host="pypi.org", because="installing dependencies"),
                AllowedHost(host="crates.io", because="a rust crate, once"),
            ]
        )
    )
    found = survey(image, "feat", reached=["TCP_TUNNEL/200 pypi.org:443"])
    assert [item.entry for item in found] == ["crates.io"]
    assert "not been asked for it once" in found[0].finding


def test_no_proxy_log_is_not_evidence_of_disuse() -> None:
    """A proxy that is not running says nothing either way, and says that.

    Reporting every admitted host as unexercised because nothing could be
    read would be the loudest possible way of knowing nothing, and the first
    thing anybody would silence.
    """
    image = Image(
        egress=SessionEgress(
            admits=[AllowedHost(host="pypi.org", because="installing dependencies")]
        )
    )
    assert survey(image, "feat", reached=[]) == []


def test_a_bare_hostname_still_parses_and_still_reports() -> None:
    """Widening in a hurry stays one word, and shows up as one that said nothing.

    Refusing the short spelling would make the honest answer -- widened
    quickly, reason not recorded -- unwritable, and an unwritable answer is
    written as a plausible one instead.
    """
    egress = SessionEgress.model_validate({"admits": ["crates.io"]})
    assert egress.admits[0].host == "crates.io"
    assert egress.admits[0].because == ""


def test_a_cache_volume_with_no_stated_reason_is_named() -> None:
    """A mount accretes the same way a host does, and is asked the same thing."""
    image = Image(caches=[CacheVolume(name="lup-x", path="/cache/x")])
    assert [item.entry for item in survey(image, "feat", reached=[])] == ["/cache/x"]


def test_this_projects_own_declaration_has_nothing_outstanding() -> None:
    """The counter-pressure applied first to the declaration that carries it."""
    assert survey(Image(), "feat", reached=[]) == []


def test_nothing_is_printed_when_nothing_is_outstanding() -> None:
    """A check that says something every run is one nobody reads."""
    assert report([]) == []


def test_the_admitted_list_is_the_only_way_to_widen_the_allowlist() -> None:
    """Two ways to widen a boundary is one way too many.

    A declaration that set the policy's own allowlist directly would widen
    the boundary while recording no reason for widening it, so the half that
    records reasons overwrites it rather than merging with it.
    """
    from lup.sandbox.egress import EgressPolicy

    egress = SessionEgress(
        policy=EgressPolicy(allowed_domains=["snuck-in.example"]),
        admits=[AllowedHost(host="pypi.org", because="dependencies")],
    )
    rendered = egress.enforced().render()
    assert "snuck-in.example" not in rendered
    assert "pypi.org" in rendered


def test_naming_nothing_keeps_the_permissive_posture() -> None:
    """The default, and the reason it is the default.

    An allowlist is a deployment fact with a different answer per adopter,
    and a baked one hands the next project a timeout for a registry nobody
    could have known to list.
    """
    rendered = SessionEgress().enforced().render()
    assert "http_access allow all" in rendered
    assert "http_access deny forbidden_destinations" in rendered
