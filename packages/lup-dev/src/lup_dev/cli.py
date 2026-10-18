"""The `lup-dev` command: the hooks, the gate's rule check, the inbox and verdicts.

It stands in for the real `lup` command tree until the declaration and command
line piece builds it; the commands keep their meaning there, and their final
names are that piece's call (`docs/judging-writes.md`, *Modules*). It's the one
place that lists the runtimes' adapters: the host service reads each hook and
adds to its answer with the courier built here, and answers a hook a launch's
judge couldn't with the answerer (`docs/launch.md`); `hook` answers through it.

`trust` approves what the host runs for a repository, the check a launch makes
first (`docs/launch.md`, *Trust on launch*). `launch` opens a runtime's session in
a room for the worktree (*The command*). `host` runs the host service, handed
the inbox as what each conversation is told at its hooks, its tools and its
requests; `inbox` is the operator's face on it (`docs/host-tools.md`, *The
operator's face*).
"""

import asyncio
import secrets
import shutil
import sys
import webbrowser
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, override

import typer
from filelock import FileLock
from filelock import Timeout as Held
from pydantic import TypeAdapter, ValidationError

from lup.errors import LupError
from lup.rooms import ContainerError, Mount, Podman, Room
from lup.transcripts import views
from lup.transcripts.module import Transcripts
from lup.types import Model

# lup: ignore("runtime-mention", why="the one place listing the adapters")
from lup_dev.adapters import Adapter, claude, codex
from lup_dev.approval import approved
from lup_dev.clipboard.desktop import Desktop
from lup_dev.clipboard.protocol import routes as clipboard_routes
from lup_dev.clock import Clock, SystemClock
from lup_dev.codescan.conditions import loaded
from lup_dev.codescan.contract import Checker, Due, Finding, Source
from lup_dev.codescan.directives import (
    Checking,
    Fired,
    GitHubIssues,
    HostIssues,
    Issues,
    Trackers,
    without,
)
from lup_dev.codescan.engine import EngineChecker, EngineError
from lup_dev.codescan.reference import reference
from lup_dev.codescan.ruff import Ruff
from lup_dev.declaration.load import load, person_layer
from lup_dev.declaration.requirements import Machine, Report, Tools
from lup_dev.declaration.requirements import check as checked
from lup_dev.declaration.resolve import resolve
from lup_dev.errors import LupDevError
from lup_dev.forge.github import PROGRAM, GitHubError, named
from lup_dev.gate import Check, Passed, Passes, Shell, at_commit, failed, report
from lup_dev.gate import Ran as GateRan
from lup_dev.git import Git, nul_separated
from lup_dev.host.client import Detached, HostClient, RoomClient
from lup_dev.host.courier import (
    Courier,
    Heard,
    Printed,
    Spawned,
    Spawns,
    Telling,
)
from lup_dev.host.dashboard import (
    DashboardProcess,
    DashboardShown,
    ShowDashboard,
    Showing,
)
from lup_dev.host.names import shaped
from lup_dev.host.protocol import GitHubRepository, HostError, Listed, Register
from lup_dev.host.records import Called, Recorded
from lup_dev.host.service import Answerer, HostService, Naming, Route
from lup_dev.host.watch import Changes
from lup_dev.host.workers import Workers
from lup_dev.inbox.delivery import (
    Delivery,
    clocked,
    opening,
    standing,
    what,
    who,
)
from lup_dev.inbox.notices import NotifySend
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AnswerItem,
    Context,
    FinishItem,
    Items,
    ListInbox,
    SendItem,
    Settled,
    ShowContext,
    ShowDiff,
    ShowItem,
    Shown,
    Whole,
)
from lup_dev.inbox.protocol import routes as inbox_routes
from lup_dev.inbox.store import (
    Answer,
    Approval,
    Comment,
    HeldChange,
    Inbox,
    InboxError,
    Item,
    Message,
    Party,
    Question,
    Review,
    Ruling,
    Verdict,
)
from lup_dev.inbox.store import Conversation as InboxConversation
from lup_dev.inbox.tools import InboxTools
from lup_dev.launch.clis import CliCache
from lup_dev.launch.images import build
from lup_dev.launch.room import (
    Lent,
    RoomClipboard,
    RoomError,
    host_needs,
    lend,
    lent,
    maintaining_room,
    receiving,
    refreshed,
    related,
    room_git,
    unlent,
)
from lup_dev.launch.session import (
    LaunchError,
    approved_declaration,
    hooked,
    terminal_settings,
)
from lup_dev.launch.trust import (
    Approving,
    Given,
    InboxApprovals,
    Outcome,
    Terminal,
    machine_trust,
    trusted,
)
from lup_dev.layout import (
    ROOM_SOCKETS,
    CheckoutLayout,
    GitDirectoryLayout,
    HostLayout,
    Layout,
)
from lup_dev.policy.checkpoint import Bench, Services, Worktree
from lup_dev.policy.holds import InboxAnnouncing, Response, answer
from lup_dev.policy.importers import BackgroundSpawner
from lup_dev.policy.judge import finding
from lup_dev.policy.report import finding_lines
from lup_dev.policy.tools import JudgeTools
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.remote.config import Gating
from lup_dev.remote.protocol import Remotes
from lup_dev.remote.protocol import routes as remote_routes
from lup_dev.settings import LupDevSettings, TerminalVariables
from lup_dev.stored import write_model
from lup_dev.worker import worked

