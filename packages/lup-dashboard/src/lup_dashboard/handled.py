"""The host's own handlers over a state of a demo's own, with nothing reaching the operator: what every demo answers the page with.

`docs/dashboard.md`, *The demo*. `lup-dashboard demo` seeds that state with
stand-ins (`lup_dashboard/demo.py`); `--copy` takes it from the host
(`lup_dashboard/copied.py`). Either way, each request the page sends
(`api.Asked`) is answered by the host's own handler for its kind
(`lup_dev.host.service`, `.inbox.protocol`, `.inbox.marks`, `.inbox.threaded`,
`.policy.waits`, `.host.views`), as this checkout has them, so what the host
refuses is refused here too, saying what the host says, and acts on that state
alone.

**Nothing reaches out, by construction.** On the host, what the page's requests
set off reaches beyond the inbox. Here, each part that would is given to the
handlers as one that refuses, or keeps what it would do in the state:
- an approval approved, by its answer or by a draft sent (`AnswerApproval`,
  `SendDraft`): the host installs the copy approved and restarts on it, in a
  process of its own (`Host.settle`, `lup-dev inbox answer --approve`). Here
  nothing is installed or run: the number is kept (`Withheld.settled`);
- the host service moved to a copy kept (`SwitchCopy`): the host runs `lup-dev
  restore`, in a process of its own, which stops it. Here nothing runs or stops:
  the state's own link and approval are moved and what came of it kept
  (`withheld_switch`);
- what's on trial (`ListTrial`, `PickBranches`, `ChangeBranches`, `AcceptBranch`,
  `DropBranch`): the
  host computes `live` with git, and accepts a branch in a room. Over a copy of
  the operator's state nothing's on trial (`NothingOnTrial`); the stand-in demo holds
  branches, with the host's own handlers over what stands in for git
  (`lup_dashboard/trialed.py`);
- a held change answered, the same ways: the host writes the answer into the
  store of the hold's worktree, runs git in that worktree and logs the verdict,
  for the hook waiting on it to put the files back or keep them
  (`Delivery.settle_hold`, `lup_dev.policy.holds.answer`). Here the answer is
  kept in memory (`Withheld.holds`), nothing written;
- an item for a conversation (`AnswerItem`, `SendItem`, `SendDraft`, an
  approval's comment, a landing's answer): the host releases their waiting
  call, pushes the item to their session on its connection to lup's tool
  server, or rings their runtime's messaging socket (`Delivery.delivered`,
  `wake`, `pushed`, `rung`). Here no call waits, no connection is open
  (`Pushes`), and the waker spells neither a push nor a ring (`Asleep`): no
  session is woken, or reached, and the item stays not told yet;
- an item for the operator, or one of theirs reopened: a desktop notice
  (`Delivery.noticed`, `notify-send`). Here it's kept (`Withheld.notices`);
- a launch renamed (`Rename`): its container renamed by podman
  (`Launches.moved`). Here there's no podman;
- a module's view or action (`Viewing`, `Acting`): the repository's process,
  started from its approved copy (`Workers`). Here this checkout's modules answer
  in this process, given the state's records, items and marks, none of the other
  repositories a declaration names, which the host finds with git (`Modules`),
  and these same routes for what they ask of the host as the operator
  (`RoutesAsked`);
- a launch's hooks (the service's `Courier`, `Answerer` and judge): never heard
  here, nothing served on a launch's sockets (`NoCourier`, `NoAnswerer`,
  `NoJudge`).
What the handlers write, lup's state and runtime directory and each module's
data, is inside the demo's own directory (`DemoLayout.lup`), what the page
measured of itself among it (`KeepTimings`), unless the demo was given a
directory of its own for that (`--timings`). Each demo adds the routes of what
its state can't answer with the host's handlers, what an agent's branches changed
since the operator saw them, which the host reads with git in their worktrees
(`ShowSince`, `ReviewSince`), and what it reads records with.
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, get_args, override

from lup.types import Model, MutableModel
from lup_dashboard.api import Asked, Replied
from lup_dashboard.errors import LupDashboardError
from lup_dashboard.host import Host, read
from lup_dev.declaration.resolve import Resolved
from lup_dev.declaration.serving import OperatorHost
from lup_dev.errors import LupDevError
from lup_dev.host.client import read_reply
from lup_dev.host.courier import Courier, Heard, Telling, Waker
from lup_dev.host.names import Names
from lup_dev.host.on_trial import (
    AcceptBranch,
    ChangeBranches,
    DropBranch,
    LastSwitch,
    ListTrial,
    PickBranches,
)
from lup_dev.host.protocol import HostError, Looks, Refused, Register, Reply, Request
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Recorded
from lup_dev.host.service import (
    Answerer,
    Dispatcher,
    HoldingSetting,
    Launches,
    Renaming,
    Route,
    Served,
)
from lup_dev.host.service import Listing as LaunchesListing
from lup_dev.host.timings import TimingsStore
from lup_dev.host.timings import routes as timings_routes
from lup_dev.host.views import ModuleActions, ModuleViews
from lup_dev.host.watch import Changes
from lup_dev.host.workers import Acting, LaunchJudge, RepositoryAsking, Viewing
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.marks import MarkStore, StoredMarks
from lup_dev.inbox.marks import routes as marks_routes
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.protocol import Exchanged, ItemsListing, ListItems
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import HeldChange
from lup_dev.inbox.threaded import routes as threaded_routes
from lup_dev.layout import CopyLayout, Layout
from lup_dev.policy.waits import Waits
from lup_dev.policy.waits import routes as waits_routes
from lup_dev.stored import write_model
from lup_dev.switching import CopiesAnswering, CopySwitch, host_copies
from lup_dev.worker import RepositoryModules
from lup_ledger.parties import Conversation

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lup.blocks import OfAgent
    from lup.tools.serving import Notice
    from lup.types import JsonObject
    from lup_dashboard.trialed import TrialStandIn
    from lup_dev.clock import Clock
    from lup_dev.declaration.serving import Related
    from lup_dev.inbox.store import Inbox


class Asleep(Model, Waker):
    """Wakes no session: spells neither a push to it nor a ring of its messaging socket, so an item for a conversation waits for a call that never comes."""

    @override
    def woken(self, runtime: str, session: str, text: str) -> str | None:
        return None

    @override
    def pushed(self, runtime: str, text: str, token: str) -> Notice | None:
        return None

    @override
    def capabilities(self, runtime: str) -> dict[str, JsonObject]:
        return {}


class NoAnswerer(Model, Answerer):
    """Answers no runtime's hook: a demo serves no launch's."""

    @override
    def runtimes(self) -> list[str]:
        return []

    @override
    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        message = "a demo serves no launch's hooks"
        raise HostError(message)


class NoCourier(Model, Courier):
    """Reads no runtime's hook: a demo serves no launch's."""

    @override
    def heard(self, runtime: str, payload: str) -> Heard:
        message = "a demo serves no launch's hooks"
        raise HostError(message)

    @override
    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        message = "a demo serves no launch's hooks"
        raise HostError(message)


class NoJudge(Model, LaunchJudge):
    """Judges no launch's hook: a demo serves no launch's."""

    @override
    async def judged(self, launch: Register, payload: str) -> str:
        message = "a demo serves no launch's hooks"
        raise HostError(message)


class HoldAnswered(Model):
    """The operator's answer to a held change, as the host would write it for the hook waiting on it."""

    change: HeldChange
    approved: bool
    comment: str


