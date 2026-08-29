"""Standing a wizard up as routes, for whatever a project's steps are about.

The engine says what a step means and the page draws it; this is the seam
between them. It is generic over the scope because that is the whole point of
the split — this library's own dashboard configures an environment file, and a
project adopting it may be configuring something with a name and several of
them. Neither knows about the other.

Five routes and no cleverness. Every one that changes anything answers with
both what happened *and* the page as it stands afterwards, so a surface never
draws from what it assumed: the reply it renders is a fresh reading, in one
round trip.
"""

from collections.abc import Callable

from fastapi import FastAPI
from pydantic import BaseModel

from lup.devtools.dashboard.page import WIZARD_PAGE
from lup.devtools.dashboard.wizard import (
    ScopeChoice,
    StepAnswers,
    StepOutcome,
    Wizard,
    WizardView,
)
from lup.web.serve import page_app


class ScopeRequest(BaseModel):
    """A scope somebody asked to make."""

    name: str = ""


class RowRequest(BaseModel):
    """Which of a row's acts somebody clicked, and the one value it asked for."""

    row: str = ""
    act: str = ""
    answer: str = ""


class StepReply(BaseModel, frozen=True):
    """What an act did, and the page as it stands afterwards."""

    outcome: StepOutcome
    view: WizardView


def create_wizard_app[Scope](
    url: str,
    *,
    title: str,
    wizard: Wizard[Scope],
    resolve: Callable[[str], Scope | None],
    choices: Callable[[], list[ScopeChoice]],
    lede: str = "",
    scope_label: str = "",
    empty_notice: str = "",
    create: Callable[[str], StepOutcome] | None = None,
    creates: str = "",
    create_asks: str = "",
) -> FastAPI:
    """Serve one wizard over whatever scopes a project has.

    ``resolve`` turns the name a request carries into the thing steps act on,
    and answers ``None`` for a name that means nothing — which is what a stale
    tab sends after somebody deleted the scope it was looking at. Falling back
    to the first real scope rather than refusing keeps that tab recoverable: it
    redraws something true instead of an empty frame.
    """
    application = page_app(title, url, WIZARD_PAGE)

    def chosen(name: str) -> str:
        if resolve(name) is not None:
            return name
        available = choices()
        return available[0].name if available else ""

    def offered_create() -> str:
        """The create label, only where a project actually gave one a handler."""
        return creates if create is not None else ""

    def view(name: str) -> WizardView:
        scope = resolve(name) if name else None
        if scope is None:
            return WizardView(
                title=title,
                lede=lede,
                scope_label=scope_label,
                creates=offered_create(),
                create_asks=create_asks,
                notice=empty_notice,
            )
        return WizardView(
            title=title,
            lede=lede,
            scope_label=scope_label,
            scopes=choices(),
            chosen=name,
            steps=wizard.viewed(scope),
            creates=offered_create(),
            create_asks=create_asks,
        )

    def gone() -> StepOutcome:
        """What every route says when there is nothing left to act on."""
        subject = scope_label.lower() or "scope"
        return StepOutcome(ok=False, message=f"That {subject} is gone — reload.")

    @application.get("/api/wizard")
    async def read(scope: str = "") -> WizardView:
        return view(chosen(scope))

    @application.post("/api/scopes")
    async def make(request: ScopeRequest) -> StepReply:
        """Make another scope, where the project said one can be made.

        Refused rather than ignored when it cannot: a page drawing the button
        is one thing, and a request naming the route is another, so the second
        is checked here rather than assumed from the first.
        """
        if create is None:
            return StepReply(
                outcome=StepOutcome(ok=False, message="Nothing can be made here."),
                view=view(chosen("")),
            )
        name = request.name.strip()
        if not name:
            subject = scope_label.lower() or "it"
            return StepReply(
                outcome=StepOutcome(ok=False, message=f"Give {subject} a name."),
                view=view(chosen("")),
            )
        return StepReply(outcome=create(name), view=view(chosen(name)))

    @application.post("/api/wizard/{slug}/run")
    async def run(slug: str, answers: StepAnswers, scope: str = "") -> StepReply:
        name = chosen(scope)
        against = resolve(name)
        if against is None:
            return StepReply(outcome=gone(), view=view(name))
        return StepReply(
            outcome=await wizard.run(against, slug, answers), view=view(name)
        )

    @application.post("/api/wizard/{slug}/test")
    async def check(slug: str, scope: str = "") -> StepReply:
        name = chosen(scope)
        against = resolve(name)
        if against is None:
            return StepReply(outcome=gone(), view=view(name))
        return StepReply(outcome=await wizard.test(against, slug), view=view(name))

    @application.post("/api/wizard/{slug}/reset")
    async def undo(slug: str, scope: str = "") -> StepReply:
        name = chosen(scope)
        against = resolve(name)
        if against is None:
            return StepReply(outcome=gone(), view=view(name))
        return StepReply(outcome=await wizard.reset(against, slug), view=view(name))

    @application.post("/api/wizard/{slug}/act")
    async def act(slug: str, request: RowRequest, scope: str = "") -> StepReply:
        """Run one of a row's acts.

        Whether the row offers it is decided in the wizard rather than taken
        from what the page posted, so a destructive verb the browser was never
        shown is not reachable by asking for it directly.
        """
        name = chosen(scope)
        against = resolve(name)
        if against is None:
            return StepReply(outcome=gone(), view=view(name))
        outcome = await wizard.act(
            against, slug, request.row, request.act, request.answer
        )
        return StepReply(outcome=outcome, view=view(name))

    return application
