"""What the session's network boundary must keep true.

The container was already the filesystem boundary before any of this; what a
test here protects is the half that was missing, where the mount table said
one thing and the network said nothing at all. Each assertion below
corresponds to a way that gap can silently come back: a session attached to
no network, a proxy the session cannot resolve, a component routed around the
boundary because nobody told it the boundary was there.
"""

from pathlib import Path

import pytest
import sh

import lup.devtools.harness.contained as contained
from lup.harness.egress import SessionEgress, Unproxied
from lup.harness.image import Docker, Image
from lup.harness.requirements import Manifest
from lup.sandbox.egress import EgressPolicy


def test_a_session_is_attached_to_the_internal_network_by_name() -> None:
    """The gap this closes: run arguments that named no network at all.

    A container started without ``--network`` gets the engine's default
    bridge, which reaches the operator's LAN and every port on their
    localhost. Nothing about that failure is visible -- the session works
    perfectly, with no boundary.
    """
    arguments = Image().run_arguments(Path("/repo/tree/feat"), 1000, 1000, Docker())
    assert "--network" in arguments
    assert arguments[arguments.index("--network") + 1] == "lup-egress-net-feat"


def test_a_declaration_that_turns_the_boundary_off_says_so_in_the_argv() -> None:
    """An absent flag and a deliberate choice must not look the same.

    ``bridge`` is spelled out rather than left to the engine's default, so
    the difference between "this project chose no egress boundary" and "the
    launcher forgot one" is readable in the command that was run.
    """
    image = Image(egress=SessionEgress(mode="bridge"))
    arguments = image.run_arguments(Path("/repo/tree/feat"), 1000, 1000, Docker())
    assert arguments[arguments.index("--network") + 1] == "bridge"


def test_the_session_is_pointed_at_the_proxy_it_is_the_only_way_out_through() -> None:
    """An internal network with unset proxy variables is a session with no network.

    Both the boundary and the route through it come from one declaration, so
    a session cannot be attached to the internal network without also being
    told how to reach the proxy that is its only member with a way out.
    """
    environment = SessionEgress().environment()
    assert environment["HTTPS_PROXY"] == "http://egress:3128"
    assert environment["https_proxy"] == environment["HTTPS_PROXY"]
    # Written rather than emptied: emptying kept the host's exemptions out
    # and took the session's own loopback with them, so an agent that started
    # a dev server and curled it was answered by the proxy.
    assert environment["NO_PROXY"] == "localhost,127.0.0.1,::1"


def test_node_is_told_to_read_the_proxy_variables_it_otherwise_ignores() -> None:
    """The CLI this harness launches is a Node program, and Node opts in.

    Measured against Node's own release notes: from 22.21 and 24.5,
    ``NODE_USE_ENV_PROXY`` routes ``fetch``, ``node:http`` and ``node:https``
    through the proxy variables, and without it they are ignored entirely. On
    an internal network that means the session's own API calls go to a
    network with no gateway and wait -- the boundary breaking the one thing
    the session exists to do, with a timeout for a diagnostic.
    """
    assert SessionEgress().environment()["NODE_USE_ENV_PROXY"] == "1"


def test_an_unfiltered_declaration_sets_no_proxy_variables() -> None:
    """A proxy variable pointing at a proxy nobody started is worse than none."""
    assert SessionEgress(mode="bridge").environment() == {}


def test_the_proxy_reaches_the_outside_and_the_session_reaches_the_proxy() -> None:
    """The two halves that make one process the only bridge.

    The proxy starts on the engine's ordinary network -- that is the half
    with a route out -- and is joined to the internal network afterwards
    under the alias the session's environment resolves. Either half alone is
    a boundary with nothing behind it.
    """
    egress = SessionEgress()
    started = egress.proxy_arguments("feat", Path("/repo/tmp/egress.conf"))
    assert started[started.index("--network") + 1] == "bridge"
    connected = egress.connect_arguments("feat")
    assert connected[:3] == ["network", "connect", "--alias"]
    assert connected[3] == egress.alias
    assert connected[-2:] == ["lup-egress-net-feat", "lup-egress-feat"]


def test_the_network_the_proxy_joins_is_the_one_the_session_attaches_to() -> None:
    """One string, asked for twice. Two spellings is a session with no route."""
    egress = SessionEgress()
    attached = egress.attachment_arguments("feat")[1]
    assert attached in egress.connect_arguments("feat")
    assert attached in egress.network_arguments("feat")


def test_the_network_is_created_internal() -> None:
    """The whole posture rests on this flag.

    Without ``--internal`` the engine gives the network a gateway, and the
    session has a route out that merely happens not to be the proxy -- a
    boundary that is asked rather than enforced.
    """
    assert "--internal" in SessionEgress().network_arguments("feat")