class Withheld(MutableModel, Notices):
    """What the host would do beyond the inbox, which a demo keeps in its memory instead: each desktop notice, each answer to a held change, each approval it would install."""

    notices: list[str] = []
    holds: list[HoldAnswered] = []
    settled: list[int] = []
    """Each approval approved, by its number, whose copy the host would install."""
    switched: list[str] = []
    """Each commit asked for, whose copy the host would move to."""

    @override
    async def notify(self, summary: str, body: str) -> None:
        self.notices = [*self.notices, f"{summary}\n{body}"]

    def hold(self, change: HeldChange, *, approved: bool, comment: str) -> None:
        """Keep the answer to `change`, where the host writes it for its hook (`Delivery.settle_hold`)."""
        answered = HoldAnswered(change=change, approved=approved, comment=comment)
        self.holds = [*self.holds, answered]


class ItemsExchanged(Model, Exchanges, arbitrary_types_allowed=True):
    """The items one of a repository's conversations exchanged, as the host's handler answers `ListItems` over the demo's inbox."""

    repository: Path
    listing: ItemsListing

    @override
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        party = Conversation(
            repository=self.repository,
            runtime=viewed.runtime,
            session=viewed.session,
            agent=viewed.agent,
        )
        answered = await self.listing.answer(ListItems(conversation=party))
        if not isinstance(answered, Exchanged):
            message = f"the inbox answered a conversation's items with {answered.kind}"
            raise HostError(message)
        return answered