if TYPE_CHECKING:
    from lup.tools.tool import ToolSpec
    from lup_dev.declaration.resolve import Resolved
    from lup_dev.declaration.runner import Runner
    from lup_dev.host.records import Transcript
    from lup_dev.host.rooms import RoomTools
    from lup_dev.policy.runtime import Runtime

app = typer.Typer(no_args_is_help=True, help="Develop a project with agents.")
rules = typer.Typer(no_args_is_help=True, help="lup's code rules.")
host = typer.Typer(help="lup's host service, which rooms call.")
inbox = typer.Typer(help="What your agents tell and ask you, and your answers.")
transcripts = typer.Typer(
    no_args_is_help=True,
    help=(
        "This repository's past sessions, as lup keeps them: your words first, "
        "each with what it answered."
    ),
)
app.add_typer(rules, name="rules")
app.add_typer(host, name="host")
app.add_typer(inbox, name="inbox")
app.add_typer(transcripts, name="transcripts")


def engine() -> Checker:
    """Return the typed engine the judge asks about files, as this machine sets it."""
    return EngineChecker.configured(LupDevSettings())


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

    def answer(self, runtime: str, payload: str) -> str:
        """Answer one of `runtime`'s hooks, judging with this machine's services.

        What the hook prints is its adapter's output on a line, or nothing.
        """
        adapter = self.named(runtime)
        bench = Bench(runtime=adapter.runtime, services=services())
        output = adapter.hook(payload, bench)
        return f"{output}\n" if output else ""

    @override
    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        """Answer one of `runtime`'s hooks a launch's judge couldn't, as its adapter says it, on a line."""
        return f"{self.named(runtime).unanswered(payload, failure)}\n"


class SpawnRecords(Model, Spawns):
    """How every runtime lup knows recorded its subagents' spawns, as its adapter reads them."""

    adapters: Adapters

    @override
    def spawned(self, runtime: str, payload: str) -> Spawned | None:
        return self.adapters.named(runtime).spawned(payload)


class Couriers(Model, Courier):
    """Every runtime lup knows, as the host service reads its hooks and adds to their answers."""

    adapters: Adapters

    @override
    def heard(self, runtime: str, payload: str) -> Heard:
        return self.adapters.named(runtime).heard(payload)

    @override
    def told(
        self, runtime: str, payload: str, answer: str, telling: Telling
    ) -> Printed:
        """Return what one of `runtime`'s hooks prints, its adapter's answer with `telling` added, on a line, or `answer` as it is; and whether it lets a turn end."""
        adapter = self.adapters.named(runtime)
        added = adapter.told(payload, answer, telling)
        text = answer if added is None else f"{added}\n"
        return Printed(text=text, ends=adapter.ends(text))

    @override
    def woken(self, runtime: str, session: str, text: str) -> str | None:
        spelled = self.adapters.named(runtime).woken
        return None if spelled is None else spelled(session, text)


def services() -> Services:
    """Return what judging reaches, as configured on this machine."""
    settings = LupDevSettings()
    return Services(
        checker=engine(),
        linter=Ruff(),
        clock=SystemClock(),
        layout=Layout.of(settings),
        spawner=BackgroundSpawner(),
        integration=settings.lup_integration_branch,
        announcing=InboxAnnouncing(
            layout=Layout.of(settings).host, clock=SystemClock()
        ),
    )


def toplevel(directory: Path) -> Path:
    """Return the root of the git worktree holding `directory`."""
    return Path(Git(cwd=directory).text("rev-parse", "--show-toplevel"))


def branch_name(worktree: Path) -> str:
    """Return a launch's name by default: the branch the worktree at `worktree` has checked out, in a name's shape (`feat/x` is `feat-x`), or the worktree's directory's where none is."""
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
    """Answer one of a runtime's hooks, its payload on stdin."""
    known = Adapters(known=adapters())
    # An unknown runtime is refused before standard input is read.
    known.named(runtime)
    typer.echo(known.answer(runtime, sys.stdin.read()), nl=False)


