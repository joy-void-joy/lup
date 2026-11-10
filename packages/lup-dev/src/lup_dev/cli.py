"""The `lup-dev` command: the hooks, the gate's rule check, the inbox and verdicts.

It stands in for the real `lup` command tree until the declaration and command
line piece builds it; the commands keep their meaning there, and their final
names are that piece's call (#114). It's the one
place that lists the runtimes' adapters: the host service reads each hook and
adds to its answer with the courier built here, and answers a hook a launch's
judge couldn't with the answerer (`docs/launch.md`); `hook` answers through it.

`trust` approves what the host runs for a repository, the check a launch makes
first (`docs/trust.md`). `launch` opens a runtime's session in
a room for the worktree (*The command*). `host` runs the host service, handed
the inbox as what each conversation is told at their hooks, their tools and their
requests; `inbox` is the operator's face on it (`docs/inbox.md`, *The operator's face*).
`stage` stages the hunks of a file an agent names, which `git add -p` would ask
at a terminal (`docs/judging-writes.md`, *Staging part of a file*).
"""

import asyncio
import itertools
import secrets
import shutil
import sys
import traceback
import webbrowser
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, get_args, override

import typer
from filelock import FileLock
from filelock import Timeout as Held
from pydantic import Field, TypeAdapter, ValidationError
from typer.core import TyperGroup

from lup.doors import served as methods
from lup.errors import LupError
from lup.programs import Apart, detached
from lup.rooms import ContainerError, Mount, Podman, Room
from lup.rooms.engine import stopped
from lup.types import JsonObject, Model, MutableModel
from lup_dev import commanding, conversions
from lup_dev.accounts import AccountError, Accounts, Login, RuntimeLogin

# lup: ignore("runtime-mention", why="the one place listing the adapters")
from lup_dev.adapters import Adapter, claude, codex
from lup_dev.approval import approved, approved_branches
from lup_dev.clipboard.desktop import Desktop
from lup_dev.clipboard.protocol import routes as clipboard_routes
from lup_dev.clock import Clock, SystemClock
from lup_dev.codescan.conditions import loaded
from lup_dev.codescan.contract import Checker, Due, Finding, Parser, Rule, Source
from lup_dev.codescan.directives import (
    AskedOnce,
    Checking,
    Fired,
    GitHubIssues,
    HostIssues,
    Issues,
    Trackers,
    holding,
    waited_on,
    without,
)
from lup_dev.codescan.engine import EngineChecker, EngineError, EngineParser
from lup_dev.codescan.reference import reference
from lup_dev.codescan.ruff import Ruff
from lup_dev.commanding import RoomExchanges, RoomMarks
from lup_dev.confined import Confined
from lup_dev.conversions import inbox_opened
from lup_dev.copies import Kept, removable
from lup_dev.declaration.load import declared_profiles, load, person_layer
from lup_dev.declaration.profiles import chosen
from lup_dev.declaration.project import Project
from lup_dev.declaration.requirements import Machine, Report, Tools
from lup_dev.declaration.requirements import check as checked
from lup_dev.declaration.resolve import Declaration, Selected, resolve
from lup_dev.declaration.serving import Operator
from lup_dev.declaration.serving import Room as RoomAsker
from lup_dev.declaration.serving import tools as module_tools
from lup_dev.environments import environment
from lup_dev.errors import LupDevError
from lup_dev.forge.github import PROGRAM, GitHubError, named
from lup_dev.gate import (
    Amended,
    Check,
    Passed,
    Passes,
    Shell,
    at_commit,
    failed,
    report,
)
from lup_dev.gate import Ran as GateRan
from lup_dev.git import Git, GitError, link_file, nul_separated
from lup_dev.git import Worktree as Checkout
from lup_dev.host.client import FromRoom, HostClient, RoomClient, own_command
from lup_dev.host.copying import Copying
from lup_dev.host.courier import (
    Courier,
    Heard,
    Spawned,
    Spawns,
    Telling,
    Waker,
)
from lup_dev.host.dashboard import (
    DashboardProcess,
    DashboardShown,
    ShowDashboard,
    Showing,
    plain_page,
)
from lup_dev.host.held import (
    Abandon,
    Abandoning,
    AwaitHeld,
    Awaiting,
    CalledUp,
    CallingUp,
    End,
    HeldLaunch,
    HeldUp,
    Interrupt,
    Launchers,
    Spawn,
    Spawning,
    Starting,
    launcher_command,
)
from lup_dev.host.held import Ending as HeldEnding
from lup_dev.host.held import Interrupting as HeldInterrupting
from lup_dev.host.holders import Holders
from lup_dev.host.names import shaped
from lup_dev.host.on_trial import (
    AcceptBranch,
    BranchListed,
    DropBranch,
    LastSwitch,
    ListTrial,
    PickBranches,
    TrialListed,
    TrialSaid,
)
from lup_dev.host.protocol import (
    Branches,
    Done,
    GitHubRepository,
    HostError,
    Listed,
    ListLaunches,
    Register,
    Talker,
    segment,
)
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Called, Recorded
from lup_dev.host.rooms import OwnLaunch, OwnLaunches, RoomRoute, ShowOwnLaunch
from lup_dev.host.service import (
    Answerer,
    Companion,
    HostService,
    Naming,
    Route,
    recorded_launches,
)
from lup_dev.host.timings import (
    ShowTimings,
    Summary,
    Timings,
    TimingsStore,
)
from lup_dev.host.timings import routes as timings_routes
from lup_dev.host.views import ModuleActions, ModuleViews
from lup_dev.host.watch import Changes
from lup_dev.host.workers import JudgeHook, WorkerJudge, Workers, WorkersAsking
from lup_dev.inbox.bearings import RepositoryBearings
from lup_dev.inbox.citations import plainly
from lup_dev.inbox.delivery import (
    Delivery,
    clocked,
    standing,
)
from lup_dev.inbox.marks import routes as marks_routes
from lup_dev.inbox.namesakes import NodeNames
from lup_dev.inbox.notices import NotifySend, Unsaid
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AnswerCheck,
    AnswerItem,
    CheckShown,
    Context,
    FinishItem,
    Items,
    ListInbox,
    Pathed,
    ReadInbox,
    Readout,
    SendItem,
    Settled,
    ShowCheck,
    ShowContext,
    ShowDiff,
    ShowItem,
    Shown,
    Whole,
)
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.reading import Flags, by_agent, counted, landed
from lup_dev.inbox.roster import ids
from lup_dev.inbox.store import (
    Answer,
    Approval,
    ChangedFile,
    Comment,
    Ended,
    Flagged,
    Friction,
    HeldChange,
    HowItFelt,
    InboxError,
    Item,
    Message,
    Question,
    Review,
    Ruling,
    Stop,
    Unresolved,
    Verdict,
    cited,
    item_number,
)
from lup_dev.inbox.texts import (
    ItemKind,
    opening,
    what,
)
from lup_dev.inbox.threaded import (
    DeclineThread,
    ReopenThread,
    SettleThread,
    ThreadStated,
)
from lup_dev.inbox.threaded import routes as threaded_routes
from lup_dev.inbox.tools import InboxTools
from lup_dev.inbox.typed import TypeReader
from lup_dev.launch.clis import CliCache
from lup_dev.launch.held import Holder, Writing, untraceable
from lup_dev.launch.hidden import removed
from lup_dev.launch.homes import LaunchHome
from lup_dev.launch.images import build
from lup_dev.launch.moving import MovingOver
from lup_dev.launch.room import (
    QRENCODE,
    Lent,
    OperatorsEditor,
    RoomClipboard,
    RoomEnvironments,
    RoomError,
    RoomPackageAge,
    cleared,
    host_needs,
    lend,
    lent,
    maintaining_room,
    qr_code,
    receiving,
    refreshed,
    related,
    room_git,
    unclaimed,
    unlent,
    vacated,
)
from lup_dev.launch.room import Repository as Found
from lup_dev.launch.room import repository as repository_of
from lup_dev.launch.secrets import RoomSecrets, Search, Tree, git_directory
from lup_dev.launch.session import (
    LaunchError,
    approved_declaration,
    hooked,
    terminal_settings,
)
from lup_dev.launch.spawning import SpawnTools
from lup_dev.launch.trial import TerminalRun, Trial, scratched, taken_over_there
from lup_dev.launch.trust import (
    Approving,
    Given,
    InboxApprovals,
    Outcome,
    Terminal,
    Unattended,
    machine_trust,
    trusted,
)
from lup_dev.layout import (
    CheckoutLayout,
    GitDirectoryLayout,
    HostLayout,
    HostPaths,
    InboxLayout,
    LaunchLayout,
    Layout,
    RoomPaths,
)
from lup_dev.listing import given, latest, many, moment, unlisted
from lup_dev.merging import Merging, gated_commit, merged
from lup_dev.migration import HostRuntime, Migrating
from lup_dev.policy.checkpoint import Bench, Services, Worktree
from lup_dev.policy.coming import Coming
from lup_dev.policy.flags import InboxFlagging
from lup_dev.policy.holds import (
    InboxAnnouncing,
    Response,
    answer,
    answer_unheard,
    said_answering,
)
from lup_dev.policy.importers import BackgroundSpawner
from lup_dev.policy.judge import finding
from lup_dev.policy.landing import (
    LandingTools,
    RoomAccepting,
    Turns,
    hosted_files,
    unapproved_files,
)
from lup_dev.policy.report import finding_lines
from lup_dev.policy.since import routes as since_routes
from lup_dev.policy.tools import JudgeTools, judge_call
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.policy.waits import Waits
from lup_dev.policy.waits import routes as waits_routes
from lup_dev.private.building import listed
from lup_dev.private.module import Private
from lup_dev.private.protocol import Scanned as Read
from lup_dev.private.protocol import Scanning, Sent
from lup_dev.private.scanning import UNAPPROVED, UNSELECTED
from lup_dev.private.scanning import scanned as read_for_values
from lup_dev.private.withheld import Facts, HostFacts, Withheld, kept
from lup_dev.remote.config import Gating
from lup_dev.remote.protocol import Remotes, Update
from lup_dev.remote.protocol import routes as remote_routes
from lup_dev.restoring import RestoreError, Restoring
from lup_dev.settings import LupDevSettings, TerminalVariables
from lup_dev.staging import Changed, Lines, StagingError
from lup_dev.stored import read_model, write_model
from lup_dev.switching import (
    CopiesAnswering,
    CopySwitch,
    Programs,
    Serving,
    Switch,
    Switched,
    Switching,
    host_starter,
    restore_detached,
)
from lup_dev.trial import named as in_sentence
from lup_dev.trying import (
    OwnViewsSaid,
    TrialAccepting,
    TrialChanging,
    TrialDropping,
    TrialListing,
    TrialPicking,
    Trying,
)
from lup_dev.worker import RepositoryModules, worked
from lup_ledger.parties import Conversation as InboxConversation
from lup_ledger.parties import Party
from lup_transcripts.environment import views

if TYPE_CHECKING:
    from lup.tools import serving
    from lup.tools.serving import Notice
    from lup.tools.tool import ToolSpec
    from lup_dev.declaration.resolve import Resolved
    from lup_dev.declaration.runner import Runner
    from lup_dev.host.rooms import RoomTools
    from lup_dev.host.workers import JudgeCalling, LaunchModules
    from lup_dev.policy.runtime import Runtime

# lup: defer(issue=114, why="`lup-dev` stands in for the `lup` command tree until the declaration and command line piece builds it, which names its commands")
app = typer.Typer(no_args_is_help=True, help="Develop a project with agents.")
rules = typer.Typer(no_args_is_help=True, help="lup's code rules.")
host = typer.Typer(help="lup's host service, which rooms call.")
inbox = typer.Typer(help="What your agents tell and ask you, and your answers.")
dashboard = typer.Typer()
private = typer.Typer(
    no_args_is_help=True,
    help="What never leaves under your name: the `Private` module's values.",
)
live = typer.Typer(
    help="What the host runs while it's on trial: `dev` and the branches picked."
)
account = typer.Typer(
    no_args_is_help=True,
    help="The accounts rooms log in with, each a login per runtime.",
)
app.add_typer(rules, name="rules")
app.add_typer(host, name="host")
app.add_typer(inbox, name="inbox")
app.add_typer(dashboard, name="dashboard")
app.add_typer(private, name="private")
app.add_typer(account, name="account")
app.add_typer(live, name="live")
spawn = typer.Typer(
    no_args_is_help=True,
    help=(
        "Sessions lup holds with no terminal, each its own launch: start one, "
        "interrupt it, end it, or try the whole of it once."
    ),
)
app.add_typer(spawn, name="spawn")


def engine(environments: Path | None = None) -> Checker:
    """Return the typed engine the judge asks about files, as this machine sets it, reading each worktree's environment among a launch's own `environments` where they're given."""
    return EngineChecker.configured(LupDevSettings(), environments)


def adapters() -> list[Adapter]:
    """List every runtime lup knows, each with what lup needs of its adapter."""
    return [
        # lup: ignore("runtime-mention", why="the one place listing the adapters")
        claude.adapter(),
        # lup: ignore("runtime-mention", why="the one place listing the adapters")
        codex.adapter(),
    ]


def recorded() -> dict[str, Recorded]:
    """Return each runtime's records on this machine, and how they're read, by its name."""
    return {
        adapter.runtime.name(): Recorded(records=adapter.records, reader=adapter.reader)
        for adapter in adapters()
    }


def runtimes() -> list[Runtime]:
    """List every runtime lup knows."""
    return [adapter.runtime for adapter in adapters()]


class Adapters(Model, Answerer):
    """Every runtime lup knows, answering its hooks: for `hook`, and for the host service where a launch's judge couldn't."""

    known: list[Adapter]

    @override
    def runtimes(self) -> list[str]:
        return [adapter.runtime.name() for adapter in self.known]

    def named(self, runtime: str) -> Adapter:
        """Return the adapter of the runtime named `runtime`, or say which lup knows."""
        chosen = [
            adapter for adapter in self.known if adapter.runtime.name() == runtime
        ]
        if not chosen:
            names = ", ".join(self.runtimes())
            message = f"no runtime named `{runtime}`; lup knows {names}"
            raise typer.BadParameter(message)
        [adapter] = chosen
        return adapter

    def answer(
        self,
        runtime: str,
        payload: str,
        services: Services,
        launch: Register | None = None,
    ) -> str:
        """Answer one of `runtime`'s hooks, judging with `services`, of `launch`'s room where one ran it (`Bench.launch`).

        What the hook prints is its adapter's output on a line, or nothing. A
        hold its call waits on gives up where the host service marks the hook
        ended, its runtime having ended it before its answer (`HostLayout.ended`).
        """
        adapter = self.named(runtime)
        ended = services.layout.host.ended(payload)
        bench = Bench(
            runtime=adapter.runtime, services=services, ended=ended, launch=launch
        )
        output = adapter.hook(payload, bench)
        return f"{output}\n" if output else ""

    async def called(self, calling: JudgeCalling, services: Services) -> serving.Answer:
        """Run a call to one of the judge's own tools that asks the engine, for a conversation of `calling`'s launch, judging with `services` as that launch's runtime's hooks are."""
        bench = Bench(
            runtime=self.named(calling.launch.runtime).runtime,
            services=services,
            launch=calling.launch,
        )
        return await judge_call(bench, calling)

    @override
    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        """Answer one of `runtime`'s hooks a launch's judge couldn't, as its adapter says it, on a line."""
        return f"{self.named(runtime).unanswered(payload, failure)}\n"


class SpawnRecords(Model, Spawns):
    """How every runtime lup knows recorded its subagents' spawns, as its adapter reads them, in the home the launch whose hook it is registered (`lup_dev.host.homes.translated`)."""

    adapters: Adapters

    @override
    def spawned(self, launch: Register, payload: str) -> Spawned | None:
        return self.adapters.named(launch.runtime).spawned(payload, launch)


class Couriers(Model, Courier):
    """Every runtime lup knows, as the host service reads its hooks and adds to their answers."""

    adapters: Adapters

    @override
    def heard(self, runtime: str, payload: str) -> Heard:
        return self.adapters.named(runtime).heard(payload)

    @override
    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        """Return what one of `runtime`'s hooks prints: its adapter's answer with `telling` added, on a line, or `answer` as it is."""
        added = self.adapters.named(runtime).told(payload, answer, telling)
        return answer if added is None else f"{added}\n"


class Wakers(Model, Waker):
    """Every runtime lup knows, as its idle sessions are woken."""

    adapters: Adapters

    @override
    def woken(self, runtime: str, session: str, text: str) -> str | None:
        spelled = self.adapters.named(runtime).woken
        return None if spelled is None else spelled(session, text)

    @override
    def pushed(self, runtime: str, text: str, token: str) -> Notice | None:
        pushing = self.adapters.named(runtime).pushing
        return None if pushing is None else pushing.notice(text, token)

    @override
    def capabilities(self, runtime: str) -> dict[str, JsonObject]:
        pushing = self.adapters.named(runtime).pushing
        return {} if pushing is None else pushing.capabilities

    def held(self, runtime: str, text: str, token: str) -> str | None:
        """Return the user turn that starts an idle held session of `runtime` on `text`, carrying `token`; none where it has no held session (`Holders.prompt`)."""
        holding = self.adapters.named(runtime).holding
        return None if holding is None else holding.prompt(text, token)


def services(environments: Path | None = None) -> Services:
    """Return what judging reaches, as configured on this machine.

    `environments` are a launch's own, where the hooks judged are of a room that
    has them: the engine reads each worktree's environment there, and so does
    the importers pass a checkpoint starts (`docs/launch.md`, *The project's
    environment, the room's own*).
    """
    settings = LupDevSettings()
    host = Layout.of(settings).host
    return Services(
        checker=engine(environments),
        linter=Ruff(),
        clock=SystemClock(),
        layout=Layout.of(settings),
        spawner=BackgroundSpawner(environments=environments),
        announcing=InboxAnnouncing(layout=host, clock=SystemClock()),
        flagging=InboxFlagging(layout=host, clock=SystemClock()),
        facts=HostFacts(),
    )


def toplevel(directory: Path) -> Path:
    """Return the root of the git worktree holding `directory`."""
    return Path(Git(cwd=directory).text("rev-parse", "--show-toplevel"))


def branch_name(worktree: Path, listed: Checkout | None = None) -> str:
    """Return a launch's name by default: the branch the worktree at `worktree` has checked out, as its repository lists it (`listed`) where it's given, in a name's shape (`feat/x` is `feat-x`), or the worktree's directory's where none is."""
    if listed is not None:
        branch = (listed.branch or "").removeprefix("refs/heads/")
        return shaped(branch) or shaped(worktree.name) or "session"
    found = Git(cwd=worktree).run("symbolic-ref", "--short", "-q", "HEAD", ok=[0, 1])
    branch = found.output.decode().strip() if found.status == 0 else ""
    return shaped(branch) or shaped(worktree.name) or "session"


def addressed(launches: list[Register], to: str) -> list[Register]:
    """Return the launches `to` names: by id, else by name, else those whose worktree holds the path it is."""
    by_id = [each for each in launches if each.launch == to]
    if by_id:
        return by_id
    by_name = [each for each in launches if each.name == to]
    if by_name:
        return by_name
    place = Path(to).expanduser().resolve()
    return [each for each in launches if place.is_relative_to(each.worktree)]


@app.command("hook")
def hook(
    runtime: Annotated[
        str, typer.Argument(help="The runtime whose hook this is, by its name.")
    ],
) -> None:
    """Answer one of a runtime's hooks, its payload on stdin, as a repository's process answers each hook its judge reads."""
    known = Adapters(known=adapters())
    # An unknown runtime is refused before standard input is read.
    known.named(runtime)
    typer.echo(known.answer(runtime, sys.stdin.read(), services()), nl=False)


def host_client() -> HostClient:
    """Return the host service's client, as this machine places the service, the copy approved being what it starts."""
    layout = Layout.of(LupDevSettings())
    return HostClient(
        layout=layout.host, clock=SystemClock(), starter=host_starter(layout)
    )