def test_the_proxy_is_stripped_of_every_capability_it_does_not_need() -> None:
    """It is the one process with a route out, so it is the one worth hardening."""
    started = SessionEgress().proxy_arguments("feat", Path("/c"))
    assert started[started.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in started


def test_the_default_policy_refuses_the_destinations_every_adopter_shares() -> None:
    """Naming no domains is not naming no boundary.

    The default is permissive about *public* destinations, because an
    allowlist is a deployment fact with a different answer per adopter and a
    baked one hands the next project a timeout for a registry nobody could
    have known to list. What it still refuses is the part that is the same
    everywhere, and that is what would be lost if "no domains" were read as
    "no policy".
    """
    rendered = SessionEgress().policy.render()
    assert "http_access deny forbidden_destinations" in rendered
    assert "169.254.0.0/16" in rendered
    assert "metadata.google.internal" in rendered
    assert "http_access allow all" in rendered


def test_naming_domains_flips_the_policy_to_refuse_by_default() -> None:
    """A project whose destinations really are enumerable gets the strict posture."""
    egress = SessionEgress(policy=EgressPolicy(allowed_domains=["pypi.org"]))
    rendered = egress.policy.render()
    assert "http_access allow allowed_domains" in rendered
    assert "http_access deny all" in rendered


def test_the_launch_names_what_will_hang_rather_than_be_refused() -> None:
    """The one failure the boundary cannot attribute after the fact.

    A refused request leaves a proxy log line :mod:`lup.sandbox.attribution`
    can read. A component that ignores the variables sends packets onto a
    network with no gateway and waits, leaving nothing behind at all -- so
    before it happens is the only time it can be said.
    """
    lines = "\n".join(item.text for item in SessionEgress().notice("feat"))
    assert "ssh" in lines
    assert "hang" in lines


def test_an_unfiltered_launch_says_what_it_is_leaving_open() -> None:
    """Turning the boundary off is a posture, and a posture is announced."""
    lines = "\n".join(item.text for item in SessionEgress(mode="bridge").notice("feat"))
    assert "no proxy" in lines
    assert "metadata" in lines


def test_teardown_removes_the_proxy_before_the_network_holding_it() -> None:
    """Reversed, the engine refuses and names the network rather than the cause."""
    argv = SessionEgress().teardown_arguments("feat")
    assert argv[0][:2] == ["rm", "--force"]
    assert argv[1][:2] == ["network", "rm"]


def test_a_declared_unproxied_component_reaches_the_launch_notice() -> None:
    """The declaration is the only channel, so an addition must surface itself."""
    egress = SessionEgress(
        unproxied=[Unproxied(component="rsync", reason="speaks ssh", consequence="no")]
    )
    assert any("rsync" in item.text for item in egress.notice("feat"))


def test_the_egress_environment_is_not_baked_into_the_image() -> None:
    """A posture in a layer costs a distribution rebuild to change.

    The paths and the project environment really are facts about what was
    built. Which network the session runs on is not, and baking it would mean
    flipping one variable invalidated every layer above the base.
    """
    rendered = Image().dockerfile(Manifest())
    assert "HTTPS_PROXY" not in rendered
    assert "ENV LUP_CONTAINED=1" in rendered


def test_a_running_proxy_off_the_network_is_repaired_rather_than_believed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The hole a launch fell into: running is not the same as reachable.

    An earlier `start_egress` returned as soon as the proxy was *running*, so
    a proxy that had lost its place on the internal network — or never taken
    one, the connect half having failed after the run half succeeded — was
    found running and left exactly as it was, on that launch and every launch
    afterwards.

    What that costs is why it is worth a test rather than a comment. The
    session addresses its only way out by an alias on that network, so every
    request fails at DNS, and the runtime reports it as the operator's own
    internet or DNS being broken. Nothing in that sentence mentions a proxy.
    """
    issued: list[list[str]] = []

    def spelled(binary: str):
        def call(*words: str, **_: object) -> str:
            issued.append([binary, *words])
            return {
                # The network is there, the proxy is up — and it is on the
                # engine's default bridge and nothing else, which is exactly
                # the state that reads as healthy from every cheaper question.
                "inspect": "true" if "{{.State.Running}}" in words else "bridge ",
            }.get(words[0], "")

        return call

    monkeypatch.setattr(sh, "Command", spelled)
    contained.start_egress(SessionEgress(), "feat", Docker(), tmp_path)

    assert ["docker", "network", "connect", "--alias", "egress"] == issued[-1][:5]


def test_a_proxy_already_on_the_network_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Idempotent, so a second launch neither restarts nor reconnects anything.

    Reconnecting a container that is already connected is an error on both
    engines, so a repair that did not first ask would turn every launch after
    the first into a refusal.
    """
    issued: list[list[str]] = []

    def spelled(binary: str):
        def call(*words: str, **_: object) -> str:
            issued.append([binary, *words])
            return {
                "inspect": "true"
                if "{{.State.Running}}" in words
                else "bridge lup-egress-net-feat ",
            }.get(words[0], "")

        return call

    monkeypatch.setattr(sh, "Command", spelled)
    contained.start_egress(SessionEgress(), "feat", Docker(), tmp_path)

    assert not any("connect" in argv for argv in issued)
    assert not any("run" in argv for argv in issued)
