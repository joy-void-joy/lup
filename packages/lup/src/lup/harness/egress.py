"""The network an agent session reaches through, and the one process bridged out.

A container bought without this is half a boundary. The filesystem is scoped
by the mount table and the network is not scoped at all: an ordinary bridge
network reaches the operator's LAN, every port on their localhost, and the
cloud metadata endpoint that hands out credentials to whoever asks. Those are
the three destinations a compromised session would want, and a container that
protects the home directory while leaving them open protects the wrong half.

So the session's network is ``internal`` -- Docker gives it no gateway, so
there is no route out to decline rather than a route the container is asked
not to take -- and one proxy is the only member of both it and the outside.
:class:`~lup.sandbox.egress.EgressPolicy` is what that proxy enforces, and it
is the same declaration the code-execution sandbox already used, pointed at
the session container that replaced it.

**Why the default names no domains.** An allowlist is a deployment fact with
a different answer per adopter: this project reaches PyPI and GitHub, the next
needs crates.io, an npm registry, a distro mirror, or a corporate proxy. A
list baked here would hand each of them a timeout -- the exact vocabulary this
design forbids -- for a destination nobody could have known to name. What the
default *does* refuse is the part that is the same everywhere: the private
ranges, the metadata hosts, and the names a host answers to for itself. A
project whose destinations really are enumerable names them and gets
refuse-by-default.

**What does not honour the variables.** A proxy is a convention, not a
kernel rule, and a component that ignores ``HTTPS_PROXY`` on an internal
network does not fail politely -- it hangs until something times out. That is
knowable in advance rather than discoverable at runtime, so it is declared
here and said at launch. The one that matters most is ssh: it reads none of
these variables, and git over ``git@host:`` is therefore unreachable from a
filtered session. That is not a gap to close later. It is the measurement
§9.2's HTTPS credential exists because of.
"""

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from lup.harness.notice import Notice
from lup.sandbox.egress import EgressPolicy
from lup.sandbox.models import NetworkMode
from lup.types import EnvVars

DEFAULT_PROXY_IMAGE = "ubuntu/squid:6.6-24.04_edge"
"""The image the filtered network is bridged through, pinned rather than latest.

Same image the code-execution sandbox reached for, and pinned for the reason
every other version in this harness is: a proxy that silently became a
different build is a boundary that silently changed what it lets through.
"""


class Unproxied(BaseModel, frozen=True):
    """A component that ignores the proxy variables, named rather than discovered.

    Declared because the failure has no vocabulary of its own. A component
    that honours ``HTTPS_PROXY`` and is refused gets a 403 the proxy wrote and
    :mod:`lup.sandbox.attribution` can explain; a component that ignores it
    sends its packets onto a network with no gateway and simply waits. There
    is nothing to attribute afterwards, so the only place this can be said is
    before it happens.
    """

    component: str = Field(description="What ignores the variables")
    reason: str = Field(description="Why it does, in its own terms")
    consequence: str = Field(description="What is unreachable as a result")

    def sentence(self) -> str:
        """One line naming this component and what it costs, for the launch.

        Unindented: subordination is the notice's to express, so a line that
        carried its own two spaces would be indented twice over.
        """
        return f"{self.component}: {self.reason} — {self.consequence}"


SSH_IGNORES_THE_PROXY = Unproxied(
    component="ssh",
    reason="reads none of the proxy variables and speaks its own protocol on port 22",
    consequence=(
        "a `git@host:` remote is unreachable; use HTTPS with a scoped token, "
        "which is what the credential design assumes"
    ),
)
"""The measurement the credential design rests on, kept where a launch says it."""


