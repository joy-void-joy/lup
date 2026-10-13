"""The `lup-dev` command: the hooks, the gate's rule check, holds, verdicts, reviews.

It stands in for the real `lup` command tree until the declaration and command
line piece builds it; the commands keep their meaning there, and their final
names are that piece's call (`docs/judging-writes.md`, *Modules*). It's the one
place that lists the runtimes' adapters, so the host service answers each launch's
hooks with the answerer built here (`docs/launch.md`), as `hook` does.

`trust` approves what the host runs for a repository, the check a launch makes
first (`docs/launch.md`, *Trust on launch*). `submit`, `wait`, `reviews` and
`reply` serve the built drafts flow (`docs/review-flow.md`). Who calls one is a
conversation of its own, `operator`, in the directory it runs in.
"""

import asyncio
import secrets
import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, override

import sh
import typer
from pydantic import TypeAdapter, ValidationError

from lup.types import Model

# lup: ignore("runtime-mention", why="the one place listing the adapters")
from lup_dev.adapters import claude, codex
from lup_dev.clock import SystemClock
from lup_dev.codescan.conditions import loaded
from lup_dev.codescan.contract import Checker, Finding, Source
from lup_dev.codescan.directives import Checking, Fired, GitHubIssues, Trackers
from lup_dev.codescan.engine import EngineChecker
from lup_dev.codescan.reference import reference
from lup_dev.codescan.ruff import Ruff
from lup_dev.declaration.requirements import Machine
from lup_dev.errors import LupDevError
from lup_dev.gate import Check, Shell, failed, report
from lup_dev.git import Git, nul_separated
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.service import Answerer, HostService
from lup_dev.launch.trust import trusted
from lup_dev.layout import CheckoutLayout, Layout
from lup_dev.legacy_dashboard import LegacyQueue
from lup_dev.policy.checkpoint import Bench, Services, Worktree
from lup_dev.policy.holds import Hold, Response, answer, waiting
from lup_dev.policy.importers import BackgroundSpawner
from lup_dev.policy.judge import finding
from lup_dev.policy.report import finding_lines
from lup_dev.policy.runtime import Runtime
from lup_dev.policy.submissions import (
    AllReviews,
    AnyReview,
    Awaited,
    Caller,
    Desk,
    FileApplied,
    Offered,
    OneReview,
)
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from lup_dev.review import Queue

app = typer.Typer(no_args_is_help=True, help="Develop a project with agents.")
rules = typer.Typer(no_args_is_help=True, help="lup's code rules.")
holds = typer.Typer(help="Changes waiting for your answer.")
review = typer.Typer(no_args_is_help=True, help="Reviews parked for your answer.")
host = typer.Typer(help="lup's host service, which rooms call.")
app.add_typer(rules, name="rules")
app.add_typer(holds, name="holds")
app.add_typer(review, name="review", hidden=True)
app.add_typer(host, name="host")


class Adapter(Model, arbitrary_types_allowed=True):
    """A runtime lup knows, with how its adapter answers one of its hooks."""

    runtime: Runtime
    hook: Callable[[str, Bench], str]
    """The adapter's `hook`: a payload in, what the hook prints out."""


def engine() -> Checker:
    """Return the typed engine the judge asks about files, as this machine sets it."""
    return EngineChecker.configured(LupDevSettings())


def adapters() -> list[Adapter]:
    """List every runtime lup knows, each with how its adapter answers a hook."""
    return [
        # lup: ignore("runtime-mention", why="the one place listing the adapters")
        Adapter(runtime=claude.Claude(), hook=claude.hook),
        # lup: ignore("runtime-mention", why="the one place listing the adapters")
        Adapter(runtime=codex.Codex(), hook=codex.hook),
    ]


def runtimes() -> list[Runtime]:
    """List every runtime lup knows."""
    return [adapter.runtime for adapter in adapters()]


class Adapters(Model, Answerer):
    """Every runtime lup knows, answering its hooks: for `hook`, and the host service."""

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

    @override
    def answer(self, runtime: str, payload: str) -> str:
        """Answer one of `runtime`'s hooks, judging with this machine's services.

        What the hook prints is its adapter's output on a line, or nothing.
        """
        adapter = self.named(runtime)
        bench = Bench(runtime=adapter.runtime, services=services())
        output = adapter.hook(payload, bench)
        return f"{output}\n" if output else ""


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
    )


def toplevel(directory: Path) -> Path:
    """Return the root of the git worktree holding `directory`."""
    return Path(Git(cwd=directory).text("rev-parse", "--show-toplevel"))


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


