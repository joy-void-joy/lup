"""Unified pre-flight checks: ruff, pyright, pytest."""

import json
import os
import tomllib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from importlib.util import find_spec
from pathlib import Path
from tempfile import NamedTemporaryFile

import sh
import typer
from pydantic import BaseModel

from lup.providers.harness import guidance_artifacts
from lup.harness.codescan.markers import find_feedback
from lup.harness.coverage import coverage_gaps
from lup.harness.modules import unloaded_guidance
from lup.harness.models import (
    GUIDANCE_BYTE_BUDGET,
    TEMPLATE_GUIDANCE_HEADROOM,
    GuidanceSection,
    HookSet,
    document_byte_size,
)
from lup.devtools.hooks.classify import stopped_everyday
from lup.policy.assets.host import project_environment
from lup.policy.everyday import SESSION_SHAPES
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
from lup.devtools.dev.worktree import OWNERSHIP_MERGE_DRIVER, MergeDriver
from lup.devtools.dev.comments import FoundComment, scan_tracked
from lup.devtools.dev.environment import foreign_installs
from lup.devtools.dev.gates import sweep_all
from lup.devtools.dev.records import branches_awaiting_adoption, record_location
from lup.devtools.harness.drift import (
    RepositoryWriter,
    inspect_drift,
    report_stale,
    roster_gaps,
)
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.devtools.utils import decode_stderr, uv
from lup.execution.shell import git

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
    """One external tool's verdict, carrying what it printed when it failed.

    A tool that never started is a verdict too. `sh` prepares the child before
    exec — the working directory among it — and what fails there arrives as a
    fork exception rather than an exit status, so it is a sibling of the class
    a caller catches rather than a kind of it. Escaping here takes the whole
    gate down: the checks that had already passed go unreported, and a
    condition of the environment reads as a crash in the checker. So the two
    are reported the same way and told apart by what the row says.
    """
    try:
        command()
    except sh.ErrorReturnCode as error:
        printed = [error.stdout.decode().rstrip()] if error.stdout else []
        return CheckReport(name=name, passed=False, lines=[f"{name}: FAIL", *printed])
    except sh.ForkException as error:
        return CheckReport(
            name=name,
            passed=False,
            lines=[
                f"{name}: FAIL (never started)",
                *(f"  {line}" for line in str(error).strip().splitlines()),
            ],
        )
    return CheckReport(name=name, lines=[f"{name}: {ok}"])


def non_code_roots(project: DevProject) -> list[str]:
    """Retained data and disposable scratch that no code check should read."""
    return [
        row["root"] for row in project.path_roles if row["role"] in ("data", "scratch")
    ]


def option_arguments(option: str, values: list[str]) -> list[str]:
    """Repeat one CLI option once for every value it carries."""
    return [argument for value in values for argument in (option, value)]


def ruff_format_check(fix: bool, excluded_roots: list[str]) -> CheckReport:
    """Whether every file is formatted — or, with *fix*, formatting them."""
    return ran(
        "ruff format",
        lambda: uv(
            "run",
            "ruff",
            "format",
            *([] if fix else ["--check"]),
            *option_arguments("--exclude", excluded_roots),
            ".",
        ),
        "applied" if fix else "ok",
    )


def ruff_lint_check(fix: bool, excluded_roots: list[str]) -> CheckReport:
    """Whether the lint rules hold — or, with *fix*, applying what they can."""
    return ran(
        "ruff check",
        lambda: uv(
            "run",
            "ruff",
            "check",
            *option_arguments("--exclude", excluded_roots),
            ".",
            *(["--fix"] if fix else []),
        ),
    )


def pyright_base_configuration(root: Path) -> Path | None:
    """The configuration Pyright would discover from the repository root."""
    json_config = root / "pyrightconfig.json"
    if json_config.is_file():
        return json_config
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    with pyproject.open("rb") as stream:
        settings = tomllib.load(stream)
    match settings:
        case {"tool": {"pyright": _}}:
            return pyproject
        case _:
            return None


def pyright_check(excluded_roots: list[str]) -> CheckReport:
    """Whether the code-bearing workspace type-checks."""
    root = project_root()
    base = pyright_base_configuration(root)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".lup-pyright-",
        suffix=".json",
        dir=root,
        delete=False,
    ) as stream:
        configuration = Path(stream.name)
        json.dump(
            {
                **({"extends": str(base)} if base is not None else {"include": ["."]}),
                "exclude": excluded_roots,
            },
            stream,
        )
    try:
        return ran(
            "pyright",
            lambda: uv("run", "pyright", "--project", str(configuration)),
        )
    finally:
        configuration.unlink(missing_ok=True)


