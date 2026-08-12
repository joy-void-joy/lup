"""Resolver command glue between the CLI and the shared persisted resolver.

Owns the console question broker, resolver-scoped Git snapshotting of
review-note files, the per-adapter worker and reviewer session factories,
and the driver that starts a persisted resolver run, resumes it, and widens
it with work discovered while it ran.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import sh
import typer
from pydantic import BaseModel, ConfigDict

from lup.codescan.markers import find_feedback
from lup.mcp import create_mcp_server, serve_stdio, server_tool_names
from lup.policy.identity import (
    agent_identity_environment,
    concern_allowances_environment,
)
from lup.harness.environment import non_interactive_environment
from lup.harness.ownership import GeneratedArtifacts, generated_artifacts
from lup.harness.process import LaunchRequest, LocalProcessLauncher, ProcessLauncher
from lup.resolver.contracts import (
    ResolverAwaitingAnswers,
    ResolverObserver,
    WorktreePreparer,
)
from lup.resolver.actors import create_inbox_hooks
from lup.resolver.core import ResolverCore
from lup.resolver.journal import Journal
from lup.resolver.orchestrator import WorktreeOrchestrator
from lup.resolver.rebase import BaseRefresher
from lup.resolver.run import ResolveRun
from lup.resolver.state import ResolverStateRepository
from lup.resolver.models import (
    AdmissionRequest,
    Concern,
    ConcernAdmission,
    ConcernProgress,
    InventoryNote,
    IssueEvidence,
    ResolveManifest,
    MaterialQuestion,
    RefreshReport,
    ResolvePhase,
    ResolveRequest,
    ResolverConfig,
    RunTally,
    SourceSnapshot,
    VerificationCommand,
    WorkerContext,
)
from lup.channels.models import utc_now
from lup.resolver.mailbox import (
    AnswerDoor,
    AnswerOffer,
    MailboxConflictError,
    QuestionMailbox,
)
from lup.resolver.tools import (
    RESOLVER_CONCERN_ENV,
    RESOLVER_RUN_DIR_ENV,
    ResolverToolContext,
    create_question_tools,
    read_resolver_tool_context,
)
from lup.runtime.factory import SessionFactory
from lup.types import EnvVars
from lup.workspace.paths import project_root
from lup.devtools.dev.comments import FoundComment, scan_tracked
from lup.devtools.dev.issues import comment_on_issues, fetch_open_issues
from lup.devtools.dev.remote_auth import check_remote_auth
from lup.devtools.dev.worktree import (
    copy_gitignored_extras,
    sync_dependencies,
)
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.devtools.supervisor.projection import answer_recipe as rerun_recipe


class ConfiguredModel(BaseModel):
    """The model an application is configured to run, and where it routes.

    A resolver session runs through one native adapter, and a model reaches
    only the backend its vendor prefix names. Naming both here lets the
    driver say which one it declined rather than silently taking a default.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    adapter: str

    def reaching(self, adapter: str) -> str | None:
        """This model when that adapter can run it, nothing when it cannot."""
        return self.name if self.adapter == adapter else None


class ResolverIntake(BaseModel):
    """The scan partitioned at the resolver boundary.

    Deferred notes never enter the resolver inventory — waking one is an
    explicit edit that removes its `defer` head — so an editor can never be
    assigned parked work. ``carried`` reports each parked note, and
    ``generated`` each note a generator answers for rather than this tree.
    """

    actionable: list[FoundComment]
    carried: list[str]
    generated: list[str]


# lup: There is no way to see what a run would plan without starting one. Every
# resolve subcommand — supervise, questions, answer, actors, say, redirect, park
# — operates on a run that already exists, so discovering an inventory means
# committing to a run that leases a worktree per concern. Add `harness resolve
# intake`, printing all three buckets this returns with file, line, and for a
# generated note the owning `semantic_id`. Reported from downstream: answering
# "is this good to clean and restart from scratch?" took a dozen calls of
# reading this function, `scan_tracked`, and cross-referencing ownership by
# hand — and that reconstruction is what found the bug fixed in #47.
def resolver_intake(
    comments: list[FoundComment], owned: GeneratedArtifacts
) -> ResolverIntake:
    """Partition scanned notes into resolver work, deferrals, and generated ones.

    A note inside a generated artifact was written against the generator's own
    source and copied here when the harness materialized. This tree can neither
    resolve it nor park it: editing the artifact is refused, and the next
    generation restores whatever an edit changed. Assigning one spends a concern
    that can only fail, so it is reported and left to whoever owns the source.
    """
    notes = [comment for comment in comments if comment.kind == "note"]

    def generated() -> Iterator[str]:
        """Each note a generated artifact holds, named by the artifact."""
        for comment in notes:
            artifact = owned.owning(comment.file)
            if artifact is not None:
                yield (
                    f"{artifact.semantic_id} owns "
                    f"{comment.file}:{comment.start_line}-{comment.end_line}"
                )

    return ResolverIntake(
        actionable=[note for note in notes if owned.owning(note.file) is None],
        generated=list(generated()),
        carried=[
            f"carrying {comment.deferral_label()} "
            f"{comment.file}:{comment.start_line}-{comment.end_line}"
            for comment in comments
            if comment.kind == "defer"
        ],
    )


def lease_plugin_dir(root: Path, plugin_name: str) -> Path:
    """The plugin a session opened in *root* is judged by: that tree's own.

    An interactive launch names its directory with `--plugin-dir` and is
    immune to this; a session the SDK opens names nothing, so it resolves
    plugins through the settings at its working directory. Those settings
    register a marketplace under a name, and a name is one global namespace
    shared by every checkout declaring it — so the plugin a lease actually
    loaded was whichever tree registered that name last, and a worker was
    refused an edit by a policy kernel generated from another commit.
    """
    return root / ".claude" / "plugins" / plugin_name