class Modules(RepositoryModules):
    """A repository's modules in a demo: made as its process makes them, but given none of the other repositories its declaration names, which the host finds with git (`related_of`)."""

    @override
    def related(self) -> list[Related]:
        return []


class RoutesAsked(MutableModel, OperatorHost, arbitrary_types_allowed=True):
    """The host as a module's method asks it for the operator in a demo: each request answered by these same routes, as the host's control socket answers it, reaching no socket."""

    routes: dict[str, Route] = {}
    """Each kind the demo answers, what the page can't ask among it, by its kind."""
    say: Callable[[str], None]

    @override
    async def asked[R: Reply](self, request: Request, reply: type[R]) -> R:
        dispatcher = Dispatcher(
            routes=self.routes,
            answering="the demo",
            say=self.say,
            changes=Changes(),
        )
        replied = await dispatcher.answered(request.model_dump_json())
        return read_reply(replied.model_dump_json().encode(), reply)


class Views(MutableModel, RepositoryAsking, arbitrary_types_allowed=True):
    """Each repository's modules, answering its views and running its actions as its process would, in this process: `own`'s made from `declared`, every other's from lup's defaults, its declaration out of reach."""

    own: Path
    """The repository whose declaration a demo has, by its git directory."""
    declared: Resolved
    """That declaration, resolved."""
    defaults: Resolved
    """lup's default declaration, resolved: every other repository's."""
    repositories: list[Path]
    """Each repository the demo's launches run in, whose views look as its
    modules say."""
    layout: Layout
    """lup's places in the demo, where each module keeps its own data."""
    recorded: dict[str, Recorded]
    listing: ItemsListing
    """The demo's items, as the host's handler lists a conversation's."""
    marks: MarkStore
    """The demo's review marks, as the host holds them."""
    host: RoutesAsked
    """What their methods ask of the host as the operator."""
    made: dict[Path, Modules] = {}

    def modules(self, repository: Path) -> Modules:
        """Return `repository`'s modules, made once."""
        found = self.made.get(repository)
        if found is not None:
            return found
        made = Modules(
            repository=repository,
            resolved=self.declared if repository == self.own else self.defaults,
            recorded=self.recorded,
            layout=self.layout,
            exchanges=ItemsExchanged(repository=repository, listing=self.listing),
            marks=StoredMarks(store=self.marks),
            host=self.host,
        )
        self.made = {**self.made, repository: made}
        return made

    def by_defaults(self) -> list[Path]:
        """List the repositories whose views lup's default modules answer."""
        return [each for each in self.repositories if each != self.own]

    @override
    async def asked(self, repository: Path, request: Request) -> Reply:
        """Answer a view of `repository`'s or run an action of it, or refuse it saying why, as its process does (`lup_dev.worker.Views`, `.Actions`)."""
        modules = self.modules(repository)
        try:
            match request:
                case Viewing():
                    return await modules.view(request)
                case Acting():
                    return await modules.act(request)
                case _:
                    message = f"a demo asks a repository's modules no `{request.kind}`"
                    raise HostError(message)
        except LupDevError as refused:
            raise HostError(str(refused)) from refused

    @override
    @asynccontextmanager
    async def watching(self, repository: Path) -> AsyncGenerator[None]:
        """Hold nothing while a view of `repository`'s is watched: its modules stay made."""
        del repository
        yield

    @override
    def looks(self) -> dict[Path, Looks]:
        return {each: self.modules(each).resolved.looks for each in self.repositories}