def parallel_arguments(workers: int) -> list[str]:
    """The flag that spreads a suite over processes, where one answers for it.

    `-n` belongs to pytest-xdist, and a project building on this library has
    no reason to hold it: a package declares what it needs to run, and a
    dependency group installs for the project that writes it rather than for
    anyone depending on that project. Declaring the plugin would therefore
    either reach this library's own developers alone or push test parallelism
    into every adopter's runtime install, so the flag is offered where it is
    importable and dropped where it is not. Pytest rejects an unrecognized
    argument before collecting anything, and a gate that failed on that would
    be reporting on its own speed rather than on the suite.

    Fewer than two workers spells serial, so the count descends into running
    the same tests behind a single interpreter rather than needing a second
    way of saying nothing.
    """
    if workers < 2 or find_spec("xdist") is None:
        return []
    return ["-n", str(workers)]


def ignored_arguments(excluded_roots: list[str]) -> list[str]:
    """The globs that keep collection out of retained data and scratch."""
    return option_arguments(
        "--ignore-glob",
        [pattern for root in excluded_roots for pattern in (root, f"{root}/**")],
    )


class TestRoot(BaseModel):
    """One independently installed test suite the project asks the gate to run."""

    name: str
    directory: Path

    def absent(self) -> CheckReport:
        """The verdict a root naming a directory this checkout lacks earns.

        A different fact from a suite that failed, and the reader's next move
        differs: the declaration is wrong, or the tree it named is somewhere
        else. It is answered before the run rather than caught after it,
        because `sh` changes directory in the forked child — where the failure
        arrives as a fork exception rather than an exit status, escapes the
        handler that reads exit statuses, and takes the whole gate down with a
        traceback while the checks that had already passed go unreported.
        """
        return CheckReport(
            name=self.name,
            passed=False,
            lines=[
                f"{self.name}: FAIL (no directory at {self.directory})",
                f"  the '{self.name}' test root names a path this checkout does "
                "not hold — drop it from the project's declared `test_roots`, "
                "or point it at the suite it meant",
            ],
        )

    def checked(self, workers: int, excluded_roots: list[str]) -> CheckReport:
        """Whether this suite passes, run from its own root.

        The library ships to an index without the application beside it, so
        its suite runs from its own directory where `src` is all it can see —
        a library test reaching for a template fixture passes at the root and
        fails there, which is the only place that difference shows.
        """
        if not self.directory.is_dir():
            return self.absent()
        return ran(
            self.name,
            lambda: uv(
                "run",
                "pytest",
                *parallel_arguments(workers),
                *ignored_arguments(excluded_roots),
                _cwd=str(self.directory),
            ),
        )


class RootSelection(BaseModel):
    """One suite's share of what a caller named, spelled from inside that suite.

    Empty *paths* asks for everything the suite declares, which is what the
    root's own `testpaths` already says — so a caller who named nothing gets
    each suite whole rather than a selection of none.
    """

    root: TestRoot
    paths: list[str]


def owning_index(test_roots: list[TestRoot], selection: Path) -> int | None:
    """Which declared suite holds a named path, deepest root winning.

    A workspace root contains the package roots under it, so the outermost
    suite would claim every path if the roots were read in the order they
    were declared. The deepest one containing the path is the suite that
    installs it.
    """
    named = selection.resolve()
    deepest = sorted(
        range(len(test_roots)),
        key=lambda index: len(test_roots[index].directory.resolve().parts),
        reverse=True,
    )
    return next(
        (
            index
            for index in deepest
            if named.is_relative_to(test_roots[index].directory.resolve())
        ),
        None,
    )