def host_client() -> HostClient:
    """Return the host service's client, as this machine places the service."""
    return HostClient(
        layout=Layout.of(LupDevSettings()).host, clock=SystemClock(), starter=Detached()
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


@host.callback(invoke_without_command=True)
def host_serve(context: typer.Context) -> None:
    """Run the host service in the foreground, until it's stopped.

    It answers each launch's hooks as `lup-dev hook` does, on the launch's own
    socket. `lup-dev host stop` or Ctrl-C stops it; the launches it serves stay
    recorded, and the next service serves them.
    """
    if context.invoked_subcommand is not None:
        return
    known = Adapters(known=adapters())
    couriers = Couriers(adapters=known)
    settings = LupDevSettings()
    layout = Layout.of(settings)
    changes = Changes()
    dashboard = installed_dashboard(settings, layout.host)
    delivery = Delivery(
        inbox=Inbox.opened(layout.inbox, changes),
        courier=couriers,
        layout=layout.host,
        notices=NotifySend(),
        clock=SystemClock(),
        say=typer.echo,
        settle_hold=lambda change, approved, said: hold_answered(
            layout, change, approved=approved, comment=said
        ),
    )
    service = HostService(
        layout=layout.host,
        answerer=known,
        courier=couriers,
        spawns=SpawnRecords(adapters=known),
        post=delivery,
        routes=[
            *inbox_routes(delivery, recorded()),
            Route.to(dashboard_shown(dashboard)),
        ],
        tools=room_tools(delivery, layout),
        room_routes=[
            *remote_routes(
                Remotes(say=typer.echo, landed=partial(proposed_after, delivery))
            ),
            *clipboard_routes(Desktop.of(settings)),
        ],
        modules=Workers(layout=layout.host, say=typer.echo),
        say=typer.echo,
        refresh=lambda launch: refreshed(layout.launch(launch.launch)),
        changes=changes,
        companions=[] if dashboard is None else [dashboard],
    )
    asyncio.run(service.serve())


async def proposed_after(delivery: Delivery, launch: Register, refs: list[str]) -> None:
    """Put the approval of the host zone at the integration branch's tip in the operator's inbox, where a launch's push moved that branch and the zone isn't the one approved.

    Trust reads the zone with git and asks the service itself, so it runs off
    the event loop. Its repository is the launch's git directory, found
    through git from its main worktree; one holding a `commondir`, which would
    lead git elsewhere, isn't read (`docs/host-tools.md`, *Running git on the
    host*). The approval names the main conversation of the session the launch
    runs, as `delivery` last heard it, which the operator's comment on their
    answer is told to: a push comes from the room's git, not from a call, so
    which of the session's conversations pushed isn't known. What fails is said
    in the service's log, and the push stands.
    """
    integration = LupDevSettings().lup_integration_branch
    if f"refs/heads/{integration}" not in refs:
        return
    if (launch.repository / "commondir").exists():
        typer.echo(
            f"{launch.launch}: the push moved {integration}, but its approval "
            f"wasn't asked: {launch.repository} holds a `commondir`, which would "
            "lead git to another repository"
        )
        return
    root = Git.pinned(launch.repository).main_worktree()
    pushed_by = delivery.running(launch.launch)
    try:
        number = await asyncio.to_thread(machine_trust(root, []).proposed, pushed_by)
    except (LupDevError, LupError) as failure:
        typer.echo(
            f"{launch.launch}: the push moved {integration}, but its approval "
            f"wasn't asked: {failure}"
        )
        return
    if number is not None:
        typer.echo(
            f"{launch.launch}: the push moved {integration}, and with it the code "
            f"the host runs: approval item {number} is in the inbox"
        )


def room_tools(delivery: Delivery, layout: Layout) -> list[RoomTools]:
    """List the core's tools the host service serves each launched session: the inbox's, and the judge's, reading lup's state at `layout`."""
    return [InboxTools(delivery=delivery), JudgeTools(layout=layout)]


def served_tools(resolved: Resolved) -> list[ToolSpec]:
    """List what a launched session is told of each of lup's tools, which its guidance lists: the core's, then its modules'.

    The core's are read from the tools the service is handed, made over a
    delivery and a layout without their fields: what a tool is doesn't depend
    on whom it delivers to or where lup's state is. The modules' are read from
    their classes, with no instance.
    """
    core = [
        spec
        for tools in room_tools(Delivery.model_construct(), Layout.model_construct())
        for spec in tools.specs()
    ]
    naming = Naming.model_construct().specs()
    modules = [spec for each in resolved.served for spec in each.tools.specs()]
    return [*core, *naming, *modules]


@app.command("worker", hidden=True)
def worker(
    socket: Annotated[Path, typer.Argument(help="Where to answer the host service.")],
) -> None:
    """Serve a launch's modules on `socket`, its registration on standard input's first line: for the host service."""
    records = {adapter.runtime.name(): adapter.records for adapter in adapters()}
    worked(socket, services(), records)


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


def line(item: Item, listed: Listed | None = None) -> str:
    """Say an item in a line: its number, when it was made, what it is, from whom (as it's called, where `listed` knows it), and its first line; for an approval, how to read it whole and answer it."""
    where = "" if item.worktree is None else f" in {item.worktree}"
    reading = (
        f" (`answer {item.number}` shows its summary, offers its whole diff, and "
        f"asks; `show {item.number} --diff` pages the diff alone)"
        if isinstance(item.reason, Approval)
        else ""
    )
    return (
        f"{item.number:>4}  {clocked(item.made)}  {what(item)} from "
        f"{sender_named(item.sender, listed or Listed(launches=[]))}{where}: "
        f"{opening(item)}{reading}"
    )


def sender_named(party: Party, listed: Listed) -> str:
    """Say who `party` is: a conversation as it's called first, where `listed` knows it: a subagent by its path while its launch runs, a session's own by its launch's name."""
    talkers = [each for launch in listed.talkers.values() for each in launch]
    match party:
        case InboxConversation(session=session, agent=str() as agent):
            found = [
                each
                for each in talkers
                if each.session == session and each.agent == agent
            ]
            return f"`{found[0].path}` ({who(party)})" if found else who(party)
        case InboxConversation(session=session) if session in listed.sessions:
            return f"`{listed.sessions[session]}` ({who(party)})"
        case _:
            return who(party)


def settled(*, approved: bool) -> str:
    """Say an approval's answer in a word."""
    return "approved" if approved else "declined"


def heading(item: Item) -> str:
    """Say what an item is, whose to whom, when it was made and where it stands."""
    where = "" if item.worktree is None else f" in {item.worktree}"
    return (
        f"Item {item.number}, {what(item)} from {who(item.sender)}{where} to "
        f"{who(item.recipient)}, made {clocked(item.made)}, {standing(item)}:"
    )


def hold_answered(
    layout: Layout, change: HeldChange, *, approved: bool, comment: str
) -> None:
    """Write the operator's answer to a held change where its hook waits for it, or a later checkpoint tells it."""
    answer(
        layout,
        change.key,
        Response(approved=approved, comment=comment),
        runtimes(),
        SystemClock(),
    )


def shown(item: Item) -> str:
    """Say an item whole, for the operator: an approval by its summary, its whole diff on request."""
    match item.reason:
        case Message(text=text):
            body = [text]
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
            body = [f"To item {question}.", *decided, comment]
        case (
            Approval(text=text, summary=summary)
            | HeldChange(text=text, summary=summary)
        ):
            body = [
                summary,
                "",
                text,
                f"The whole diff: `lup-dev inbox show {item.number} --diff`.",
            ]
        case Review(covers=covers, comments=comments):
            body = [
                f"Of items {', '.join(str(each) for each in covers)}.",
                *(commented(each) for each in comments),
            ]
    return "\n".join([heading(item), *body])


def commented(comment: Comment) -> str:
    """Say one comment of a review, for the operator: where it's on, then what it says."""
    if comment.quote is None:
        return f"On item {comment.item}: {comment.text}"
    return f'On item {comment.item}, "{comment.quote.text}": {comment.text}'


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


def prompted(item: Item) -> AnswerItem:
    """Ask the operator their answer to a question, each decision in turn, then a comment on the whole; a plain question, or a reply to a message, in words."""
    typer.echo(shown(item))
    match item.reason:
        case Message():
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
            message = f"item {item.number} is {what(item)}: nothing to answer"
            raise InboxError(message)


def kept_sessions(directory: Path) -> list[Transcript]:
    """Read every session lup keeps of the repository `directory` is in, of every runtime it knows."""
    repository = Path(
        Git(cwd=directory).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
    )
    data = Layout.of(LupDevSettings()).module_data(Transcripts.name, repository)
    return [
        each.reader.read(record)
        for each in adapters()
        for record in each.reader.sessions(data / each.runtime.name())
    ]


@transcripts.command("list")
def transcripts_list() -> None:
    """List this repository's kept sessions, newest first: when each started, its name and id, how often you spoke, where it ran."""
    lines = views.listed(kept_sessions(Path.cwd()))
    typer.echo(
        "\n".join(lines) if lines else "No session of this repository is kept yet."
    )


@transcripts.command("show")
def transcripts_show(
    session: Annotated[
        str,
        typer.Argument(help="The session: its id, the start of its id, or its name."),
    ],
    *,
    everything: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Everything said, the agent's words too, each run of tool calls a line.",
        ),
    ] = False,
) -> None:
    """Show what you said in a session, each time after what the agent last said before it; or, with `--all`, the whole conversation."""
    chosen = views.chosen(kept_sessions(Path.cwd()), session)
    typer.echo(views.whole(chosen) if everything else views.answered(chosen), nl=False)