def installed_dashboard(
    settings: LupDevSettings, layout: HostLayout
) -> DashboardProcess | None:
    """Return the dashboard the host service runs, where its command is installed beside the interpreter running it; none where it isn't."""
    command = Path(sys.executable).parent / "lup-dashboard"
    if not command.is_file():
        return None
    return DashboardProcess(
        command=[str(command), "serve"],
        port=settings.lup_dashboard_port,
        addresses=settings.lup_dashboard_addresses,
        token=layout.dashboard_token,
    )


def dashboard_shown(dashboard: DashboardProcess | None) -> Showing:
    """Answer the operator's `lup-dev dashboard` with `dashboard`'s address, or why there's none."""
    return Showing(
        dashboard=dashboard,
        missing=(
            f"the dashboard isn't installed beside this lup-dev: no `lup-dashboard` "
            f"in {Path(sys.executable).parent}, which lup's own approval installs"
        ),
    )


def control_routes(
    delivery: Delivery,
    recorded: dict[str, Recorded],
    dashboard: DashboardProcess | None,
    layout: Layout,
    views: ModuleViews | None = None,
    *,
    waits: Waits,
    trying: Trying | None = None,
    landing: LandingTools | None = None,
) -> list[Route]:
    """Route the kinds the core registers on the control socket, beside the service's own: the inbox's, over `delivery`, an item's moment read from `recorded`; the dashboard's, `dashboard`'s address; the drawer's, what a branch changed since the operator approved it, read from lup's state at `layout`, each file a landing waits on in `waits` held there; the landings waiting; the review marks, as `delivery`'s inbox holds them; the review's threads; what a page measured of itself, kept in lup's state; a module's view the dashboard shows, through `views`, watched at its own triggers, and its actions, where it's given; and what's on trial, moved through `trying` and accepted through `landing`, where they're given."""
    return [
        *inbox_routes(delivery, recorded),
        Route.to(dashboard_shown(dashboard)),
        *since_routes(delivery, layout, waits),
        *waits_routes(waits),
        *marks_routes(delivery.inbox.marks, delivery.clock, delivery.inbox.changes),
        *threaded_routes(delivery),
        *timings_routes(TimingsStore(home=layout.host.timings), delivery.clock),
        *(
            []
            if views is None
            else [
                Route.reading(views, watch=views.watched),
                Route.to(ModuleActions(asking=views.asking, changes=views.changes)),
            ]
        ),
        Route.to(CopiesAnswering(layout=layout)),
        Route.to(CopySwitch(layout=layout, start=restore_detached(layout))),
        *([] if trying is None else trial_routes(trying, delivery, landing)),
    ]


def launcher_started(spec: HeldLaunch, log: Path) -> Apart:
    """Start a held launch's launcher from the `lup-dev` the service runs, in its worktree, what it prints in its launch's log, apart from the service."""
    program, *rest = launcher_command(own_command(), spec)
    return detached(program, *rest, log=log, cwd=spec.worktree)


def held_routes(
    layout: Layout,
    holders: Holders,
    launchers: Launchers,
    delivery: Delivery | None = None,
) -> list[Route]:
    """Route what the operator asks of sessions held with no terminal, and their launchers' word that one is up, which gives the session what waits for it through `delivery`, where it's given (`lup_dev.host.held`)."""

    async def up(called: CalledUp) -> None:
        launch = recorded_launch(layout.host, called.launch)
        if delivery is not None and launch is not None:
            await delivery.called_up(launch, called.session)

    return [
        Route.to(Spawning(layout=layout, launchers=launchers, start=launcher_started)),
        Route.to(Awaiting(layout=layout, launchers=launchers)),
        Route.to(Abandoning(launchers=launchers)),
        Route.to(CallingUp(launchers=launchers, up=up, say=typer.echo)),
        Route.to(HeldInterrupting(holders=holders)),
        Route.to(HeldEnding(holders=holders)),
    ]


def recorded_launch(layout: HostLayout, launch: str) -> Register | None:
    """Return launch `launch` as the service recorded it; none where it isn't served, or its record doesn't read."""
    return next(
        (each for each in recorded_launches(layout) if each.launch == launch), None
    )


def trial_routes(
    trying: Trying, delivery: Delivery, landing: LandingTools | None
) -> list[Route]:
    """Route what the operator asks of what's on trial, through `trying`, accepting through `landing`, where it's given."""
    return [
        Route.to(TrialListing(trying=trying)),
        Route.to(TrialPicking(trying=trying)),
        Route.to(TrialChanging(trying=trying)),
        Route.to(TrialDropping(trying=trying, delivery=delivery)),
        *(
            []
            if landing is None
            else [
                Route.to(
                    TrialAccepting(
                        trying=trying,
                        tools=RoomAccepting(tools=landing),
                        changes=delivery.inbox.changes,
                    )
                )
            ]
        ),
    ]


@host.callback(invoke_without_command=True)
def host_serve(context: typer.Context) -> None:
    """Run the host service in the foreground, until it's stopped.

    It answers each launch's hooks as `lup-dev hook` does, on the launch's own
    socket, through its repository's process of the repository's approved copy,
    and ends each launch whose launcher and container are both gone
    (`Sweeping`). `lup-dev host stop` or Ctrl-C stops it; the launches it serves
    stay recorded, and the next service serves them.

    Tried on a state of its own (`LupDevSettings.lup_host_rehearsing`), it raises
    no notice, wakes no thread parked in the ledger it copied, and reads no
    approval's types, so nothing it does reaches past that state.
    """
    if context.invoked_subcommand is not None:
        return
    known = Adapters(known=adapters())
    couriers = Couriers(adapters=known)
    wakers = Wakers(adapters=known)
    settings = LupDevSettings()
    rehearsing = settings.lup_host_rehearsing
    layout = Layout.of(settings)
    changes = Changes()
    pushes = Pushes()
    holders = Holders(layout=layout, prompt=wakers.held)
    launchers = Launchers()
    dashboard = installed_dashboard(settings, layout.host)
    delivery = Delivery(
        inbox=inbox_opened(layout, changes, typer.echo),
        waker=wakers,
        pushes=pushes,
        holders=holders,
        layout=layout.host,
        notices=Unsaid() if rehearsing else NotifySend(),
        clock=SystemClock(),
        say=typer.echo,
        settle_hold=lambda change, approved, said: hold_answered(
            layout, change, approved=approved, comment=said
        ),
        hold_unheard=lambda change: hold_unheard(layout, change),
        queues={
            adapter.runtime.name(): adapter.queues
            for adapter in known.known
            if adapter.queues is not None
        },
    )
    holders.interrupted = delivery.interrupted
    types = TypeReader(delivery=delivery, read=typed_reading, say=typer.echo)
    podman = Podman()
    workers = Workers(
        layout=layout.host,
        say=typer.echo,
        approval=partial(approval_of, layout),
        approved=partial(approved_command, layout),
    )
    asking = WorkersAsking(workers=workers)
    coming = Coming(delivery=delivery, layout=layout, say=typer.echo)
    delivery.starting = coming.started
    spawning = spawn_tools(delivery, layout, launchers, known)

    async def reap() -> None:
        for each in launchers.reaped():
            await spawning.lost(each)

    sweeping = Sweeping(
        layout=layout,
        host=host_client(),
        podman=podman,
        say=typer.echo,
        running=workers.commands,
        coming=None if rehearsing else coming,
        reap=reap,
        rewake=delivery.rewoken,
    )
    turns = Turns()
    trying = Trying(
        layout=layout,
        clock=delivery.clock,
        say=typer.echo,
        turns=turns,
        fingerprint=zone_fingerprint,
        propose=proposed_for,
        start=restore_detached(layout),
    )
    remotes = host_remotes(
        delivery, layout, coming, workers, EngineParser(), trying=trying
    )
    waits = Waits(changes=changes)
    delivery.landing = waits.holding
    landing = LandingTools(
        delivery=delivery,
        remotes=remotes,
        layout=layout,
        waits=waits,
        coming=coming,
        turns=turns,
    )
    service = HostService(
        layout=layout.host,
        answerer=known,
        courier=couriers,
        judge=WorkerJudge(modules=workers),
        spawns=SpawnRecords(adapters=known),
        operators={name: each.records for name, each in recorded().items()},
        post=delivery,
        bearings=RepositoryBearings(
            delivery=delivery, running=partial(running_branch, layout)
        ),
        namesakes=NodeNames(delivery=delivery),
        routes=[
            *control_routes(
                delivery,
                recorded(),
                dashboard,
                layout,
                ModuleViews(asking=asking, changes=changes, say=typer.echo),
                waits=waits,
                trying=trying,
                landing=landing,
            ),
            *held_routes(layout, holders, launchers, delivery),
        ],
        tools=room_tools(delivery, layout, workers, landing=landing, spawning=spawning),
        room_routes=[
            *remote_routes(remotes),
            *clipboard_routes(Desktop.of(settings)),
            RoomRoute.to(OwnLaunches()),
            RoomRoute.to(
                Copying(
                    layout=layout, ledger=delivery.inbox.ledger, recorded=recorded()
                )
            ),
        ],
        modules=workers,
        asking=asking,
        standing=resolve(Project()).looks,
        say=typer.echo,
        refresh=lambda launch: refreshed(layout.launch(launch.launch)),
        podman=podman,
        changes=changes,
        waker=wakers,
        pushes=pushes,
        holders=holders,
        ended=delivery.closed,
        companions=[
            *(
                []
                if rehearsing
                else [
                    types,
                    OwnViewsSaid(
                        layout=layout, asking=asking, changes=changes, say=typer.echo
                    ),
                ]
            ),
            sweeping,
            *([] if dashboard is None else [dashboard]),
        ],
    )
    asyncio.run(service.serve())


def approval_of(layout: Layout, repository: Path) -> str | None:
    """Return what the operator approved last for the repository at `repository`, by its fingerprint; none before the first approval."""
    approval = approved(layout, repository)
    return None if approval is None else approval.fingerprint


def running_branch(layout: Layout, repository: Path) -> str:
    """Return the branch work lands on in the repository at `repository`, as the declaration approved for it names it; `dev` before the first approval."""
    return approved_branches(layout, repository).running


def approved_command(layout: Layout, repository: Path) -> Path | None:
    """Return the command of the copy approved for the repository at `repository`, which a request put with no launch starts its process from; none before the first approval."""
    approval = approved(layout, repository)
    if approval is None:
        return None
    return layout.judge(repository).command(approval.tool.name)


def typed_reading(
    approval: Approval, worktree: Path, files: list[ChangedFile]
) -> list[ChangedFile]:
    """Read an approval's files wholly, types and lup's rules included, as trust in the worktree it was asked from reads them, on this machine (`Trust.typed`)."""
    return machine_trust(worktree, []).typed(approval.repository, files)


def approval_reading(git: Git, branches: Branches, main: Path) -> Path:
    """Return the worktree a push's approval has its types read in: the checkout of the running branch, whose tip it's about; else of the integration branch, what that branch is made from, as `live` may have none; else `main`, the repository's main worktree."""
    return git.checkout(branches.running) or git.checkout(branches.integration) or main


def host_remotes(
    delivery: Delivery,
    layout: Layout,
    coming: Coming,
    modules: LaunchModules,
    parser: Parser,
    *,
    trying: Trying | None = None,
) -> Remotes:
    """Return git on the host for each launch's room: each push held to what the operator approved of what it lands (`unapproved_files`), each file read from its parse alone by `parser`, put to `modules`, told to what follows a push (`after_push`), and kept off what the host computes, what `trying` moves (`computing`, `hosted_files`)."""
    return Remotes(
        say=typer.echo,
        landed=partial(after_push, delivery, coming, trying=trying),
        asking=partial(unapproved_files, delivery, layout, parser=parser),
        trying=partial(computing, layout),
        hosted=partial(hosted_files, layout),
        modules=modules,
    )


def computing(layout: Layout, launch: Register) -> Branches | None:
    """Return the branches of `launch`'s repository where it computes its running branch, as the declaration approved names them; none where it doesn't (`Remotes.trying`)."""
    branches = approved_branches(layout, launch.repository)
    return None if branches.running == branches.integration else branches


def zone_fingerprint(repository: Path, commit: str) -> str:
    """Return the fingerprint of the host zone at `commit` in the repository at `repository`, reading no code of it (`Trust.zone_at`)."""
    root = Git.pinned(repository).main_worktree()
    trust = machine_trust(root, [])
    return trust.fingerprint(trust.zone_at(commit))


def proposed_for(repository: Path) -> int | None:
    """Put the approval of the running branch's tip in the repository at `repository` in the operator's inbox where it isn't what's approved, as a push moving it does, and return its number (`Trust.proposed`, `proposed_after`)."""
    git = Git.pinned(repository)
    root = git.main_worktree()
    branches = approved_branches(Layout.of(LupDevSettings()), repository)
    return machine_trust(root, [], approval_reading(git, branches, root)).proposed()


async def after_push(
    delivery: Delivery,
    coming: Coming,
    launch: Register,
    updates: list[Update],
    *,
    trying: Trying | None = None,
) -> None:
    """Once a launch's push updated `updates`: put the approval of the host zone at the running branch's tip in the operator's inbox where it moved there (`proposed_after`), wake each thread parked until a commit it brings (`Coming.pushed`), and where it moved the integration branch of a project computing its running branch, compute that again (`Trying.moved_dev`), what fails being said in the service's log, as the push stands."""
    refs = [each.destination for each in updates]
    await proposed_after(delivery, launch, refs)
    await coming.pushed(launch, updates)
    branches = approved_branches(Layout.of(LupDevSettings()), launch.repository)
    if trying is None or branches.integration_ref not in refs:
        return
    try:
        moved = await trying.moved_dev(launch.repository)
    except (LupDevError, LupError) as failure:
        typer.echo(
            f"{launch.launch}: the push moved {branches.integration}, but "
            f"{branches.running} wasn't computed again: {failure}"
        )
        return
    for line in moved:
        typer.echo(f"{launch.launch}: {line}")


async def proposed_after(delivery: Delivery, launch: Register, refs: list[str]) -> None:
    """Put the approval of the host zone at the running branch's tip in the operator's inbox, where a launch's push moved that branch and the zone isn't the one approved.

    Trust reads the zone with git and asks the service itself, so it runs off
    the event loop. Its repository is the launch's git directory, found
    through git from its main worktree; one holding a `commondir`, which would
    lead git elsewhere, isn't read (`docs/credentials.md`, *Running git on the
    host*). That main worktree is a bare repository's own directory, where
    lup's own is laid out so, which holds no project to read types in, so the
    approval's are read in a checkout (`approval_reading`), while trust's git
    stays where it is, out of a worktree the room can aim at a `config` of its
    own. The approval names the main conversation of the session the launch
    runs, as `delivery` last heard it, which the operator's comment on their
    answer is told to: a push comes from the room's git, not from a call, so
    which of the session's conversations pushed isn't known. What fails is said
    in the service's log, and the push stands.
    """
    branches = approved_branches(Layout.of(LupDevSettings()), launch.repository)
    running = branches.running
    if branches.running_ref not in refs:
        return
    if (launch.repository / "commondir").exists():
        typer.echo(
            f"{launch.launch}: the push moved {running}, but its approval "
            f"wasn't asked: {launch.repository} holds a `commondir`, which would "
            "lead git to another repository"
        )
        return
    git = Git.pinned(launch.repository)
    root = git.main_worktree()
    pushed_by = delivery.running(launch.launch)
    try:
        trust = machine_trust(root, [], approval_reading(git, branches, root))
        number = await asyncio.to_thread(trust.proposed, pushed_by)
    except (LupDevError, LupError) as failure:
        typer.echo(
            f"{launch.launch}: the push moved {running}, but its approval "
            f"wasn't asked: {failure}"
        )
        return
    if number is not None:
        typer.echo(
            f"{launch.launch}: the push moved {running}, and with it the code "
            f"the host runs: approval {cited(number)} is in the inbox"
        )


def room_tools(
    delivery: Delivery,
    layout: Layout,
    modules: LaunchModules,
    *,
    landing: LandingTools,
    spawning: SpawnTools,
) -> list[RoomTools]:
    """List the core's tools the host service serves each launched session: the inbox's; the judge's, reading lup's state at `layout` by the delivery's clock, and running `quiet` in each launch's repository's process (`modules`); `landing`'s, `land`; and `spawning`'s, `spawn`."""
    return [
        InboxTools(delivery=delivery),
        JudgeTools(layout=layout, clock=delivery.clock, modules=modules),
        landing,
        spawning,
    ]


def spawn_tools(
    delivery: Delivery, layout: Layout, launchers: Launchers, known: Adapters
) -> SpawnTools:
    """Return the `spawn` tool as the service serves it: launchers started as `lup-dev spawn`'s are, among `launchers`; the launches served read from their records; a session's id minted by its runtime's adapter, where it has a held session; and a worktree started from the integration branch the declaration approved for its repository names."""

    def mint(runtime: str) -> str | None:
        held = next(
            (
                each.holding
                for each in known.known
                if each.runtime.name() == runtime and each.holding is not None
            ),
            None,
        )
        return None if held is None else held.minted()

    return SpawnTools(
        delivery=delivery,
        layout=layout,
        spawning=Spawning(layout=layout, launchers=launchers, start=launcher_started),
        launchers=launchers,
        served=lambda: recorded_launches(layout.host),
        mint=mint,
        starting=lambda repository: approved_branches(layout, repository).integration,
    )


def served_tools(resolved: Resolved) -> list[ToolSpec]:
    """List what a launched session is told of each of lup's tools, which their guidance lists: the core's, then its modules'.

    The core's are read from the tools the service is handed, made over a
    delivery with nothing but its clock, and a layout, remotes and repositories'
    processes without their fields: what a tool is doesn't depend on whom it
    delivers to, where lup's state is, how it pushes, or where it runs. The
    modules' are read from their classes, with no instance.
    """
    unread = Delivery.model_construct(clock=SystemClock())
    core = [
        spec
        for tools in room_tools(
            unread,
            Layout.model_construct(),
            Workers.model_construct(),
            landing=LandingTools.model_construct(),
            spawning=SpawnTools.model_construct(),
        )
        for spec in tools.specs()
    ]
    naming = Naming.model_construct().specs()
    modules = [spec for each in resolved.served for spec in module_tools(each.serving)]
    return [*core, *naming, *modules]


@app.command("worker", hidden=True)
def worker(
    socket: Annotated[Path, typer.Argument(help="Where to answer the host service.")],
    repository: Annotated[
        Path, typer.Argument(help="The git directory of the repository served.")
    ],
) -> None:
    """Serve the judge and the modules of `repository`'s launches on `socket`, until standard input closes: for the host service.

    Their hooks are answered as `hook` answers them, and the judge's own tools
    that ask the engine run, with this machine's services made for each: none of
    them keeps state of its own, and each reads the environments of the launch
    asking, where its room has its own, and a path a hook names in that
    launch's home alone (`Bench.launch`).
    """
    known = Adapters(known=adapters())

    def judged(hook: JudgeHook) -> str:
        return known.answer(
            hook.runtime, hook.payload, services(hook.environments), hook.launch
        )

    async def called(calling: JudgeCalling) -> serving.Answer:
        return await known.called(calling, services(calling.launch.environments))

    worked(
        socket,
        repository,
        services(),
        recorded(),
        judge=judged,
        called=called,
    )


@host.command("stop")
def host_stop() -> None:
    """Stop the host service, if one runs."""
    if host_client().stop():
        typer.echo("Stopped the host service.")
        return
    typer.echo("No host service runs.")


def answering(what: str = "the inbox") -> HostClient:
    """Reach the host service for the operator's `what`, starting it where none runs; refuse inside an agent's session."""
    inside = [runtime.name() for runtime in runtimes() if runtime.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session, and {what} is the "
            "operator's: run it in your own terminal"
        )
        raise InboxError(message)
    client = host_client()
    client.ensure()
    return client