def group_by_root(
    test_roots: list[TestRoot], selections: list[str]
) -> list[RootSelection]:
    """Split what a caller named into one invocation per suite that owns part.

    Two independently installed suites each own a top-level `tests` package,
    and one interpreter has one meaning for that name: a run naming a path
    from each has both suites claiming `tests.conftest`, and collection dies
    before a test runs. No import mode settles it, because the collision is in
    what the suites are rather than in how pytest finds them — the isolation
    that makes them separate installs is the same isolation that stops them
    sharing an interpreter. So the narrowing move a caller reaches for — run
    the suites I touched — is served by one run per suite instead.
    """
    owned: list[list[str]] = [[] for _ in test_roots]
    for selection in selections:
        index = owning_index(test_roots, Path(selection))
        if index is None:
            declared = ", ".join(str(root.directory) for root in test_roots)
            raise typer.BadParameter(
                f"{selection} sits under no declared test root ({declared})"
            )
        installed = test_roots[index].directory.resolve()
        owned[index].append(str(Path(selection).resolve().relative_to(installed)))
    return [
        RootSelection(root=root, paths=paths)
        for root, paths in zip(test_roots, owned, strict=True)
        if paths or not selections
    ]


def run_selected(
    test_roots: list[TestRoot],
    selections: list[str],
    excluded_roots: list[str],
    workers: int = TEST_WORKERS,
) -> None:
    """Run each named path in the suite that installs it, reporting per suite.

    Output reaches the terminal as it arrives rather than being carried back
    the way the gate carries it: a caller who named one file wants pytest's
    own failure report, and the gate's ordered summary exists for a run whose
    checks finish out of order.
    """
    failed: list[str] = []
    for group in group_by_root(test_roots, selections):
        if not group.root.directory.is_dir():
            for line in group.root.absent().lines:
                typer.echo(line)
            failed.append(group.root.name)
            continue
        typer.echo(f"\n{group.root.name}  ({group.root.directory})")
        try:
            uv(
                "run",
                "pytest",
                *group.paths,
                *parallel_arguments(workers),
                *ignored_arguments(excluded_roots),
                _cwd=str(group.root.directory),
                _fg=True,
            )
        except sh.ErrorReturnCode:
            failed.append(group.root.name)
        except sh.ForkException as error:
            typer.echo(f"{group.root.name}: never started\n{str(error).strip()}")
            failed.append(group.root.name)
    if failed:
        typer.echo(f"\nFailed: {', '.join(failed)}")
        raise typer.Exit(1)


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


def guidance_bytes(compositions: list[NativeHarnessComposition]) -> int:
    """The heaviest always-loaded document any runtime tree renders, in bytes.

    Read off the compiled artifacts rather than re-rendered from the parts,
    because ``reject_oversized_guidance`` refuses on ``artifact.content`` —
    banner included — and a row measuring anything else is not measuring the
    gate it reports for. Re-rendering read 260 bytes light, which is a window
    where the row says ok about a tree generation would refuse.
    """
    sizes = [
        document_byte_size(artifact.content)
        for composition in compositions
        for artifact in guidance_artifacts(composition.recipe.desired)
    ]
    if not sizes:
        raise ValueError(
            "no target renders an always-loaded guidance artifact, so its "
            "budget cannot be weighed — a runtime tree lost its "
            "'harness.guidance' artifact, or no targets were resolved."
        )
    return max(sizes)


def budget_reports(
    used: int, scaffold: bool, declined: list[GuidanceSection] | None = None
) -> list[CheckReport]:
    """Every verdict the guidance's weight earns, given what this repository is.

    The runtime ceiling always; the scaffold's share of it only while this
    repository is still the template, because only then is the document one
    somebody else inherits and only then is there a reservation to keep. The
    all-on row whenever there is prose this tree declines, because that is the
    only condition under which the number differs from the one above it.
    """
    return [
        guidance_budget_report(used),
        *([scaffold_budget_report(used)] if scaffold else []),
        *([roster_budget_report(used, declined)] if declined else []),
    ]


def roster_budget_report(used: int, declined: list[GuidanceSection]) -> CheckReport:
    """Whether a project taking every module could load every module's prose.

    The row the two above it cannot stand in for. Both weigh the document this
    tree renders, and this tree is the lightest interesting composition of its
    own roster — a scaffold takes every module and loads the prose of only the
    ones it offers. So a module off by default can grow its section without
    either row moving, and the project that turns it on finds a document the
    runtime truncates.

    Measured as the tree's own weight plus the sections it declines, rather
    than by recomposing: the compiled artifact carries a banner the parts do
    not, and a recomposed measurement reads light by exactly that much.
    """
    return budget_report(
        "roster budget",
        used + sum(document_byte_size(section.text) for section in declined),
        GUIDANCE_BYTE_BUDGET,
        f"every module's prose loaded, {len(declined)} section(s) this tree declines",
    )


