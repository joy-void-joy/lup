"""The external programs a project needs, declared once and exercised.

A launch that assumes its toolchain is there fails later, inside whatever it
was doing, in that thing's own vocabulary: a missing program reads as
`command not found`, a dead socket as "the daemon is down", a boundary that
refused a write as a broken filesystem. Each of those points somewhere other
than the cause, and each has to be diagnosed by hand before any work starts.

So a requirement is declared, and the declaration carries what is needed, how
to *exercise* it, what to say when the exercise fails, **where** it is
needed, and what absence costs. From that one declaration come the probe, the
sentence a human reads, and the packages an image installs -- so a
requirement cannot be checked without being announced, announced without
being checked, or announced while the image it is checked against was built
from a different list.

Three properties are load-bearing and easy to lose:

**Exercise, not presence.** ``shutil.which(tool) is None`` passes for a
program installed against a socket nobody is serving, for a client redirected
by an environment variable to a path that does not exist, and for a session
whose supplementary groups were fixed before its account joined the group it
needs. All three were diagnosed by hand once already. The check runs the
smallest real operation instead -- evaluate an expression, ask the daemon what
it is, render one page -- because every one of those failures survives a
presence test.

**Where decides who is asked.** Some capabilities belong to the host and must
never reach the image: a container runtime is the clearest, since a container
holding one could start a sibling with the whole host mounted. Others belong
only to the image, and exercising those here would report a perfectly good
machine broken for lacking a toolchain nothing outside a container was going
to run. Checking everything everywhere is how a manifest starts lying.

**Absence is usually a valid answer**, in grades. Most cost a named
capability and are worth saying at every launch. A few are conveniences worth
saying once, to somebody setting a machine up, because a nicety repeated
before every session becomes a line people learn to skip -- along with the
line above it, which mattered. Only a requirement whose absence would leave
something silently untrue refuses to open at all.
"""

import grp
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

import sh
from pydantic import BaseModel, Discriminator, Field

from lup.types import EnvVars


class Advisory(BaseModel, frozen=True):
    """Absence makes the experience worse and takes nothing away.

    The softest grade, and the one that keeps the other two worth reading. A
    convenience reported at every launch becomes a line people learn to skip,
    and the line above it is the one that mattered -- so this is said where
    somebody is setting a machine up and can act on it, and stays quiet in
    front of the sessions that follow.
    """

    kind: Literal["advisory"] = "advisory"
    improves: str = Field(description="What having it would make nicer")

    def refuses(self) -> bool:
        return False

    def at_launch(self) -> bool:
        return False

    def consequence(self) -> str:
        return f"{self.improves} would be smoother with it"


class LostCapability(BaseModel, frozen=True):
    """Absence costs one named capability and stops nothing else.

    The capability is named rather than described so the sentence a session
    opens with says what the operator no longer has, not merely that
    something is missing: "no container -- multi-worker resolve unavailable"
    is actionable where "docker: missing" is a fact somebody has to interpret.
    """

    kind: Literal["degrades"] = "degrades"
    capability: str = Field(description="What this session cannot do without it")

    def refuses(self) -> bool:
        return False

    def at_launch(self) -> bool:
        return True

    def consequence(self) -> str:
        return f"{self.capability} is unavailable"


class RefusedLaunch(BaseModel, frozen=True):
    """Absence makes a claimed boundary worth less than it says, so nothing opens.

    Reserved for the case where continuing would be *quietly* weaker rather
    than visibly smaller: a rootful daemon, a confinement that did not start.
    A session that opens anyway there is one whose operator believes in a wall
    that is not standing.
    """

    kind: Literal["refuses"] = "refuses"
    because: str = Field(description="What would be silently untrue if this opened")

    def refuses(self) -> bool:
        return True

    def at_launch(self) -> bool:
        return True

    def consequence(self) -> str:
        return f"refusing to open: {self.because}"


type Absence = Annotated[
    Advisory | LostCapability | RefusedLaunch, Discriminator("kind")
]


class EnvironmentRedirect(BaseModel, frozen=True):
    """A variable aiming a client somewhere, named when that place is absent.

    The failure this catches is the one that reads most convincingly as
    something else: a client redirected to a socket that was never created
    reports that it cannot reach the daemon, which sends the reader to start
    a service that had nothing to do with it.
    """

    kind: Literal["environment_redirect"] = "environment_redirect"
    variable: str
    scheme: str = Field(
        default="unix://",
        description="Prefix stripped before the value is read as a path",
    )

    def cause(self, environment: EnvVars, outcome: "ExerciseOutcome") -> str:
        """Why this redirect explains the failure, or nothing when it does not.

        Ungated on what the failure said, unlike its sibling: this one checks
        the redirect target itself, so it only ever speaks when a variable is
        genuinely aiming a client at something absent. That is a cause
        whatever words the client chose to fail in.
        """
        value = environment.get(self.variable, "")  # lup: ignore[dict-get]
        if not value:
            return ""
        target = Path(value.removeprefix(self.scheme))
        if target.exists():
            return ""
        return (
            f"{self.variable} points at {target}, which does not exist. "
            f"Unset {self.variable} to use the default, or start whatever "
            "serves that path -- the service you were about to restart is "
            "probably not the one at fault."
        )