def reading() -> HostClient | FromRoom:
    """Reach the host service for what only reads lup's state: from a room, on its launch's request socket, for its repository alone; on the host, from any terminal, an agent's session's too.

    The service is started only outside every agent's session: one started from
    an agent's shell would run on in that shell's environment.
    """
    room = RoomClient()
    if room.socket.exists():
        return FromRoom(room=room)
    client = host_client()
    if not any(runtime.inside() for runtime in runtimes()):
        client.ensure()
        return client
    if not client.answers():
        message = (
            "no host service runs, and none is started from an agent's session: a "
            "launch starts it, or the operator's own `lup-dev` in their terminal"
        )
        raise HostError(message)
    return client


def line(
    entry: Item | Flags,
    paths: Sequence[Pathed] = (),
    landings: Mapping[int, str] | None = None,
) -> str:
    """Say an item in a line: its number, when it was made, what it is, from whom (by its name, where `paths` gives it) and, for a copy of a message between conversations, to whom, and its first line; for an approval, how to read it whole and answer it. A conversation's flagged writes are one line: each number, the latest's time, how many, how many files on which branches (`Flags`), and each landing waiting on them, as `landings` names it by flag."""
    if isinstance(entry, Flags):
        last = entry.items[-1]
        where = "" if last.worktree is None else f" in {last.worktree}"
        waiting = landings or {}
        held = landed([waiting.get(each.number) for each in entry.items])
        return (
            f"{entry.cited():>5}  {clocked(entry.made)}  "
            f"{many(len(entry.items), 'flagged write')} from "
            f"{called(entry.sender, paths)}{where}: {entry.said()}{held}"
        )
    item = entry
    where = "" if item.worktree is None else f" in {item.worktree}"
    reading = (
        f" (`answer {item.number}` shows its summary, offers its whole diff, and "
        f"asks; `show {item.number} --diff` pages the diff alone)"
        if isinstance(item.reason, Approval)
        else ""
    )
    match item.reason:
        case Message(to=InboxConversation() as to):
            between = f" to {called(to, paths)}"
        case _:
            between = ""
    return (
        f"{cited(item.number):>5}  {clocked(item.made)}  {what(item)} from "
        f"{called(item.sender, paths)}{between}{where}: "
        f"{opening(item)}{reading}"
    )


def called(party: Party, paths: Sequence[Pathed]) -> str:
    """Say who `party` is, as lup names them: the operator; a conversation by their path among `paths`, their runtime's ids beside it where another shares the path (`Pathed`), else by those ids."""
    match party:
        case InboxConversation():
            found = next((each for each in paths if each.conversation == party), None)
            if found is None:
                return ids(party)
            return (
                f"`{found.path}` ({ids(party)})" if found.alike else f"`{found.path}`"
            )
        case _:
            return "the operator"


def settled(*, approved: bool) -> str:
    """Say an approval's answer in a word."""
    return "approved" if approved else "declined"


def heading(item: Item, paths: Sequence[Pathed] = ()) -> str:
    """Say what an item is, whose to whom, each by its name where `paths` gives it, when it was made and where it stands: a copy of a message between conversations to the conversation it was sent to."""
    where = "" if item.worktree is None else f" in {item.worktree}"
    match item.reason:
        case Message(to=InboxConversation() as to):
            recipient = f"{called(to, paths)}, your copy"
        case _:
            recipient = called(item.recipient, paths)
    return (
        f"{cited(item.number)}, {what(item)} from {called(item.sender, paths)}{where} to "
        f"{recipient}, made {clocked(item.made)}, {standing(item)}:"
    )


def hold_answered(
    layout: Layout, change: HeldChange, *, approved: bool, comment: str
) -> str | None:
    """Write the operator's answer to a held change where its hook waits for it, and return what to tell the conversation that made it where no call waits to hear it; a hold at landing has no hook, its answer its item's own state."""
    if change.key is None:
        return None
    hold = answer(
        layout,
        change.key,
        Response(approved=approved, comment=comment),
        runtimes(),
        SystemClock(),
        worktree=change.worktree,
        telling=True,
    )
    return said_answering(layout, hold) if hold.told else None


def hold_unheard(layout: Layout, change: HeldChange) -> str | None:
    """Return what to tell the conversation that made a held change answered already, where nothing told them (`answer_unheard`); none else, as for a hold at landing."""
    if change.key is None:
        return None
    return answer_unheard(layout, change.worktree, change.key)


def shown(item: Item, paths: Sequence[Pathed] = ()) -> str:
    """Say an item whole, for the operator, each conversation by their name where `paths` gives it: an approval by its summary, its whole diff on request."""
    match item.reason:
        case (
            Message(text=text)
            | Friction(text=text)
            | HowItFelt(text=text)
            | Stop(text=text)
            | Ended(text=text)
        ):
            body = [text]
        case Unresolved(of=of, citations=citations):
            body = [plainly(citations, of)]
        case Question(text=text, decisions=decisions):
            numbered = [
                f"{number}. {decision.text}\n   Its lean: {decision.lean}"
                for number, decision in enumerate(decisions, start=1)
            ]
            body = [text, *numbered]
        case Answer(question=question, rulings=rulings, comment=comment):
            decided = [
                f"{each.decision}. {each.verdict or 'in words'}"
                + (f": {each.comment}" if each.comment else "")
                for each in rulings
            ]
            body = [f"To {cited(question)}.", *decided, comment]
        case (
            Approval(text=text, summary=summary)
            | HeldChange(text=text, summary=summary)
            | Flagged(text=text, summary=summary)
        ):
            body = [
                summary,
                "",
                text,
                f"The whole diff: `lup-dev inbox show {item.number} --diff`.",
            ]
        case Review(covers=covers, comments=comments, letters=letters):
            numbers = ", ".join(cited(each) for each in covers)
            body = [
                *([f"Of {numbers}."] if covers else []),
                *(
                    f"To {called(each.to, paths)}: {each.text}"
                    for each in letters
                    if each.to is not None
                ),
                *(commented(each) for each in comments),
            ]
    return "\n".join([heading(item, paths), *body])


def commented(comment: Comment) -> str:
    """Say one comment of a review, for the operator: where it's on, then what it says."""
    if comment.quote is None:
        return f"On {cited(comment.item)}: {comment.text}"
    return f'On {cited(comment.item)}, "{comment.quote.text}": {comment.text}'


def ruling(decision: int) -> Ruling:
    """Ask the operator their answer to decision `decision`: a verdict, then what they add if anything; or their answer in their own words.

    Nothing is taken for an answer: an empty line asks again, so going with
    the agent's lean is said, never assumed.
    """
    said = typer.prompt(
        f"{decision}: leaning, undecided, leave open, or your answer in words"
    )
    try:
        chosen = TypeAdapter[Verdict](Verdict).validate_python(said)
    except ValidationError:
        return Ruling(decision=decision, comment=said)
    comment = typer.prompt(
        f"{decision}: a comment (optional)", default="", show_default=False
    )
    return Ruling(decision=decision, verdict=chosen, comment=comment)


def prompted(item: Item, paths: Sequence[Pathed]) -> AnswerItem:
    """Ask the operator their answer to a question, each decision in turn, then a comment on the whole; a plain question, or a reply to a message, in words."""
    typer.echo(shown(item, paths))
    match item.reason:
        case Message() | Friction() | HowItFelt() | Stop() | Flagged():
            words = typer.prompt("Your reply")
            return AnswerItem(number=item.number, comment=words)
        case Question(decisions=[]):
            words = typer.prompt("Your answer")
            return AnswerItem(number=item.number, comment=words)
        case Question(decisions=decisions):
            rulings = [ruling(decision) for decision in range(1, len(decisions) + 1)]
            whole = typer.prompt(
                "A comment on the whole (optional)", default="", show_default=False
            )
            return AnswerItem(number=item.number, rulings=rulings, comment=whole)
        case _:
            message = f"{cited(item.number)} is {what(item)}: nothing to answer"
            raise InboxError(message)


@app.command("sessions")
def sessions(
    *,
    every: Annotated[
        bool,
        typer.Option(
            "--all", help="List each ended subagent too, rather than counting them."
        ),
    ] = False,
) -> None:
    """List the sessions the host service serves, each with their subagents under them.

    Each launch by its name, its runtime, its worktree, its id, and its
    container, running or not as podman has it; under it, its session and each
    subagent beneath the conversation who spawned them, by their path
    (`dev/explore-auth`) and their kind; an unnamed one by their kind and their id,
    until they name themselves. The subagents that ended under a conversation are
    counted, as the dashboard folds them; `--all` lists them, each said ended.
    It only reads, so an agent's session runs it too: on the host, listing
    every launch; in a room, its repository's alone, whose containers the host
    service says run, since a room has no podman.
    """
    listed = reading().ask(ListLaunches(), Listed)
    if not listed.launches:
        typer.echo("No session runs.")
        return
    podman = Podman()

    def running(launch: Register) -> bool:
        container = launch.container
        return (
            listed.running.get(launch.launch, False)
            if listed.running is not None
            else container is not None and podman.exists(container)
        )

    for line in served_lines(listed, running, every=every):
        typer.echo(line)


def served_lines(
    listed: Listed, running: Callable[[Register], bool], *, every: bool
) -> Iterator[str]:
    """Yield `lup-dev sessions`' lines: each launch, its conversations under it (`conversations`), and each launch an agent of it spawned through lup under those, set in, saying who spawned it and how; a launch whose spawner's launch isn't served where it would be at the top."""
    served = {each.launch: each for each in listed.launches}

    def above(launch: Register) -> str | None:
        spawner = launch.spawner
        return (
            None if spawner is None or spawner.launch not in served else spawner.launch
        )

    def spawned(launch: Register) -> str:
        spawner = launch.spawner
        if spawner is None:
            return ""
        by = spawner.conversation
        path = next(
            (
                each.path
                for each in listed.talkers.get(spawner.launch, [])
                if each.session == by.session and each.agent == by.agent
            ),
            by.session,
        )
        kind = "a side job" if spawner.concern is None else "handed a concern"
        return f"  spawned by `{path}`, {kind}"

    def shown(launch: Register, depth: int) -> Iterator[str]:
        set_in = "    " * depth
        yield (
            f"{set_in}`{launch.name}`  {launch.runtime} in {launch.worktree}  "
            f"({launch.launch})  container {launch.container}, "
            f"{'running' if running(launch) else 'not running'}{spawned(launch)}"
        )
        talkers = listed.talkers.get(launch.launch, [])
        yield from (f"{set_in}{line}" for line in conversations(talkers, every=every))
        for each in listed.launches:
            if above(each) == launch.launch:
                yield from shown(each, depth + 1)

    for each in listed.launches:
        if above(each) is None:
            yield from shown(each, 0)


def conversations(talkers: list[Talker], *, every: bool) -> list[str]:
    """Return a launch's conversations as `lup-dev sessions` lists them: each under the one who spawned them, by their path and their kind.

    The subagents over under a conversation are counted after those that
    aren't, unless `every`, which lists them in their place, each said ended.
    A subagent is over where they ended, or where nothing they did is kept, as
    from before the host kept it: as the dashboard folds them (`over`,
    `agents.ts`).
    """

    def over(talker: Talker) -> bool:
        activity = talker.activity
        return talker.agent is not None and (
            activity is None or activity.state == "ended"
        )

    def shown(talker: Talker, depth: int) -> list[str]:
        kind = "" if talker.kind is None else f"  {talker.kind}"
        ended = "  ended" if over(talker) else ""
        children = [each for each in talkers if each.parent == talker.path]
        listed = children if every else [each for each in children if not over(each)]
        folded = len(children) - len(listed)
        counted = f"{'  ' * (depth + 1)}{folded} ended, which `--all` lists"
        return [
            f"{'  ' * depth}{talker.path}{kind}{ended}",
            *(line for each in listed for line in shown(each, depth + 1)),
            *([counted] if folded else []),
        ]

    return [line for each in talkers if each.parent is None for line in shown(each, 1)]


@dashboard.callback(invoke_without_command=True)
def dashboard_open(
    context: typer.Context,
    *,
    opened: Annotated[
        bool,
        typer.Option(
            "--open/--no-open",
            help="Open it in your browser, or only print where it is.",
        ),
    ] = True,
    address: Annotated[
        str | None,
        typer.Option(
            help=(
                "Which of the addresses the dashboard listens on to print: by "
                "default the first beyond localhost where `LUP_DASHBOARD_ADDRESSES` "
                "names one, since that's what another device needs."
            )
        ),
    ] = None,
    copies: Annotated[
        bool,
        typer.Option(
            "--copies",
            help=(
                "Open the plain page, what runs and the copies kept, with nothing of "
                "the review's: for when the review itself is broken."
            ),
        ),
    ] = False,
) -> None:
    """Open the dashboard: every agent, what each is doing, and your inbox, in one page.

    Run it yourself, in your own terminal. It prints the dashboard's address, its
    token after the `#`, and opens it in your browser on localhost; the host
    service runs the dashboard, starting it again where it's gone. Where the
    dashboard listens on an address of this machine's beyond localhost, as its
    WireGuard one (`LUP_DASHBOARD_ADDRESSES`), it prints that address instead,
    drawn as a QR code for your phone to scan where `qrencode` is installed:
    the page, opened once, keeps the token as its cookie. `--copies` opens the
    plain page there instead, which works where the review doesn't. `timings` says
    how long its keys took to reach the screen in the browsers you used it in.
    """
    if context.invoked_subcommand is not None:
        return
    shown = answering("the dashboard").ask(ShowDashboard(), DashboardShown)
    chosen = shown.chosen(address)
    where = plain_page if copies else str
    typer.echo(where(chosen))
    if chosen != shown.address:
        typer.echo(
            qr_code(where(chosen))
            or f"To scan it as a QR code, install `{QRENCODE.named()}`: "
            f"{QRENCODE.install}, then run this again."
        )
    if opened:
        webbrowser.open(where(shown.address))


@dashboard.command("timings")
def dashboard_timings(
    *,
    since: Annotated[
        str | None,
        typer.Option(
            help=(
                "Only what the host received from this time on: an ISO 8601 time, "
                "such as 2026-10-30T09:30 (without a zone, this machine's), or an "
                "ISO 8601 duration back from now, such as PT2H or P3D."
            )
        ),
    ] = None,
    sessions: Annotated[
        bool,
        typer.Option(
            "--sessions",
            help=(
                "Each page session apart, a page loaded, with a line for each window "
                "of it: the page's size then, and its keys' median and slowest."
            ),
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json", help="Each window as the host keeps it, a line of JSON each."
        ),
    ] = False,
    kept: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Read the timings kept in this directory, laid out as the host keeps "
                "them in lup's state, as a demo keeps its page's "
                "(`lup-dashboard demo --timings`), rather than asking the host."
            )
        ),
    ] = None,
) -> None:
    """Say how long each key took to reach the screen in the browsers the dashboard was used in, by the page's build.

    The page measures itself as it's used, from the browser's Event Timing
    API, and sends what it measured every 5 minutes and as its tab is hidden;
    the host keeps it 14 days (`docs/dashboard.md`, *Its timings*). Each
    build of the page, oldest first, with the browsers it ran in, the page's
    size, and for each kind of key how many and the percentiles of how long
    each took from going down to the next paint, `<16` for one under the
    browser's floor, with how long the slowest waited before the page handled
    them and in its handlers; the long animation frames and what ran in them,
    where the browser reports them; and what each browser couldn't measure.
    Timings and sizes only, never what was typed or shown, so an agent's
    session runs it too, in any room.
    """
    now = SystemClock().now()
    try:
        start = moment(given(since), now)
    except ValueError as unread:
        message = (
            "--since takes an ISO 8601 time, such as 2026-10-30T09:30, or an ISO "
            "8601 duration, such as PT2H"
        )
        raise typer.BadParameter(message) from unread
    asked = ShowTimings(since=start)
    if kept is None:
        timings = reading().ask(asked, Timings)
    else:
        store = TimingsStore(home=kept)
        measured = store.read(asked.page, now, asked.since)
        timings = Timings(page=asked.page, measured=measured, days=store.days)
    if as_json:
        for each in timings.measured:
            typer.echo(each.model_dump_json())
        return
    for line in Summary().said(timings, by_session=sessions):
        typer.echo(line)


@inbox.callback(invoke_without_command=True)
def inbox_list(
    context: typer.Context,
    *,
    since: Annotated[
        str | None,
        typer.Option(
            help=(
                "Only what was made from this time on: an ISO 8601 time, such as "
                "2026-10-19T09:30 (without a zone, the host's), or an ISO 8601 "
                "duration back from now, such as PT2H or P3D."
            )
        ),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            help="Only what was made before this time, in the same forms as --since."
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            min=1,
            help=(
                "How many to list at most, the latest; left out, every one, or with "
                "the options below 50 a line each, or 10 whole."
            ),
        ),
    ] = None,
    conversation: Annotated[
        str | None,
        typer.Option(
            help=(
                "Only one conversation's exchange, what they sent and were sent: a "
                "session by their name, a subagent by their path (flow-review/explore) "
                "or their own name, or either by their id or the id's start."
            )
        ),
    ] = None,
    subagents: Annotated[
        bool,
        typer.Option(
            "--subagents", help="With --conversation, their subagents' items too."
        ),
    ] = False,
    kinds: Annotated[
        list[str] | None,
        typer.Option(
            "--kind",
            help=(
                "Only items of this kind, as a tag's `kind` names it: turn's end, "
                "note, question, review…; repeat it for several."
            ),
        ),
    ] = None,
    whole: Annotated[
        bool,
        typer.Option(
            "--whole",
            help=(
                "Each item whole, your words on a conversation's item under it with "
                "its replies to them."
            ),
        ),
    ] = False,
    every: Annotated[
        bool,
        typer.Option(
            "--every",
            help="Every item, answered, done or told too, not those waiting alone.",
        ),
    ] = False,
    thread: Annotated[
        str | None,
        typer.Option(
            help=(
                "One thread, by its name or number, read whole: where it stands, "
                "the threads under it, then what's in it, each whole."
            )
        ),
    ] = None,
) -> None:
    """List what waits for you from your agents, oldest first; or read the inbox as the agents' `inbox` tool does.

    Each item has a number, which `show`, `answer` and `done` take; each
    agent's flagged writes are one line, with every number. `--since`
    and `--until` narrow them by when each was made, as `judged` and the agents'
    `inbox` do, and `--limit` lists the latest alone, saying how many it left
    out and how to read them. With `--conversation`, `--kind`, `--whole` or
    `--every`, it reads your own exchange, the items you sent or were sent,
    as the agents' `inbox` tool reads theirs, each line in the tool's form
    rather than the one above (`@12  2026-10-23 14:00  a note from `w` to
    you, waiting: …`): what waits for you unless `--every`, your exchange with
    one conversation with `--conversation`, and each item whole, your words
    on a conversation's item under it, with `--whole`; one thread whole, with
    `--thread`. Listing and `show` only read, so an agent's
    session runs them too: on the host, over the whole inbox; in a room, over
    its repository's items alone. Answering is the operator's, in their own
    terminal.
    """
    if context.invoked_subcommand is not None:
        return
    try:
        asked = ListInbox(since=given(since), until=given(until))
    except ValueError as unread:
        message = (
            "--since and --until each take an ISO 8601 time, such as "
            "2026-10-19T09:30, or an ISO 8601 duration, such as PT2H"
        )
        raise typer.BadParameter(message) from unread
    client = reading()
    if conversation is not None or kinds or whole or every or thread is not None:
        try:
            kinded = (
                TypeAdapter[list[ItemKind]](list[ItemKind]).validate_python(kinds)
                if kinds
                else None
            )
        except ValidationError as unread:
            known = ", ".join(get_args(ItemKind.__value__))
            message = f"--kind takes one of {known}"
            raise typer.BadParameter(message) from unread
        narrowed = ReadInbox(
            since=asked.since,
            until=asked.until,
            limit=limit,
            conversation=conversation,
            subagents=subagents,
            kinds=kinded,
            whole=whole,
            every=every,
            thread=thread,
        )
        typer.echo(client.ask(narrowed, Readout).text)
        return
    listing = client.ask(asked, Items)
    items = sorted(listing.items, key=lambda item: item.made)
    if not items:
        narrowed = "" if asked == ListInbox() else " made in that time"
        typer.echo(f"Nothing{narrowed} waits for you.")
        return
    # Each conversation's flagged writes are one entry, counted as one against the limit.
    entries = by_agent(items)
    shown = entries if limit is None else latest(entries, lambda each: each.made, limit)
    for each in shown:
        typer.echo(line(each, listing.paths, listing.landings))
    for left in unlisted(
        len(items) - counted(shown),
        "earlier item",
        shown[0].made,
        len(entries),
        until="--until",
        limit="--limit",
    ):
        typer.echo(left)