class AllowedHost(BaseModel, frozen=True):
    """One destination the boundary admits, and what made it necessary.

    The motivation is the field that matters. A boundary answered by widening
    its own declaration teaches an agent that every wall is answered by
    widening it, and mounts and allowed hosts then accrete with nothing ever
    removing one -- each entry perfectly defensible when written and nobody
    afterwards able to say whether it is still needed. Recording the command
    that motivated it makes the second question answerable: an entry whose
    command nobody runs any more is an entry to take out, and the check that
    reads the proxy's log can say which have not been reached at all.

    A bare hostname still parses, so widening the list in a hurry stays one
    word -- and shows up in the check as an entry that never said why.
    """

    host: str = Field(description="The domain the proxy admits")
    because: str = Field(
        default="",
        description=(
            "The command or capability that needed it. Empty is accepted and "
            "reported, because refusing it would make the honest answer -- "
            "'I do not remember' -- unwritable"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    # lup: ignore[bare-object] — pydantic hands a before-hook whatever the
    # caller wrote, which is the untyped boundary the rule says to narrow at
    def a_bare_name_is_a_host_nobody_said_why_about(cls, value: object) -> object:
        """Accept the shortest spelling, and let the check ask for the rest."""
        return {"host": value} if isinstance(value, str) else value


class SessionEgress(BaseModel, frozen=True):
    """How one agent session reaches the network, declared with what enforces it.

    One model rather than two for the same reason :class:`Image` is one: the
    network name the session attaches to and the network the proxy is
    connected to have to be the same string, and the way that stays true is
    that one declaration answers both.
    """

    mode: NetworkMode = Field(
        default="filtered",
        description=(
            "``filtered`` puts the session on an internal network whose only "
            "way out is the proxy; ``bridge`` gives it the host's ordinary "
            "network and no egress boundary at all; ``none`` cuts it off "
            "entirely, which no session that installs a dependency survives. "
            "Filtered by default because a container whose network is "
            "unscoped protects the home directory and leaves the LAN, "
            "localhost, and the metadata endpoint open"
        ),
    )
    policy: EgressPolicy = Field(
        default=EgressPolicy(),
        description=(
            "The denial vocabulary and the ports, which are the same for "
            "every adopter. What is *admitted* is not set here -- "
            "`admits` below owns it, and :meth:`enforced` overwrites this "
            "field's allowlist with what that says, so there is no second "
            "way to widen the boundary that records no reason for widening it"
        ),
    )
    admits: list[AllowedHost] = Field(
        default=[],
        description=(
            "Destinations this project reaches, each with what needed it. "
            "Empty keeps the permissive posture: every public destination "
            "reachable, the private ranges and metadata hosts still refused. "
            "That is the default because an allowlist is a deployment fact "
            "with a different answer per adopter, and a baked one hands the "
            "next project a timeout for a registry nobody could have known "
            "to list. Naming any host flips the posture to refuse-by-default"
        ),
    )
    reached_directly: list[str] = Field(
        default=["localhost", "127.0.0.1", "::1"],
        description=(
            "Destinations a session reaches without the proxy, written into "
            "``NO_PROXY`` rather than inherited from the host. The session's "
            "own loopback, and only that: an agent that runs a dev server "
            "and curls it is reaching a port inside its own container, which "
            "no boundary here was ever meant to stand between. Widening this "
            "to a real destination would be widening the boundary, because "
            "an exempt name is one the proxy never sees -- which is why the "
            "default names nothing the container could not already reach"
        ),
    )
    proxy_image: str = DEFAULT_PROXY_IMAGE
    alias: str = Field(
        default="egress",
        description=(
            "The name the session resolves the proxy by, on the internal "
            "network. A name rather than an address because the address is "
            "assigned when the network is created and the environment has to "
            "be baked before that"
        ),
    )
    unproxied: list[Unproxied] = Field(
        default=[SSH_IGNORES_THE_PROXY],
        description=(
            "Components known not to honour the proxy variables. Said at "
            "launch, because a component that ignores them hangs rather than "
            "failing and leaves nothing behind to attribute"
        ),
    )

    def filtered(self) -> bool:
        """Whether this declaration puts a proxy between the session and the world."""
        return self.mode == "filtered"

    def enforced(self) -> EgressPolicy:
        """The policy the proxy is actually given, allowlist and all.

        One place the two halves are joined, so nothing else has to remember
        that ``admits`` is where hosts are named and ``policy`` is where
        everything else is. A declaration that set ``policy.allowed_domains``
        directly is overwritten rather than merged: two ways to widen the
        boundary is one way too many, and the one that survives is the one
        that records why.
        """
        return self.policy.model_copy(
            update={"allowed_domains": [item.host for item in self.admits] or None}
        )

    def network_name(self, project: str) -> str:
        """The internal network this project's sessions attach to."""
        return f"lup-egress-net-{project}"

    def proxy_name(self, project: str) -> str:
        """The proxy container bridging that network to the outside."""
        return f"lup-egress-{project}"

    def environment(self) -> EnvVars:
        """The variables pointing a session's toolchain at its only way out.

        Both cases are set because the tools disagree about which they read,
        and ``NO_PROXY`` is *written* rather than inherited, so nothing
        arrives from the host claiming an exemption that the internal network
        could not honour anyway.

        Written rather than emptied, which is the same argument carried one
        step further. Emptying it took the host's exemptions away and the one
        exemption that is always right along with them: a client honours
        these variables for ``localhost`` too, so a session that started its
        own dev server and reached for it sent the request to the proxy --
        measured, ``curl -v http://localhost:3000`` answering ``Uses proxy
        env variable http_proxy`` -- where squid refused it twice over, as a
        denied local name and as a port outside 80 and 443. Nothing was
        protected by that. The session container is on a network with no
        gateway, so it cannot reach the host's loopback whatever the proxy
        says, and the denial only ever stopped it reaching *its own*
        services by name.

        ``NODE_USE_ENV_PROXY`` is here because the CLI this harness launches
        is itself a Node program, and Node honours these variables only when
        asked: from 22.21 and 24.5 the flag routes ``fetch``, ``node:http``
        and ``node:https`` through them, and without it the session's own API
        calls go straight onto a network with no gateway. A filtered session
        would then fail at the one thing it exists to do, slowly, with a
        timeout for a diagnostic.
        """
        if not self.filtered():
            return {}
        proxy = f"http://{self.alias}:{self.policy.listen_port}"
        direct = ",".join(self.reached_directly)
        return {
            "HTTP_PROXY": proxy,
            "HTTPS_PROXY": proxy,
            "ALL_PROXY": proxy,
            "http_proxy": proxy,
            "https_proxy": proxy,
            "all_proxy": proxy,
            "NO_PROXY": direct,
            "no_proxy": direct,
            "NODE_USE_ENV_PROXY": "1",
        }

    def attachment_arguments(self, project: str) -> list[str]:
        """The run arguments putting a session container on this network.

        ``bridge`` and ``none`` are spelled too rather than left to the
        engine's default, so a declaration that turned the boundary off says
        so in the argv a reader can see instead of by the absence of a flag.
        """
        network = self.network_name(project) if self.filtered() else self.mode
        return ["--network", network]

    def network_arguments(self, project: str) -> list[str]:
        """The argv creating the internal network, for a caller to run."""
        return ["network", "create", "--internal", self.network_name(project)]

    def proxy_arguments(self, project: str, configuration: Path) -> list[str]:
        """The argv starting the proxy, bridged out and stripped of everything else.

        Started on the engine's ordinary network, which is the half that
        reaches the world; :meth:`connect_arguments` adds the other half.
        Every capability but the four it needs to drop privileges and bind
        its port is removed, because this container is the one process with a
        route out of the session's network and is therefore the one worth
        hardening.

        Deliberately **not** ``--rm``, and the absence is the point. A
        detached container that removes itself on exit is one whose logs are
        gone by the time anybody asks, and ``run --detach`` returns zero the
        moment the container is *created* -- so a proxy whose process dies a
        moment later reports a clean start and leaves nothing behind. Measured
        exactly that: a filtered session opened, the launch said the boundary
        was up, the proxy was already gone, and three passes read it as a name
        that would not resolve. A corpse costs nothing and is the only copy of
        why. :func:`~lup.devtools.harness.contained.start_egress` reads it and
        then clears it, so at most one is ever kept.
        """
        return [
            "run",
            "--detach",
            "--name",
            self.proxy_name(project),
            "--network",
            "bridge",
            "-v",
            f"{configuration}:/etc/squid/squid.conf:ro",
            "--memory",
            "256m",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "SETUID",
            "--cap-add",
            "SETGID",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "DAC_OVERRIDE",
            "--security-opt",
            "no-new-privileges:true",
            self.proxy_image,
        ]

    def connect_arguments(self, project: str) -> list[str]:
        """The argv joining the proxy to the internal network under its alias."""
        return [
            "network",
            "connect",
            "--alias",
            self.alias,
            self.network_name(project),
            self.proxy_name(project),
        ]

    def teardown_arguments(self, project: str) -> list[list[str]]:
        """Every argv that removes this project's egress infrastructure, in order.

        The proxy first: a network with a container still attached refuses to
        go, and the resulting diagnostic names the network rather than the
        thing holding it.
        """
        return [
            ["rm", "--force", self.proxy_name(project)],
            ["network", "rm", self.network_name(project)],
        ]

    def notice(self, project: str) -> list[Notice]:
        """What a launch says about the network the session is about to get.

        Every line here is one the friction table demands: the posture, what
        the posture refuses, what will hang rather than fail, and how to take
        the infrastructure back down. A boundary nobody was told about is one
        whose refusals get debugged as something else.
        """
        if not self.filtered():
            return [
                Notice(
                    text=(
                        f"Egress: {self.mode} — no proxy between this session "
                        "and the network. The LAN, localhost and any metadata "
                        "endpoint are reachable from inside the container."
                    ),
                    urgency="warning",
                )
            ]
        scoped = (
            f"only {', '.join(item.host for item in self.admits)}"
            if self.admits
            else "any public destination"
        )
        return [
            Notice(
                text=(
                    f"Egress: filtered through {self.proxy_name(project)} — "
                    f"{scoped}. Private ranges, cloud metadata hosts and local "
                    "names are refused."
                ),
                urgency="boundary",
            ),
            *(
                [
                    Notice(
                        text=(
                            "These ignore the proxy and will hang rather than "
                            "be refused:"
                        ),
                        urgency="warning",
                    )
                ]
                if self.unproxied
                else []
            ),
            *[
                Notice(text=item.sentence(), urgency="warning", indent=1)
                for item in self.unproxied
            ],
            Notice(
                text=(
                    "It outlives this session so the next one does not pay for "
                    "it again; `harness egress --down` removes it."
                ),
                urgency="detail",
            ),
        ]