def budget_report(name: str, used: int, ceiling: int, note: str) -> CheckReport:
    """One budget's verdict, in the sentence every budget row answers in.

    Both rows weigh the same document against a different ceiling, so the
    sentence is written once: what a reader learns to expect from one row
    holds for the other, and neither can drift into reporting a different set
    of facts than its neighbour. What differs is the note each appends, which
    is the only part its own ceiling makes it the authority on.
    """
    free = ceiling - used
    state = "ok" if free >= 0 else f"FAIL (over by {-free})"
    return CheckReport(
        name=name,
        passed=free >= 0,
        lines=[f"{name}: {state} — {used}/{ceiling} bytes, {note}"],
    )


def guidance_budget_report(used: int) -> CheckReport:
    """Whether a session will load the whole document or a truncated one."""
    return budget_report(
        "guidance budget",
        used,
        GUIDANCE_BYTE_BUDGET,
        f"{GUIDANCE_BYTE_BUDGET - used} free",
    )


def scaffold_budget_report(
    used: int, headroom: int = TEMPLATE_GUIDANCE_HEADROOM
) -> CheckReport:
    """Whether a scaffold has left its adopter room inside the runtime ceiling.

    A separate verdict from the budget row beside it, because the two ask
    different questions of the same number. That one asks whether a runtime
    will truncate this tree, which is true of every project. This one asks
    whether a repository still shipping as a template is spending guidance
    budget on itself that the domain adopting it will need for its own
    architecture and conventions — and there is no domain yet to notice.

    Gating rather than advisory: a reservation nobody has to honour is spent
    by the first section that wants the room, which is how the headroom
    disappeared before anyone declared one.

    A passing row states the room left, because the number a session needs
    before it writes is how much it may spend, and the reservation — which
    never moves — cannot tell it that. The failing row states the overage
    instead: a negative amount of room is what the overage already says.
    """
    ceiling = GUIDANCE_BYTE_BUDGET - headroom
    free = ceiling - used
    reserved = f"{headroom} reserved for the adopting domain"
    note = f"{free} free, {reserved}" if free >= 0 else reserved
    return budget_report("scaffold budget", used, ceiling, note)