@inbox.command("show")
def inbox_show(
    number: Annotated[
        int,
        typer.Argument(parser=item_number, help="The item's number: `@12`, or `12`."),
    ],
    *,
    diff: Annotated[
        bool,
        typer.Option(
            "--diff",
            help=(
                "An approval's, a held change's or a flagged write's whole diff, "
                "through your pager."
            ),
        ),
    ] = False,
    context: Annotated[
        bool,
        typer.Option(
            "--context",
            help="Its moment in the conversation that sent it, after it.",
        ),
    ] = False,
) -> None:
    """Show one item whole: an approval by its summary, its whole diff with `--diff`; with `--context`, its moment in its sender's conversation."""
    client = reading()
    if diff:
        Terminal().show(client.ask(ShowDiff(number=number), Whole).text)
        return
    seen = client.ask(ShowItem(number=number), Shown)
    typer.echo(shown(seen.item, seen.paths))
    if context:
        typer.echo(f"\n{momented(client.ask(ShowContext(number=number), Context))}")


def momented(found: Context) -> str:
    """Say an item's moment, as `lup-dev transcripts show --all` says a session: each step in order, the call that made the item marked."""
    call = found.entries[found.anchor]
    tool = call.tool if isinstance(call, Called) else "?"
    return "\n\n".join(
        [
            "Its moment in the conversation that sent it:",
            *views.stepped(found.entries[: found.anchor]),
            f"→ called {tool}: this item",
            *views.stepped(found.entries[found.anchor + 1 :]),
        ]
    )


def approved_here(number: int, given: Given) -> str:
    """Say what came of answering approval `number` at this terminal."""
    if not given.here:
        return (
            f"{cited(number)} was {settled(approved=given.approved)} already, "
            "elsewhere: your answer changes nothing."
        )
    return (
        f"{cited(number)} is {settled(approved=given.approved)}: each launch waiting "
        "on it goes on."
    )


def acted_on(approval: Approval, given: Given) -> str | None:
    """Act on an approval approved at this terminal, as a launch waiting on it would, once between them, and say what came of it; none for an approval declined, which leaves the copy approved before.

    An approval may have nobody waiting on it: a push that moved the
    running branch asks it from the host (`proposed_after`).
    """
    if not given.approved:
        return None
    root = Git.pinned(approval.repository).main_worktree()
    outcome = machine_trust(root, []).settle(approval.fingerprint, given)
    if outcome is None:
        return (
            "The running branch moved since this was asked, so its tip isn't "
            "the code you read: `lup-dev trust` asks about it."
        )
    return outcome.report()


@inbox.command("answer")
def inbox_answer(
    number: Annotated[
        int,
        typer.Argument(parser=item_number, help="The item's number: `@12`, or `12`."),
    ],
    *,
    approve: Annotated[
        bool | None,
        typer.Option(
            "--approve/--decline",
            help="An approval's answer, without asking.",
            show_default=False,
        ),
    ] = None,
    leaning: Annotated[
        list[int] | None,
        typer.Option(help="A decision you go with the agent's lean on; repeat it."),
    ] = None,
    undecided: Annotated[
        list[int] | None,
        typer.Option(help="A decision you haven't decided; repeat it."),
    ] = None,
    leave_open: Annotated[
        list[int] | None,
        typer.Option(help="A decision left for later; repeat it."),
    ] = None,
    comment: Annotated[
        str | None,
        typer.Option(
            help="A comment on the whole, a plain question's answer, or a reply."
        ),
    ] = None,
) -> None:
    """Answer a question, each decision leaning, undecided, leave open or in your words, then a comment; reply to a message; or answer an approval, yes or no.

    At a terminal, each numbered decision is asked in turn, with an optional
    comment, then a comment on the whole; a plain question takes its answer in
    words, as a message takes your reply, which says the item it replies to and
    takes the message off your list. `--leaning`, `--undecided` and
    `--leave-open`, each repeated for several decisions, and `--comment` answer
    without asking. The answer reaches the conversation that sent the item.

    An approval shows its summary, asks whether to show the whole diff, then
    whether to approve, as the launch asking it does, and stops where the launch's
    terminal answers first; `--approve` or `--decline` answers without asking,
    and `--comment` beside it is told to the session whose push asked it.
    Every launch waiting on it goes on with the answer; approved, the copy is
    installed here where no launch did it first, the host service restarted on
    it for lup's own repository.

    A held change shows what's held and its diff, then asks whether to let it
    land, and a comment for the agent; `--approve` or `--decline`, with
    `--comment`, answer without asking. The agent waiting on it goes on with
    the answer.

    A write that landed flagged takes your reply in words, as a message does,
    for the agent who made it: the write has landed, and your reply comes to
    them as "yes, but".

    A check, which an agent's question put in a thread for you to try, takes
    what you saw, or nothing for a tick; `--comment` gives it without asking.
    The agent who asked it is told.
    """
    client = answering()
    check = client.ask(ShowCheck(number=number), CheckShown)
    if check.check is not None:
        check_answered(client, check, comment)
        return
    approvals = InboxApprovals(host=client)
    seen = client.ask(ShowItem(number=number), Shown)
    item = seen.item
    if isinstance(item.reason, HeldChange):
        held_answer(client, seen, approve=approve, comment=comment)
        return
    if approve is not None:
        given_here = approvals.answer(number, approved=approve, comment=comment or "")
        typer.echo(approved_here(number, given_here))
        if isinstance(item.reason, Approval):
            acted = acted_on(item.reason, given_here)
            if acted is not None:
                typer.echo(acted)
        return
    given = [
        *(Ruling(decision=each, verdict="leaning") for each in leaning or []),
        *(Ruling(decision=each, verdict="undecided") for each in undecided or []),
        *(Ruling(decision=each, verdict="leave open") for each in leave_open or []),
    ]
    if not given and comment is None:
        match item.reason:
            case Approval(text=text, summary=summary) as approval:
                asking = Approving(
                    asker=Terminal(),
                    approvals=approvals,
                    number=number,
                    summary=f"{heading(item, seen.paths)}\n{summary}",
                    question=text,
                    diff=client.ask(ShowDiff(number=number), Whole).text,
                )
                answered = asking.given()
                if answered.here:
                    typer.echo(approved_here(number, answered))
                acted = acted_on(approval, answered)
                if acted is not None:
                    typer.echo(acted)
                return
            case _:
                request = prompted(item, seen.paths)
    else:
        request = AnswerItem(number=number, rulings=given, comment=comment or "")
    answered = client.ask(request, Shown)
    answer = answered.item
    done = "Replied to" if isinstance(answer.reason, Message) else "Answered"
    noun = "reply" if isinstance(answer.reason, Message) else "answer"
    typer.echo(
        f"{done} {cited(number)}: your {noun}, {cited(answer.number)}, is for "
        f"{called(answer.recipient, answered.paths)}."
    )


def check_answered(client: HostClient, shown: CheckShown, comment: str | None) -> None:
    """Answer the check `shown` with what the operator saw: `comment` where given, else asked at this terminal after it, nothing for a tick."""
    check = shown.check
    if check is None:
        return
    if not shown.waiting:
        message = f"{cited(check.number)} is answered already"
        raise InboxError(message)
    if comment is None:
        where = "" if shown.thread is None else f" in @{shown.thread}"
        typer.echo(f"{cited(check.number)}, a check{where}:\n{check.text}")
    said: str = (
        typer.prompt("What you saw (empty for a tick)", default="", show_default=False)
        if comment is None
        else comment
    )
    client.ask(AnswerCheck(number=check.number, text=said), CheckShown)
    typer.echo(f"Answered {cited(check.number)}: whoever asked it is told.")


def held_answer(
    client: HostClient, seen: Shown, *, approve: bool | None, comment: str | None
) -> None:
    """Answer a held change, `seen`: as given, or asked at this terminal after its summary and diff."""
    item = seen.item
    if approve is None:
        typer.echo(shown(item, seen.paths))
        Terminal().show(client.ask(ShowDiff(number=item.number), Whole).text)
    landing = (
        typer.confirm("Let it land?", default=False) if approve is None else approve
    )
    said: str = (
        typer.prompt(
            "A comment for the agent (optional)", default="", show_default=False
        )
        if comment is None
        else comment
    )
    settled = client.ask(
        AnswerApproval(number=item.number, approved=landing, comment=said),
        Settled,
    )
    told = "let it land" if landing else "declined it"
    typer.echo(
        f"{cited(item.number)}: you {told}; the agent waiting on it goes on."
        if settled.here
        else f"{cited(item.number)} was answered already, elsewhere: yours changes nothing."
    )


@inbox.command("done")
def inbox_done(
    number: Annotated[
        int,
        typer.Argument(
            parser=item_number, help="The message's number: `@12`, or `12`."
        ),
    ],
) -> None:
    """Take a message or a flagged write you've read off your list."""
    answering().ask(FinishItem(number=number), Shown)
    typer.echo(f"{cited(number)} is done.")


ThreadNumber = Annotated[
    int,
    typer.Argument(
        parser=item_number,
        help="The thread's number, as the review's banner and `inbox --thread` say it: `@2601`, or `2601`.",
    ),
]
"""A thread named on the command line, by its number: unique on the machine, where its name is its repository's alone."""

Why = Annotated[
    str,
    typer.Option(help="Why, in a line: whoever answers for the thread is told it."),
]


def thread_stated(stated: ThreadStated, did: str) -> str:
    """Say what settling, declining or reopening a thread did: the thread, where it stands after, and who answers for it, who was told."""
    read = stated.read
    told = (
        "nobody answers for it, so nobody was told"
        if read.answering is None
        else f"{called(read.answering, stated.paths)} answers for it, and was told"
    )
    return f'@{read.thread.name} (@{read.thread.number}), "{read.thread.title}", {did}: {read.state}; {told}.'


@inbox.command("settle-thread")
def inbox_settle_thread(number: ThreadNumber) -> None:
    """Settle a thread, any, as Space d on its banner does in the review once nothing on it is new: it folds into what's settled, and whoever answers for it is told."""
    stated = answering().ask(SettleThread(number=number), ThreadStated)
    typer.echo(thread_stated(stated, "settled"))


@inbox.command("decline-thread")
def inbox_decline_thread(number: ThreadNumber, why: Why = "") -> None:
    """Decline a thread, any, as Space x on its banner does in the review: nothing more will be done about it, and whoever answers for it is told why."""
    stated = answering().ask(DeclineThread(number=number, why=why), ThreadStated)
    typer.echo(thread_stated(stated, "declined"))


@inbox.command("reopen-thread")
def inbox_reopen_thread(number: ThreadNumber, why: Why = "") -> None:
    """Reopen a thread done, parked, settled or declined, back to whoever held it, as a reply of yours in it does: whoever answers for it is told why."""
    stated = answering().ask(ReopenThread(number=number, why=why), ThreadStated)
    typer.echo(thread_stated(stated, "reopened"))


@inbox.command("check-conversion")
def inbox_check_conversion(
    files: Annotated[
        Path | None,
        typer.Option(
            "--inbox",
            help=(
                "The inbox's files to convert, read alone: a copy of them, or "
                "lup's own, `$XDG_STATE_HOME/lup/inbox`, where left out."
            ),
        ),
    ] = None,
) -> None:
    """Rehearse each conversion lup runs as its host service starts, in a scratch directory removed after, and compare what it keeps with what it converts.

    The inbox's files onto the ledger; the review marks' files onto it, the
    judge's older marks of each branch carried in. It reads lup's files alone,
    and the ledger the host service keeps through a connection that only reads
    it, writing only in the scratch directory: lup's state is left as it is.
    For each, it says how many of each it converted, how long it took, and
    what differs, by item number, or by repository, module and mark, and
    field, never what an item says or what a mark is on. It exits with 1
    where something differs.
    """
    layout = Layout.of(LupDevSettings())
    checks = conversions.checked(
        layout, layout.inbox if files is None else InboxLayout(home=files.resolve())
    )
    for check in checks:
        typer.echo(f"{check.of}:")
        for line in check.said:
            typer.echo(f"  {line}")
    if any(each.differs for each in checks):
        raise typer.Exit(1)


@inbox.command("send")
def inbox_send(
    to: Annotated[
        str,
        typer.Argument(
            help=(
                "The launch, by its name, its id or its worktree; or one of its "
                "subagents, by their path (`dev/explore-auth`)."
            )
        ),
    ],
    text: Annotated[str, typer.Argument(help="What to tell them.")],
) -> None:
    """Send a message to the session a launch runs, their main conversation; or to one of their subagents, by their path."""
    client = answering()
    listed = client.listed()
    subagents = [
        Addressed(launch=launch, agent=talker.agent)
        for launch, talkers in listed.talkers.items()
        for talker in talkers
        if talker.path == to and talker.agent is not None
    ]
    match subagents:
        case [Addressed(launch=launch, agent=agent)]:
            sent = client.ask(SendItem(launch=launch, text=text, agent=agent), Shown)
            typer.echo(
                f"Sent {cited(sent.item.number)} to "
                f"{called(sent.item.recipient, sent.paths)}."
            )
            return
        case _:
            pass
    launch = the_launch(listed.launches, to)
    sent = client.ask(SendItem(launch=launch.launch, text=text), Shown)
    typer.echo(
        f"Sent {cited(sent.item.number)} to {called(sent.item.recipient, sent.paths)}."
    )


class Addressed(Model):
    """A subagent a message is sent to: the launch their session runs in, and the runtime's id for them."""

    launch: str
    agent: str


def the_launch(launches: list[Register], to: str | None) -> Register:
    """Return the one launch `to` names (`addressed`); where it's none, the one whose worktree holds this directory, or the only one running.

    Raise `InboxError` where none is, or several are, naming them.
    """
    found = (
        addressed(launches, to)
        if to is not None
        else addressed(launches, str(Path.cwd())) or launches
    )
    match found:
        case [launch]:
            return launch
        case []:
            message = f"no launch served is `{to}`, by its name, its id or its worktree"
            raise InboxError(message)
        case _:
            named = ", ".join(
                f"`{each.name}` ({each.launch}, in {each.worktree})" for each in found
            )
            message = f"several launches run: {named}; name one"
            raise InboxError(message)


@app.command("rename")
def rename(
    to: Annotated[
        str, typer.Argument(help="The launch, by its name, its id or its worktree.")
    ],
    name: Annotated[str, typer.Argument(help="Its name from now on.")],
) -> None:
    """Rename a running launch: how you, lup's commands and its session call it.

    Run it yourself, in your own terminal. A name another launch holds is
    refused, saying whose. The session hears the name at their next start, where
    their runtime takes it as their own title, where the runtime has a way.
    """
    client = answering()
    launch = the_launch(client.launches(), to)
    renamed = client.rename(launch.launch, name)
    typer.echo(f"Launch {renamed.launch} is `{renamed.name}`.")


class Launcher(Model, arbitrary_types_allowed=True):
    """What a launch reaches on this machine, each a seam a test stubs."""

    layout: Layout
    trust: Callable[[Path, Path], Outcome]
    """Checks what the host runs for the repository of a worktree, whose git directory the launch found already, asking where it changed."""
    host: HostClient
    podman: Podman
    tools: Tools
    """Where the host's requirements, and the runner's tools, are found."""
    clock: Clock
    terminal: TerminalVariables
    say: Callable[[str], None]
    """Where the launch tells the operator what it does."""
    github: Callable[[Path], GitHubRepository]
    """Names the repository on GitHub whose git directory it's given, from its own
    remotes, raising `GitHubError` where `gh` can't."""
    facts: Facts
    """What the host says of itself, which the list of values never published
    is built from."""
    rules: Callable[[list[Selected]], list[Rule]]
    """Lists the rules a project's selection runs, which the engine resolves,
    raising `EngineError` where it refuses the selection or can't run."""
    ask: Callable[[str], str | None] | None = None
    """Asks the operator a question in their terminal, returning the line they
    answer, none at the end of its input; none where the launch runs in no
    terminal to ask in."""
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep
    """Waits the seconds between two looks a held launch takes at whether the
    host heard its session's first hook; a test gives its own."""
    host_paths: HostPaths = HostPaths()
    """The host's own places a held launch reads; a test gives its own."""


def host_runtime(adapter: Adapter) -> HostRuntime:
    """Return a runtime as the migration takes it, from its adapter."""
    return HostRuntime(
        name=adapter.runtime.name(),
        directory=adapter.directory,
        records=adapter.records,
        written=adapter.written,
        recorded=adapter.recorded,
    )


def withheld_at_launch(
    launcher: Launcher, resolved: Resolved, repository: Path
) -> None:
    """Build the list of values never published from the repository whose git directory is `repository`, as the launch found it, where the declaration selects `Private`, and keep it where the module reads it; where it doesn't, remove the one kept.

    What the build couldn't read is said once, in the operator's terminal; no
    value is.
    """
    made = asyncio.run(listed(resolved, repository, launcher.facts, launcher.layout))
    for note in [] if made is None else made.notes:
        launcher.say(f"Private: {note}.")


def on_github(
    launcher: Launcher, repository: Path, needs: Report
) -> GitHubRepository | None:
    """Name the repository on GitHub for a launch, from its git directory `repository`; where it can't be, say why once and return none.

    Where `gh` is off on the host, which the launch said with its requirements,
    it isn't asked again.
    """
    if any(PROGRAM in each.needed.requirement.programs() for each in needs.off):
        return None
    try:
        return launcher.github(repository)
    except GitHubError as unnamed:
        launcher.say(
            f"lup's GitHub tools won't reach GitHub from this launch: {unnamed}."
        )
        return None


def swept(
    layout: Layout, host: HostClient, podman: Podman, say: Callable[[str], None]
) -> list[str]:
    """End each launch the host service serves whose launcher and container are both gone, and return the launches still served.

    A launcher holds its launch's lock for its whole life, which the OS frees, so
    a launch whose lock can be taken has no launcher left; its container, named
    when it registered, tells whether its session still runs, and one that
    isn't running, left as its launch ended before it started, is removed with
    it. A held launch's container still running is stopped first: nothing
    reaches its session without its launcher, and its runtime outlives its
    input during a call, a held hook or a background command
    (`docs/field-notes.md`, *A session held with no terminal*), spending on
    with no one reading; one podman can't stop is said and left for the next
    sweep, so it keeps no other launch from starting. Each launch ended is
    said, and a launch ended first elsewhere is passed over; its environments
    go with it. A launch runs it
    before it registers, and the host service on its own (`Sweeping`).
    """

    def ending(each: Register) -> bool:
        own = layout.launch(each.launch)
        own.lock.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(own.lock, timeout=0)
        try:
            lock.acquire()
        except Held:
            return False
        try:
            if each.container is None:
                return False
            state = podman.state(each.container)
            if state is not None and not stopped(state):
                if not each.held:
                    return False
                try:
                    podman.stop(each.container)
                except ContainerError as failed:
                    say(
                        f"{each.container}, launch {each.launch}'s room, held by a "
                        f"launcher that's gone, wasn't stopped, so it stays for the "
                        f"next sweep: {failed}"
                    )
                    return False
                say(
                    f"Stopped {each.container}: launch {each.launch}'s session was "
                    "held by a launcher that's gone."
                )
                state = podman.state(each.container)
            try:
                host.unregister(each.launch)
            except HostError as gone:
                say(f"Launch {each.launch} was ended already: {gone}")
                return False
            if state is not None:
                podman.discard(each.container)
            released(podman, own, say)
            vacated(own)
            own.held.unlink(missing_ok=True)
            rooms = layout.rooms(each.repository)
            removed(rooms.home, rooms.launch(each.launch))
            say(
                f"Ended launch {each.launch}, {each.runtime} in {each.worktree}: its "
                f"launcher and its container, {each.container}, are gone."
            )
        finally:
            lock.release()
        own.lock.unlink(missing_ok=True)
        return True

    return [each.launch for each in host.launches() if not ending(each)]