def nothing_on_trial() -> list[Route]:
    """Return the routes of what's on trial for a demo over a copy of the operator's state, which holds nothing of it: its plain page lists no branch to pick, and a module's view says why it reads nothing."""

    async def refused(raw: str) -> Reply:
        del raw
        message = "a demo over a copy of your state runs nothing on trial"
        raise HostError(message)

    return [
        Route(kind=each.named(), answer=refused)
        for each in [ListTrial, PickBranches, ChangeBranches, AcceptBranch, DropBranch]
    ]


def withheld_switch(
    lup: Layout, withheld: Withheld, clock: Clock
) -> Callable[[CopyLayout, str], None]:
    """Return what stands in for starting `lup-dev restore`, for a demo's copies alone (`CopySwitch.start`): the link in `lup` names the commit's, as a switch that answered leaves it, what came of it said where a page waiting on it reads that, and no program runs."""

    def switched(copy: CopyLayout, commit: str) -> None:
        del copy
        withheld.switched = [*withheld.switched, commit]
        copies = host_copies(lup)
        kept = None if copies is None else copies.of(commit)
        if copies is None or kept is None:
            return
        at = clock.now()
        copies.switch(copies.place(kept))
        copies.recorded(kept.model_copy(update={"answered": at}))
        write_model(lup.approved(kept.repository), kept.approval)
        said = (
            f"The demo's copy of {commit} is the one running, and nothing else moved."
        )
        write_model(
            lup.host.switched,
            LastSwitch(commit=commit, at=at, said=said, answered=True),
        )

    return switched


def asked_kinds() -> list[str]:
    """List the kinds the page may ask (`api.Asked`)."""
    [union, _] = get_args(Asked.__value__)
    return [each.named() for each in get_args(union)]


def answering(routes: list[Route], who: str) -> dict[str, Route]:
    """Return the routes of the kinds the page may ask, each by its kind, every other left out, so nothing else the handlers serve is reached.

    Raise `LupDashboardError` where a kind the page may ask has none, saying who answers none of them.
    """
    kinds = asked_kinds()
    routed = {each.kind: each for each in routes if each.kind in kinds}
    missing = [each for each in kinds if each not in routed]
    if missing:
        message = f"{who} answers none of {', '.join(missing)}"
        raise LupDashboardError(message)
    return routed


class Handled(MutableModel, Host, arbitrary_types_allowed=True):
    """The host over a demo's own state: each request answered by the host's own handler of its kind, as this checkout has them."""

    dispatcher: Dispatcher
    changes: Changes
    """Told once each request is answered, as the host service's control socket
    tells it, so each watch answers again."""
    delivery: Delivery
    launches: Launches
    waits: Waits
    views: Views
    withheld: Withheld
    """What the host would have done beyond the inbox, kept here instead."""

    @property
    def inbox(self) -> Inbox:
        """The inbox the handlers answer over."""
        return self.delivery.inbox

    @override
    async def ask(self, request: Asked) -> Replied:
        replied = await self.dispatcher.answered(request.model_dump_json())
        self.changes.changed()
        return read(replied.model_dump_json().encode())

    @override
    async def watch(self, request: Asked) -> AsyncGenerator[Replied]:
        sent = ""
        async for replied in self.dispatcher.replies(request.model_dump_json()):
            line = replied.model_dump_json()
            if line != sent:
                yield read(line.encode())
                sent = line
            if isinstance(replied, Refused):
                return

    @override
    async def settle(self, number: int) -> None:
        """Install nothing, and restart nothing: keep the approval's number."""
        self.withheld.settled = [*self.withheld.settled, number]


