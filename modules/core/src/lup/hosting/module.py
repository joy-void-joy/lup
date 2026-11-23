"""`Hosting`: the module of the parts that run on the operator's machine, which the home repository's declaration selects.

The machine's parts are one for the whole machine, serving every project, so
they're the home repository's to run: lup's own, unless the operator chose
another. A project's declaration doesn't select them; the home repository's adds
this module.
"""

from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.hosting.approvals import Approvals
from lup.hosting.carrying import Carrying
from lup.hosting.containers import Containers
from lup.hosting.logins import Logins
from lup.hosting.projects import Projects
from lup.hosting.promises import (
    AimingPromises,
    ApprovalsPromises,
    BuildingPromises,
    ClearingPromises,
    HerePromises,
    HostingPromises,
    LendingPromises,
    MachinewidePromises,
    ProjectsPromises,
    TreesPromises,
    WithoutPromises,
)
from lup.hosting.secrets import Secrets
from lup.hosting.trees import Trees
from lup.shell.kinds import FoldKind, Folds, Tone, Tones


class Hosting(Module):
    """What runs on your machine, and what you approved to run.

    Starting every container lup runs, and, as they're built, carrying calls,
    keeping approvals and secrets, and brokering credentials. Typed `lup
    machine …`: its name says what it's for, where its package's and its
    class's say how it runs.
    """

    name = "machine"
    parts: Parts = Parts.of(
        Containers,
        Secrets,
        Logins,
        Trees,
        Approvals,
        Carrying,
        Projects,
        HostingPromises,
        TreesPromises,
        ApprovalsPromises,
        ProjectsPromises,
        LendingPromises,
        ClearingPromises,
        WithoutPromises,
        HerePromises,
        BuildingPromises,
        MachinewidePromises,
        AimingPromises,
    )
    tones: Tones = Tones.of(
        Tone(name="up", colour="ok"),
        Tone(name="down", colour="err"),
        Tone(name="waiting", colour="warn"),
    )
    """How `status` says a container stands: running, ended or failed, or a
    part waiting on what it needs."""
    folds: Folds = Folds.of(
        FoldKind(
            name="project",
            letter="p",
            called="project",
            starts_open=True,
            colour="cyan",
        )
    )
    """A project `status` shows, its containers under it, or the machine's own
    parts."""