@transcripts.command("search")
def transcripts_search(
    words: Annotated[list[str], typer.Argument(help="Words you said, all of them.")],
) -> None:
    """Find each time you said all of `words`, in any kept session: when, your words, and what they answered."""
    typer.echo(views.found(kept_sessions(Path.cwd()), words), nl=False)


@app.command("sessions")
def sessions() -> None:
    """List the sessions the host service serves, each with its subagents under it.

    Run it yourself, in your own terminal. Each launch by its name, its runtime,
    its worktree and its id; under it, its session and each subagent beneath
    the conversation that spawned it, by its path (`dev/explore-auth`) and its
    kind; an unnamed one by its kind and its id, until it names itself.
    """
    listed = answering().listed()
    if not listed.launches:
        typer.echo("No session runs.")
        return
    for launch in listed.launches:
        typer.echo(
            f"`{launch.name}`  {launch.runtime} in {launch.worktree}  ({launch.launch})"
        )
        for talker in listed.talkers.get(launch.launch, []):
            kind = "" if talker.kind is None else f"  {talker.kind}"
            typer.echo(f"{'  ' * (talker.depth + 1)}{talker.path}{kind}")


@app.command("dashboard")
def dashboard_open(
    *,
    opened: Annotated[
        bool,
        typer.Option(
            "--open/--no-open",
            help="Open it in your browser, or only print where it is.",
        ),
    ] = True,
) -> None:
    """Open the dashboard: every agent, what each is doing, and your inbox, in one page.

    Run it yourself, in your own terminal. It prints the dashboard's address, its
    token after the `#`, and opens it in your browser; the host service runs the
    dashboard, starting it again where it's gone.
    """
    shown = answering("the dashboard").ask(ShowDashboard(), DashboardShown)
    typer.echo(shown.address)
    if opened:
        webbrowser.open(shown.address)


