"""Unified pre-flight checks: ruff, pyright, pytest."""

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.adapters.harness import claude_prompt_renderer, codex_prompt_renderer
from lup.codescan.markers import find_feedback
from lup.harness.models import GUIDANCE_BYTE_BUDGET, PromptDocument, document_byte_size
from lup.workspace.paths import is_template_scaffold, project_root

from lup.devtools.dev.antipatterns import scan_antipatterns
from lup.devtools.project import DevProject
from lup.devtools.dev.boundaries import (
    scan_boundaries,
    scan_application_placement,
    scan_library_placement,
)
from lup.devtools.dev.branches import unlanded_siblings
from lup.devtools.dev.git_guards import GitGuard, read_hooks
from lup.devtools.dev.comments import FoundComment, scan_tracked
from lup.devtools.dev.gates import sweep_all
from lup.devtools.harness.drift import (
    RepositoryWriter,
    inspect_drift,
    report_stale,
    roster_gaps,
)
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.devtools.utils import decode_stderr, git, uv

# The suite waits on git subprocesses and hook scripts far more than it
# computes, so it parallelizes well — but each worker pays a full interpreter
# boot and package import, and past roughly this many that startup costs more
# than the concurrency returns. Measured on a 32-core host, the root suite ran
# in 19.1s under 8 workers, 15.7s under 16, and back up at 18.0s under 24: so
# `-n auto` on a large host is slower than serial arithmetic suggests, and the
# count is capped rather than derived from cores. It is bounded by them too,
# because a cap that suits a large host oversubscribes a laptop.
TEST_WORKERS = min(16, os.process_cpu_count() or 8)


class CheckReport(BaseModel):
    """One check's verdict, and the lines it wants printed where it belongs.

    A check running beside its neighbours finishes whenever it finishes, so a
    gate echoing as it went would report in a different order every run. Each
    check hands its lines back instead, and the gate prints them in the order
    it declares them rather than the order they arrived.
    """

    name: str
    passed: bool = True
    lines: list[str]
    counted: bool = True
    """Whether the summary tallies this row. An advisory one reports and never
    gates: a note asking somebody for something is worth reading, not worth
    refusing a branch over."""


def ran(name: str, command: Callable[[], object], ok: str = "ok") -> CheckReport:
    """One external tool's verdict, carrying what it printed when it failed."""
    try:
        command()
    except sh.ErrorReturnCode as error:
        printed = [error.stdout.decode().rstrip()] if error.stdout else []
        return CheckReport(name=name, passed=False, lines=[f"{name}: FAIL", *printed])
    return CheckReport(name=name, lines=[f"{name}: {ok}"])


def ruff_format_check(fix: bool) -> CheckReport:
    """Whether every file is formatted — or, with *fix*, formatting them."""
    return ran(
        "ruff format",
        lambda: uv("run", "ruff", "format", *([] if fix else ["--check"]), "."),
        "applied" if fix else "ok",
    )


def ruff_lint_check(fix: bool) -> CheckReport:
    """Whether the lint rules hold — or, with *fix*, applying what they can."""
    return ran(
        "ruff check",
        lambda: uv("run", "ruff", "check", ".", *(["--fix"] if fix else [])),
    )


def pyright_check() -> CheckReport:
    """Whether the workspace type-checks."""
    return ran("pyright", lambda: uv("run", "pyright"))


class TestRoot(BaseModel):
    """One independently installed test suite the project asks the gate to run."""

    name: str
    directory: Path

    def checked(self, workers: int) -> CheckReport:
        """Whether this suite passes, run from its own root.

        The library ships to an index without the application beside it, so
        its suite runs from its own directory where `src` is all it can see —
        a library test reaching for a template fixture passes at the root and
        fails there, which is the only place that difference shows.
        """
        return ran(
            self.name,
            lambda: uv("run", "pytest", "-n", str(workers), _cwd=str(self.directory)),
        )