@host.callback(invoke_without_command=True)
def host_serve(context: typer.Context) -> None:
    """Run the host service in the foreground, until it's stopped.

    It answers each launch's hooks as `lup-dev hook` does, on the launch's own
    socket. `lup-dev host stop` or Ctrl-C stops it; the launches it serves stay
    recorded, and the next service serves them.
    """
    if context.invoked_subcommand is not None:
        return
    service = HostService(
        layout=Layout.of(LupDevSettings()).host,
        answerer=Adapters(known=adapters()),
        say=typer.echo,
    )
    asyncio.run(service.serve())


@host.command("stop")
def host_stop() -> None:
    """Stop the host service, if one runs."""
    if host_client().stop():
        typer.echo("Stopped the host service.")
        return
    typer.echo("No host service runs.")


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
    deferral whose issue is closed, or whose condition holds, fails the check.
    lup's rules read production and protected modules; tests are checked by
    pyright and ruff only; what the declaration excludes isn't checked. With no
    paths, it checks every such file in the worktree, as the gate's `rules` step
    runs it.
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
            .stdout
        )
        if (root / name).is_file()
    ]
    checked = [path for path in listed if worktree.roles.checked(path)]
    if not checked:
        typer.echo("lup checked no files.")
        return
    sources = [Source(path=path) for path in checked]
    declaration = worktree.declaration
    reports = engine().check(root, sources, declaration.rules, declaration.runner)
    ruff = Ruff().findings(root, sources, declaration.runner)
    conditions = loaded(root, declaration.conditions)
    gate = Trackers(issues=GitHubIssues(root=root), conditions=conditions)

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

    findings = [each for path in checked for each in found(path)]
    for line in (line for each in findings for line in finding_lines(each, "")):
        typer.echo(line)
    typer.echo(f"lup checked {len(checked)} files: {len(findings)} findings.")
    if findings:
        raise typer.Exit(code=1)


@holds.callback(invoke_without_command=True)
def holds_list(context: typer.Context) -> None:
    """List the changes waiting for your answer, with their diffs.

    What a move of `HEAD` asks is listed apart: it's committed already, no agent
    waits on it, and a decline changes no file.
    """
    if context.invoked_subcommand is not None:
        return
    held = waiting(Layout.of(LupDevSettings()))
    if not held:
        typer.echo("Nothing is waiting.")
        return

    def shown(hold: Hold, where: str) -> None:
        typer.echo(f"{hold.key}  {hold.worktree}  ({where})")
        for each in hold.files:
            for asked in each.asks:
                typer.echo(f"  {each.path}: {asked}")
        typer.echo(hold.diff)

    for hold in held:
        if hold.commit is None:
            shown(hold, f"session {hold.session}")
    moved = [hold for hold in held if hold.commit is not None]
    if moved:
        typer.echo("Asked after the fact, about commits already made (no agent waits):")
    for hold in moved:
        shown(hold, f"commit {hold.commit}")


@holds.command("approve")
def holds_approve(
    key: str,
    comment: Annotated[str, typer.Option(help="Passed on to the agent.")] = "",
) -> None:
    """Approve a held change: it's accepted as it stands."""
    answer(
        Layout.of(LupDevSettings()),
        key,
        Response(approved=True, comment=comment),
        runtimes(),
        SystemClock(),
    )
    typer.echo(f"Approved {key}.")


@holds.command("decline")
def holds_decline(
    key: str,
    comment: Annotated[str, typer.Option(help="Why, for the agent.")],
) -> None:
    """Decline a held change: it's put back, and the agent's version saved."""
    answer(
        Layout.of(LupDevSettings()),
        key,
        Response(approved=False, comment=comment),
        runtimes(),
        SystemClock(),
    )
    typer.echo(f"Declined {key}.")


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
    """
    gated = Check.declared(toplevel(Path.cwd()), Shell(), Machine(), fix=fix).run()
    typer.echo(report(gated))
    if failed(gated.outcomes):
        raise typer.Exit(code=1)


@app.command("trust")
def trust() -> None:
    """Approve what the host runs for this repository, as a launch does first.

    Run it yourself, in your own terminal. It reads the host zone at the
    integration branch's tip: the declaration, the files its modules name that the
    host imports, and the `lup-dev` the host runs. Where that isn't the zone you
    approved last, it shows what changed since through your pager and asks once:
    approved, it installs the tip's `lup-dev` as the host's, restarts the host
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
    the integration branch's, so the pass and the judge share one engine.
    """
    judging = services()
    repository = Worktree.at(worktree, judging.layout).repository
    judged = Worktree.of(worktree, repository, judging)
    judged.importers().run(judging.checker, judged.declaration.runner)


@review.command("keep", hidden=True)
def review_keep(worktree: Path) -> None:
    """Keep a worktree's reviews in the first lup's dashboard; parking starts it."""
    LegacyQueue.configured(worktree, LupDevSettings(), SystemClock()).keep()


def queue(worktree: Path) -> Queue:
    """Return where the worktree's reviews are parked, as this machine sets it."""
    return LegacyQueue.configured(worktree, LupDevSettings(), SystemClock())