@inbox.callback(invoke_without_command=True)
def inbox_list(context: typer.Context) -> None:
    """List what waits for you from your agents, oldest first.

    Run it yourself, in your own terminal. Each item has a number, which `show`,
    `answer` and `done` take.
    """
    if context.invoked_subcommand is not None:
        return
    client = answering()
    items = client.ask(ListInbox(), Items).items
    if not items:
        typer.echo("Nothing waits for you.")
        return
    listed = client.listed()
    for item in items:
        typer.echo(line(item, listed))


@inbox.command("show")
def inbox_show(
    number: Annotated[int, typer.Argument(help="The item's number.")],
    *,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="An approval's whole diff, through your pager."),
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
    client = answering()
    if diff:
        Terminal().show(client.ask(ShowDiff(number=number), Whole).text)
        return
    typer.echo(shown(client.ask(ShowItem(number=number), Shown).item))
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
            f"Item {number} was {settled(approved=given.approved)} already, "
            "elsewhere: your answer changes nothing."
        )
    return (
        f"Item {number} is {settled(approved=given.approved)}: each launch waiting "
        "on it goes on."
    )


def acted_on(approval: Approval, given: Given) -> str | None:
    """Act on an approval approved at this terminal, as a launch waiting on it would, once between them, and say what came of it; none for an approval declined, which leaves the copy approved before.

    An approval may have nobody waiting on it: a push that moved the
    integration branch asks it from the host (`proposed_after`).
    """
    if not given.approved:
        return None
    root = Git.pinned(approval.repository).main_worktree()
    outcome = machine_trust(root, []).settle(approval.fingerprint, given)
    if outcome is None:
        return (
            "The integration branch moved since this was asked, so its tip isn't "
            "the code you read: `lup-dev trust` asks about it."
        )
    return outcome.report()


@inbox.command("answer")
def inbox_answer(
    number: Annotated[int, typer.Argument(help="The item's number.")],
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
    """
    client = answering()
    approvals = InboxApprovals(host=client)
    item = client.ask(ShowItem(number=number), Shown).item
    if isinstance(item.reason, HeldChange):
        held_answer(client, item, approve=approve, comment=comment)
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
                    summary=f"{heading(item)}\n{summary}",
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
                request = prompted(item)
    else:
        request = AnswerItem(number=number, rulings=given, comment=comment or "")
    answer = client.ask(request, Shown).item
    done = "Replied to" if isinstance(answer.reason, Message) else "Answered"
    noun = "reply" if isinstance(answer.reason, Message) else "answer"
    typer.echo(
        f"{done} item {number}: your {noun}, item {answer.number}, is for "
        f"{who(answer.recipient)}."
    )


def held_answer(
    client: HostClient, item: Item, *, approve: bool | None, comment: str | None
) -> None:
    """Answer a held change: as given, or asked at this terminal after its summary and diff."""
    if approve is None:
        typer.echo(shown(item))
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
        f"Item {item.number}: you {told}; the agent waiting on it goes on."
        if settled.here
        else f"Item {item.number} was answered already, elsewhere: yours changes nothing."
    )


@inbox.command("done")
def inbox_done(
    number: Annotated[int, typer.Argument(help="The message's number.")],
) -> None:
    """Take a message you've read off your list."""
    answering().ask(FinishItem(number=number), Shown)
    typer.echo(f"Item {number} is done.")


@inbox.command("send")
def inbox_send(
    to: Annotated[
        str,
        typer.Argument(
            help=(
                "The launch, by its name, its id or its worktree; or one of its "
                "subagents, by its path (`dev/explore-auth`)."
            )
        ),
    ],
    text: Annotated[str, typer.Argument(help="What to tell it.")],
) -> None:
    """Send a message to the session a launch runs, its main conversation; or to one of its subagents, by its path."""
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
                f"Sent item {sent.item.number} to `{to}`, {who(sent.item.recipient)}."
            )
            return
        case _:
            pass
    launch = the_launch(listed.launches, to)
    sent = client.ask(SendItem(launch=launch.launch, text=text), Shown).item
    typer.echo(f"Sent item {sent.number} to `{launch.name}`, {who(sent.recipient)}.")