def inline_notes_lines(found: list[FoundComment], scaffold: bool = False) -> list[str]:
    """The inline-notes header and detail lines.

    Advisory rather than gating: a note is a standing request to somebody, and
    the tree is expected to carry open ones for as long as the work they name
    is open. Failing on them would make every branch red for a condition its
    author chose deliberately, so this reports and the reader decides. Their
    `deferred` lines render after the unresolved ones, carrying the gate a
    bracketed deferral stated, so what is still being asked reads first.

    Customization markers read two ways, and *scaffold* says which. In the
    scaffold itself they are inventory — counted, never listed, because a
    permanent wall of text would sit in front of the notes somebody is
    actually owed, and `dev todos` exists to walk them. In a repository that
    adopted the template they are decisions nobody has made yet, so they list
    like any other note. Advisory either way: a domain that means to leave one
    standing writes `# lup: defer:`, and that is the sentence it should have
    to write rather than a red branch it learns to ignore.
    """
    unresolved = [comment for comment in found if comment.kind in ("note", "solved")]
    deferred = [comment for comment in found if comment.kind == "defer"]
    customization = [comment for comment in found if comment.kind == "template"]
    counts = f"{len(unresolved)} unresolved"
    if deferred:
        counts += f", {len(deferred)} deferred"
    if customization:
        counts += f", {len(customization)} customization"
    lines = [f"inline notes: {counts} (advisory)"]
    lines.extend(
        f"  {comment.file}:{comment.start_line}-{comment.end_line}"
        for comment in unresolved
    )
    lines.extend(
        f"  {comment.deferral_label()} "
        f"{comment.file}:{comment.start_line}-{comment.end_line}"
        for comment in deferred
    )
    lines.extend(
        f"  customization {comment.file}:{comment.start_line}-{comment.end_line}"
        for comment in ([] if scaffold else customization)
    )
    return lines


def changed_paths(since: str) -> list[str]:
    """Every tracked path this tree changed since a ref, as posix strings.

    A ref git cannot resolve refuses the run rather than answering nothing.
    The two readings are indistinguishable once the exit status is dropped —
    an empty answer is exactly what a tree that changed nothing gives — and
    the scope this builds decides which files the blocking gates read. A
    mistyped ref would scope them to none of them and report ok.
    """
    try:
        named = git.lines("diff", "--name-only", since, _ok_code=[0])
    except sh.ErrorReturnCode as error:
        raise typer.BadParameter(
            f"--since {since!r} does not name a commit in this tree: "
            f"{decode_stderr(error)}"
        ) from error
    return [line for line in named if line]


def owned_comments(
    found: list[FoundComment], scope: list[str] | None
) -> list[FoundComment]:
    """Which unresolved notes this check is answerable for.

    A resolver worker's own notes are already cleared from its worktree
    before it starts, so every note it can still see belongs to a sibling
    concern it has no lease on. Reporting the whole tree would tell it about
    work it cannot touch; reporting what it changed says the only thing it
    can act on, which is whether it left a note in its own code.
    """
    if scope is None:
        return found
    owned = dict.fromkeys(scope)
    return [item for item in found if str(item.file) in owned]


