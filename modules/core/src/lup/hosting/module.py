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
from lup.hosting.projects import Projects
from lup.hosting.promises import (
    ApprovalsPromises,
    HostingPromises,
    ProjectsPromises,
    TreesPromises,
)
from lup.hosting.secrets import Secrets
from lup.hosting.trees import Trees


class Hosting(Module):
    """What runs on the operator's machine: starting every container lup runs, and, as they're built, carrying calls, keeping approvals and secrets, and brokering credentials."""

    name = "hosting"
    parts: Parts = Parts.of(
        Containers,
        Secrets,
        Trees,
        Approvals,
        Carrying,
        Projects,
        HostingPromises,
        TreesPromises,
        ApprovalsPromises,
        ProjectsPromises,
    )
