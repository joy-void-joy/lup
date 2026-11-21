"""`Landing`: the module an agent finishing a piece lands it through, and the operator puts it on trial and accepts it, among lup's default modules."""

from typing import ClassVar

from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.gate.module import Gate
from lup.landing.landers import Landers
from lup.landing.landings import Landings, WaitsOnReview
from lup.landing.promises import LandingPromises
from lup.shell.kinds import FoldKind, Folds
from lup.store.records import Recorded


class Landing(Module):
    """Landing a branch: the agent who wrote it puts it before the operator, whose yes puts it on trial in what their lup runs, and who accepts it onto the integration branch once they've lived with it.

    A branch lands once it holds the integration branch's tip and the gate
    passed on its files, so it needs the gate.
    """

    name = "landing"
    requires: ClassVar[list[type[Module]]] = [Gate]
    integration: str = "dev"
    """The branch work starts from and accepted work lands on, which only the
    operator's accept moves."""
    remote: str = "origin"
    """The remote the integration branch is read from and pushed to, by its
    name in the repository's configuration."""
    released: str = "main"
    """The branch a release lands on, which only the operator merges into: no
    branch of that name lands."""
    folds: Folds = Folds.of(
        FoldKind(
            name="landing",
            letter="g",
            called="landing",
            level=1,
            colour="orange",
            outlined=True,
        )
    )
    """A landing in what's on trial, its review under it."""
    kinds: Recorded = Recorded.of(WaitsOnReview)
    """A landing's item, waiting on the operator in the agent's conversation."""
    parts: Parts = Parts.of(Landings, Landers, LandingPromises)