def branch_record_reports(pending: list[str]) -> list[CheckReport]:
    """What lup's branch bookkeeping earns while it still sits in two places.

    Advisory rather than gating. Every read falls back to the shared config
    per field, so a clone that never adopts its records answers exactly as
    one that did: there is no defect here to refuse a branch over. The
    command that finishes it writes the shared git directory, which is the
    host's, so a gating row would be red in every worktree until somebody
    stood somewhere no session reaches — and a gate whose resting colour is
    red is a gate a reader stops reading.

    Nothing at all once no branch is left, rather than a permanent ok, for
    the same reason: this is one move with an end, and a row that can only
    say ok from then on is a line everybody learns to skip. The gate prints
    the lines a check hands back, so handing back no check is how a row
    leaves — the shape the borrowed-environment and unlanded-sibling rows
    already use.
    """
    if not pending:
        return []
    destination = record_location(pending[0]).parent
    return [
        CheckReport(
            name="branch records",
            counted=False,
            lines=[
                f"branch records: {len(pending)} branch(es) still recorded in "
                "the shared git config (advisory)",
                "  every read falls back to those keys, so nothing is broken",
                "  `lup-devtools git worktree adopt-records` moves them, "
                "once per clone",
                f"  it writes the shared git directory's `{destination}/`, "
                "so it runs on the host",
            ],
        )
    ]


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
    git_guards: list[GitGuard],
    hooks_declaration: HookSet,
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
                ("module", project.modules.declined()),
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

        # Asked here for the reason the guards above are: git resolves a driver
        # name from config alone, which no repository can ship, so a checkout
        # that never ran `worktree create` reads the declaration, finds nothing
        # registered, and text-merges the generated trees without a word. What
        # that costs is the compiled dispatcher: conflict markers in a script
        # the runtime executes leave a boundary refusing every call in the
        # session, the merge abort included.
        registered = MergeDriver().satisfied()
        yield CheckReport(
            name="merge driver",
            passed=registered,
            lines=[
                f"merge driver: ok ({OWNERSHIP_MERGE_DRIVER})"
                if registered
                else f"merge driver: FAIL ({OWNERSHIP_MERGE_DRIVER} is unregistered)",
                *(
                    []
                    if registered
                    else [
                        "  the generated trees text-merge and can conflict",
                        "  register it with `lup-devtools git merge-driver`",
                    ]
                ),
            ],
        )

        # Beside the guards for the reason they are here: this is the other
        # thing about a clone that no file in the tree can settle, and it is
        # the only place the unfinished half of a move says so. The keys it
        # counts answer every read, so nothing else has any reason to speak.
        yield from branch_record_reports(branches_awaiting_adoption())

        # The one measurement of the shell vocabulary that reads the direction
        # a tightening shows up in. The recorded asks say which commands a
        # question was raised about, and the rule census says what each row
        # earns; neither would notice a de-escalation that stopped firing, so
        # a change putting a question in front of `git status` passes both.
        stopped = stopped_everyday(hooks_declaration)
        declared_count = sum(
            len(family.commands) for family in hooks_declaration.everyday_commands
        )
        swept = declared_count * len(SESSION_SHAPES)
        yield CheckReport(
            name="everyday commands",
            passed=not stopped,
            lines=[
                f"everyday commands: FAIL ({len(stopped)} stopped of {swept})",
                *(
                    line
                    for item in stopped
                    for line in (
                        f"  [{item.effect}] {item.command}",
                        f"    {item.what}, {item.shape} — {item.reason}",
                    )
                ),
            ]
            if stopped
            else [
                f"everyday commands: ok, {declared_count} allowed in "
                f"{len(SESSION_SHAPES)} session shapes"
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

        # Beside parity because both ask whether the roster arrived whole, one
        # turn further out: parity reads a declaration against the trees, and
        # this reads the checkout against the modules that were meant to
        # declare it. A subject nobody claims reaches neither of the others —
        # it renders into every tree, identically, forever.
        unclaimed = coverage_gaps(project_root(), project.coverage)
        yield CheckReport(
            name="module coverage",
            passed=not unclaimed,
            lines=[
                f"module coverage: FAIL ({len(unclaimed)} unclaimed)",
                *(f"  {gap.describe()}" for gap in unclaimed),
            ]
            if unclaimed
            else [
                "module coverage: ok, "
                f"{len(project.coverage.modules)} module(s) claim everything declared"
            ],
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

        yield from budget_reports(
            guidance_bytes(compositions),
            scaffold,
            unloaded_guidance(project.coverage.modules, project.modules),
        )

        # advisory — the environment is the operator's arrangement rather than
        # this branch's, so a borrowed one is worth reading and not worth
        # refusing a merge over. It is reported at all because nothing else
        # would ever say it: a sync into a shared environment succeeds, and
        # the project it uninstalled finds out somewhere nobody touched.
        environment = project_environment(project_root())
        borrowed = (
            foreign_installs(project_root(), environment)
            if environment.is_dir()
            else []
        )
        if borrowed:
            yield CheckReport(
                name="borrowed environment",
                counted=False,
                lines=[
                    f"borrowed environment: {len(borrowed)} other project(s) "
                    "(advisory)",
                    f"  {environment}",
                    *(f"  holds {owner}" for owner in borrowed),
                    "  `dev env sync` refuses to write over them, "
                    "`dev env status` says why",
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
                    *(f"  {branch.name}  {branch.standing()}" for branch in unlanded),
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
    git_guards: list[GitGuard],
    hooks_declaration: HookSet,
    scope: list[str] | None = None,
    test_workers: int = TEST_WORKERS,
) -> None:
    """Run ruff format, ruff check, pyright, pytest, and this gate's own sweeps.

    Read-only by default (reports issues without modifying files).
    Pass *fix* to auto-fix formatting and lint issues. ``scope`` narrows the
    note and anti-pattern gates to paths this tree is answerable for.
    """
    excluded_roots = non_code_roots(project)
    tools: list[Callable[[], CheckReport]] = [
        partial(ruff_format_check, fix, excluded_roots),
        partial(ruff_lint_check, fix, excluded_roots),
        partial(pyright_check, excluded_roots),
        *(
            []
            if no_test
            else [
                partial(root.checked, test_workers, excluded_roots)
                for root in test_roots
            ]
        ),
    ]
    sweeps = partial(
        scan_reports,
        project,
        scope,
        compositions,
        repository_writers,
        git_guards,
        hooks_declaration,
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