class FeatureWorktreePreparer(WorktreePreparer):
    """Prepare leased resolver worktrees exactly like feature worktrees.

    Copies the same gitignored extras and runs the same dependency sync as
    ``dev worktree create``, so verification and tests inside a lease bind
    to the leased checkout instead of the source tree's environment.
    """

    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root

    def prepare(self, root: Path) -> None:
        copy_gitignored_extras(self.source_root, root)
        sync_dependencies(root)


class ConsoleResolverObserver(ResolverObserver):
    """Print one line per durably recorded resolver transition.

    Long worker phases are otherwise silent; these lines are the liveness
    signal that lets an operator stop polling state files and worktrees.
    """

    def phase_changed(self, phase: ResolvePhase) -> None:
        typer.echo(f"[resolve] phase: {phase}")

    def concern_changed(self, progress: ConcernProgress) -> None:
        line = f"[resolve] {progress.concern_id}: {progress.status}"
        if progress.reason:
            line = f"{line} ({progress.reason})"
        typer.echo(line)

    def tally_changed(self, tally: RunTally) -> None:
        typer.echo(f"[resolve] progress: {tally.concerns_line()}")


def parse_answer_flags(
    flags: list[str],
) -> dict[str, str]:  # lup: ignore[dict-str-payload] — open question-id map
    """Split repeatable ``--answer`` flags into a question-id to value map."""
    pairs = [
        flag.split("=", 1)  # lup: ignore[string-split] — this CLI's flag grammar
        for flag in flags
    ]
    malformed = [
        flag
        for flag, pair in zip(flags, pairs, strict=True)
        if len(pair) != 2 or not pair[0]
    ]
    if malformed:
        raise typer.BadParameter(
            "--answer takes <question-id>=<value>; got: " + ", ".join(malformed)
        )
    identifiers = [pair[0] for pair in pairs]
    if len(identifiers) != len(dict.fromkeys(identifiers)):
        raise typer.BadParameter("--answer question ids must be unique")
    return {pair[0]: pair[1] for pair in pairs}


class NoteTargetRef(BaseModel):
    """One `file:line` target naming a note already written in the tree."""

    model_config = ConfigDict(frozen=True)

    file: Path
    line: int


def parse_note_targets(targets: list[str]) -> list[NoteTargetRef]:
    """Split repeatable ``--admit-note`` flags into located note targets."""
    parsed = [
        target.rpartition(":")  # lup: ignore[string-split] — this CLI's flag grammar
        for target in targets
    ]
    malformed = [
        target
        for target, pair in zip(targets, parsed, strict=True)
        if not pair[0] or not pair[2].isdigit()
    ]
    if malformed:
        raise typer.BadParameter(
            "--admit-note takes <file>:<line>; got: " + ", ".join(malformed)
        )
    return [NoteTargetRef(file=Path(pair[0]), line=int(pair[2])) for pair in parsed]


def admission_notes(
    targets: list[NoteTargetRef], actionable: list[FoundComment]
) -> list[InventoryNote]:
    """Locate each named note among the notes a scan found actionable.

    The note's own text and surrounding context are carried rather than
    retyped, so a concern admitted from a note is grounded in exactly what
    intake would have planned from. Deferred notes never reach ``actionable``,
    so a target landing on parked work is refused with the rest.
    """
    located = {
        f"{comment.file}:{comment.start_line}": comment for comment in actionable
    }
    missing = [
        f"{target.file}:{target.line}"
        for target in targets
        if f"{target.file}:{target.line}" not in located
    ]
    if missing:
        raise typer.BadParameter(
            "no actionable `# lup:` note at: " + ", ".join(missing)
        )
    return [
        InventoryNote(
            file=target.file,
            line=located[f"{target.file}:{target.line}"].start_line,
            text=located[f"{target.file}:{target.line}"].marker_text(),
            context=located[f"{target.file}:{target.line}"].context,
        )
        for target in targets
    ]


def offer_flag_answers(
    mailbox: QuestionMailbox,
    run_id: str,
    provided: dict[str, str],  # lup: ignore[dict-str-payload] — open id map
) -> None:
    """Offer every ``--answer`` value through the mailbox.

    Offers may precede their questions, so a flag answers a question this
    run has not asked yet — which is why a fresh run no longer has to park
    once before its answers can count.

    Every flag is put to the mailbox before any refusal is raised, so one
    rerun is told about all of its stale corrections rather than finding the
    next one only after it has dropped the last.
    """
    refused: list[str] = []
    for identifier, value in provided.items():
        try:
            mailbox.offer(
                AnswerOffer(
                    run_id=run_id,
                    question_id=identifier,
                    value=value,
                    door=AnswerDoor.FLAG,
                    offered_at=utc_now(),
                )
            )
        except MailboxConflictError as error:
            refused.append(str(error))
    if refused:
        raise typer.BadParameter(
            "\n  ".join(["", *refused])
            + "\nDrop those --answer flags to resume on the settled values, or "
            "end this run with --abort and start one answerable afresh."
        )


def run_owned(workspace: Path, root: Path, worktree_root: Path) -> bool:
    """Whether one run's own invocation already covers a workspace.

    Pointing a run at a repository is an explicit act of trust by whoever
    ran it, and a more deliberate one than accepting a dialog — so trust
    reaches that repository, where the planner reads, and the checkouts the
    run makes of it, where every worker and reviewer works. Those all land
    under ``worktree_root``, which is what keeps "a checkout this run
    created" a structural test rather than a judgement, and what stops trust
    from reaching anywhere a session merely happens to be opened.
    """
    return workspace.resolve() == root.resolve() or workspace.is_relative_to(
        worktree_root
    )