class Addressed(Model):
    """A subagent a message is sent to: the launch its session runs in, and the runtime's id for it."""

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
    refused, saying whose. The session hears its name at its next start, where
    its runtime takes it as its own title, where the runtime has a way.
    """
    client = answering()
    launch = the_launch(client.launches(), to)
    renamed = client.rename(launch.launch, name)
    typer.echo(f"Launch {renamed.launch} is `{renamed.name}`.")


class Launcher(Model, arbitrary_types_allowed=True):
    """What a launch reaches on this machine, each a seam a test stubs."""

    layout: Layout
    trust: Callable[[Path], Outcome]
    """Checks what the host runs for the repository at a worktree, asking where it changed."""
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


def swept(launcher: Launcher) -> None:
    """End each launch the host service serves whose launcher and container are both gone.

    A launcher holds its launch's lock for its whole life, which the OS frees, so
    a launch whose lock can be taken has no launcher left; its container, named
    when it registered, tells whether its session still runs. Each launch ended
    is said, and a launch another launcher ended first is passed over.
    """
    for each in launcher.host.launches():
        own = launcher.layout.launch(each.launch)
        own.lock.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(own.lock, timeout=0)
        try:
            lock.acquire()
        except Held:
            continue
        try:
            if launcher.podman.exists(each.container):
                continue
            try:
                launcher.host.unregister(each.launch)
            except HostError as gone:
                launcher.say(f"Launch {each.launch} was ended already: {gone}")
                continue
            released(launcher, each.launch)
            if own.directory.is_dir():
                shutil.rmtree(own.directory)
            launcher.say(
                f"Ended launch {each.launch}, {each.runtime} in {each.worktree}: its "
                f"launcher and its container, {each.container}, are gone."
            )
        finally:
            lock.release()
        own.lock.unlink(missing_ok=True)


def launched(
    adapter: Adapter,
    arguments: list[str],
    worktree: Path,
    launcher: Launcher,
    lending: list[Lent] | None = None,
    *,
    modules: list[str] | None = None,
    name: str | None = None,
) -> int:
    """Launch `adapter`'s runtime in a room for `worktree`, in this terminal, and return its CLI's exit status.

    In the order `docs/launch.md` gives (*The command*): trust on launch, its
    report said; the declaration at the commit approved, with the person's own
    layer approved beside it; the host's requirements, each optional one off
    said; the repository named on GitHub, or why not said; the host service; the
    latest CLI, a fallback said; the other repositories the declaration names
    for its sessions to read, each missing one said; the room, its image built
    where it's missing; the terminal settings; the repository's `config` checked
    for the room's git; the sweep, then the launch registered, under its
    launcher's lock; the room's git configuration and helper written; the CLI in
    the room, with `arguments` after lup's own. The registration ends, and the launch's directory goes,
    whatever the CLI did.
    """
    runtime = adapter.runtime.name()
    launcher.say(launcher.trust(worktree).report())
    repository = Path(
        Git(cwd=worktree).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
    )
    approval = approved(launcher.layout, repository)
    if approval is None:
        message = f"nothing is approved for {repository}, so nothing launches"
        raise LaunchError(message)
    judge = launcher.layout.judge(repository).command(approval.tool.name)
    with approved_declaration(
        worktree, approval.commit, local=approval.local
    ) as declared:
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
        neighbours = related(declared.resolved.repositories, worktree)
        for each in neighbours:
            if not each.mounted:
                launcher.say(
                    f"The repository `{each.name}` the declaration names for "
                    f"sessions to read isn't at {each.path}, so the room doesn't "
                    "mount it, and its guidance says it's missing."
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
        room = maintaining_room(
            declared.resolved,
            worktree,
            launcher.layout,
            launcher.terminal,
            launcher.tools,
            neighbours=neighbours,
            shared=shared,
            lent=lending,
        )
        built = build(
            room.image, launcher.podman, launcher.clock, launcher.layout.builds
        )
        if built is not None:
            launcher.say(f"Built the room's image in {built.took()}: {built.tag}.")
        launch = secrets.token_hex(8)
        own = launcher.layout.launch(launch)
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
        )
        gating = Gating(
            command=declared.resolved.runner.command(["lup-dev", "check", "--at"]),
            refs=declared.resolved.limits.gated,
        )
        git = room_git(
            repository,
            own,
            [*room.mounts, *adapter.agent().terminal(settings).mounts],
            gating,
        )
        registered = Register(
            launch=launch,
            runtime=runtime,
            worktree=worktree,
            repository=repository,
            judge=judge,
            container=f"lup-{launch}",
            limits=declared.resolved.limits,
            github=github,
            name=name or branch_name(worktree),
            exact=name is not None,
        )
        own.lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(own.lock):
                swept(launcher)
                served = launcher.host.register(registered)
                sockets = served.directory
                launcher.say(f"This launch is `{served.name}`.")
                try:
                    git.write()
                    clipboard = RoomClipboard(launch=own)
                    clipboard.write()
                    receives = receiving(launcher.podman, own)
                    walled = room.model_copy(
                        update={
                            "name": registered.container,
                            "mounts": [
                                *room.mounts,
                                *git.mounts,
                                Mount(source=sockets, target=ROOM_SOCKETS),
                                receives,
                            ],
                            "env": {**room.env, **git.env, **clipboard.env},
                        }
                    )
                    opened = Room(
                        agent=adapter.agent(), container=walled, engine=launcher.podman
                    )
                    return opened.launch(arguments=arguments, settings=settings)
                finally:
                    ended(launcher, launch)
        finally:
            own.lock.unlink(missing_ok=True)


def ended(launcher: Launcher, launch: str) -> None:
    """End a launch's registration, and remove its directory.

    Where the host service can't end it, that's said, and the launch's record
    stays for the next launch's sweep.
    """
    try:
        launcher.host.unregister(launch)
    except HostError as failed:
        launcher.say(
            f"The host service didn't end launch {launch}: {failed}. The next "
            "launch ends it."
        )
    own = launcher.layout.launch(launch)
    released(launcher, launch)
    if own.directory.is_dir():
        shutil.rmtree(own.directory)


def released(launcher: Launcher, launch: str) -> None:
    """Unmount what was lent to a launch's room while it ran; where podman can't, say so."""
    try:
        unlent(launcher.podman, launcher.layout.launch(launch))
    except ContainerError as failed:
        launcher.say(f"What was lent to launch {launch} wasn't unmounted: {failed}")


def launching(say: Callable[[str], None]) -> Launcher:
    """Return what a launch reaches on this machine, as its settings place it.

    It runs outside every agent's session, which the command checks first.
    """
    layout = Layout.of(LupDevSettings())
    clock = SystemClock()

    def trust(root: Path) -> Outcome:
        return trusted(root, [])

    def github(repository: Path) -> GitHubRepository:
        return asyncio.run(named(repository))

    return Launcher(
        layout=layout,
        trust=trust,
        host=HostClient(layout=layout.host, clock=clock, starter=Detached()),
        podman=Podman(),
        tools=Machine(),
        clock=clock,
        terminal=TerminalVariables(),
        say=say,
        github=github,
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
) -> None:
    """Launch a runtime's session in a room for this worktree, in this terminal.

    Run it yourself, in your own terminal: it first checks what the host runs for
    this repository, asking where that changed, as `trust` does. `--mount`
    lends a directory to this launch alone, read-only, and `--mount-rw` one it
    may write, each mounted at its path and listed in the session's guidance,
    with nothing declared. Every argument
    after the runtime's name that lup doesn't know reaches the runtime's CLI as
    given, so `lup-dev launch <runtime> --resume` resumes. It ends with the CLI's
    exit status.
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
    )
    raise typer.Exit(code=status)


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
        f"item {told.number} tells its session."
    )