class Sweeping(MutableModel, Companion, arbitrary_types_allowed=True):
    """The sweep beside the host service: once it listens, then every `every`, so a launch whose launcher and container are gone is ended though no launch follows it (`swept`), a repository's approved copy no process runs and none judges is removed (`lup_dev/copies.py`), and each thread parked until a time that came, a conversation that ended or a condition the gate found holding is woken (`Coming.swept`): the one moment the host looks of its own accord, whether a session runs or not.

    It asks the service as a launch does, from a thread, so the service goes on
    answering meanwhile; its end waits for a sweep under way, so none outlives
    the service's socket. The copies to remove are chosen on the event loop,
    beside the repositories' processes starting, so none is chosen as one
    starts from it, and removed from a thread.
    """

    layout: Layout
    host: HostClient
    podman: Podman
    say: Callable[[str], None]
    running: Callable[[], list[Path]]
    """The commands of the repositories' processes, running or starting, their
    links followed: the copies in use."""
    every: timedelta = timedelta(seconds=30)
    coming: Coming | None = None
    """What wakes the threads parked until what the sweep sees come; none wakes
    none."""
    rewake: Callable[[], Awaitable[None]] | None = None
    """Gives each idle held session what waits for them that no hook would tell,
    giving it having failed (`Delivery.rewoken`); none gives nothing."""
    reap: Callable[[], Awaitable[None]] | None = None
    """Collects each held launch's launcher the service started that has
    ended, so none is left a zombie, and tells the agent who spawned one whose
    session never came up (`Launchers.reaped`, `SpawnTools.lost`); none
    collects none."""
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep
    """Waits the seconds between two sweeps; a test gives its own."""
    stopping: asyncio.Event = Field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    ending: dict[str, asyncio.Task[None]] = {}
    """Each side job whose spawner's launch the service doesn't serve, by
    its launch, while its launcher is asked to end it."""

    @override
    async def begin(self) -> None:
        await self.sweep()
        self.task = asyncio.create_task(self.sweeping())

    @override
    async def end(self) -> None:
        self.stopping.set()
        if self.task is not None:
            await self.task

    async def sweeping(self) -> None:
        """Sweep every `every`, until the service stops."""
        while not self.stopping.is_set():
            paused = asyncio.ensure_future(self.pause(self.every.total_seconds()))
            stopped = asyncio.ensure_future(self.stopping.wait())
            await asyncio.wait([paused, stopped], return_when=asyncio.FIRST_COMPLETED)
            paused.cancel()
            stopped.cancel()
            if not self.stopping.is_set():
                await self.sweep()

    async def sweep(self) -> None:
        """Sweep once, off the event loop; where it fails, say why, with its traceback where it's not podman's or the service's, and the next sweep goes on."""
        failing = "The sweep of launches whose launcher and container are gone failed"
        try:
            await asyncio.to_thread(
                swept, self.layout, self.host, self.podman, self.say
            )
        except (HostError, ContainerError, OSError) as failed:
            self.say(f"{failing}: {failed}")
        except Exception as failed:
            told = "".join(traceback.format_exception(failed))
            self.say(f"{failing}:\n{told}")
        await self.pruned()
        if self.reap is not None:
            await self.reap()
        await self.orphans_ended()
        if self.rewake is not None:
            await self.rewake()
        self.woken()

    async def orphans_ended(self) -> None:
        """Ask the launcher of each side job whose spawner's launch the service doesn't serve to end it, in the background, as that launch's end does (`Launches.close`): one that registered after its spawner ended, or whose spawner's end a restart cut short, would run on for nobody, its reports reaching someone gone. Where the launches can't be listed, say so; the next sweep looks again."""
        self.ending = {
            launch: task for launch, task in self.ending.items() if not task.done()
        }
        try:
            launches = await asyncio.to_thread(self.host.launches)
        except (HostError, OSError) as failed:
            self.say(f"Side jobs whose spawner ended weren't looked for: {failed}")
            return
        for each in orphaned(launches):
            if each.launch not in self.ending:
                self.say(
                    f"{each.launch}: a side job whose spawner's launch "
                    f"{each.spawner.launch if each.spawner else '?'} ended, so it's "
                    "ended too"
                )
                self.ending[each.launch] = asyncio.create_task(
                    asyncio.to_thread(ended_held, self.host, each, self.say)
                )

    def woken(self) -> None:
        """Wake each thread parked until what the sweep sees come (`Coming.swept`), on the event loop, as the inbox is written; where it fails, say why, with its traceback, and the next sweep goes on."""
        if self.coming is None:
            return
        try:
            self.coming.swept()
        except Exception as failed:
            told = "".join(traceback.format_exception(failed))
            self.say(f"Waking the threads parked until what came failed:\n{told}")

    async def pruned(self) -> None:
        """Remove each repository's copies no process runs and none judges, saying each; where one can't be, say why, and the next sweep tries again."""
        try:
            unused = removable(self.layout.judges, self.running())
        except OSError as failed:
            self.say(
                f"The copies of `lup-dev` nothing runs weren't looked for: {failed}"
            )
            return
        for each in unused:
            try:
                await asyncio.to_thread(shutil.rmtree, each)
            except OSError as failed:
                self.say(f"{each}, a copy of `lup-dev` nothing runs, stays: {failed}")
                continue
            self.say(
                f"Removed {each}, a copy of `lup-dev` nothing runs or judges with."
            )


def launched(
    adapter: Adapter,
    arguments: list[str],
    worktree: Path,
    launcher: Launcher,
    lending: list[Lent] | None = None,
    *,
    modules: list[str] | None = None,
    name: str | None = None,
    profile: str | None = None,
    account: str | None = None,
    held: HeldLaunch | None = None,
    take_over: bool = False,
) -> int:
    """Launch `adapter`'s runtime in a room for `worktree`, in this terminal, or held with none where `held` is given, and return its CLI's exit status.

    A held launch (`held`) runs under the launch id the host minted, its session
    named up front, new or resumed, its settings compiled for a held session,
    and its last step the launcher holding it (`lup_dev.launch.held`) rather
    than a terminal. Each launch whose session's id is known before its room
    starts, a held one's, and a terminal's resuming one by its id, holds the
    lock on that session's writer while its room runs (`Writing`); a terminal
    finding a held launch on it offers to end that launch and take the session
    over, or, with `take_over`, does so asking nothing.

    In the order `docs/launch.md` gives (*The command*): trust on launch, its
    report said; replace refs in the repository said, which lup's git ignores
    (`lup_dev.git`); the declaration at the commit approved, with the person's own
    layer approved beside it; the launch's profile, `profile` or else the one
    the person's layer chooses, and its runtime's account, `account` or else
    the profile's, from the person's profiles approved with it, said where
    either isn't `default` (`chosen`); the offer to move the runtime's records
    of the repository from the operator's own directory into the home the
    profile chooses, where something would move, asked on a terminal and moved
    on a yes, before anything registers (`lup_dev.launch.moving`); the home of
    the rooms' own the runtime runs on, the profile's choice of one, with the account's login and the
    profile's configuration over the operator's (`LaunchHome`); the rules its selection runs, which the
    engine resolves for the guidance; the host's requirements, each optional
    one off said; the repository named on GitHub, or why not said; the host
    service; the latest CLI, a fallback said; the other repositories the
    declaration names for its sessions to read, each missing one said; the
    operator's editor, said where lup doesn't know it; the room, its image
    built where it's missing; the package age each package manager in its
    image keeps, said where one keeps none; the terminal settings; the
    repository's `config` checked for the room's git; the files with a secret's
    name whose content their repository's git objects don't hold, in the
    project's tree and each related repository mounted, found as late as can be
    and said (`lup_dev.launch.secrets`), with a home not made yet, an account
    holding no login for the runtime, and what of the configuration copied in
    was left out where that changed; the sweep, and the
    environments a launch that crashed left, then the launch registered, under
    its launcher's lock; the room's git configuration and helper, the
    clipboard's programs, the package managers' settings, the environments'
    program and places, what the hidden files are mounted from, and the
    editor's link written, and the account's login made where there's none;
    the CLI in the room, behind the start making the worktree's environment,
    with `arguments` after lup's own. What the session saved of its
    preferences is carried back to the profile, and the first change seen of
    the account's login said, each said; then the registration ends, and the
    launch's directory and environments go,
    with each of the host's environments that appeared in a worktree while the
    room ran, whatever the CLI did; each file with a secret's name that
    appeared or changed in the project's tree meanwhile is said, and left.
    """
    runtime = adapter.runtime.name()
    holding = adapter.holding
    if held is not None and holding is None:
        message = f"{runtime} has no session held with no terminal yet"
        raise LaunchError(message)
    traced = None if held is None else untraceable(launcher.host_paths)
    if traced is not None:
        message = f"no session is held on this machine: {traced}"
        raise LaunchError(message)
    found = located(worktree, None if held is None else held.repository)
    repository = found.git
    launcher.say(launcher.trust(worktree, repository).report())
    if Git.pinned(repository).text("for-each-ref", "--count=1", "refs/replace/"):
        launcher.say(
            "This repository holds replace refs (`refs/replace/`), which a room "
            "can write to hand git other content for an object: lup's git ignores "
            "them. `git replace -l` lists them, and `git replace -d` removes one."
        )
    approval = approved(launcher.layout, repository)
    if approval is None:
        message = f"nothing is approved for {repository}, so nothing launches"
        raise LaunchError(message)
    judge = launcher.layout.judge(repository).command(approval.tool.name)
    with approved_declaration(
        repository, approval.commit, local=approval.local
    ) as declared:
        choice = chosen(
            declared_profiles(approval.profiles, launcher.layout.profiles.declared),
            runtime,
            [each.name() for each in runtimes()],
            profile=profile or declared.resolved.profile,
            account=account,
        )
        said = choice.said()
        if said is not None:
            launcher.say(said)
        MovingOver(
            migrating=Migrating(
                layout=launcher.layout,
                repository=repository,
                runtimes=[host_runtime(adapter)],
                home=Path.home(),
                shared=choice.profile.rooms_home == "global",
            ),
            runtime=host_runtime(adapter),
            resumed=adapter.resumed(arguments),
            say=launcher.say,
            ask=launcher.ask,
        ).walked()
        running = launcher.rules(declared.resolved.rules)
        needs = checked(host_needs(), launcher.tools).require()
        for off in needs.off:
            launcher.say(f"Turned off, for want of a tool: {off.described()}")
        github = on_github(launcher, repository, needs)
        launcher.host.ensure()
        cached = CliCache(
            layout=launcher.layout.clis(runtime), channel=adapter.channel
        ).current()
        if cached.fallback is not None:
            launcher.say(
                f"{runtime} {cached.version}, kept, runs: its release channel couldn't "
                f"give the latest. {cached.fallback}"
            )
        neighbours = related(declared.resolved.repositories, found)
        for each in neighbours:
            if not each.mounted:
                launcher.say(
                    f"The repository `{each.name}` the declaration names for "
                    f"sessions to read isn't at {each.path}, so the room doesn't "
                    "mount it, and its guidance says it's missing."
                )
        withheld_at_launch(launcher, declared.resolved, repository)
        editor = OperatorsEditor.of(launcher.terminal)
        if editor.program is not None and editor.known is None:
            launcher.say(
                f"Your editor, `{editor.program}` (`$VISUAL`, else `$EDITOR`), isn't "
                "one lup knows the package of, so the room doesn't install it, and "
                "Ctrl+G there won't find it unless your own layer, "
                "`lup_project.local.py`, adds its package to `Core`. Every room "
                "has `nano`."
            )
        lendable = [each.module for each in declared.resolved.shared]
        unknown = [each for each in modules or [] if each not in lendable]
        if unknown:
            message = (
                f"`--mount {unknown[0]}` names neither a directory nor a module "
                f"whose data a launch lends: those are {', '.join(lendable) or 'none'}"
            )
            raise LaunchError(message)
        shared = {
            each.module: launcher.layout.module_data(each.module, repository)
            for each in declared.resolved.shared
            if each.always or each.module in (modules or [])
        }
        for place in shared.values():
            place.mkdir(parents=True, exist_ok=True)
        launch = secrets.token_hex(8) if held is None else held.launch
        own = launcher.layout.launch(launch)
        homing = LaunchHome.of(
            launcher.layout,
            own,
            repository,
            runtime,
            choice=choice,
            login=Login(
                runtime=runtime,
                path=adapter.login(
                    launcher.layout.accounts.account(choice.account).runtime(runtime)
                ),
            ),
        )
        environments = RoomEnvironments.of(
            declared.resolved.runner,
            worktree,
            launcher.layout,
            launch,
            launcher.tools,
            held=found,
        )
        room = maintaining_room(
            declared.resolved,
            worktree,
            launcher.terminal,
            environments,
            neighbours=neighbours,
            shared=shared,
            lent=lending,
        )
        built = build(
            room.image, launcher.podman, launcher.clock, launcher.layout.builds
        )
        if built is not None:
            launcher.say(f"Built the room's image in {built.took()}: {built.tag}.")
        ages = RoomPackageAge.of(own, declared.resolved, worktree)
        for each in ages.ungated:
            launcher.say(each.why)
        settings = terminal_settings(
            declared,
            worktree,
            own.directory,
            cached.cli,
            hooked(adapter.hooks),
            tools=served_tools(declared.resolved),
            neighbours=neighbours,
            shared=shared,
            lent=lending,
            rules=running,
            main=found.main,
            home=homing.home,
        )
        compiled = (
            adapter.agent().terminal(settings)
            if held is None
            else adapter.agent().held(settings)
        )
        gating = Gating(
            command=declared.resolved.runner.command(["lup-dev", "check", "--at"]),
            refs=declared.resolved.limits.gated,
        )
        git = room_git(
            repository,
            own,
            [*room.mounts, *ages.mounts, *compiled.mounts],
            gating,
        )
        naming = named_session(adapter, arguments, held)
        registered = Register(
            launch=launch,
            runtime=runtime,
            worktree=worktree,
            repository=repository,
            judge=judge,
            limits=declared.resolved.limits,
            github=github,
            name=name or branch_name(worktree, found.worktree),
            exact=name is not None,
            runner=declared.resolved.runner.command([]),
            environments=environments.own,
            home=homing.home.shared,
            own=homing.home.directory,
            held=held is not None,
            spawner=None if held is None else held.spawner,
            model=model_named([*arguments, *([] if held is None else held.arguments)]),
            session=None if held is None else naming.session,
        )
        session, arguments = naming.session, naming.arguments
        hiding = RoomSecrets.of(
            Search(
                patterns=declared.resolved.paths.secret,
                hidden=[each.path for each in environments.hidden.found],
            ),
            Tree(path=environments.hidden.tree, git=environments.held.git),
            [
                Tree(path=each.path, git=git_directory(each.path))
                for each in neighbours
                if each.mounted
            ],
            own,
        )
        for line in [
            *hiding.said(),
            *homing.said(),
            *homing.left(compiled.left_out),
        ]:
            launcher.say(line)
        own.lock.parent.mkdir(parents=True, exist_ok=True)
        writing = (
            None if session is None else Writing.of(launcher.layout, runtime, session)
        )
        writer = (
            None
            if writing is None
            else written_by(
                launcher, writing, launch, held=held is not None, take_over=take_over
            )
        )
        try:
            with FileLock(own.lock):
                serving = swept(
                    launcher.layout, launcher.host, launcher.podman, launcher.say
                )
                for each in unclaimed(environments.rooms, serving, launcher.layout):
                    launcher.say(
                        f"Removed {each}, the environments of a launch that ended "
                        "without removing them."
                    )
                served = launcher.host.register(registered)
                sockets = served.directory
                launcher.say(f"This launch is `{served.name}`.")
                before: str | None = None
                try:
                    cleared(launcher.podman, served.container, launcher.say)
                    git.write()
                    clipboard = RoomClipboard(launch=own)
                    clipboard.write()
                    ages.write()
                    environments.write()
                    hiding.write()
                    editor.link(own)
                    receives = receiving(launcher.podman, own)
                    before = homing.ready()
                    walled = room.model_copy(
                        update={
                            "name": served.container,
                            "mounts": [
                                *room.mounts,
                                *hiding.mounts,
                                *git.mounts,
                                *ages.mounts,
                                Mount(source=sockets, target=RoomPaths().sockets),
                                receives,
                            ],
                            "env": {**room.env, **git.env, **clipboard.env},
                        }
                    )
                    opened = Room(
                        agent=adapter.agent(),
                        container=walled,
                        home_source=own.room_home,
                        engine=launcher.podman,
                        before=environments.before,
                    )
                    if held is None or holding is None or session is None:
                        return opened.launch(arguments=arguments, settings=settings)
                    holder = Holder(
                        layout=launcher.layout,
                        host=launcher.host,
                        holding=holding.session,
                        launch=launch,
                        session=session,
                        name=served.name,
                        container=served.container,
                        sockets=sockets,
                        podman=launcher.podman,
                        say=launcher.say,
                        pause=launcher.pause,
                    )
                    return asyncio.run(holder.held(opened, arguments, settings))
                finally:
                    carried = compiled.preferences
                    for line in [
                        *([] if carried is None else carried.carried()),
                        *([] if before is None else homing.ended(before)),
                    ]:
                        launcher.say(line)
                    if held is not None and still_running(
                        launcher.podman, served.container
                    ):
                        launcher.say(
                            f"Launch `{served.name}`'s room, {served.container}, "
                            "may still run: the launch stays registered, for the "
                            "host's sweep to stop it and end it once this launcher "
                            "is gone."
                        )
                    else:
                        ended(launcher, launch)
                        for line in [*environments.end(), *hiding.end()]:
                            launcher.say(line)
                        if held is not None:
                            own.log.unlink(missing_ok=True)
                            own.spawned.unlink(missing_ok=True)
        finally:
            own.lock.unlink(missing_ok=True)
            if writing is not None and writer is not None:
                writing.let_go(writer)


def located(worktree: Path, pinned: Path | None) -> Found:
    """Return the repository the launch in `worktree` runs for, once, which every step of the launch then takes as given: the one whose git directory is `pinned`, where an agent spawned the launch and the host recorded the spawner's; else the one git finds through the worktree, the operator's starting point.

    A room writes every worktree's `.git` file and the git directory's
    `worktrees/`, so finding the repository again through the worktree at a
    later step would let a room lead it elsewhere meanwhile, to another
    repository approved on this machine, whose tree the room would mount
    read-write. Refuse a worktree the repository doesn't name back
    (`Git.listed`), which a room can't fake for a repository whose git
    directory it doesn't write.
    """
    try:
        found = repository_of(worktree, pinned)
    except RoomError as unmountable:
        raise LaunchError(str(unmountable)) from unmountable
    if found.worktree is None:
        raise LaunchError(unnamed(worktree, found.git))
    return found


def unnamed(worktree: Path, common: Path) -> str:
    """Say why `worktree` isn't one of the repository's at `common` as it names them back, by what its `.git` file names: a submodule's checkout, a checkout whose git directory sits apart, or a linked worktree the repository's record of doesn't match, as one moved or recorded through a link."""
    named = link_file(worktree / ".git")
    gitdir = None if named is None else Path(named.strip().removeprefix("gitdir: "))
    place = None if gitdir is None else worktree / gitdir
    refused = "nothing launches in it"
    if place is not None and "modules" in place.parts:
        return (
            f"{worktree} is a submodule's checkout, its git directory {place}: lup "
            f"launches in a repository's own worktrees, not a submodule's, so "
            f"{refused}"
        )
    if place is not None and not place.is_relative_to(common / "worktrees"):
        return (
            f"{worktree}'s git directory sits apart from it, at {place} "
            "(`git init --separate-git-dir`), and isn't one a linked worktree "
            f"names: lup launches in a repository whose worktrees its git "
            f"directory names, so {refused}"
        )
    return (
        f"{worktree} isn't one of the worktrees of {common}, as that repository "
        "names them back: its `.git` file names another place, or the "
        "repository's record of it does, as where it moved, or was recorded "
        f"through a link. `git worktree repair` there mends it; {refused} until "
        "then"
    )