def inert_offers(mailbox: QuestionMailbox) -> list[str]:
    """Every offer left on disk that a promoted answer has already outrun.

    Nothing under ``.lup/resolve`` is ever unlinked, so an offer written
    before a promoter took a different value stays there reading like a
    pending correction while being none. A run that says what it found
    cannot be mistaken for one holding the newer value.
    """
    settled = {
        record.answer.question_id: record.answer.value for record in mailbox.answers()
    }
    return [
        f"offer {offer.question_id}={offer.value!r} through the {offer.door} door "
        f"never took: the question settled as {settled[offer.question_id]!r}"
        for offer in mailbox.offers()
        if offer.question_id in settled and settled[offer.question_id] != offer.value
    ]


def run_resolver_tool_server() -> None:
    """Serve the question tools to a worker whose tools run out of process.

    The Codex runtime spawns MCP servers as subprocesses, so a handler there
    cannot see any in-process object. It rebuilds the same mailbox from the
    relayed run directory instead, which is why the mailbox is files.
    """
    context = read_resolver_tool_context()
    if context is None:
        raise typer.BadParameter(
            f"{RESOLVER_RUN_DIR_ENV} and {RESOLVER_CONCERN_ENV} must both be set"
        )
    serve_stdio(
        create_mcp_server(
            "resolver",
            tools=create_question_tools(
                QuestionMailbox(context.run_dir),
                context.concern_id,
                run_id=context.run_dir.name,
                lease_root=context.lease_root,
            ),
        )
    )


SUPERVISED_WAIT_SECONDS = 3600.0