def desk(directory: Path) -> Desk:
    """Return the reviews of the worktree holding `directory`."""
    root = toplevel(directory)
    configured = services()
    common = Git(cwd=root).text(
        "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    return Desk(
        worktree=Worktree.of(root, Path(common), configured),
        services=configured,
        queue=queue(root),
    )


def caller() -> Caller:
    """Name who calls from the command line: the operator, where they run it."""
    return Caller(session="operator", call=secrets.token_hex(8), cwd=Path.cwd())


def duration(text: str | None) -> timedelta | None:
    """Read a timeout given as `HH:MM:SS` or ISO 8601 (`PT30M`); none for none."""
    if text is None:
        return None
    try:
        return TypeAdapter(timedelta).validate_python(text)
    except ValidationError as failure:
        message = f"a timeout is `HH:MM:SS` or ISO 8601 (`PT30M`), not {text!r}"
        raise typer.BadParameter(message) from failure


Timeout = Annotated[
    str | None,
    typer.Option(
        help="Say what still waits after at most this long: `HH:MM:SS`, or `PT30M`."
    ),
]


@app.command("submit")
def submit(
    why: Annotated[
        str,
        typer.Option(help="What the whole change does; optional with one file."),
    ] = "",
    *,
    wait_for_answer: Annotated[
        bool, typer.Option("--wait", help="Wait for its answer, as `wait` does.")
    ] = False,
    timeout: Timeout = None,
) -> None:
    """Submit drafts for review as one review, its files as JSON on standard input.

    Standard input holds a list of the files, each with its `path` (the file, or
    its draft's path), its `context` (what changes in it and why, in plain
    words), and for a rename, `renamed_from`, the old path, which the approval
    removes: `[{"path": "src/a.py", "context": "..."}]`. A draft is written at
    `.lup/drafts/<path>`, a dot starting a segment of the path written `%2E` and a
    `%` starting one written `%25`; a file landed since the session started is
    shown as context.
    """
    try:
        files = TypeAdapter(list[Offered]).validate_json(sys.stdin.read())
    except ValidationError as failure:
        message = f"standard input isn't a list of files to submit: {failure}"
        raise typer.BadParameter(message) from failure
    submitted = desk(Path.cwd()).submit(
        caller(), files, why, wait=wait_for_answer, timeout=duration(timeout)
    )
    typer.echo(submitted.text())


def awaited(
    numbers: list[int], *, first: bool, every: bool, file: Path | None
) -> Awaited:
    """Read what `wait` waits for from its arguments: exactly one form."""
    forms = int(bool(numbers) or first) + int(every) + int(file is not None)
    if forms != 1:
        message = "name one review, several with --any, or give --all or --file"
        raise typer.BadParameter(message)
    if every:
        return AllReviews()
    if file is not None:
        return FileApplied(path=file)
    if first:
        return AnyReview(numbers=numbers)
    if len(numbers) != 1:
        message = "several reviews are waited on with --any"
        raise typer.BadParameter(message)
    [number] = numbers
    return OneReview(number=number)


@app.command("wait")
def wait(
    numbers: Annotated[
        list[int] | None,
        typer.Argument(help="The review to wait on, or with --any, several."),
    ] = None,
    *,
    first: Annotated[
        bool, typer.Option("--any", help="Wait for the first of these to end.")
    ] = False,
    every: Annotated[
        bool, typer.Option("--all", help="Wait for every review you submitted.")
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option(help="Wait for the review submitted last holding this file."),
    ] = None,
    timeout: Timeout = None,
) -> None:
    """Wait for the answers to reviews, carrying out each approval as it's read.

    Each answer, and each remark the operator sends before answering, is said
    once; a remark ends the wait too.
    """
    chosen = awaited(numbers or [], first=first, every=every, file=file)
    typer.echo(desk(Path.cwd()).wait(caller(), chosen, duration(timeout)).text())


@app.command("reviews")
def reviews() -> None:
    """List the worktree's drafts, and every review submitted with how it stands."""
    typer.echo(desk(Path.cwd()).reviews().text())


@app.command("reply")
def reply(
    number: Annotated[int, typer.Argument(help="The review, which waits.")],
    text: Annotated[str, typer.Argument(help="What to say in its thread.")],
) -> None:
    """Answer in the thread of a review you submitted; the review waits as it did."""
    typer.echo(desk(Path.cwd()).reply(caller(), number, text))


def main() -> None:
    """Run the command line, reporting lup's own errors without a traceback."""
    try:
        app()
    except LupDevError as failure:
        typer.echo(f"lup-dev: {failure}", err=True)
        raise SystemExit(1) from failure
    except sh.ErrorReturnCode as failure:
        typer.echo(
            f"lup-dev: {failure.full_cmd} failed: {failure.stderr.decode()}", err=True
        )
        raise SystemExit(1) from failure


if __name__ == "__main__":
    main()