def model_named(arguments: list[str]) -> str | None:
    """Return the model a launch's runtime arguments name with `--model`, the last where they name it twice; none where they name none.

    >>> model_named(["--resume", "s1", "--model", "haiku"]), model_named(["--model=opus"]), model_named([])
    ('haiku', 'opus', None)
    """
    named = [
        after if each == "--model" else each.removeprefix("--model=")
        for each, after in itertools.pairwise([*arguments, ""])
        if each == "--model" or each.startswith("--model=")
    ]
    return named[-1] if named and named[-1] else None


def orphaned(launches: list[Register]) -> list[Register]:
    """Return each held side job among `launches` whose spawner's launch isn't among them: what ends with its spawner (`Launches.side_jobs`)."""
    served = {each.launch: each for each in launches}
    return [
        each
        for each in launches
        if each.held
        and each.spawner is not None
        and each.spawner.concern is None
        and each.spawner.launch not in served
    ]


def ended_held(host: HostClient, launch: Register, say: Callable[[str], None]) -> None:
    """End `launch`'s held session through its launcher, once it has ended; where it can't be, say so, for the operator to end it."""
    try:
        outstanding = host.held(End(launch=launch.launch))
        try:
            outstanding.reply(Done)
        finally:
            outstanding.close()
    except (HostError, OSError) as failed:
        say(
            f"{launch.launch}: the side job wasn't ended, `lup-dev spawn end "
            f"{launch.name}` ends it: {failed}"
        )


class NamedSession(Model):
    """The session a launch runs, where its id is known before its room starts, and the runtime's arguments naming it."""

    session: str | None
    arguments: list[str]


def still_running(podman: Podman, container: str) -> bool:
    """Say whether the container named `container` may still run: podman says it does, or can't say."""
    try:
        state = podman.state(container)
    except ContainerError:
        return True
    return state is not None and not stopped(state)


def named_session(
    adapter: Adapter, arguments: list[str], held: HeldLaunch | None
) -> NamedSession:
    """Return the runtime's id for the session a launch runs, where it's known before its room starts, and the runtime's arguments: a held launch's, named up front, new or resumed, before the operator's own; a terminal's, the one its arguments resume by its id, they unchanged.

    Raise `LaunchError` where a held launch resumes an id that can't be one of
    the runtime's.
    """
    holding = adapter.holding
    if held is None or holding is None:
        return NamedSession(
            session=an_id(adapter, adapter.resumed(arguments)), arguments=arguments
        )
    fresh = held.session or holding.minted()
    try:
        session = fresh if held.resume is None else holding.normal(held.resume)
        naming = (
            holding.fresh(session) if held.resume is None else holding.resuming(session)
        )
    except ValueError as unnamed:
        message = f"`{held.resume}` can't be a session of {adapter.runtime.name()}'s"
        raise LaunchError(message) from unnamed
    return NamedSession(session=session, arguments=[*naming, *held.arguments])


def an_id(adapter: Adapter, resumed: str | None) -> str | None:
    """Return what a terminal launch's arguments resume where it's one of the runtime's session ids, in the one form the runtime gives it, by which its writer's lock is kept and the host heard it; none for a search term its picker opens on, or for none."""
    if resumed is None:
        return None
    holding = adapter.holding
    try:
        return segment(resumed if holding is None else holding.normal(resumed))
    except ValueError:
        return None


def run_elsewhere(launcher: Launcher, session: str) -> Register | None:
    """Return the launch the host serves whose session's hooks name `session`, its latest; none where none does."""
    listed = launcher.host.listed()
    return next(
        (
            each
            for each in listed.launches
            if any(
                talker.session == session
                for talker in listed.talkers.get(each.launch, [])
            )
        ),
        None,
    )


def written_by(
    launcher: Launcher,
    writing: Writing,
    launch: str,
    *,
    held: bool,
    take_over: bool = False,
) -> FileLock:
    """Take the lock on the session's writer for `launch`, and return it held.

    Where a launch holds it already, a held launch refuses, naming it, and so
    does a terminal's where that launch is another terminal's, which ends it
    there. Where none holds it, but the host heard a served launch's hooks
    name the session, as a terminal's that started it with no id it knew, one
    `--continue`d, or one after `/clear`, it refuses too, naming that launch. Where it's a held one, the terminal's asks the operator whether to
    end it, its session taken over here once it lets the lock go
    (`lup_dev.launch.held`); `take_over` ends it asking nothing, and a
    terminal with no one to ask refuses.
    """
    holder = writing.held_by()
    if holder is None:
        running = run_elsewhere(launcher, writing.path.stem)
        if running is not None:
            message = (
                f"the session {writing.path.stem} is run by launch "
                f"`{running.name}`, its hooks naming it, though it holds no lock "
                "on its writer: a runtime lets a second process write one session, "
                "and its record branches, so end that one first"
            )
            raise LaunchError(message)
        return writing.taken(launch)
    if held:
        return writing.taken(launch)
    holding = next(
        (each for each in launcher.host.launches() if each.launch == holder), None
    )
    if holding is None or not holding.held:
        return writing.taken(launch)
    if not take_over:
        if launcher.ask is None:
            return writing.taken(launch)
        answer = launcher.ask(
            f"The session {writing.path.stem} is held by launch `{holding.name}`, "
            "with no terminal. End it and take it over here? [Y/n] "
        )
        if answer is None or answer.strip().lower() not in ["", "y", "yes"]:
            return writing.taken(launch)
    outstanding = launcher.host.held(End(launch=holder))
    try:
        outstanding.reply(Done)
    finally:
        outstanding.close()
    launcher.say(f"Launch `{holding.name}` ended; its session is taken over here.")
    return writing.taken(launch, within=timedelta(minutes=1))


def ended(launcher: Launcher, launch: str) -> None:
    """End a launch's registration, and remove its directory and its room's home (`vacated`).

    Where the host service can't end it, that's said, and the launch's record
    stays for the sweep.
    """
    try:
        launcher.host.unregister(launch)
    except HostError as failed:
        launcher.say(
            f"The host service didn't end launch {launch}: {failed}. The sweep "
            "ends it, once its container is gone too."
        )
    own = launcher.layout.launch(launch)
    released(launcher.podman, own, launcher.say)
    vacated(own)


def released(podman: Podman, launch: LaunchLayout, say: Callable[[str], None]) -> None:
    """Unmount what was lent to a launch's room while it ran; where podman can't, say so."""
    try:
        unlent(podman, launch)
    except ContainerError as failed:
        say(
            f"What was lent to launch {launch.directory.name} wasn't unmounted: {failed}"
        )


def launching(
    say: Callable[[str], None], *, unattended: bool = False, asked_for: str = ""
) -> Launcher:
    """Return what a launch reaches on this machine, as its settings place it.

    It runs outside every agent's session, which the command checks first.
    `unattended`, a held launch's launcher with no terminal, an approval waits
    for its answer in the inbox alone, what trust says going to `say`, and
    saying first whom it's asked for, `asked_for`, where that's said.
    """
    layout = Layout.of(LupDevSettings())
    clock = SystemClock()

    def trust(root: Path, found: Path) -> Outcome:
        if unattended:
            return machine_trust(
                root,
                [],
                asker=Unattended(say_to=say),
                found=found,
                asked_for=asked_for,
            ).ensure()
        return trusted(root, [], found=found)

    def github(repository: Path) -> GitHubRepository:
        return asyncio.run(named(repository))

    def asked(question: str) -> str | None:
        typer.echo(question, nl=False)
        said = sys.stdin.readline()
        return said.strip() if said else None

    return Launcher(
        layout=layout,
        trust=trust,
        host=HostClient(layout=layout.host, clock=clock, starter=host_starter(layout)),
        podman=Podman(),
        tools=Machine(),
        clock=clock,
        terminal=TerminalVariables(),
        say=say,
        github=github,
        facts=HostFacts(),
        rules=engine().rules,
        ask=asked if sys.stdin.isatty() and sys.stdout.isatty() else None,
    )