def handled(
    lup: Layout,
    inbox: Inbox,
    changes: Changes,
    recorded: dict[str, Recorded],
    *,
    own: Path,
    declared: Resolved,
    defaults: Resolved,
    served: list[Served],
    beyond: list[Route],
    who: str,
    clock: Clock,
    say: Callable[[str], None],
    timings: Path | None,
    trial: TrialStandIn | None = None,
) -> Handled:
    """Return the host over the state at `lup`: `inbox` told to `changes`, each runtime's records read through `recorded`, the launches `served`, `own`'s views answered by `declared` and every other's by `defaults`, what the page measures of itself kept in `timings`, else in the state; what's on trial as `trial` holds it, where it holds any; and `beyond`, the routes of what the host's handlers can't answer over it. `who` is who answers, as a refusal names it.

    Raise `LupDashboardError` where a kind the page may ask has no route.
    """
    withheld = Withheld()
    waits = Waits(changes=changes)
    delivery = Delivery(
        inbox=inbox,
        waker=Asleep(),
        pushes=Pushes(),
        layout=lup.host,
        notices=withheld,
        clock=clock,
        say=say,
        settle_hold=lambda change, _repository, approved, said: withheld.hold(
            change, approved=approved, comment=said
        ),
        landing=waits.holding,
    )
    launches = Launches(
        layout=lup.host,
        answerer=NoAnswerer(),
        courier=NoCourier(),
        post=None,
        judge=NoJudge(),
        tools=[],
        room_routes=[],
        modules=None,
        line_limit=0,
        waker=Asleep(),
        pushes=Pushes(),
        say=say,
        names=Names(path=lup.host.names),
        changes=changes,
        clock=clock,
    )
    launches.served = {each.launch.launch: each for each in served}
    asked = RoutesAsked(say=say)
    views = Views(
        own=own,
        declared=declared,
        defaults=defaults,
        repositories=list(
            dict.fromkeys([own, *(each.launch.repository for each in served)])
        ),
        layout=lup,
        recorded=recorded,
        listing=ItemsListing(delivery=delivery),
        marks=inbox.marks,
        host=asked,
    )
    module_views = ModuleViews(asking=views, changes=changes, say=say, clock=clock)
    start = withheld_switch(lup, withheld, clock)
    routes = [
        Route.reading(
            LaunchesListing(
                launches=launches, asking=views, standing=views.defaults.looks
            )
        ),
        Route.to(Renaming(launches=launches)),
        Route.to(HoldingSetting(launches=launches)),
        *inbox_routes(delivery, recorded),
        *marks_routes(inbox.marks, clock, changes),
        *threaded_routes(delivery),
        *waits_routes(waits),
        *timings_routes(TimingsStore(home=timings or lup.host.timings), clock),
        Route.to(CopiesAnswering(layout=lup)),
        Route.to(CopySwitch(layout=lup, start=start)),
        *(
            nothing_on_trial()
            if trial is None
            else trial.routes(
                lup, delivery, clock=clock, say=say, start=start, changes=changes
            )
        ),
        *beyond,
        Route.reading(module_views, watch=module_views.watched),
        Route.to(ModuleActions(asking=views, changes=changes)),
    ]
    asked.routes = {each.kind: each for each in routes}
    return Handled(
        dispatcher=Dispatcher(
            routes=answering(routes, who), answering=who, say=say, changes=changes
        ),
        changes=changes,
        delivery=delivery,
        launches=launches,
        waits=waits,
        views=views,
        withheld=withheld,
    )
