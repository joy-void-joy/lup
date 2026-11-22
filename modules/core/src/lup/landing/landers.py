"""`Landers`: the agents' side of landing, in each project: their tools, each a call on the machine's `Landings` for the agent calling.

It runs in the project's container, from the commit the operator approved, so
the repository a landing is kept under is the one lup vouches for, never one
an agent names, and the integration branch and remote are the project's own
declaration's (`Landing.integration`, `Landing.remote`).
"""

import lup
from lup.doors.parties import Agent
from lup.doors.parts import Part
from lup.landing.landings import LandingAsked, Landings, Wanting
from lup.types import Model
lazy from lup.landing.module import Landing


class Land(Model):
    """Your branch, landed for the operator's review."""

    branch: str
    """Your branch, by its name, as `git branch` lists it."""
    message: str
    """What its merge onto the integration branch will say, whole: what
    changed and why, how it was tested."""


class Want(Model):
    """A branch on trial you need on the integration branch, and why."""

    branch: str
    why: str
    """Why you need it accepted, as the operator reads it on its line."""


class Landers(Part):
    """What an agent finishing a piece calls: their tools, each kept by `Landings`."""

    module: Landing

    @lup.tool
    async def land(self, said: Land, by: Agent) -> str:
        """Put your finished branch before the operator.

        Your branch has to hold the integration branch's tip (merge it in
        first), and the gate has to have passed on its files (`lup gate
        check` in its worktree, everything committed); otherwise this says
        what to do, and lands nothing. It returns as soon as the operator's
        review waits: their yes puts it on trial, running in their lup, and
        their comment reaches you, after which you land it again. Accepting it
        onto the integration branch is theirs, later.
        """
        landed = await Landings.lands(
            LandingAsked(
                agent=by,
                branch=said.branch,
                message=said.message,
                integration=self.module.integration,
                remote=self.module.remote,
                released=self.module.released,
            )
        )
        deferrals = (
            "".join(f"\n- {each.said()}" for each in landed.deferrals)
            if landed.deferrals
            else " It adds and removes no `# lup: defer`."
        )
        changed = (
            "\n\nThe `# lup: defer` comments it changes:" if landed.deferrals else ""
        )
        return (
            f"{landed.branch} at {landed.tip} waits on the operator's review. Their "
            "answer reaches you as a message: a yes puts it on trial, a comment "
            "is theirs to you. A commit you add from here lands with your next "
            f"`land`.{changed}{deferrals}"
            + "".join(f"\n\n{each}" for each in landed.filed)
        )

    @lup.tool
    async def want(self, said: Want, by: Agent) -> str:
        """Ask for a branch on trial to be accepted.

        A branch on trial runs in the operator's lup but isn't on the
        integration branch until they accept it, so a branch you start doesn't
        hold it. Saying why you need it shows on its line in what's on trial.
        """
        return await Landings.wants(Wanting(agent=by, branch=said.branch, why=said.why))