@app.command(
    "launch",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def launch(
    context: typer.Context,
    runtime: Annotated[str, typer.Argument(help="The runtime to launch, by its name.")],
    *,
    mount: Annotated[
        list[str] | None,
        typer.Option(
            "--mount",
            help=(
                "A directory this session may read, at its path, or a module whose "
                "data a launch lends, by its name (`transcripts`); repeat it."
            ),
        ),
    ] = None,
    mount_rw: Annotated[
        list[Path] | None,
        typer.Option(
            "--mount-rw",
            exists=True,
            file_okay=False,
            resolve_path=True,
            help="A directory this session may read and write, at its path; repeat it.",
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=(
                "Name this launch as it is, refused where another holds it; by "
                "default, its worktree's branch, numbered where that's taken."
            ),
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help=(
                "The profile this launch runs on, by its name among yours "
                "(`~/.config/lup/profiles.py`); by default, the one your own layer "
                "chooses for the repository, else `default`. The runtime's own "
                "`--profile` goes after `--`."
            ),
        ),
    ] = None,
    account: Annotated[
        str | None,
        typer.Option(
            "--account",
            help=(
                "The account this launch's runtime logs in with, by its name, in "
                "place of its profile's."
            ),
        ),
    ] = None,
    take_over: Annotated[
        bool,
        typer.Option(
            "--take-over",
            help=(
                "Where a launch lup holds with no terminal runs the session this "
                "resumes, end it and take the session over here, asking nothing."
            ),
        ),
    ] = False,
) -> None:
    """Launch a runtime's session in a room for this worktree, in this terminal.

    Run it yourself, in your own terminal: it first checks what the host runs for
    this repository, asking where that changed, as `trust` does. `--mount`
    lends a directory to this launch alone, read-only, and `--mount-rw` one it
    may write, each mounted at its path and listed in the session's guidance,
    with nothing declared. `--profile` and `--account` choose the profile it
    runs on and its runtime's account. Every argument
    after the runtime's name that lup doesn't know reaches the runtime's CLI as
    given, so `lup-dev launch <runtime> --resume` resumes, and every one after
    `--`, so a runtime's own flag of a name lup takes reaches it there. It ends
    with the CLI's exit status.
    """
    inside = [each.name() for each in runtimes() if each.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session: launch from your own terminal"
        )
        raise LaunchError(message)
    adapter = Adapters(known=adapters()).named(runtime)
    launcher = launching(typer.echo)
    reading = [Path(each).expanduser() for each in mount or []]
    lending = [
        *lent([each for each in reading if each.is_dir()], read_only=True),
        *lent(mount_rw or [], read_only=False),
    ]
    named = [str(each) for each in reading if not each.is_dir()]
    status = launched(
        adapter,
        list(context.args),
        toplevel(Path.cwd()),
        launcher,
        lending,
        modules=named,
        name=name,
        profile=profile,
        account=account,
        take_over=take_over,
    )
    raise typer.Exit(code=status)


def refused_inside(doing: str) -> None:
    """Refuse to run inside an agent's session, as a launch and an approval do: `doing` is what's refused, said."""
    inside = [each.name() for each in runtimes() if each.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session, and {doing} is the "
            "operator's: run it from your own terminal"
        )
        raise LaunchError(message)


def spawned(
    runtime: str,
    arguments: list[str],
    *,
    worktree: Path,
    name: str | None = None,
    profile: str | None = None,
    account: str | None = None,
    resume: str | None = None,
    restarts: int = 3,
) -> HeldUp:
    """Start a session of `runtime` lup holds with no terminal, in the worktree whose root is `worktree`, and return it once it's up.

    Where the service restarts meanwhile, as answering the launcher's approval
    restarts it, the wait is asked again of the one that runs next, `restarts`
    times at most.

    What the host runs is checked first, here, where an approval can be asked,
    as a launch does; then the host service starts the launch's launcher apart,
    which does the launch's whole setup and holds its session
    (`lup_dev.host.held`). Refused inside an agent's session.
    """
    refused_inside("starting a held session")
    adapter = Adapters(known=adapters()).named(runtime)
    if adapter.holding is None:
        message = f"{runtime} has no session held with no terminal yet"
        raise LaunchError(message)
    root = worktree
    launcher = launching(typer.echo)
    launcher.say(launcher.trust(root, located(root, None).git).report())
    launcher.say(
        "Starting the held session: the launcher sets its room up as a launch "
        "does, an image build taking minutes where one is missing."
    )
    starting = launcher.host.ask(
        Spawn(
            runtime=runtime,
            worktree=root,
            name=name,
            profile=profile,
            account=account,
            resume=resume,
            arguments=arguments,
        ),
        Starting,
    )
    launcher.say(f"Launch {starting.launch}'s launcher writes to {starting.log}.")
    awaiting = AwaitHeld(launch=starting.launch, pid=starting.pid)
    outstanding = launcher.host.held(awaiting)
    for _ in range(restarts):
        try:
            up = outstanding.reply(HeldUp)
        except KeyboardInterrupt:
            # Giving up here gives up the launch: its launcher, which may be
            # waiting on an approval in the inbox, never calls a session up after.
            launcher.host.ask(Abandon(launch=starting.launch, pid=starting.pid), Done)
            launcher.say(f"Launch {starting.launch} abandoned: its launcher is ended.")
            raise
        finally:
            outstanding.close()
        if up is not None:
            return up
        # The service closed the wait, as an approval the launcher asked
        # restarts it: the one that runs next is asked to wait on.
        launcher.say(
            "The host service restarted meanwhile; waiting on the launch with the "
            "one that runs now."
        )
        outstanding = launcher.host.rejoined(awaiting)
    outstanding.close()
    message = (
        f"the host service closed its wait on launch {starting.launch} "
        f"{restarts} times; `lup-dev sessions` says whether it runs"
    )
    raise HostError(message)


def spawning_command(runtime: str) -> Callable[..., None]:
    """Return the command starting a held session of `runtime`, which `lup-dev spawn <runtime>` runs."""

    def held(
        context: typer.Context,
        *,
        name: Annotated[
            str | None,
            typer.Option(
                "--name",
                help=(
                    "Name the launch as it is, refused where another holds it; by "
                    "default, its worktree's branch, numbered where that's taken."
                ),
            ),
        ] = None,
        resume: Annotated[
            str | None,
            typer.Option(
                "--resume",
                help=(
                    "The runtime's id for a session to resume, in this worktree; "
                    "by default, a new one."
                ),
            ),
        ] = None,
        profile: Annotated[
            str | None,
            typer.Option("--profile", help="The profile it runs on, by its name."),
        ] = None,
        account: Annotated[
            str | None,
            typer.Option(
                "--account", help="The account its runtime logs in with, by its name."
            ),
        ] = None,
    ) -> None:
        up = spawned(
            runtime,
            list(context.args),
            worktree=toplevel(Path.cwd()),
            name=name,
            profile=profile,
            account=account,
            resume=resume,
        )
        typer.echo(
            f"`{up.name}` holds the session {up.session}, with no terminal. "
            f"`lup-dev inbox send {up.name} TEXT` gives it your words, `lup-dev "
            f"spawn interrupt {up.name}` interrupts it, `lup-dev spawn end "
            f"{up.name}` ends it, and `lup-dev launch {runtime} --resume "
            f"{up.session}` takes it over in a terminal. Its launcher writes to "
            f"{up.log}."
        )

    held.__doc__ = (
        f"Start a {runtime} session lup holds with no terminal, in this worktree.\n\n"
        "Run it yourself, in your own terminal: it checks what the host runs "
        "first, as a launch does. The host service then starts the launch's "
        "launcher apart from itself, which sets its room up as a launch does and "
        "holds its session until it's ended, a restart of the service leaving it "
        "be. It returns once the session is up, the host having heard its first "
        "hook. Every argument it doesn't know, and each after `--`, reaches the "
        "runtime."
    )
    return held


def held_launch(to: str) -> Register:
    """Return the held launch `to` names, by its name, its id or its worktree; refuse one that isn't held."""
    client = host_client()
    launch = the_launch(client.launches(), to)
    if not launch.held:
        message = (
            f"`{launch.name}` runs in a terminal, which interrupts and ends it: only "
            "a held session is lup's to"
        )
        raise LaunchError(message)
    return launch


@spawn.command("interrupt")
def spawn_interrupt(
    to: Annotated[
        str,
        typer.Argument(help="The held launch, by its name, its id or its worktree."),
    ],
) -> None:
    """End the turn a held session has under way, a running command with it, as Escape does in a terminal."""
    refused_inside("interrupting a held session")
    launch = held_launch(to)
    host_client().ask(Interrupt(launch=launch.launch), Done)
    typer.echo(f"Interrupted `{launch.name}`.")


@spawn.command("end")
def spawn_end(
    to: Annotated[
        str,
        typer.Argument(help="The held launch, by its name, its id or its worktree."),
    ],
) -> None:
    """End a held session and its room, once a turn under way has finished: it resumes with `lup-dev spawn <runtime> --resume`, or in a terminal."""
    refused_inside("ending a held session")
    launch = held_launch(to)
    outstanding = host_client().held(End(launch=launch.launch))
    try:
        outstanding.reply(Done)
    finally:
        outstanding.close()
    typer.echo(f"Ended `{launch.name}`.")


@spawn.command("trial")
def spawn_trial(
    model: Annotated[
        str,
        typer.Option(
            "--model", help="The model the trial's session runs on, by its alias."
        ),
    ] = "haiku",
) -> None:
    """Try a held session end to end, once, on this machine, and file the report in your inbox.

    Run it yourself, in your own terminal, in a worktree of a repository you
    approved. In a scratch worktree beside this one, it starts a held session,
    sends it your words and sees its answer, interrupts a long turn, restarts
    the host service and sees the session survive, ends it, resumes it held,
    has a terminal launch take it over, and resumes it held again; then it
    removes the scratch worktree and files what passed, what failed and what
    that means (`lup_dev.launch.trial`). It takes a few minutes, a few short
    turns on your account, and a restart of the host service, which every
    launch outlives. The host service must run a copy of lup that holds
    sessions, one you approved with them.
    """
    refused_inside("the spawn trial")
    known = [each for each in adapters() if each.holding is not None]
    if not known:
        message = "no runtime lup knows has a held session yet"
        raise LaunchError(message)
    runtime = known[0].runtime.name()
    root = toplevel(Path.cwd())
    layout = Layout.of(LupDevSettings())

    def approved_commit(repository: Path) -> str | None:
        approval = approved(layout, repository)
        return None if approval is None else approval.commit

    scratch = scratched(root, f"spawn-trial-{secrets.token_hex(4)}", approved_commit)
    podman = Podman()
    trial: Trial | None = None
    try:

        def spawning(worktree: Path, resume: str | None) -> HeldUp:
            return spawned(
                runtime, ["--model", model], worktree=worktree, resume=resume
            )

        def terminal(worktree: Path, session: str) -> TerminalRun:
            return taken_over_there(worktree, session, runtime, model)

        def running(container: str) -> bool:
            return podman.state(container) == "running"

        def inside(container: str, command: list[str]) -> TerminalRun:
            ran = podman.inside(container, command)
            return TerminalRun(status=ran.status, output=ran.text())

        trial = Trial(
            host=host_client(),
            spawn=spawning,
            terminal=terminal,
            running=running,
            inside=inside,
            clock=SystemClock(),
            say=typer.echo,
            worktree=scratch.path,
        )
        trial.run()
        report = trial.report()
        typer.echo(report)
        number = trial.filed(scratch.repository, runtime)
        typer.echo(f"The report is {cited(number)} in your inbox.")
    finally:
        if trial is not None:
            scratch.unspawned(trial.spawned, typer.echo)
        scratch.removed()


@spawn.command("launcher", hidden=True)
def spawn_launcher(
    spec: Annotated[str, typer.Argument(help="The held launch, as JSON.")],
) -> None:
    """Hold a launch's session with no terminal, its setup a launch's: what the host service starts, apart from itself, for `lup-dev spawn`."""
    held = HeldLaunch.model_validate_json(spec)

    def said(line: str) -> None:
        typer.echo(line)
        sys.stdout.flush()

    adapter = Adapters(known=adapters()).named(held.runtime)
    status = launched(
        adapter,
        [],
        held.worktree,
        launching(said, unattended=True, asked_for=asked_for(held)),
        name=held.name,
        profile=held.profile,
        account=held.account,
        held=held,
    )
    raise typer.Exit(code=status)


def asked_for(held: HeldLaunch) -> str:
    """Say whom a held launch asks an approval for, first in it, where an agent spawned it: a room chose when it's asked, starting a session at whatever the running branch's tip then holds.

    The spawner's ids come from their room's hooks, free text: each is shown as
    code where it's an id's shape, letters, digits, `-`, `_` and `.`, else
    said to be none, never as what it says (`shown_id`).

    >>> from lup_dev.host.protocol import Spawner
    >>> from lup_ledger.parties import Conversation
    >>> spawner = Spawner(launch="a1", conversation=Conversation(repository=Path("/r.git"), runtime="r", session="s1", agent="**x**"))
    >>> print(asked_for(HeldLaunch(launch="b2", runtime="r", worktree=Path("/r.git/tree/x"), spawner=spawner)))
    **Asked by an agent's spawn,** not at your terminal: launch `a1`'s session `s1`, its subagent (an id lup won't show), spawned one in `/r.git/tree/x`, whose start waits on this. Declining it starts nothing.
    """
    spawner = held.spawner
    if spawner is None:
        return ""
    by = spawner.conversation
    agent = "" if by.agent is None else f", its subagent {shown_id(by.agent)}"
    return (
        f"**Asked by an agent's spawn,** not at your terminal: launch "
        f"{shown_id(spawner.launch)}'s session {shown_id(by.session)}{agent}, "
        f"spawned one in {shown_id(str(held.worktree))}, whose start waits on "
        "this. Declining it starts nothing."
    )


def shown_id(value: str) -> str:
    """Show `value`, an id or a path a room may have chosen, as code where it holds only an id's or a path's letters, digits, `-`, `_`, `.` and `/`; else say it isn't shown, so nothing a room wrote reads as markup.

    >>> shown_id("4f1e-c5"), shown_id("a`b")
    ('`4f1e-c5`', "(an id lup won't show)")
    """
    plain = all(each.isascii() and (each.isalnum() or each in "-_./") for each in value)
    return f"`{value}`" if value and plain else "(an id lup won't show)"


def machine_accounts() -> Accounts:
    """Return every account on this machine, by the runtimes lup knows, as the settings place them."""
    return Accounts(
        layout=Layout.of(LupDevSettings()).accounts,
        runtimes=[
            RuntimeLogin(name=each.runtime.name(), login=each.login)
            for each in adapters()
        ],
    )


for known in adapters():
    spawn.command(
        known.runtime.name(),
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )(spawning_command(known.runtime.name()))


@account.command("list")
def account_list() -> None:
    """List every account, `default` first, and the runtimes each holds a login for.

    Each is kept at `~/.local/share/lup/accounts/<name>/`, a directory per
    runtime; `default` is listed whether or not anything signed in to it yet.
    """
    for line in machine_accounts().listed():
        typer.echo(line)


@account.command("logout")
def account_logout(
    name: Annotated[str, typer.Argument(help="The account, by its name.")],
    runtime: Annotated[
        str | None,
        typer.Argument(
            help="The runtime to log it out of, by its name; by default, every one."
        ),
    ] = None,
) -> None:
    """Log an account out of a runtime, or of every one: its login file is emptied in place, which a room's own logout can't do through a mount.

    Run it yourself, in your own terminal. The login is forgotten on this
    machine alone: it isn't revoked with the provider.
    """
    inside = [each.name() for each in runtimes() if each.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session: log an account out from your "
            "own terminal"
        )
        raise AccountError(message)
    for line in machine_accounts().logout(name, runtime):
        typer.echo(line)


@account.command("migrate")
def account_migrate(
    *,
    move: Annotated[
        bool,
        typer.Option(
            "--move",
            help="Move them; without it, a dry run says what would move and changes nothing.",
        ),
    ] = False,
    shared: Annotated[
        bool,
        typer.Option(
            "--shared",
            help=(
                "Move them into the rooms' home every project shares, as a profile "
                'with `rooms_home="global"` runs on, rather than this project\'s.'
            ),
        ),
    ] = False,
) -> None:
    """Move this repository's sessions from your own runtime directories into its rooms' home, so they resume in a room; a dry run without `--move`.

    Run it yourself, in your own terminal, in the repository, every session of
    it ended. Every room could write your own directories until rooms had
    homes of their own, so every record of the repository's directories
    moves, whoever wrote it, and the rest stay. It then says what a host
    session acts on there that a room could have written, and how to replace
    your host login, which every room could read. A launch offers the same
    move for its runtime before its room starts, until one is made; this moves
    whatever's there whenever it's run.
    """
    inside = [each.name() for each in runtimes() if each.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session: move your sessions from "
            "your own terminal"
        )
        raise AccountError(message)
    layout = Layout.of(LupDevSettings())
    repository = Path(
        Git(cwd=Path.cwd()).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
    )
    if approved(layout, repository) is None:
        message = (
            f"nothing is approved for {repository}, so no room has run in it: "
            "nothing of it is to move"
        )
        raise AccountError(message)
    migrating = Migrating(
        layout=layout,
        repository=repository,
        runtimes=[host_runtime(each) for each in adapters()],
        home=Path.home(),
        shared=shared,
    )
    for line in migrating.said(move=move):
        typer.echo(line)


@app.command("mount")
def mount(
    lending: Annotated[
        str,
        typer.Argument(
            help=(
                "The directory to lend, or a module whose data a launch lends, by "
                "its name (`transcripts`)."
            )
        ),
    ],
    *,
    writable: Annotated[
        bool,
        typer.Option("--rw", help="Lend the directory writable; read-only otherwise."),
    ] = False,
    to: Annotated[
        str | None,
        typer.Option(
            "--launch",
            help=(
                "The launch, by its name, its id or its worktree; by default, the "
                "one here."
            ),
        ),
    ] = None,
) -> None:
    """Lend a directory to a launch's running room, at once, without restarting it.

    Run it yourself, in your own terminal. The room finds it under `/lent`, by
    its name, read-only, or writable with `--rw`, until the launch ends; the session is told where, through the inbox. The launch is the one
    whose worktree holds the directory this runs in, the only one running
    where there's one, or the one `--launch` names.
    """
    client = answering()
    launch = the_launch(client.launches(), to)
    layout = Layout.of(LupDevSettings())
    given = Path(lending).expanduser()
    data = layout.module_data(lending, launch.repository)
    source, module = (
        (given.resolve(), False) if given.is_dir() else (data, data.is_dir())
    )
    if not source.is_dir():
        message = (
            f"`{lending}` names neither a directory nor a module whose data this "
            "repository's launches lend"
        )
        raise RoomError(message)
    sealed = not writable or module
    room = lend(
        Podman(),
        layout.launch(launch.launch),
        source,
        read_only=sealed,
        name=lending if module else None,
    )
    access = "read-only" if sealed else "writable"
    what = f"the `{lending}` module's data (`{source}`)" if module else f"`{source}`"
    told = client.ask(
        SendItem(
            launch=launch.launch,
            text=(
                f"The operator lent {what} to this session, {access}, at `{room}`: "
                "it's there now, until the session ends."
            ),
        ),
        Shown,
    ).item
    typer.echo(
        f"Lent {source} to launch {launch.launch}, {access}, at {room} in its room; "
        f"{cited(told.number)} tells its session."
    )


@rules.command("list")
def rules_list(
    *,
    every: Annotated[
        bool,
        typer.Option(
            "--all",
            help=(
                "Every rule of lup's table, each this project doesn't run marked "
                "`(left out)`."
            ),
        ),
    ] = False,
) -> None:
    """List the rules this project runs: the mistake each prevents, and its steer.

    The worktree's own declaration is read, as `rules check` reads it, and the
    engine resolves its selection as it does for a check.
    """
    checker = engine()
    running = checker.rules(Declaration.read(toplevel(Path.cwd())).rules)
    runs = [rule.id for rule in running]
    for rule in checker.rules() if every else running:
        mark = "" if rule.id in runs else " (left out)"
        typer.echo(f"{rule.id}{mark}: {rule.mistake}\n    steer: {rule.steer}")


@rules.command("docs")
def rules_docs() -> None:
    """Write `docs/rules.md`, compiled from the engine's rule table."""
    target = CheckoutLayout(root=toplevel(Path.cwd())).rules_reference
    target.write_text(reference(engine().rules()))
    typer.echo(f"wrote {target}")


class Scanned(Model):
    """What checking files as the gate does found: the files checked, and each finding."""

    files: list[Path]
    findings: list[Finding]
    unreachable: str | None = None
    """Why deferrals' issues weren't checked, where they weren't."""
    unread: list[Path] = []
    """The files left out, which resolve outside the worktree, its links
    followed: lup doesn't read them (`lup_dev.confined`)."""
    held: list[str] = []
    """The conditions the project declares that held, each asked once."""


def scanned(paths: list[Path] | None, *, issues: bool) -> Scanned:
    """Check `paths`, or every file the worktree's roles check, as the gate does.

    lup's rules are those the worktree's declaration selects, sent to the engine
    as the judge sends them, pyright reading the environment the declaration's
    runner names, and ruff is lup's own, as the judge's are. `# lup: ignore`
    applies to every owner's findings. With `issues`, the issue a deferral or an
    `ignore` waits on is checked: on GitHub, or in a room through the host
    service; without, it goes unchecked. Each file is read only where it
    resolves inside the worktree (`lup_dev.confined`): one that doesn't is left
    out, unread, and named; so is a path given that isn't in the worktree at all,
    as a scratch file elsewhere, whatever the roles say.
    """
    root = toplevel(Path.cwd())
    layout = Layout.of(LupDevSettings())
    worktree = Worktree.at(root, layout)

    def placed(path: Path) -> Path | None:
        """Return `path` from the root, its directory resolved; none where that directory is outside the root."""
        directory = (root / path).parent.resolve()
        if not directory.is_relative_to(root):
            return None
        return directory.relative_to(root) / path.name

    placing = {path: placed(path) for path in paths or []}
    elsewhere = [path for path, place in placing.items() if place is None]
    inside = [place for place in placing.values() if place is not None]
    listed = (
        inside
        if paths
        else [
            Path(name)
            for name in nul_separated(
                Git(cwd=root)
                .run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
                .output
            )
            if (root / name).is_file()
        ]
    )
    checked = [path for path in listed if worktree.roles.checked(path)]
    within = Confined(root=root)
    unread = [*elsewhere, *(path for path in checked if within.outside(path))]
    read = {path: within.text(path) for path in checked if path not in unread}
    files = [path for path, content in read.items() if content is not None]
    if not files:
        return Scanned(files=[], findings=[], unread=unread)
    sources = [Source(path=path, content=read[path]) for path in files]
    declaration = worktree.declaration
    reports = engine().check(root, sources, declaration.rules, declaration.runner)
    ruff = Ruff().findings(root, sources)
    conditions = loaded(root, declaration.conditions)
    tracker: Issues | None = None
    unreachable: str | None = None
    if issues:
        room = RoomClient()
        tracker = (
            HostIssues(client=room, say=typer.echo)
            if room.socket.exists()
            else GitHubIssues(root=root)
        )
        unreachable = tracker.unreachable()
    held = holding(conditions)
    named = [
        issue
        for report in reports
        for directive in report.directives
        if (issue := waited_on(directive)) is not None
    ]
    asked = (
        AskedOnce.of(tracker, named)
        if tracker is not None and unreachable is None
        else None
    )
    gate = Trackers(issues=asked, held=held)

    def found(path: Path) -> list[Finding]:
        report = next(each for each in reports if each.path == path)
        every = [*report.findings, *(each for each in ruff if each.path == path)]
        kept = worktree.roles.kept(report, every)
        checking = Checking(
            fired=[Fired(rule=each.rule, line=each.span.start.line) for each in every],
            conditions=list(conditions),
            gate=gate,
        )
        problems = [
            finding(path, problem)
            for directive in report.directives
            for problem in directive.problems(checking)
        ]
        return [*kept, *problems]

    findings = [each for path in files for each in found(path)]
    return Scanned(
        files=files,
        findings=findings,
        unreachable=unreachable,
        unread=unread,
        held=held,
    )


@rules.command("check")
def rules_check(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Files to check; every file the roles check, by default."),
    ] = None,
) -> None:
    """Check files as the gate does: lup's rules, pyright, ruff and the deferrals.

    lup's rules are those the worktree's declaration selects, sent to the engine
    as the judge sends them, and pyright and ruff run through its runner as the
    judge runs them. `# lup: ignore` applies to every owner's findings. A
    deferral whose issue is closed, or whose condition holds, is due, and so is
    an `ignore` whose issue is closed, which is listed and doesn't fail the
    check; where the issue tracker can't be
    reached (no `gh`, no login, offline), the
    issues go unchecked and the check says why. In a room, which holds no `gh`,
    the host service is asked each issue's state on the launch's request socket,
    and an issue it doesn't answer goes unchecked, said. lup's rules read production and
    protected modules; tests are checked by
    pyright and ruff only; what the declaration excludes isn't checked. With no
    paths, it checks every such file in the worktree, as the gate's `rules` step
    runs it. An `ignore` that keeps nothing fails it too, until `lup-dev rules
    fix` removes it. What came due is kept, over every file and where every
    issue was asked, for a session to be told at their start, with each
    condition the project declares that held, which wakes a thread parked
    until it.
    """
    found = scanned(paths, issues=True)
    if found.unread:
        named = ", ".join(str(each) for each in found.unread)
        typer.echo(f"lup didn't read {named}: each resolves outside the worktree.")
    if not found.files:
        typer.echo("lup checked no files.")
        return
    failing = [each for each in found.findings if not each.reminder]
    due = Due(
        reminders=[each for each in found.findings if each.reminder], held=found.held
    )
    for line in (line for each in failing for line in finding_lines(each, "")):
        typer.echo(line)
    if due.reminders:
        typer.echo(due.told())
    if found.unreachable is not None:
        typer.echo(
            f"The issues `# lup:` comments wait on weren't checked: {found.unreachable}."
        )
    if paths is None and found.unreachable is None:
        common = Git(cwd=toplevel(Path.cwd())).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        write_model(GitDirectoryLayout(common=Path(common)).due, due)
    typer.echo(f"lup checked {len(found.files)} files: {len(failing)} findings.")
    if failing:
        raise typer.Exit(code=1)


def worktree_files(root: Path) -> list[Sent]:
    """Return each file of the worktree at `root` git doesn't ignore, tracked or not, whole, by its path from the root."""
    listed = Git(cwd=root).run(
        "ls-files", "-z", "--cached", "--others", "--exclude-standard"
    )
    return [
        Sent.of(name, (root / name).read_bytes())
        for name in nul_separated(listed.output)
        if (root / name).is_file()
    ]


def withheld_here(common: Path) -> Withheld | Read:
    """Return the list of values never published kept for the repository whose git directory is `common`, building it where none is kept, as a launch would; or, where it isn't read, what the gate says.

    It's built from the declaration at the commit approved for the repository on
    this machine, with the person's own layer approved beside it. Where nothing
    is approved, as on a machine no launch ran on, nothing is read; where it
    can't be built, the gate fails, saying why.
    """
    layout = Layout.of(LupDevSettings())
    held = read_model(kept(layout.module_data(Private.name, common)), Withheld)
    if held is not None:
        return held
    approval = approved(layout, common)
    if approval is None:
        return Read(unchecked=UNAPPROVED)
    try:
        with approved_declaration(
            common, approval.commit, local=approval.local
        ) as declared:
            made = asyncio.run(listed(declared.resolved, common, HostFacts(), layout))
    except (LupDevError, OSError) as failed:
        return Read(unbuilt=f"the host couldn't build it: {failed}")
    if made is None:
        return Read(unchecked=UNSELECTED)
    return made.withheld


@private.command("check")
def private_check() -> None:
    """Read the worktree for a value never published, as the gate's `private` step does, failing on one.

    Every file git doesn't ignore, whole, its path too, and the commits `HEAD`
    reaches that the repository's remotes lack, each as a push reads it. Each
    value found is said by its kind and place, never the value. On the host it
    reads the list kept for the repository, building it where none is, as a
    launch would; in a room, which never sees the list, the host reads them on
    the launch's request socket. Where no launch was approved on this machine,
    as in CI, or the host can't be reached from a room, it says so and passes:
    the push or the post is where a value is refused. Where the list can't be
    built, it fails, saying why.
    """
    root = toplevel(Path.cwd())
    files = worktree_files(root)
    head = Git(cwd=root).commit("HEAD")
    room = RoomClient()
    if room.socket.exists():
        try:
            scan = room.ask(Scanning(files=files, head=head), Read)
        except HostError as refused:
            typer.echo(f"Values never published weren't read: the host said {refused}.")
            return
    else:
        common = Path(
            Git(cwd=root).text(
                "rev-parse", "--path-format=absolute", "--git-common-dir"
            )
        )
        match withheld_here(common):
            case Withheld() as held:
                scan = read_for_values(files, head, common, held)
            case Read() as said:
                scan = said
    if scan.unbuilt is not None:
        typer.echo(f"Values never published weren't read: {scan.unbuilt}.")
        raise typer.Exit(code=1)
    for each in scan.found:
        typer.echo(f"{each.place.text()} - private: {each.what}")
        typer.echo(f"    steer: {each.steer}")
    if scan.unchecked is not None:
        typer.echo(f"Not read: {scan.unchecked}.")
    commits = "commit" if scan.commits == 1 else "commits"
    typer.echo(
        f"lup read {len(files)} files and {scan.commits} {commits} for values "
        f"never published: {len(scan.found)} found."
    )
    if scan.found:
        raise typer.Exit(code=1)


@rules.command("fix")
def rules_fix(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Files to fix; every file the roles check, by default."),
    ] = None,
) -> None:
    """Remove each `# lup: ignore` that keeps nothing, as `lup-dev check --fix` does.

    An `ignore` whose rule doesn't fire on the line it covers is never told to
    an agent: it's removed here, its line with it where nothing else is on it,
    and nothing else changes. The formatter, which `--fix` runs after, tidies
    what's left.
    """
    root = toplevel(Path.cwd())
    fixing = [
        each
        for each in scanned(paths, issues=False).findings
        if each.owner == "lup" and each.fixable
    ]
    lines = {
        path: [each.span.start.line for each in fixing if each.path == path]
        for path in dict.fromkeys(each.path for each in fixing)
    }
    for path, numbers in lines.items():
        file = root / path
        file.write_text(without(file.read_text(), numbers))
        typer.echo(f"{path}: removed {len(numbers)} `# lup: ignore` keeping nothing")