class SupplementaryGroup(BaseModel, frozen=True):
    """Membership the account holds that this process was started without.

    Supplementary groups are captured when a process starts, so joining a
    group leaves every already-running shell outside it. The permission error
    that follows names no group and no remedy, and the remedy is not a
    permission change at all -- it is a new session.
    """

    kind: Literal["supplementary_group"] = "supplementary_group"
    group: str
    when: list[str] = Field(
        default=["permission denied", "Permission denied", "EACCES"],
        description=(
            "Markers that make a group difference the plausible cause. A "
            "default rather than a constant: which words a toolchain uses "
            "for 'you may not' is that toolchain's, not this module's"
        ),
    )

    def cause(self, environment: EnvVars, outcome: "ExerciseOutcome") -> str:
        """Why the group explains *this* failure, or nothing when it does not.

        Gated on the failure looking like a refusal, because a group
        difference is nearly always present and nearly never the cause. Left
        ungated it volunteered "this session is not in the docker group" for
        a daemon reached over a socket the user already owns outright --
        true about the groups, unrelated to the failure, and worse than
        silence, since a reader who acts on it starts a new session and finds
        nothing changed.
        """
        if not any(marker in outcome.detail for marker in self.when):
            return ""
        try:
            entry = grp.getgrnam(self.group)
        except KeyError:
            return f"there is no {self.group} group on this host"
        if environment.get("USER", "") not in entry.gr_mem:  # lup: ignore[dict-get]
            return (
                f"this account is not in the {self.group} group; adding it is "
                "what grants access, and takes a new session to take effect"
            )
        if entry.gr_gid in os.getgroups():
            return ""
        return (
            f"this account is in {self.group} but this session is not: "
            "supplementary groups are fixed when a process starts. Start a "
            "new session -- nothing needs installing or reconfiguring."
        )


type Diagnosis = Annotated[
    EnvironmentRedirect | SupplementaryGroup, Discriminator("kind")
]


class ExerciseOutcome(BaseModel, frozen=True):
    """What running the smallest real operation established.

    ``detail`` carries the operation's own words either way: on success it is
    what proves the claim, and on failure it is the message a reader would
    otherwise have gone looking for. Neither is thrown away, because the whole
    point of exercising is to have something concrete to show.
    """

    proved: bool
    detail: str = ""


class Run(BaseModel, frozen=True):
    """The smallest real operation that proves a requirement actually works.

    ``expect`` is what the operation has to have produced. Left empty, a clean
    exit is the whole claim -- right for a program asked its own version, and
    wrong for anything whose failure mode is succeeding at the wrong thing,
    which is what the field exists for.
    """

    kind: Literal["run"] = "run"
    command: list[str] = Field(min_length=1)
    expect: str = Field(
        default="",
        description="Text the output must contain; empty means a clean exit suffices",
    )

    def run(self) -> ExerciseOutcome:
        """Carry the operation out, answering whether it proved the claim."""
        try:
            output = str(sh.Command(self.command[0])(*self.command[1:]))
        except sh.CommandNotFound:
            return ExerciseOutcome(
                proved=False, detail=f"{self.command[0]} is not on PATH"
            )
        except sh.ErrorReturnCode as failure:
            spoken = failure.stderr.decode("utf-8", "replace").strip()
            return ExerciseOutcome(
                proved=False,
                detail=spoken or f"{self.command[0]} exited {failure.exit_code}",
            )
        if self.expect and self.expect not in output:
            return ExerciseOutcome(
                proved=False,
                detail=(
                    f"{' '.join(self.command)} ran but did not produce "
                    f"{self.expect!r}, so it is installed without working"
                ),
            )
        return ExerciseOutcome(proved=True, detail=output.strip())


class AnyOf(BaseModel, frozen=True):
    """Several spellings of one capability, where holding any is holding it.

    A clipboard is `xclip` or `xsel` or `wl-copy` or `pbcopy` depending on the
    desktop; a display is X11 or Wayland or neither. Declaring one of them and
    calling its absence the capability's absence is how a machine that has the
    capability gets told it does not -- and the report then names a program the
    operator has no reason to install.
    """

    kind: Literal["any_of"] = "any_of"
    alternatives: list[Run] = Field(min_length=1)

    def run(self) -> ExerciseOutcome:
        """Take the first spelling that works, or report what each one said."""
        outcomes = [candidate.run() for candidate in self.alternatives]
        proved = next((item for item in outcomes if item.proved), None)
        if proved is not None:
            return proved
        return ExerciseOutcome(
            proved=False,
            detail="; ".join(
                f"{' '.join(candidate.command)}: {outcome.detail}"
                for candidate, outcome in zip(self.alternatives, outcomes, strict=True)
            ),
        )