class SupervisorSpawn(BaseModel):
    """Whether a run opens a page beside itself, and on which port."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    port: int = 8766
    linger: bool = False


@asynccontextmanager
async def spawned_supervisor(
    spawn: SupervisorSpawn, run_id: str, adapter: str
) -> AsyncGenerator[None]:
    """Run the supervisor page beside this run, as a separate process.

    The page is an ordinary reader of the run directory, so it does not
    have to share this process — which is what removes the whole thread
    split the in-process host needed. The run's own loop hosts nothing.
    """
    if not spawn.enabled:
        yield
        return
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "lup-devtools",
        "harness",
        "resolve",
        "supervise",
        "--run-id",
        run_id,
        "--adapter",
        adapter,
        "--port",
        str(spawn.port),
    )
    typer.echo(f"Resolver supervisor: http://127.0.0.1:{spawn.port}")
    try:
        yield
    finally:
        if spawn.linger:
            typer.echo("Supervisor left running; stop it with Ctrl-C in its terminal.")
        else:
            process.terminate()
            await process.wait()


def report_concern_evidence(concern: Concern) -> None:
    """Print what a concern was planned from, so its questions can be judged.

    A question prompt alone reads as a decision with no stakes: whoever
    answers it needs the `# lup:` notes that raised it and the spec the
    planner wrote from them, or they are guessing on the asker's behalf.
    """
    typer.echo(f"concern {concern.id}: {concern.title}")
    for note in concern.notes:
        typer.echo(f"  note {note.file}:{note.line}: {note.text}")
    for criterion in concern.criteria:
        typer.echo(f"  criterion {criterion.id}: {criterion.description}")
    for path in concern.files:
        typer.echo(f"  starting file: {path}")
    typer.echo(f"  spec: {concern.spec}")


def report_questions(
    questions: list[MaterialQuestion], concerns: list[Concern]
) -> None:
    """Print each open question under the concern evidence that raised it."""
    evidence = {concern.id: concern for concern in concerns}
    for concern_id in dict.fromkeys(question.concern_id for question in questions):
        if concern_id in evidence:
            report_concern_evidence(evidence[concern_id])
        for question in [item for item in questions if item.concern_id == concern_id]:
            typer.echo(f"question {question.id} (concern {concern_id}):")
            typer.echo(f"  {question.prompt}")
            if question.choices:
                typer.echo("  choices: " + " | ".join(question.choices))
            if question.recommendation is not None:
                typer.echo(f"  recommendation: {question.recommendation}")
            if not question.closed_choices:
                typer.echo("  (choices are suggestions; any answer is accepted)")


def report_awaiting(
    parked: ResolverAwaitingAnswers,
    adapter: str,
    run_id: str,
    concerns: list[Concern],
) -> None:
    """Print parked questions, their evidence, and the rerun recipe."""
    typer.echo("Resolver run parked awaiting material answers.")
    for problem in parked.problems:
        typer.echo(f"  problem: {problem}")
    report_questions(parked.pending, concerns)
    typer.echo("Relay the questions to the human, then rerun:")
    typer.echo(f"  {rerun_recipe(adapter, run_id, parked.pending)}")


def report_admission(admission: ConcernAdmission, adapter: str, run_id: str) -> None:
    """Print what joined the run and the gates it still has to pass."""
    typer.echo(
        f"Admitted {len(admission.concerns)} concern(s) into {run_id} "
        f"at phase {admission.phase}."
    )
    report_questions(admission.questions, admission.concerns)
    for problem in admission.rejected:
        typer.echo(f"  rejected: {problem}")
    answered = len(admission.questions) - len(admission.outstanding)
    if answered:
        typer.echo(f"Applied {answered} answer(s) supplied with this admission.")
    if not admission.outstanding:
        typer.echo("Every admitted question is answered; rerun to drive the run on:")
        typer.echo(f"  {rerun_recipe(adapter, run_id, [])}")
        return
    typer.echo("Relay the new questions to the human, then rerun:")
    typer.echo(f"  {rerun_recipe(adapter, run_id, admission.outstanding)}")


def resolver_git(
    launcher: ProcessLauncher,
    root: Path,
    arguments: list[str],
    *,
    environment: EnvVars | None = None,
) -> str:
    """Run one resolver-owned Git inspection or snapshot operation."""
    status = launcher.launch(
        LaunchRequest(
            arguments=["git", *arguments],
            cwd=root,
            environment=environment or {},
        )
    )
    if status.code != 0:
        raise RuntimeError(
            f"resolver Git operation failed ({' '.join(arguments)}): {status.stderr}"
        )
    lines = status.stdout.splitlines()
    return lines[0] if len(lines) == 1 else "\n".join(lines)


def resolver_source_snapshot(
    launcher: ProcessLauncher,
    root: Path,
    run_root: Path,
    note_paths: list[Path],
) -> SourceSnapshot:
    """Create an unattached source commit containing current review-note files."""
    branch = resolver_git(launcher, root, ["branch", "--show-current"]) or "HEAD"
    head = resolver_git(launcher, root, ["rev-parse", "HEAD"])
    status = launcher.launch(
        LaunchRequest(
            arguments=["git", "diff", "--quiet", "HEAD", "--", *map(str, note_paths)],
            cwd=root,
        )
    )
    if status.code == 0:
        return SourceSnapshot(branch=branch, commit=head)
    if status.code != 1:
        raise RuntimeError(f"resolver source inspection failed: {status.stderr}")
    run_root.mkdir(parents=True, exist_ok=True)
    index = (run_root / ".source.index").resolve()
    environment = {"GIT_INDEX_FILE": str(index)}
    try:
        resolver_git(launcher, root, ["read-tree", "HEAD"], environment=environment)
        resolver_git(
            launcher,
            root,
            ["add", "--", *map(str, note_paths)],
            environment=environment,
        )
        tree = resolver_git(launcher, root, ["write-tree"], environment=environment)
        commit = resolver_git(
            launcher,
            root,
            [
                "commit-tree",
                tree,
                "-p",
                head,
                "-m",
                "chore(review): resolver source snapshot",
            ],
            environment=environment,
        )
    finally:
        if index.exists():
            index.unlink()
    return SourceSnapshot(branch=branch, commit=commit)


REVIEW_BRANCH_SUFFIX = "/review"


def integration_branch(launcher: ProcessLauncher, root: Path, run_id: str) -> str:
    """Where this run integrates: onto a standing review branch, or a fresh one.

    A resolve run started while HEAD is already a review branch is resolving
    that branch's own feedback, so minting a second one strands the work on a
    branch nobody asked for and leaves the human to reconcile two. Advancing
    the branch it was launched from is what makes a nested run compose.
    """
    current = resolver_git(launcher, root, ["branch", "--show-current"])
    if current.startswith("resolve/") and current.endswith(REVIEW_BRANCH_SUFFIX):
        return current
    return f"resolve/{run_id}{REVIEW_BRANCH_SUFFIX}"


def refresh_run(
    run_id: str = typer.Option(..., "--run-id", help="Run whose base to refresh"),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Take the refresh, instead of only reporting what it would do",
    ),
    base: str = typer.Option(
        "",
        "--base",
        help="Adopt a base you resolved by hand, where the combine conflicts. "
        "It must contain both the run's base and the branch, so a resolution "
        "that dropped one side is refused rather than taken",
    ),
) -> None:
    """Bring a run's base, and the leases holding work, up to its branch.

    A run's leases are cut from the commit it was created at, so a fix made
    on the integration branch to unblock that very run is the one thing it
    cannot see. A lease made after this reads the branch as it stands; a
    lease already holding work is merged only with `--apply`, and only where
    this has already reported that it would not conflict.

    Where combining the two bases conflicts, this reports the paths and
    stops: the fix that unblocks a run touches what that run's notes are
    about, so conflicting is ordinary. Resolve it once in a worktree and
    hand the commit back with `--base`, rather than meeting the same
    conflict again in every lease at land.

    This takes the run's own lock, so the run's process must have exited —
    which is exactly when a parked run is waiting for the fix to land.
    """
    root = project_root()
    state_root = root / ".lup" / "resolve"
    repository = ResolverStateRepository(state_root, run_id)
    if not repository.exists():
        raise typer.BadParameter(f"no resolver run {run_id!r} under {state_root}")
    launcher = LocalProcessLauncher()
    journal = Journal(repository.root)
    run = ResolveRun(repository, journal)
    run.state = repository.load()
    report = BaseRefresher(run, WorktreeOrchestrator(launcher, root), journal).report(
        run.require(), apply, base
    )
    for line in describe_refresh(report):
        typer.echo(line)


def describe_refresh(report: RefreshReport) -> list[str]:
    """Render a refresh the way somebody deciding whether to take it reads it."""
    base = report.base
    if base.reason:
        opening = f"base unchanged: {base.reason}"
    elif not base.moved():
        opening = f"base is current with {base.branch}"
    else:
        opening = (
            f"base {'moved' if report.applied else 'would move'} onto {base.branch}: "
            f"{base.was[:12]} → {base.commit[:12]}"
        )
    lines = [opening]
    lines.extend(f"  {path.as_posix()}" for path in base.conflicts)
    if base.conflicts:
        lines.append(
            f"Merge {base.was[:12]} with {base.branch} in a worktree, resolve it "
            "there, then adopt the result: --base <commit> --apply."
        )
    if not base.moved():
        return lines
    for lease in report.leases:
        if lease.conflicts:
            lines.append(
                f"  {lease.concern_id}: conflicts on "
                + ", ".join(path.as_posix() for path in lease.conflicts)
            )
        elif lease.applied:
            lines.append(f"  {lease.concern_id}: merged")
        elif lease.reason:
            lines.append(f"  {lease.concern_id}: {lease.reason}")
        else:
            lines.append(f"  {lease.concern_id}: merges cleanly")
    if not report.applied and any(not lease.conflicts for lease in report.leases):
        lines.append("Re-run with --apply to take it.")
    return lines


def detach_resolve(adapter: str, run_id: str | None, answers: list[str]) -> None:
    """Start a run that outlives this command, and say where to reach it.

    A blocking run holds the launching agent's only turn, so nothing could
    write to a run while it moved — which made every delivery route in the
    design unreachable, however well the channels underneath worked. Once
    launching returns, the run directory is the whole contract: the page and
    an orchestrating agent are peers on it, exactly as two pages would be.
    """
    root = project_root()
    resolved = run_id or (
        "resolve-"
        + resolver_git(
            LocalProcessLauncher(), root, ["rev-parse", "--short=12", "HEAD"]
        )
    )
    arguments = [
        "uv",
        "run",
        "lup-devtools",
        "harness",
        "resolve",
        "--adapter",
        adapter,
        "--run-id",
        resolved,
        *(part for answer in answers for part in ("--answer", answer)),
    ]
    sh.Command(arguments[0])(
        *arguments[1:],
        _cwd=str(root),
        _bg=True,
        _bg_exc=False,
        _new_session=True,
        _out="/dev/null",
        _err="/dev/null",
    )
    typer.echo(f"Run {resolved} started detached.")
    typer.echo(
        f"Follow it: uv run lup-devtools harness resolve supervise --run-id {resolved}"
    )


def admission_request(
    statements: list[str], note_targets: list[str], issue_numbers: list[int]
) -> AdmissionRequest | None:
    """Build the evidence one invocation asked to admit, if it asked at all."""
    if not statements and not note_targets and not issue_numbers:
        return None
    targets = parse_note_targets(note_targets)
    intake = resolver_intake(
        scan_tracked(find_feedback), generated_artifacts(project_root())
    )
    scanned = intake.actionable if targets else []
    return AdmissionRequest(
        notes=admission_notes(targets, scanned),
        statements=statements,
        issues=admitted_issues(issue_numbers),
    )


def answer_issues(concerns: list[Concern], manifest: ResolveManifest) -> list[int]:
    """Say on each answered issue where the work that answers it now sits.

    Only issues whose concern reached the review branch, because a concern
    that failed has nothing to point at and an issue told about work that
    does not exist is worse than an issue told nothing. Commented, never
    closed: a run's reviewer passing is not a human having read the code.
    """
    landed = {outcome.concern_id for outcome in manifest.outcomes if outcome.integrated}
    answered = {
        issue.number: issue
        for concern in concerns
        if concern.id in landed
        for issue in concern.issues
    }
    if not answered:
        return []
    return comment_on_issues(
        sorted(answered.values(), key=lambda issue: issue.number),
        f"Addressed on review branch `{manifest.review_branch}` by resolver run "
        f"`{manifest.run_id}`. Left open: the branch still wants a human review.",
    )


def admitted_issues(numbers: list[int]) -> list[IssueEvidence]:
    """Locate each named issue among the open ones, refusing any it cannot.

    Read from the tracker rather than retyped, so a concern admitted from an
    issue is grounded in exactly what intake would have planned from — and a
    number that names nothing open is a typo worth refusing at the flag
    rather than a concern planned from silence.
    """
    if not numbers:
        return []
    open_issues = {issue.number: issue for issue in fetch_open_issues()}
    missing = [str(number) for number in numbers if number not in open_issues]
    if missing:
        raise typer.BadParameter("no open issue numbered: " + ", ".join(missing))
    return [open_issues[number] for number in numbers]


def run_resolve(
    composition: NativeHarnessComposition,
    run_id: str | None,
    answers: list[str],
    abort_reason: str | None = None,
    wait_seconds: float = 0.0,
    supervisor: SupervisorSpawn | None = None,
    admission: AdmissionRequest | None = None,
    model: ConfiguredModel | None = None,
    adopt_config: bool = False,
    take_issues: bool = True,
) -> None:
    """Drive the shared persisted resolver through one explicit native adapter."""
    provided = parse_answer_flags(answers)
    if abort_reason is not None and admission is not None:
        raise typer.BadParameter("a run cannot be widened and ended in one command")
    # The recipe already names the target it compiles for and carries the
    # declaration it compiles, so the adapter a rerun recipe prints, the
    # plugin a lease deploys, and the hooks a session judges by all come from
    # the composition that was actually resolved.
    adapter = composition.recipe.label
    harness = composition.recipe.source
    plugin = harness.plugins[0]
    root = project_root()
    if not check_remote_auth():
        typer.echo(
            "Continuing local-only: agent git commands that need the remote "
            "will fail fast instead of prompting.",
            err=True,
        )
    launcher = LocalProcessLauncher()
    resolved_run_id = run_id or (
        "resolve-" + resolver_git(launcher, root, ["rev-parse", "--short=12", "HEAD"])
    )
    state_root = root / ".lup" / "resolve"
    # Every worktree this run leases lands under here, which is what makes
    # "a checkout lup created" a structural test rather than a judgement.
    worktree_root = root.parent / f"{root.name}-resolve-{resolved_run_id}"

    async def execute() -> None:
        from lup.adapters.claude.runtime import (
            ClaudeSandboxConfig,
            ClaudeSessionConfig,
            create_claude_session_factory,
        )
        from lup.adapters.codex.runtime import (
            CodexMcpServerConfig,
            CodexSessionConfig,
            create_codex_session_factory,
        )
        from lup.adapters.claude.config_home import (
            configuration_fault,
            selected_config_home,
            untrusted_degradation,
            workspace_config_environment,
        )
        from lup.adapters.claude.hooks import CLAUDE_SEMANTICS
        from lup.adapters.codex.hooks import CODEX_SEMANTICS
        from lup.harness.enforcement import semantic_policy_for
        from lup.hooks import (
            LupHooksConfig,
            create_git_inspection_hook,
            create_permission_hooks,
            merge_hooks,
        )
        from lup.policy.enforcement import NativeSemantics, create_policy_hooks

        from lup.adapters.codex.harness_runtime import (
            CodexPluginInstaller,
            PluginCacheConfig,
        )

        from lup.adapters.codex.home import select_codex_home

        def codex_policy_environment(target: str, environment: EnvVars) -> EnvVars:
            """Point a Codex session at a home carrying this project's policy.

            The other adapter takes the semantic kernel as session hooks. This
            one has no such seam — its app-server handles dynamic tools and MCP
            elicitations and holds approvals at ``never`` — so what judges a
            Codex session is the generated dispatcher its plugin registers, and
            a plugin is installed per configuration home. Preparing the home
            the way an interactive launch does is what puts a session opened
            here under the policy an operator already runs under, instead of
            leaving the OS sandbox as its only floor.

            One home per run rather than per concern: the plugin is the same
            for every worker, and seeding a personal account copy once per
            concern would differ from the operator's in nothing but cost.
            """
            if target != "codex":
                return {}
            home = select_codex_home(None, environment, root)
            cache = CodexPluginInstaller(
                PluginCacheConfig(codex_home=home.path, marketplace=plugin.marketplace)
            ).ensure(root / ".codex" / "plugins" / plugin.name, root)
            typer.echo(f"Verified installed Codex plugin: {cache.installed_root}")
            return {"CODEX_HOME": str(home.path)}

        # lup: Selecting a profile must reach every lup invocation, not just a
        # native launch. `profile use X` should decide the account for anything
        # lup runs — agents, subagents, resolver planners, workers, reviewers —
        # and today it decides only what `harness claude`/`codex` opens. This
        # site is one instance: it inherits the launching shell's identity, and
        # `select_codex_home(None, environment, root)` above drops the profile
        # and store that launch.py passes. The seam already exists in
        # `lup.runtime.profiles.ProfileDirectory`; this entry point simply never
        # reaches it. Fix it generally rather than per call site: building a
        # session environment should require naming the profile it runs under,
        # so a new entry point cannot inherit an operator's account by omission
        # the way this one does.
        session_environment = non_interactive_environment(
            os.environ  # lup: ignore[os-environ] — sessions inherit the console
        )
        # Both identities are written, never omitted: a runtime merges the
        # session environment over the launching process's, so a reviewer
        # that stayed silent would inherit an operator's exported identity.
        worker_environment = {
            **session_environment,
            **agent_identity_environment(harness.resolver.worker_identity),
        }
        reviewer_environment = {
            **session_environment,
            **agent_identity_environment(""),
            **concern_allowances_environment([]),
        }
        for environment in (worker_environment, reviewer_environment):
            environment.update(codex_policy_environment(adapter, session_environment))
        session_model = model.reaching(adapter) if model is not None else None
        if session_model is None and model is not None:
            typer.echo(
                f"Configured model {model.name!r} does not route to adapter "
                f"{adapter!r}; sessions use the adapter's native default model."
            )

        def isolated_claude_environment(
            environment: EnvVars, workspace: Path
        ) -> EnvVars:
            """One workspace's sessions, on a configuration document of their own.

            Every worker starts by reading Claude's configuration document and
            writing it back, so a phase that opens them together has each one
            reading what the others are still writing: a run of eleven lost
            six to a truncated parse and the remaining five never started,
            with no concern having produced code. A document per workspace
            removes the shared file the race needs, which is why neither a
            lock nor a cap on how many run at once appears anywhere here.

            Trust rides along because it is written into that same document.
            An untrusted workspace does not fail a session — Claude drops the
            repository's declared permissions, warns into that session's own
            stderr and carries on — so a run without this establishes nothing
            and reports the loss only as noise between progress lines. A run
            that cannot establish it stops here instead, before the session
            that would have run under a posture the repository never declared.
            """
            derived = workspace_config_environment(
                environment,
                workspace,
                trust=run_owned(workspace, root, worktree_root),
            )
            degradation = untrusted_degradation(
                workspace, selected_config_home(derived).document
            )
            if degradation is not None:
                raise typer.BadParameter(
                    f"{degradation} This run extends trust to the repository it "
                    "was invoked against and to the checkouts it made of that "
                    f"repository under {worktree_root}, and to nothing else."
                )
            return {**environment, **derived}

        # Once, before anything is leased. Every private home this run derives
        # is seeded from the one document this reads, so a run that cannot
        # read it opens no session anywhere — a fact about the environment
        # rather than about any concern. Discovering it per worker instead
        # turned one environmental fault into an exception group of concern
        # failures and burned every lease the run had taken.
        fault = (
            configuration_fault(selected_config_home(session_environment))
            if adapter == "claude"
            else None
        )
        if fault is not None:
            raise typer.BadParameter(fault)

        def toolchain_writable_paths() -> list[Path]:
            """Absolute paths a sandboxed worker's toolchain must be able to write.

            A worker is contained to its lease, which is where its work belongs
            — but every command it verifies with reaches the toolchain through
            `uv`, whose cache lives outside any worktree. Granting the declared
            paths is what keeps containment from disarming verification.
            """
            declared = plugin.hooks.sandbox if plugin.hooks is not None else None
            return [
                Path(path).expanduser()
                for path in (declared.writable_paths if declared is not None else [])
            ]

        # lup: Every session opened here loses Bash entirely. A session launched
        # from inside sandboxed Bash cannot create its own
        # `~/.claude/session-env/<id>`, so each shell call dies on `EROFS:
        # read-only file system, mkdir`. The directory holds 508 entries, all
        # made at startup *outside* the sandbox, which is why an interactive
        # session never sees this and a spawned one always does. The planner
        # that produced this run's inventory ran read-only on it: its own audit
        # records losing grep and the drift checker, and an explorer reporting
        # absence as fact after silently narrowing its scope. Workers will hit
        # exactly the same wall, so this blocks the implementation phase, not
        # just planning. Fix it with the session launcher outside the sandbox or
        # that path made writable — the deny looks like the runtime's own
        # protection of its config directory, so test that a grant can override
        # it rather than assuming.
        def worker_factory(context: WorkerContext) -> SessionFactory:
            """Open one worker session that can ask its own questions.

            The tools are bound to this concern here rather than taking the
            id as an argument, so a worker structurally cannot post against
            a sibling. ``core`` is read at call time, which is after it is
            built — the wake event only exists once the core does.

            The inbox is the run's own for this actor, not a second reader
            opened here. Two readers over one message stream each began at
            whatever its head was when they were made, so a message posted
            while a turn was in flight sat behind both of them.
            """
            cwd = context.root
            inbox = core.actors.inbox(context.actor)
            tool_context = ResolverToolContext(
                run_dir=state_root / resolved_run_id,
                concern_id=context.concern_id,
                lease_root=cwd,
            )
            # Grants are per-concern: a lease carries only what the human
            # approved with the concern it was leased for.
            granted = [allowance.value for allowance in context.allowances]
            concern_environment = {
                **worker_environment,
                **concern_allowances_environment(granted),
            }
            if adapter == "claude":
                server = create_mcp_server(
                    "resolver",
                    tools=create_question_tools(
                        QuestionMailbox(tool_context.run_dir),
                        context.concern_id,
                        run_id=resolved_run_id,
                        lease_root=tool_context.lease_root,
                        wake=core.wake,
                    ),
                )
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=session_model,
                        system_prompt="Execute the persisted Lup resolver assignment.",
                        cwd=cwd,
                        add_dirs=[cwd, *toolchain_writable_paths()],
                        plugin_dirs=[lease_plugin_dir(cwd, plugin.name)],
                        sandbox=ClaudeSandboxConfig(),
                        environment=isolated_claude_environment(
                            concern_environment, cwd
                        ),
                        tool_servers={"resolver": server},
                        allowed_tools=[
                            f"mcp__resolver__{name}"
                            for name in server_tool_names(server)
                        ],
                        hooks=merge_hooks(
                            merge_hooks(
                                merge_hooks(
                                    create_permission_hooks([cwd], []),
                                    worker_policy_hooks(granted, CLAUDE_SEMANTICS),
                                ),
                                create_git_inspection_hook(),
                            ),
                            create_inbox_hooks(inbox),
                        ),
                    )
                )
            return create_codex_session_factory(
                CodexSessionConfig(
                    model=session_model,
                    developer_instructions=(
                        "Execute the persisted Lup resolver assignment."
                    ),
                    cwd=cwd,
                    sandbox="workspace-write",
                    # An asking policy is what makes the app-server put this
                    # worker's commands to the hooks below. Left at "never" a
                    # Codex worker ran with the OS sandbox as its only floor,
                    # because its generated plugin hook is not reached either.
                    approval_policy="onRequest",
                    hooks=merge_hooks(
                        worker_policy_hooks(granted, CODEX_SEMANTICS),
                        create_inbox_hooks(inbox),
                    ),
                    environment=concern_environment,
                    mcp_servers={
                        "resolver": CodexMcpServerConfig(
                            command="uv",
                            args=[
                                "run",
                                "lup-devtools",
                                "harness",
                                "serve-resolver-tools",
                            ],
                            env={**session_environment, **tool_context.to_env()},
                        )
                    },
                    writable_roots=[cwd],
                )
            )

        def worker_policy_hooks(
            granted: list[str], semantics: NativeSemantics
        ) -> LupHooksConfig:
            """Judge a worker's calls by the policy every plugin enforces.

            The directory ACL beside this bounds the worker's filesystem
            reach and says nothing about what it may fetch or run — so
            egress and shell passed unjudged, with the OS sandbox as the
            only floor. This supplies exactly those verdicts, scoped to the
            tools it has rules for: a headless worker has no human to answer
            an `ask`, so judging a tool this vocabulary cannot classify
            would deny it, and would outrank the ACL's own grant.

            The worker is autonomous because its edits are reviewed by an
            actor of this run, which is the same fact the generated tree
            derives its autonomous list from.

            ``granted`` carries the concern's approved allowances, the same
            list the session environment declares — so this judge and the
            lease's deployed dispatcher release exactly the same gates.

            ``semantics`` is how one runtime's calls become the vocabulary
            this policy judges. It is a parameter rather than a constant
            because both runtimes have that decode now, and hardcoding one
            was what left the other's workers judged by nothing.
            """
            return create_policy_hooks(
                semantic_policy_for(
                    harness.declared_hooks,
                    autonomous=True,
                    interactive=False,
                    allowances=granted,
                ),
                semantics,
            )

        def reviewer_factory(cwd: Path) -> SessionFactory:
            if adapter == "claude":
                return create_claude_session_factory(
                    ClaudeSessionConfig(
                        model=session_model,
                        system_prompt=(
                            "Independently review the persisted resolver change."
                        ),
                        cwd=cwd,
                        add_dirs=[cwd],
                        plugin_dirs=[lease_plugin_dir(cwd, plugin.name)],
                        environment=isolated_claude_environment(
                            reviewer_environment, cwd
                        ),
                        hooks=create_permission_hooks([], [cwd]),
                    )
                )
            return create_codex_session_factory(
                CodexSessionConfig(
                    model=session_model,
                    approval_policy="onRequest",
                    hooks=create_permission_hooks([], [cwd]),
                    developer_instructions=(
                        "Independently review the persisted resolver change."
                    ),
                    cwd=cwd,
                    sandbox="read-only",
                    environment=reviewer_environment,
                )
            )

        mailbox = QuestionMailbox(state_root / resolved_run_id)
        offer_flag_answers(mailbox, resolved_run_id, provided)
        for stale in inert_offers(mailbox):
            typer.echo(stale, err=True)
        core = ResolverCore(
            ResolverConfig(
                state_root=state_root,
                workspace=root,
                worktree_root=worktree_root,
                run_id=resolved_run_id,
                integration_branch=integration_branch(launcher, root, resolved_run_id),
                # The whole gate rather than part of it restated. Naming three
                # of its checks let a worker introduce an anti-pattern or
                # leave an unresolved note and still verify green — the two
                # rules most specific to this repository were the ones its own
                # output was not held to. `--since` scopes the note gate to
                # what this tree changed, because a concern's worktree holds
                # every sibling's notes and it has no lease on any of them.
                # The commit is named per verified tree rather than here: a
                # base written into this list is part of the composition every
                # resume is checked against, so a run could not resume itself
                # once its base moved, and leases cut from different commits
                # have no one answer to give it.
                verification_commands=[
                    VerificationCommand(
                        name="dev check",
                        arguments=["uv", "run", "lup-devtools", "dev", "check"],
                        base_option="--since",
                    ),
                ],
            ),
            harness.resolver,
            worker_factory,
            reviewer_factory,
            composition.invocation_renderer,
            launcher,
            observer=ConsoleResolverObserver(),
            worktree_preparer=FeatureWorktreePreparer(root),
            answer_wait_seconds=wait_seconds,
            adopt_config=adopt_config,
        )

        async def drive() -> None:
            if abort_reason is not None:
                if not core.repository.exists():
                    raise typer.BadParameter(
                        f"no resolver run {resolved_run_id!r} to abort"
                    )
                aborted = core.abort(abort_reason)
                for record in aborted.cleanup:
                    typer.echo(
                        f"[abort] {record.action} {record.path}: {record.reason}"
                    )
                typer.echo(f"aborted {resolved_run_id}: {abort_reason}")
                return
            if admission is not None:
                if not core.repository.exists():
                    raise typer.BadParameter(
                        f"no resolver run {resolved_run_id!r} to admit into"
                    )
                report_admission(await core.admit(admission), adapter, resolved_run_id)
                return
            try:
                if core.repository.exists():
                    manifest = await core.resume()
                else:
                    # lup: A fresh run can only be seeded from notes already in
                    # the tree — `--admit` refuses with "no resolver run ... to
                    # admit into" until one exists. But `/lup:resolve <concerns>`
                    # is how a human actually arrives, with the concerns in their
                    # own words and nothing yet written down, so the agent has to
                    # invent note sites before it can start. Let statements seed
                    # a run the way they can join one.
                    intake = resolver_intake(
                        scan_tracked(find_feedback), generated_artifacts(root)
                    )
                    for carried in intake.carried:
                        typer.echo(carried)
                    for owned in intake.generated:
                        typer.echo(f"leaving to its generator: {owned}")
                    comments = intake.actionable
                    open_issues = fetch_open_issues() if take_issues else []
                    for issue in open_issues:
                        typer.echo(
                            f"taking as evidence: {issue.reference()} {issue.title}"
                        )
                    if not comments and not open_issues:
                        typer.echo("No unresolved # lup: comments, and no open issues.")
                        return
                    note_paths = sorted({Path(comment.file) for comment in comments})
                    source = resolver_source_snapshot(
                        launcher,
                        root,
                        core.repository.root,
                        note_paths,
                    )
                    manifest = await core.run(
                        ResolveRequest(
                            source=source,
                            notes=[
                                InventoryNote(
                                    file=Path(comment.file),
                                    line=comment.start_line,
                                    text=comment.marker_text(),
                                    context=comment.context,
                                )
                                for comment in comments
                            ],
                            issues=open_issues,
                        )
                    )
            except ResolverAwaitingAnswers as parked:
                planned = (
                    core.repository.load().concerns if core.repository.exists() else []
                )
                report_awaiting(parked, adapter, resolved_run_id, planned)
                return
            typer.echo(f"Review branch: {manifest.review_branch}")
            for number in answer_issues(core.repository.load().concerns, manifest):
                typer.echo(f"commented on #{number}")
            typer.echo(manifest.model_dump_json(indent=2))

        async with spawned_supervisor(
            supervisor or SupervisorSpawn(), resolved_run_id, adapter
        ):
            await drive()

    asyncio.run(execute())