@app.command("check")
def check(
    *,
    fix: Annotated[
        bool,
        typer.Option(
            "--fix",
            help="First apply ruff's safe fixes and the formatter, rewriting files.",
        ),
    ] = False,
    again: Annotated[
        bool,
        typer.Option(
            "--again",
            help="Run every step even where the gate passed on these files already.",
        ),
    ] = False,
    at: Annotated[
        str | None,
        typer.Option(
            "--at",
            metavar="COMMIT",
            help=(
                "Run the gate on a commit, in a worktree made at it, unless it "
                "passed on that commit's files already."
            ),
        ),
    ] = None,
) -> None:
    """Run the gate, every step even after one fails, and fail if any did.

    The steps are the worktree's declaration's, and so is how the project runs
    its tools: lup's rules (`rules check`), ruff, the formatter, pyright, pytest
    and the import contracts by default, with what its modules add, such as lup's
    own engine, rebuilt unless it passed on its sources as they stand. Its modules'
    requirements are checked first,
    all at once: a required tool missing stops the gate before any step. Each
    step's outcome is reported, then each failure's output in full; the exit code
    is non-zero when any step failed. With `--fix`, ruff's safe fixes and the
    formatter rewrite the worktree first.

    A pass is recorded for the worktree's files, in the repository's git
    directory, and a later run on the same files finds it and runs nothing but
    the builds stale in its worktree, unless `--again`. With `--at`, the gate
    runs on a commit, in a worktree made at it and removed after, unless it
    passed on the commit's files already: a push to a gated branch from a
    room runs it so. With `--fix` too, where the fixes change files,
    they're committed in a commit with the same parents and message, which it
    names and no branch does: `land` runs it so on the merge it makes.
    """
    root = toplevel(Path.cwd())
    passes = Passes.of(root, SystemClock())
    if at is None:
        gated = Check.declared(root, Shell(), Machine(), fix=fix, passes=passes).run(
            again=again
        )
        typer.echo(report(gated))
        if failed(gated.outcomes):
            raise typer.Exit(code=1)
        return
    runner = resolve(load(root, local=person_layer(root)).project).runner

    def stop(made: Path) -> None:
        scrapped(made, runner)

    outcome = at_commit(
        root,
        at,
        Shell(),
        passes,
        runner,
        say=typer.echo,
        stop=stop,
        again=again,
        fix=fix,
    )
    match outcome:
        case Passed():
            typer.echo(outcome.said())
        case Amended(ran=ran):
            typer.echo(ran.output, nl=False)
            typer.echo(outcome.said())
        case GateRan(code=code, output=output):
            typer.echo(output, nl=False)
            if code != 0:
                raise typer.Exit(code=code)


@app.command("stage")
def stage(
    path: Annotated[
        Path, typer.Argument(help="The file whose hunks to list or stage.")
    ],
    hunks: Annotated[
        list[int] | None,
        typer.Argument(
            help="The hunks to stage, by their numbers in the listing; none lists them."
        ),
    ] = None,
    *,
    first: Annotated[
        int | None,
        typer.Option(
            "--from",
            metavar="LINE",
            help=(
                "Stage what changed from this line of the file as it stands to "
                "`--to`'s, both taken: the lines added there, those they replace, "
                "and lines removed between two of them."
            ),
        ),
    ] = None,
    last: Annotated[
        int | None,
        typer.Option(
            "--to",
            metavar="LINE",
            help="The last line `--from` takes; by default, `--from`'s own.",
        ),
    ] = None,
    whole: Annotated[
        bool,
        typer.Option(
            "--whole", help="List every line of each hunk, not only its first."
        ),
    ] = False,
) -> None:
    """Stage chosen hunks of a file into the index, or list them, numbered: `git add -p` without a terminal.

    Given only the file, it lists its changes against the index, each hunk
    numbered with the file's lines it covers and its first lines. Given
    numbers, it stages those hunks; given `--from` and `--to`, what changed on
    those lines, which splits a hunk too coarse to stage whole. Then it says
    what it staged and how many hunks are left, numbered afresh, while the
    file's line numbers stay as they were. It never commits, and keeps the
    index entry's mode. `git restore --staged <path>` unstages the file whole.
    """
    if first is None and last is not None:
        message = "`--to` ends the range `--from` starts: give `--from` too"
        raise StagingError(message)
    changed = Changed.of(path)
    if not hunks and first is None:
        typer.echo(changed.listed(whole=whole))
        return
    lines = (
        None
        if first is None
        else Lines(first=first, last=first if last is None else last)
    )
    typer.echo(changed.stage(hunks or [], lines).said(whole=whole))


@app.command("merge", hidden=True)
def merge(
    base: Annotated[
        str,
        typer.Argument(help="The commit it goes onto: the running branch's tip."),
    ],
    tip: Annotated[str, typer.Argument(help="The commit merged: the branch's tip.")],
) -> None:
    """Merge `tip` onto `base` apart from every checkout, run the gate on the merge with its fixes, and print what came of it as JSON: what `land` runs in a launch's room.

    The merge commit's message is read from standard input
    (`lup_dev.merging`). What the gate says as it goes is on standard error.
    """
    root = toplevel(Path.cwd())
    runner = resolve(load(root, local=person_layer(root)).project).runner

    def stop(made: Path) -> None:
        scrapped(made, runner)

    def say(line: str) -> None:
        typer.echo(line, err=True)

    merging = merged(
        root,
        base,
        tip,
        sys.stdin.read(),
        processes=Shell(),
        passes=Passes.of(root, SystemClock()),
        runner=runner,
        say=say,
        stop=stop,
    )
    typer.echo(TypeAdapter[Merging](Merging).dump_json(merging).decode())


@app.command("gate-commit", hidden=True)
def gate_commit(
    commit: Annotated[str, typer.Argument(help="The commit to run the gate on.")],
) -> None:
    """Run the gate on `commit` without its fixes, and print what came of it as JSON: what `land` runs in a launch's room for what the host computed (`lup_dev.merging`). What the gate says as it goes is on standard error."""
    root = toplevel(Path.cwd())
    runner = resolve(load(root, local=person_layer(root)).project).runner

    def stop(made: Path) -> None:
        scrapped(made, runner)

    def say(line: str) -> None:
        typer.echo(line, err=True)

    gating = gated_commit(
        root,
        commit,
        processes=Shell(),
        passes=Passes.of(root, SystemClock()),
        runner=runner,
        say=say,
        stop=stop,
    )
    typer.echo(TypeAdapter[Merging](Merging).dump_json(gating).decode())


def scrapped(worktree: Path, runner: Runner) -> None:
    """End what a gate run left for the worktree at `worktree`, which goes next: its engine, the store keeping the engine's lock and log, and in a room, the environment made for it among the launch's (`LUP_ENVIRONMENTS`).

    An engine that can't be told to stop is said, and stops on its own once
    idle (`LUP_ENGINE_IDLE`).
    """
    settings = LupDevSettings()
    try:
        EngineChecker.configured(settings).stop(worktree, runner)
    except EngineError as failure:
        typer.echo(
            f"The engine the gate started for {worktree} wasn't stopped: {failure}. "
            "It stops on its own once idle.",
            err=True,
        )
    store = Layout.of(settings).store(worktree).home
    if store.exists():
        shutil.rmtree(store)
    if settings.lup_environments is not None:
        made = environment(settings.lup_environments, worktree)
        if made.is_dir():
            shutil.rmtree(made)


@app.command("trust")
def trust() -> None:
    """Approve what the host runs for this repository, as a launch does first.

    Run it yourself, in your own terminal. It reads the host zone at the
    running branch's tip, running none of it: the declaration, the files it
    runs on the host, and the `lup-dev` the host runs. Where that isn't the zone you
    approved last, it puts the approval in your inbox, starting the host service
    where none runs, and here prints a summary of what changed since (git's count
    of each file), offers the whole diff through your pager, and asks; `lup-dev
    inbox answer` at any other terminal answers it too, whichever comes first.
    Approved, it installs the tip's `lup-dev` as the host's, restarts the host
    service on it where one runs, and records the approval; declined, the copy you
    approved before keeps running. Where nothing changed, it says so and stops.
    Its repository is found once, from this worktree, as a launch finds it,
    refusing a worktree it doesn't name back (`located`).
    """
    inside = [runtime.name() for runtime in runtimes() if runtime.inside()]
    root = toplevel(Path.cwd())
    trust = machine_trust(root, inside, found=located(root, None).git)
    typer.echo(trust.ensure().report())
    kept = trust.kept_first()
    if kept is not None:
        typer.echo(kept)


@app.command("restore")
def restore(
    commit: Annotated[
        str | None,
        typer.Argument(
            help="The commit of the copy to go back to, or its start; left out, the copies are listed and nothing changes."
        ),
    ] = None,
    *,
    ledger: Annotated[
        bool,
        typer.Option(
            help="Put the ledger back as that copy left it too, losing what happened since, which it says and asks about first."
        ),
    ] = False,
    attempt: Annotated[
        bool,
        typer.Option(
            "--try",
            help="Run that copy on a copy of your state, beside the service you have, and say whether it answers, moving nothing.",
        ),
    ] = False,
) -> None:
    """Go back to a copy of `lup-dev` kept, or list them, with or without a host service or a dashboard.

    The last resort, in your own terminal. Your `lup-dev` hands this command to
    the copy that answered before the one running, so it works whatever is wrong
    with that one. It stops the host service if one runs, snapshots the ledger,
    moves the host service, the judge and your `lup-dev` to the copy, with what
    was approved with it, starts the service, and checks that it and the
    dashboard answer, putting back what it moved where they don't. A later launch
    asks about the running branch's tip again.

    A commit you approved whose copy is gone is built again from the commit. The
    ledger is left as it is unless you ask, or the copy can't read it as it stands.
    """
    inside = [runtime.name() for runtime in runtimes() if runtime.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session, and which `lup-dev` runs is "
            "the operator's: run it in your own terminal"
        )
        raise RestoreError(message)
    layout = Layout.of(LupDevSettings())
    clock = SystemClock()
    host = HostClient(
        layout=layout.host,
        clock=clock,
        starter=host_starter(layout),
        timeout=timedelta(seconds=10),
    )

    def built_again(kept: Kept, then: Callable[[Kept], Switch]) -> Switch:
        root = Git.pinned(kept.repository).main_worktree()
        trust = machine_trust(root, [])
        with trust.built(kept.approval, layout.judge(kept.repository)) as built:
            return then(built)

    restoring = Restoring(
        layout=layout,
        host=host,
        switcher=Switching(
            layout=layout,
            host=host,
            answers=Serving(clock=clock),
            processes=Programs(),
            clock=clock,
        ),
        confirm=typer.confirm,
        built_again=built_again,
        say=typer.echo,
    )
    if commit is None:
        typer.echo(restoring.listing())
        return
    if attempt:
        why = restoring.tried(commit)
        if why is not None:
            typer.echo(f"It doesn't answer, and nothing moved. Why: {why}")
            raise typer.Exit(1)
        typer.echo("It answers, on a copy of your state, and nothing moved.")
        return
    try:
        switch = restoring.restored(commit, ledger=ledger)
    except (RestoreError, HostError) as refused:
        # A page started this, and is waiting to hear: a terminal has been told.
        if not sys.stdin.isatty():
            write_model(
                layout.host.switched,
                LastSwitch(
                    commit=commit, at=clock.now(), said=str(refused), answered=False
                ),
            )
        raise
    typer.echo(switch.report())
    if not isinstance(switch, Switched):
        raise typer.Exit(1)


def trial_lines(listed: TrialListed | None) -> list[str]:
    """Say what's on trial: `dev` and the branches in `live`, a line for each other with what keeps it out, and what to type."""
    if listed is None:
        return ["This repository computes no running branch, so nothing is on trial."]
    integration, running = listed.integration, listed.running
    within = [each.branch for each in listed.branches if each.within]
    holds = (
        f"`{running}`: `{integration}` with {in_sentence(within)}."
        if within
        else f"`{running}`: `{integration}` alone."
    )

    def line(each: BranchListed) -> str:
        built = ", its copy built" if each.built else ""
        where = (
            f"in `{running}`"
            if each.within
            else each.conflict
            or ("out: you took it out" if each.out else f"not in `{running}` yet")
        )
        return f"- `{each.branch}` at {each.tip}: {where}{built}. {each.subject}"

    return [
        holds,
        *(["Nothing is on trial."] if not listed.branches else []),
        *map(line, listed.branches),
        "",
        (
            "`lup-dev live pick [branch…]` runs those on "
            f"`{integration}`; `lup-dev live accept <branch>` merges one there; "
            "`lup-dev live drop <branch>` takes it off trial. `/copies`, on the "
            "dashboard, picks too."
        ),
    ]


def live_client(*, patience: timedelta = timedelta(minutes=1)) -> HostClient:
    """Return the host service's client for what the operator asks of what's on trial, waiting `patience` for each reply, refusing inside an agent's session: which code the host runs, and what's accepted, are theirs."""
    inside = [runtime.name() for runtime in runtimes() if runtime.inside()]
    if inside:
        message = (
            f"this runs inside a {inside[0]} session, and what the host runs and "
            "what's accepted are the operator's: run it in your own terminal"
        )
        raise HostError(message)
    layout = Layout.of(LupDevSettings())
    return HostClient(
        layout=layout.host,
        clock=SystemClock(),
        starter=host_starter(layout),
        timeout=patience,
    )


def here_repository() -> Path | None:
    """Return the git directory of the repository this runs in; none outside one, where lup's own is meant."""
    try:
        common = Git(cwd=Path.cwd()).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
    except GitError:
        return None
    return Path(common)


def said_of_trial(replied: TrialSaid) -> None:
    """Print what came of what was asked of what's on trial, and how that stands."""
    if replied.said:
        typer.echo(replied.said)
    if replied.switching is not None:
        typer.echo(
            f"What came of it is in {replied.switching.log}; `lup-dev restore` goes back."
        )
        return
    if replied.said:
        typer.echo()
    typer.echo("\n".join(trial_lines(replied.listed)))


@live.callback(invoke_without_command=True)
def live_list(context: typer.Context) -> None:
    """Say what's on trial, what's in the running branch, and what conflicts, changing nothing."""
    if context.invoked_subcommand is not None:
        return
    said_of_trial(live_client().ask(ListTrial(repository=here_repository()), TrialSaid))


@live.command("pick")
def live_pick(
    branches: Annotated[
        list[str] | None,
        typer.Argument(help="The branches to run on `dev`; none runs `dev` alone."),
    ] = None,
) -> None:
    """Run `dev` plus exactly these branches.

    Your own terminal's, as `/copies` on the dashboard does it. Where you've said
    yes to that set and its copy is kept, the host moves to it at once, restarting.
    Where you haven't, the approval is in your inbox, whose yes builds it, in
    minutes, and moves there. Branches that conflict can't be picked together, which
    it says, moving nothing.
    """
    request = PickBranches(branches=branches or [], repository=here_repository())
    said_of_trial(live_client().ask(request, TrialSaid))


@live.command("accept")
def live_accept(
    branch: Annotated[str, typer.Argument(help="The branch on trial to accept.")],
) -> None:
    """Merge a branch on trial onto `dev`, at the tip it landed with, and clean up after it, as a landing does.

    Its merge's gate runs, and its worktree goes, in the room of the session that
    landed it, or another of the repository's: with none running, this says so.
    Threads parked on it wake. A branch already in the running branch changes nothing
    the host runs, so nothing is asked and nothing restarts.
    """
    client = live_client(patience=timedelta(days=1))
    request = AcceptBranch(branch=branch, repository=here_repository())
    said_of_trial(client.ask(request, TrialSaid))


@live.command("drop")
def live_drop(
    branch: Annotated[str, typer.Argument(help="The branch to take off trial.")],
    *,
    say: Annotated[
        str,
        typer.Option(
            help="What you say on it, which reaches who landed it, or waits for them."
        ),
    ] = "",
) -> None:
    """Take a branch off trial, leaving it and its worktree; landing it again puts it back.

    Where it was in the running branch, what runs moves as a pick without it does.
    """
    request = DropBranch(branch=branch, words=say, repository=here_repository())
    said_of_trial(live_client().ask(request, TrialSaid))


@app.command("verdicts")
def verdicts(
    days: Annotated[int, typer.Option(help="How many days back to count.")] = 7,
) -> None:
    """Summarize this repository's verdicts by outcome and reason."""
    layout = Layout.of(LupDevSettings())
    common = Git(cwd=Path.cwd()).text(
        "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    log = VerdictLog(path=layout.verdicts(Path(common)))
    since = SystemClock().now() - timedelta(days=days)
    tallies = log.summary(since)
    if not tallies:
        typer.echo(f"No verdicts in the last {days} days.")
        return
    for tally in tallies:
        typer.echo(tally.line())


@app.command("importers", hidden=True)
def importers(
    worktree: Path,
    environments: Annotated[
        Path | None,
        typer.Option(
            help="The launch's own environments, where the hook was a room's."
        ),
    ] = None,
) -> None:
    """Run a worktree's background importers pass; the checkpoint starts it.

    The engine is asked with the runner of the declaration the judge reads there,
    the approved commit's, and the environments of the launch whose hook started
    it, so the pass and the judge share one engine.
    """
    judging = services(environments)
    repository = Worktree.at(worktree, judging.layout).repository
    judged = Worktree.of(worktree, repository, judging)
    judged.importers().run(judging.checker, judged.declaration.runner)


def built_in() -> list[str]:
    """Return the commands `lup-dev` holds itself, by name: a first word that's none of them names a module, whose commands come under it."""
    group = typer.main.get_command(app)
    return list(group.commands) if isinstance(group, TyperGroup) else []


def module_command(words: list[str]) -> bool:
    """Say whether `words`, the command line after `lup-dev`, name one of the repository's modules' commands rather than one of `lup-dev`'s own."""
    return bool(words) and not words[0].startswith("-") and words[0] not in built_in()


def module_ran(words: list[str]) -> None:
    """Run the module command `words` names, in this process (`commanding.py`).

    In a room, from the worktree's own declaration, as the room. On the host,
    as the operator, by the repository's approved copy: any other `lup-dev`
    hands it over to that copy, becoming it.
    """
    git = Git(cwd=Path.cwd())
    repository = Path(
        git.text("rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    layout = Layout.of(LupDevSettings())
    room = RoomClient()
    if room.socket.exists():
        root = Path(git.text("rev-parse", "--show-toplevel"))
        exchanges = RoomExchanges(room=room, repository=repository)
        modules = RepositoryModules.of_worktree(
            root,
            repository,
            recorded(),
            layout,
            exchanges=exchanges,
            marks=RoomMarks(room=room),
        )

        def asker() -> RoomAsker:
            shown = FromRoom(room=room).ask(ShowOwnLaunch(), OwnLaunch)
            return RoomAsker(launch=shown.launch)

        commanding.run(words, modules.resolved.served, modules.made, asker)
        return
    command = approved_command(layout, repository)
    if not commanding.approved(Path(sys.argv[0]), command):
        commanding.handed_over(words, command, repository)
    modules = RepositoryModules.loaded(repository, services(), recorded())

    def inside() -> str | None:
        return next((each.name() for each in runtimes() if each.inside()), None)

    commanding.run(
        words, modules.resolved.served, modules.made, Operator, inside=inside
    )


def module_commands_said() -> str:
    """Say which of the repository's modules have commands, for `lup-dev --help`: from the worktree's declaration in a room, from the one the operator approved on the host, whose code alone the host runs; why not, where it can't be read."""
    try:
        git = Git(cwd=Path.cwd())
        root = Path(git.text("rev-parse", "--show-toplevel"))
        if RoomClient().socket.exists():
            served = resolve(load(root).project).served
        else:
            repository = Path(
                git.text("rev-parse", "--path-format=absolute", "--git-common-dir")
            )
            approval = approved(Layout.of(LupDevSettings()), repository)
            if approval is None:
                return "Nothing is approved for this repository, so its modules' commands don't run here."
            with approved_declaration(
                repository, approval.commit, local=approval.local
            ) as declared:
                served = declared.resolved.served
    except (LupDevError, LupError) as unread:
        return f"This repository's modules' commands couldn't be listed: {unread}"
    named = list(
        dict.fromkeys(
            owner.module.name
            for owner in served
            for method in methods(owner.serving).values()
            if method.commanded() or method.viewing() is not None
        )
    )
    if not named:
        return ""
    listed = ", ".join(f"`lup-dev {name}`" for name in named)
    return f"This repository's modules' commands come under their names: {listed}."


def helped() -> None:
    """Show `lup-dev`'s help, then which of the repository's modules have commands."""
    try:
        app()
    finally:
        said = module_commands_said()
        if said:
            typer.echo(said)


def main() -> None:
    """Run the command line, reporting lup's own errors without a traceback.

    The library's own (`LupError`) among them: a launch's room, and its runtime's
    declaration, are the library's. A first word that isn't one of `lup-dev`'s
    own commands names a module, whose commands it runs (`module_ran`); its
    help names the modules that have commands (`module_commands_said`).
    """
    try:
        words = sys.argv[1:]
        if module_command(words):
            module_ran(words)
            return
        if words in ([], ["--help"]):
            helped()
            return
        app()
    except (LupDevError, LupError) as failure:
        typer.echo(f"lup-dev: {failure}", err=True)
        raise SystemExit(1) from failure


if __name__ == "__main__":
    main()