def scan_reports(
    project: DevProject,
    scope: list[str] | None,
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
    guidance: PromptDocument,
    git_guards: list[GitGuard],
) -> list[CheckReport]:
    """Every check the gate answers itself, in the order it reports them."""

    def reported() -> Iterator[CheckReport]:
        # advisory — a note asks somebody for something, and a tree is expected
        # to carry open ones; worth reading, not worth refusing over
        found = owned_comments(scan_tracked(find_feedback), scope)
        scaffold = is_template_scaffold(project_root())
        yield CheckReport(
            name="inline notes",
            counted=False,
            lines=inline_notes_lines(found, scaffold)
            if found
            else ["inline notes: none"],
        )

        # gating — a deferral that stated a condition this checkout can resolve
        # is a question with an answer, and the answer turning yes is the one
        # moment the note was written for. Advisory is right for what somebody
        # still has to judge; this is the part nobody has to. Read from the
        # integration branch as well as from here, because a note about this
        # branch was written where its author stood and this checkout has no
        # copy of it.
        sweep = sweep_all(found)
        yield CheckReport(
            name="woken deferrals",
            passed=not sweep.woken,
            lines=sweep.lines(),
        )

        # Scoped where a scope was given, so the sweep reads the files this
        # tree is answerable for rather than reading every file and setting
        # most of the findings aside. A lease holds one concern's changes and
        # its gate answers "is this change good?" — a whole-repository read
        # made every lease's verdict depend on state no worker controls, and
        # cost the whole repository's resolve to reach it.
        scan = scan_antipatterns(project, scope)
        blocking = [f for f in scan.findings if f.kind != "untyped"]
        refined = f", {len(scan.refuted)} refuted" if scan.refuted else ""
        advisory = len(scan.findings) - len(blocking)
        tail = f" ({advisory} untyped, advisory{refined})" if advisory else refined
        yield CheckReport(
            name="antipatterns",
            passed=not blocking,
            lines=[
                f"antipatterns: FAIL ({len(blocking)} finding(s){refined})",
                *(
                    f"  {f.file}:{f.line} "
                    f"[{f.kind} {f.rule_id or '(bare)'}] {f.message}"
                    for f in blocking
                ),
            ]
            if blocking
            else [f"antipatterns: ok{tail}"],
        )

        breaches = scan_boundaries(project)
        yield CheckReport(
            name="seam boundaries",
            passed=not breaches,
            lines=[
                f"seam boundaries: FAIL ({len(breaches)} breach(es))",
                *(f"  {b.file}:{b.line}  {b.module}" for b in breaches),
            ]
            if breaches
            else ["seam boundaries: ok"],
        )

        tables = scan_library_placement()
        yield CheckReport(
            name="library placement",
            passed=not tables,
            lines=[
                f"library placement: FAIL ({len(tables)} baked-in table(s))",
                *(f"  {t.file}:{t.line}  {t.module}" for t in tables),
            ]
            if tables
            else ["library placement: ok"],
        )

        portable = scan_application_placement(project)
        yield CheckReport(
            name="application placement",
            lines=[
                f"application placement: {len(portable)} portable module(s)",
                *(f"  {module.file}" for module in portable),
            ]
            if portable
            else ["application placement: ok"],
        )

        # advisory — a retirement is a decision, and a decision nobody meets
        # again becomes permanent by default while its roster grows
        retired = [
            f"{roster}: {name}"
            for roster, names in (
                ("sub-app", project.subapps.retired),
                ("skill or agent", project.content.retired),
                ("rule", project.rules.retired),
            )
            for name in names
        ]
        if retired:
            yield CheckReport(
                name="retired from lup",
                counted=False,
                lines=[
                    f"retired from lup: {len(retired)} (advisory)",
                    *(f"  {entry}" for entry in retired),
                ],
            )

        # Asked here because the guards cannot report their own absence: a
        # hooks directory git no longer finds silences every one of them at
        # once, and every other row goes on passing exactly as before. The
        # other direction is just as quiet — git runs whatever is at the path
        # whether or not anything still declares that moment — so a checkout
        # armed by an older declaration names what it still pays for.
        hooks = read_hooks(git_guards, project_root())
        unarmed = hooks.unarmed()
        yield CheckReport(
            name="git guards",
            passed=hooks.reachable,
            lines=[
                *(
                    [
                        f"git guards: FAIL (no hooks directory at {hooks.directory})",
                        "  git runs no hook from this checkout — every guard is off",
                        "  check `git config --show-origin --get core.hooksPath`",
                    ]
                    if not hooks.reachable
                    else [
                        f"git guards: ok ({len(hooks.guards) - len(unarmed)}/"
                        f"{len(hooks.guards)} armed)",
                        *(f"  {state.describe()}" for state in unarmed),
                    ]
                ),
                *(f"  {state.describe()}" for state in hooks.orphaned),
            ],
        )

        # The same reading the commit hook and the pipeline refuse on, asked
        # here rather than recomposed, so a tree cannot be stale at one gate
        # and current at another.
        drift = inspect_drift(compositions, repository_writers)
        if not drift.clean:
            report_stale(drift)
        yield CheckReport(
            name="harness drift",
            passed=drift.clean,
            lines=["harness drift: ok"]
            if drift.clean
            else [f"harness drift: FAIL ({len(drift.stale_trees)} tree(s))"],
        )

        # Beside drift because a tree can be perfectly current against a source
        # that renders one target a skill short, and drift reads every tree as
        # clean while the two rosters have parted.
        gaps = roster_gaps(compositions)
        yield CheckReport(
            name="roster parity",
            passed=not gaps,
            lines=[
                f"roster parity: FAIL ({len(gaps)} gap(s))",
                *(f"  {gap.describe()}" for gap in gaps),
            ]
            if gaps
            else ["roster parity: ok"],
        )

        used = max(
            document_byte_size(claude_prompt_renderer().render(guidance)),
            document_byte_size(codex_prompt_renderer().render(guidance)),
        )
        free = GUIDANCE_BYTE_BUDGET - used
        state = "ok" if free >= 0 else f"FAIL (over by {-free})"
        yield CheckReport(
            name="guidance budget",
            passed=free >= 0,
            lines=[
                f"guidance budget: {state} — {used}/{GUIDANCE_BYTE_BUDGET} bytes, "
                f"{free} free"
            ],
        )

        # advisory — reports another tree's state, so it never gates this one
        unlanded = unlanded_siblings()
        if unlanded:
            yield CheckReport(
                name="unlanded siblings",
                counted=False,
                lines=[
                    f"unlanded siblings: {len(unlanded)} (advisory)",
                    *(
                        f"  {branch.name}  {branch.unique_commits} commits, "
                        f"{branch.source_diff_lines} ln"
                        for branch in unlanded
                    ),
                ],
            )

    return list(reported())