type Exercise = Annotated[Run | AnyOf, Discriminator("kind")]


type Side = Literal["host", "image", "both"]
"""Which side of the boundary is expected to satisfy a requirement."""


class Requirement(BaseModel, frozen=True):
    """One external program or condition, with the cost of not having it."""

    capability: str = Field(description="Short handle, e.g. 'docker' or 'clipboard'")
    purpose: str = Field(description="What this project uses it for")
    where: Side = Field(
        default="host",
        description=(
            "Which side needs this. A host requirement is exercised here and "
            "never installed into an image -- a container runtime is the "
            "clearest case, since a container holding one could start a "
            "sibling with the whole host mounted. An image requirement is "
            "the reverse: the host is not expected to have it, so exercising "
            "it here would report a machine broken for lacking something it "
            "was never meant to carry"
        ),
    )
    exercise: Exercise
    absence: Absence
    diagnoses: list[Diagnosis] = Field(
        default=[],
        description=(
            "Causes to look for when the exercise fails, in the order a "
            "reader should hear them. Each is a failure whose own error "
            "message points somewhere else"
        ),
    )
    install: list[str] = Field(
        default=[],
        description=(
            "Distribution packages that satisfy this *inside a container "
            "image built from this harness*, when a package manager is how "
            "it is obtained there. Empty is the common answer and means one "
            "of two things: the base image already ships it, or the "
            "capability is the host's and the container deliberately does "
            "not have it"
        ),
    )

    def check(self, environment: EnvVars) -> "Finding":
        """Exercise this requirement and say what was found, in whose words."""
        outcome = self.exercise.run()
        if outcome.proved:
            return Finding(requirement=self, working=True, detail=outcome.detail)
        causes = [
            found
            for found in (probe.cause(environment, outcome) for probe in self.diagnoses)
            if found
        ]
        return Finding(
            requirement=self, working=False, detail=outcome.detail, causes=causes
        )


class Finding(BaseModel, frozen=True):
    """What one requirement's exercise established, ready to be read aloud."""

    requirement: Requirement
    working: bool
    detail: str = ""
    causes: list[str] = []

    def refuses(self) -> bool:
        """Whether this finding is one a launch must not continue past."""
        return not self.working and self.requirement.absence.refuses()

    def lines(self) -> list[str]:
        """This finding as an operator reads it: verdict, cause, consequence.

        The consequence is printed even when a cause was found, because the
        two answer different questions -- why it failed, and what is now
        missing -- and a reader who gets only the first has to work out
        whether it mattered.
        """
        if self.working:
            return [f"{self.requirement.capability}: working"]
        consequence = self.requirement.absence.consequence()
        return [
            f"{self.requirement.capability}: {consequence}",
            *[f"    {cause}" for cause in self.causes or [self.detail]],
            f"    needed for {self.requirement.purpose}",
        ]


class Manifest(BaseModel, frozen=True):
    """Every requirement a project declares, asked all at once.

    Held as one object rather than a loose list so the launch, the standalone
    command, and the image declaration read the same roster: a requirement
    added for one of them is a requirement all three see.
    """

    requirements: list[Requirement] = []

    def on_the_host(self, advisory: bool = False) -> list[Requirement]:
        """The requirements this machine is expected to satisfy itself.

        Image-side entries are excluded outright rather than exercised and
        forgiven: a host without `bun` is not a host with a problem when
        nothing outside the container was ever going to run it, and a line
        saying otherwise is the false report this whole module exists to
        stop.

        *advisory* widens the answer to the conveniences as well, which is
        what somebody setting a machine up wants and what a session opening
        for the hundredth time does not.
        """
        return [
            item
            for item in self.requirements
            if item.where in ("host", "both") and (advisory or item.absence.at_launch())
        ]

    def check(self, environment: EnvVars, advisory: bool = False) -> list["Finding"]:
        """Exercise every host-side requirement, in declaration order."""
        return [item.check(environment) for item in self.on_the_host(advisory)]

    def packages(self) -> list[str]:
        """Everything an image installs to satisfy this manifest, deduplicated.

        Ordered by first declaration rather than sorted: an image layer reads
        better grouped by what asked for each package, and a stable order is
        what keeps a rebuild from invalidating the layer for no reason.

        For an image, and not for a CI runner, which is a distinct audience
        however alike the two lists look. Feeding this straight into a
        workflow's system packages was tried and generated
        ``apt-get install -y uv``, which no Ubuntu runner can satisfy and
        which that workflow already solves with a setup action -- and it
        would have installed a container runtime the image must never carry.
        A requirement is one thing; where each place gets it is another.
        """
        return list(
            dict.fromkeys(
                package
                for item in self.requirements
                if item.where in ("image", "both")
                for package in item.install
            )
        )


def refused(findings: Sequence[Finding]) -> list[Finding]:
    """The findings that stop a launch, which is usually none of them."""
    return [finding for finding in findings if finding.refuses()]