@rules.command("list")
def rules_list() -> None:
    """List the engine's rules: the mistake each prevents, and its steer."""
    for rule in engine().rules():
        typer.echo(f"{rule.id}: {rule.mistake}\n    steer: {rule.steer}")


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


def scanned(paths: list[Path] | None, *, issues: bool) -> Scanned:
    """Check `paths`, or every file the worktree's roles check, as the gate does.

    lup's rules are those the worktree's declaration selects, sent to the engine
    as the judge sends them, and pyright and ruff run through its runner as the
    judge runs them. `# lup: ignore` applies to every owner's findings. With
    `issues`, a deferral's issue is checked: on GitHub, or in a room through the
    host service; without, deferrals' issues go unchecked.
    """
    root = toplevel(Path.cwd())
    layout = Layout.of(LupDevSettings())
    worktree = Worktree.at(root, layout)
    chosen = [
        path.resolve().relative_to(root) if path.is_absolute() else path
        for path in paths or []
    ]
    listed = chosen or [
        Path(name)
        for name in nul_separated(
            Git(cwd=root)
            .run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            .output
        )
        if (root / name).is_file()
    ]
    files = [path for path in listed if worktree.roles.checked(path)]
    if not files:
        return Scanned(files=[], findings=[])
    sources = [Source(path=path) for path in files]
    declaration = worktree.declaration
    reports = engine().check(root, sources, declaration.rules, declaration.runner)
    ruff = Ruff().findings(root, sources, declaration.runner)
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
    gate = Trackers(
        issues=tracker if unreachable is None else None, conditions=conditions
    )

    def found(path: Path) -> list[Finding]:
        report = next(each for each in reports if each.path == path)
        every = [*report.findings, *(each for each in ruff if each.path == path)]
        ruled = worktree.roles.ruled(path)
        kept = [
            each
            for each in every
            if (ruled or each.owner != "lup")
            and not worktree.roles.exempt(path, each.rule)
            and not any(
                directive.keeps(each.rule, each.span.start.line)
                for directive in report.directives
            )
        ]
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
    return Scanned(files=files, findings=findings, unreachable=unreachable)


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
    deferral whose issue is closed, or whose condition holds, is due, which is
    listed and doesn't fail the check; where the issue tracker can't be
    reached (no `gh`, no login, offline), the
    issues go unchecked and the check says why. In a room, which holds no `gh`,
    the host service is asked each issue's state on the launch's request socket,
    and an issue it doesn't answer goes unchecked, said. lup's rules read production and
    protected modules; tests are checked by
    pyright and ruff only; what the declaration excludes isn't checked. With no
    paths, it checks every such file in the worktree, as the gate's `rules` step
    runs it. An `ignore` that keeps nothing fails it too, until `lup-dev rules
    fix` removes it. What came due is kept, over every file and where every
    issue was asked, for a session to be told at its start.
    """
    found = scanned(paths, issues=True)
    if not found.files:
        typer.echo("lup checked no files.")
        return
    failing = [each for each in found.findings if not each.reminder]
    due = Due(reminders=[each for each in found.findings if each.reminder])
    for line in (line for each in failing for line in finding_lines(each, "")):
        typer.echo(line)
    if due.reminders:
        typer.echo(due.told())
    if found.unreachable is not None:
        typer.echo(f"Deferrals' issues weren't checked: {found.unreachable}.")
    if paths is None and found.unreachable is None:
        common = Git(cwd=toplevel(Path.cwd())).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        write_model(GitDirectoryLayout(common=Path(common)).due, due)
    typer.echo(f"lup checked {len(found.files)} files: {len(failing)} findings.")
    if failing:
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
    own engine, rebuilt when stale. Its modules' requirements are checked first,
    all at once: a required tool missing stops the gate before any step. Each
    step's outcome is reported, then each failure's output in full; the exit code
    is non-zero when any step failed. With `--fix`, which the session landing work
    runs on the merged result, ruff's safe fixes and the formatter rewrite the
    worktree first.

    A pass is recorded for the worktree's files, in the repository's git
    directory, and a later run on the same files finds it and runs nothing,
    unless `--again`. With `--at`, the gate runs on a commit, in a worktree made
    at it and removed after, unless it passed on the commit's files already: a
    push to the integration branch from a room runs it so.
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
    if fix:
        message = (
            "`--fix` rewrites the worktree's files, and `--at` checks a commit's "
            "files as committed"
        )
        raise typer.BadParameter(message, param_hint="'--fix'")
    runner = resolve(load(root, local=person_layer(root)).project).runner

    def stop(made: Path) -> None:
        scrapped(made, runner)

    outcome = at_commit(
        root, at, Shell(), passes, runner, say=typer.echo, stop=stop, again=again
    )
    match outcome:
        case Passed():
            typer.echo(outcome.said())
        case GateRan(code=code, output=output):
            typer.echo(output, nl=False)
            if code != 0:
                raise typer.Exit(code=code)


def scrapped(worktree: Path, runner: Runner) -> None:
    """End what a gate run left for the worktree at `worktree`, which goes next: its engine, and the store keeping the engine's lock and log.

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