def run_checks(
    fix: bool,
    no_test: bool,
    project: DevProject,
    test_roots: list[TestRoot],
    compositions: list[NativeHarnessComposition],
    repository_writers: list[RepositoryWriter],
    guidance: PromptDocument,
    git_guards: list[GitGuard],
    scope: list[str] | None = None,
    test_workers: int = TEST_WORKERS,
) -> None:
    """Run ruff format, ruff check, pyright, pytest, and this gate's own sweeps.

    Read-only by default (reports issues without modifying files).
    Pass *fix* to auto-fix formatting and lint issues. ``scope`` narrows the
    note and anti-pattern gates to paths this tree is answerable for.
    """
    tools: list[Callable[[], CheckReport]] = [
        partial(ruff_format_check, fix),
        partial(ruff_lint_check, fix),
        pyright_check,
        *(
            []
            if no_test
            else [partial(root.checked, test_workers) for root in test_roots]
        ),
    ]
    sweeps = partial(
        scan_reports,
        project,
        scope,
        compositions,
        repository_writers,
        guidance,
        git_guards,
    )

    if fix:
        # `--fix` rewrites the tree, so its tools go one at a time: a
        # formatter moving lines under a checker reading them answers about a
        # file that is no longer there.
        tooled = [tool() for tool in tools]
        changed = git.lines("diff", "--name-only", _ok_code=[0])
        if changed:
            lint = next(report for report in tooled if report.name == "ruff check")
            lint.lines.extend(
                [f"  auto-fixed {len(changed)} file(s)", *(f"    {f}" for f in changed)]
            )
        scanned = sweeps()
    else:
        # Read-only, no check reads what another writes, so the gate costs its
        # slowest rather than the sum of all of them. Each tool waits on a
        # process of its own; the sweeps hold this thread while they do.
        with ThreadPoolExecutor(max_workers=len(tools)) as pool:
            running = [pool.submit(tool) for tool in tools]
            scanned = sweeps()
            tooled = [job.result() for job in running]

    reports = [*tooled, *scanned]
    for report in reports:
        for line in report.lines:
            typer.echo(line)

    counted = [report for report in reports if report.counted]
    passed = sum(1 for report in counted if report.passed)
    typer.echo(f"\n{passed}/{len(counted)} checks passed")

    failed = [report.name for report in counted if not report.passed]
    if failed:
        typer.echo(f"Failed: {', '.join(failed)}")
        raise typer.Exit(1)
