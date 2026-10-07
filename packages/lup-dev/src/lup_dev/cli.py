"""The `lup-dev` command: the hooks, the gate's rule check, holds and verdicts.

It stands in for the real `lup` command tree until the declaration and command
line piece builds it; the commands keep their meaning there, and their final
names are that piece's call (`docs/judging-writes.md`, *Modules*). It's the one
place that lists the runtimes' adapters.
"""

import sys
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import sh
import typer

from lup_dev.adapters import claude, codex
from lup_dev.clock import SystemClock
from lup_dev.codescan.conditions import loaded
from lup_dev.codescan.contract import Checker, Finding, Source
from lup_dev.codescan.directives import Checking, Fired, Gate, GitHubIssues
from lup_dev.codescan.ruff import Ruff
from lup_dev.errors import LupDevError
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import Bench, Services, Worktree
from lup_dev.policy.holds import Response, answer, waiting
from lup_dev.policy.importers import BackgroundSpawner
from lup_dev.policy.judge import finding
from lup_dev.policy.report import finding_lines
from lup_dev.policy.store import Git
from lup_dev.policy.verdicts import VerdictLog
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from lup_dev.policy.runtime import Runtime

app = typer.Typer(no_args_is_help=True, help="Develop a project with agents.")
hook = typer.Typer(no_args_is_help=True, help="Answer a runtime's hook.")
rules = typer.Typer(no_args_is_help=True, help="lup's code rules.")
holds = typer.Typer(help="Changes waiting for your answer.")
app.add_typer(hook, name="hook")
app.add_typer(rules, name="rules")
app.add_typer(holds, name="holds")


class EngineMissingError(LupDevError):
    """The typed engine isn't installed beside the judge."""


def engine() -> Checker:
    """Return the typed engine the judge asks about files."""
    message = (
        "the typed engine (`lup_dev.codescan.engine`) isn't installed yet: "
        "it lands with the engine's own branch"
    )
    raise EngineMissingError(message)


def runtimes() -> list[Runtime]:
    """List every runtime lup knows."""
    return [claude.Claude(), codex.Codex()]


def services() -> Services:
    """Return what judging reaches, as configured on this machine."""
    return Services(
        checker=engine(),
        linter=Ruff(),
        clock=SystemClock(),
        layout=Layout.of(LupDevSettings()),
        spawner=BackgroundSpawner(),
    )


def toplevel(directory: Path) -> Path:
    """Return the root of the git worktree holding `directory`."""
    return Path(Git(cwd=directory).text("rev-parse", "--show-toplevel"))


@hook.command("claude")
def hook_claude() -> None:
    """Answer one Claude Code hook, its payload on stdin."""
    output = claude.hook(
        sys.stdin.read(), Bench(runtime=claude.Claude(), services=services())
    )
    if output:
        typer.echo(output)


@hook.command("codex")
def hook_codex() -> None:
    """Answer one Codex hook, its payload on stdin."""
    output = codex.hook(
        sys.stdin.read(), Bench(runtime=codex.Codex(), services=services())
    )
    if output:
        typer.echo(output)


@rules.command("check")
def rules_check(
    paths: Annotated[
        list[Path] | None, typer.Argument(help="Files to check; every Python file.")
    ] = None,
) -> None:
    """Check files as the gate does: lup's rules, pyright, ruff and the deferrals.

    `# lup: ignore` applies to every owner's findings. A deferral whose issue is
    closed, or whose condition holds, fails the check. Tests are checked by
    pyright and ruff only.
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
        for name in Git(cwd=root)
        .text("ls-files", "--cached", "--others", "--exclude-standard")
        .splitlines()
    ]
    checked = [
        path
        for path in listed
        if worktree.roles.is_python(path)
        and worktree.roles.role(path) in ["production", "test"]
    ]
    if not checked:
        typer.echo("lup checked no files.")
        return
    sources = [Source(path=path) for path in checked]
    reports = engine().check(root, sources)
    ruff = Ruff().findings(root, sources)
    conditions = loaded(root, worktree.declared.project)
    gate = Gate(issues=GitHubIssues(root=root), conditions=conditions)

    def found(path: Path) -> list[Finding]:
        report = next(each for each in reports if each.path == path)
        every = [*report.findings, *(each for each in ruff if each.path == path)]
        production = worktree.roles.role(path) == "production"
        kept = [
            each
            for each in every
            if (production or each.owner != "lup")
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
    """List the changes waiting for your answer, with their diffs."""
    if context.invoked_subcommand is not None:
        return
    held = waiting(Layout.of(LupDevSettings()))
    if not held:
        typer.echo("Nothing is waiting.")
        return
    for hold in held:
        typer.echo(f"{hold.key}  {hold.worktree}  (session {hold.session})")
        for each in hold.files:
            for asked in each.asks:
                typer.echo(f"  {each.path}: {asked}")
        typer.echo(hold.diff)


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
    """Run a worktree's background importers pass; the checkpoint starts it."""
    layout = Layout.of(LupDevSettings())
    Worktree.at(worktree, layout).importers().run(engine())


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