@app.command("trust")
def trust() -> None:
    """Approve what the host runs for this repository, as a launch does first.

    Run it yourself, in your own terminal. It reads the host zone at the
    integration branch's tip, running none of it: the declaration, the files it
    runs on the host, and the `lup-dev` the host runs. Where that isn't the zone you
    approved last, it puts the approval in your inbox, starting the host service
    where none runs, and here prints a summary of what changed since (git's count
    of each file), offers the whole diff through your pager, and asks; `lup-dev
    inbox answer` at any other terminal answers it too, whichever comes first.
    Approved, it installs the tip's `lup-dev` as the host's, restarts the host
    service on it where one runs, and records the approval; declined, the copy you
    approved before keeps running. Where nothing changed, it says so and stops.
    """
    inside = [runtime.name() for runtime in runtimes() if runtime.inside()]
    typer.echo(trusted(toplevel(Path.cwd()), inside).report())


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
        answers = (
            f"  (approved {tally.approved}, declined {tally.declined}, "
            f"unanswered {tally.unanswered})"
            if tally.outcome in ["ask", "hold"]
            else ""
        )
        typer.echo(f"{tally.count:6}  {tally.outcome:7} {tally.reason}{answers}")


@app.command("importers", hidden=True)
def importers(worktree: Path) -> None:
    """Run a worktree's background importers pass; the checkpoint starts it.

    The engine is asked with the runner of the declaration the judge reads there,
    the approved commit's, so the pass and the judge share one engine.
    """
    judging = services()
    repository = Worktree.at(worktree, judging.layout).repository
    judged = Worktree.of(worktree, repository, judging)
    judged.importers().run(judging.checker, judged.declaration.runner)


def main() -> None:
    """Run the command line, reporting lup's own errors without a traceback.

    The library's own (`LupError`) among them: a launch's room, and its runtime's
    declaration, are the library's.
    """
    try:
        app()
    except (LupDevError, LupError) as failure:
        typer.echo(f"lup-dev: {failure}", err=True)
        raise SystemExit(1) from failure


if __name__ == "__main__":
    main()
