"""Typer command tree for dev operations: worktrees, branches, PRs, checks.

Everything here is workflow rather than domain, so what it needs to know
about the repository it runs in arrives as a declaration: the project facts
the scans read, the harness targets and generated files the gate checks, and
the declarations the policy and plugin commands explain. An application adds
whatever else its own `dev` tree offers to the app it gets back.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import sh
import typer

import lup.devtools.dev.antipatterns as antipatterns_mod
import lup.devtools.dev.boundaries as boundaries_mod
import lup.devtools.dev.check as check
import lup.devtools.dev.comments as comments
import lup.devtools.dev.guidance as guidance
import lup.devtools.dev.issues as issues_mod
import lup.devtools.dev.history as history
import lup.devtools.dev.undo as undo
import lup.devtools.dev.model_config as model_config_mod
import lup.devtools.dev.environment as environment_mod
import lup.devtools.dev.pending as pending_mod
import lup.devtools.dev.plugin as plugin_mod
import lup.devtools.dev.policy_explain as policy_explain
import lup.devtools.dev.questions as questions_mod
import lup.devtools.dev.preservation as preservation
import lup.devtools.dev.modules as modules
import lup.devtools.dev.seams as seams
import lup.devtools.dev.relocate as relocate_mod
import lup.devtools.dev.rules as rules
from lup.harness.codescan.markers import NoteKind
from lup.harness.codescan.registry import all_rules
import lup.devtools.py.app as py
from lup.devtools.dev.declarations import DevDeclarations
from lup.devtools.hooks.app import create_hooks_app
from lup.devtools.report.app import create_report_app
from lup.observability.usage.app import UsageEntry, create_usage_app
from lup.devtools.utils import decode_stderr, output_json, repository_slug
from lup.devtools.harness.composition import NativeTargets
from lup.devtools.harness.drift import RepositoryWriter
from lup.ledger.models import LedgerNode
from lup.policy.kernel.edit import SUPPRESSION_COLUMN_LIMIT
from lup.policy.vocabulary import default_vocabulary
from lup.workspace.paths import is_template_scaffold, project_root


def create_dev_app(
    declared: Callable[[], DevDeclarations],
    native_targets: NativeTargets,
    repository_writers: list[RepositoryWriter],
    relocate_roots: list[Path],
    usage_entries: list[UsageEntry] | None = None,
    node_classes: list[type[LedgerNode]] | None = None,
) -> typer.Typer:
    """Wire the dev command tree over what one repository declares about itself."""
    app = typer.Typer(no_args_is_help=True)
    plugin_app = typer.Typer(no_args_is_help=True)
    preserve_app = typer.Typer(no_args_is_help=True)
    env_app = typer.Typer(no_args_is_help=True)
    tracker_app = typer.Typer(no_args_is_help=True)
    app.add_typer(
        env_app,
        name="env",
        help="This project's own environment, and who else is installed in it",
    )
    app.add_typer(plugin_app, name="plugin", help="Local plugin marketplace wiring")
    app.add_typer(
        tracker_app,
        name="tracker",
        help="Answer an issue here or on a declared tracker (comment, close, reopen)",
    )
    app.add_typer(
        preserve_app,
        name="preserve",
        help="The capability capture a reorganisation is measured against",
    )
    app.add_typer(
        model_config_mod.create_model_config_app(),
        name="model-config",
        help="Pydantic configuration census and equivalence",
    )
    app.add_typer(
        questions_mod.create_questions_app(Path.cwd()),
        name="questions",
        help="The parked asks a reviewer answers, and what each is waiting on",
    )
    # Three trees that were top-level and are core's either way, so being
    # top-level bought nothing and cost a reader three names to learn instead
    # of one. Each is a way of reading this repository rather than a workflow
    # over it — what the policy decides, what a name resolves to, what is left
    # to implement — which is the same subject `dev` already is.
    app.add_typer(
        create_hooks_app(lambda: declared().hooks),
        name="hooks",
        help="Query the permission policy",
    )
    app.add_typer(py.SUBAPP.app, name="py", help=py.SUBAPP.spec.help)
    app.add_typer(
        create_report_app(native_targets, repository_writers),
        name="report",
        help="Everything left to implement, in one place",
    )
    # Not with the trace tree, though "what a session spent" reads like the
    # third of a set with "what it did" and "where its records went". Those two
    # read what a session wrote into this repository; this reads the backend's
    # own metered account, which answers whether or not a session ever ran
    # here. A project that stopped reading traces would still want its spend.
    app.add_typer(
        create_usage_app(usage_entries or []),
        name="usage",
        help="What this project has spent, per backend account",
    )

    # -- tracker commands --

    def tracker_routes() -> issues_mod.TrackerRoutes:
        """Where a forge operation may land, read when the command runs.

        `origin` answers for this checkout and the declaration answers for
        everywhere else, both resolved here rather than held on the app: a
        CLI is imported long before anybody knows which repository it will be
        pointed at, and a worktree created mid-session is a different answer
        to the first question.
        """
        return issues_mod.TrackerRoutes(
            own=repository_slug(), declared=list(declared().project.trackers)
        )

    def answer(
        verb: issues_mod.TrackerVerb, number: int, note: str, repository: str
    ) -> None:
        """Run one compensable verb, saying where it landed or why it did not.

        The three verbs differ only in the word, so they share this rather
        than restating the resolution, the failure handling and the refusal
        three times — which is where a fourth verb would have quietly skipped
        one of them.
        """
        routes = tracker_routes()
        try:
            target = routes.chosen(
                issues_mod.issue_arguments(verb, number, note), named=repository
            )
        except RuntimeError as refused:
            typer.echo(str(refused), err=True)
            raise typer.Exit(1) from refused
        if not target:
            typer.echo(
                "No repository to reach: origin names none and no tracker was"
                " given. `--repo <owner/name>` names one this project declares.",
                err=True,
            )
            raise typer.Exit(1)
        try:
            typer.echo(issues_mod.act_on_issue(verb, number, target, note))
        except sh.ErrorReturnCode as failure:
            typer.echo(decode_stderr(failure), err=True)
            raise typer.Exit(1) from failure

    @tracker_app.command("comment")
    def tracker_comment_cmd(
        number: Annotated[int, typer.Argument(min=1, help="Issue number")],
        body: Annotated[str, typer.Option("--body", help="What to say")],
        repository: Annotated[
            str,
            typer.Option("--repo", help="Which repository, if not this checkout's"),
        ] = "",
    ) -> None:
        """Say something on an issue, here or on a declared tracker.

        Compensable: a comment that was wrong is answered by the next one.
        What this will not do is anything a follow-up does not restore — the
        surface is these three verbs, and reaching further means `gh`, which
        the permission policy asks about.
        """
        answer("comment", number, body, repository)

    @tracker_app.command("close")
    def tracker_close_cmd(
        number: Annotated[int, typer.Argument(min=1, help="Issue number")],
        comment: Annotated[
            str,
            typer.Option("--comment", help="Why it is being closed"),
        ] = "",
        repository: Annotated[
            str,
            typer.Option("--repo", help="Which repository, if not this checkout's"),
        ] = "",
    ) -> None:
        """Close an issue, here or on a declared tracker.

        Reopening restores it, which is what puts closing in reach at all. A
        comment is optional and worth writing: whoever was watching sees the
        state change either way, and only the note says why.
        """
        answer("close", number, comment, repository)

    @tracker_app.command("reopen")
    def tracker_reopen_cmd(
        number: Annotated[int, typer.Argument(min=1, help="Issue number")],
        comment: Annotated[
            str,
            typer.Option("--comment", help="Why it is being reopened"),
        ] = "",
        repository: Annotated[
            str,
            typer.Option("--repo", help="Which repository, if not this checkout's"),
        ] = "",
    ) -> None:
        """Reopen an issue, here or on a declared tracker."""
        answer("reopen", number, comment, repository)

    @tracker_app.command("list")
    def tracker_list_cmd() -> None:
        """Which repositories this project may reach, and what each is for.

        The same list a refusal reads out, answerable before meeting one:
        where a report can go is a question with an answer, and finding it
        by being told no is a worse way to learn it.
        """
        routes = tracker_routes()
        typer.echo(f"this checkout: {routes.own or 'origin names no repository'}")
        for entry in routes.declared:
            claimed = f"  components: {', '.join(entry.components)}"
            typer.echo(f"declared: {entry.repository} — {entry.what}")
            if entry.components:
                typer.echo(claimed)
        if not routes.declared:
            typer.echo("declared: none — every other repository goes through gh")

    # -- environment commands --

    @env_app.command("status")
    def env_status_cmd() -> None:
        """Where this project's environment is, and who is installed in it."""
        environment_mod.environment_status()

    @env_app.command("sync")
    def env_sync_cmd(
        take_over: Annotated[
            bool,
            typer.Option(
                "--take-over",
                help="Sync even where another project is installed, uninstalling it",
            ),
        ] = False,
    ) -> None:
        """Install this project's dependencies into its own environment.

        `uv sync` with the one question `uv` cannot ask asked first: an
        absolute ``UV_PROJECT_ENVIRONMENT`` names a single directory for
        every project on the machine, and a sync into a shared one
        uninstalls whoever was there.
        """
        environment_mod.sync_environment(take_over)

    @app.command("pending")
    def pending_cmd(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output as JSON"),
        ] = False,
    ) -> None:
        """Report the real pending changes, excluding sandbox-masked device paths."""
        pending_mod.report(as_json)

    # -- check command --

    @app.command("check")
    def check_cmd(
        fix: Annotated[
            bool,
            typer.Option(
                "--fix",
                help="Auto-fix formatting and lint issues; with --antipatterns, "
                "delete the dead directives instead of reporting them",
            ),
        ] = False,
        no_test: Annotated[
            bool,
            typer.Option("--no-test", help="Skip pytest"),
        ] = False,
        antipatterns: Annotated[
            bool,
            typer.Option(
                "--antipatterns",
                help="Audit repository files for missing/spurious `# lup: ignore` "
                "markers only — the same lup.harness.codescan.antipatterns rules the edit "
                "hook enforces",
            ),
        ] = False,
        boundaries: Annotated[
            bool,
            typer.Option(
                "--boundaries",
                help="Scan for native adapter imports outside composition roots "
                "only — the lup.harness.codescan.boundaries guard the full check also runs",
            ),
        ] = False,
        placement: Annotated[
            bool,
            typer.Option(
                "--placement",
                help="List library data tables no adopter can replace only — the "
                "lup.harness.codescan.boundaries placement guard the full check also runs",
            ),
        ] = False,
        stats: Annotated[
            bool,
            typer.Option(
                "--stats",
                help="With --antipatterns: tally findings by rule and kind instead "
                "of listing each — the sweep triage view",
            ),
        ] = False,
        profiled: Annotated[
            bool,
            typer.Option(
                "--profile",
                help="With --antipatterns: report where the sweep spent its time "
                "instead of what it found — parsing, walking, or resolving",
            ),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json", help="Output findings as JSON (with --antipatterns)"
            ),
        ] = False,
        since: Annotated[
            str | None,
            typer.Option(
                "--since",
                help="Scope the note and anti-pattern gates to paths changed since "
                "this ref, for a tree that holds work it is not answerable for",
            ),
        ] = None,
        path: Annotated[
            list[str] | None,
            typer.Option(
                "--path",
                help="With --antipatterns: audit only files under these paths, for "
                "the fix-one-file loop. Repeatable",
            ),
        ] = None,
        changed: Annotated[
            bool,
            typer.Option(
                "--changed",
                help="Run ruff and pyright over the Python files changed since "
                "--since (default: the integration branch) and no tests at all — "
                "the loop while a change is moving, not the bar a commit passes",
            ),
        ] = False,
    ) -> None:
        """Run ruff format, ruff check, pyright, and pytest. Read-only by default."""
        declarations = declared()
        if changed:
            from lup.devtools.dev.branches import get_integration_branch

            check.run_changed(
                declarations.project,
                since if since is not None else get_integration_branch(),
                fix=fix,
            )
            return
        if antipatterns:
            if profiled:
                antipatterns_mod.profile(declarations.project, path)
            elif stats:
                antipatterns_mod.summarize(declarations.project, as_json, path)
            else:
                antipatterns_mod.report(declarations.project, as_json, path, fix=fix)
            return
        if boundaries:
            boundaries_mod.report(declarations.project, as_json)
            return
        if placement:
            boundaries_mod.report_placement(as_json)
            return
        check.run_checks(
            fix=fix,
            no_test=no_test,
            project=declarations.project,
            test_roots=declarations.test_roots,
            compositions=native_targets.resolve(native_targets.every, project_root()),
            repository_writers=repository_writers,
            git_guards=declarations.git_guards,
            hooks_declaration=declarations.hooks,
            scope=check.changed_paths(since) if since is not None else None,
            node_classes=node_classes or [],
        )

    # -- test command --

    @app.command("test")
    def test_cmd(
        paths: Annotated[
            list[str] | None,
            typer.Argument(
                help="Test files or directories to run. Each is dispatched to the "
                "declared test root that installs it; with none, every root runs "
                "its whole suite"
            ),
        ] = None,
    ) -> None:
        """Run named tests in the suite that installs each, one run per suite."""
        declarations = declared()
        check.run_selected(
            test_roots=declarations.test_roots,
            selections=paths or [],
            excluded_roots=check.non_code_roots(declarations.project),
        )

    # -- comments command --

    @app.command("comments")
    def comments_cmd(
        targets: Annotated[
            list[str] | None,
            typer.Argument(help="file:line markers to remove with --clear"),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output as JSON"),
        ] = False,
        kind: Annotated[
            NoteKind | None,
            typer.Option("--kind", help="Show only this note flavor"),
        ] = None,
        commit: Annotated[
            bool,
            typer.Option(
                "--commit", help="Commit comment-bearing files as a prompt snapshot"
            ),
        ] = False,
        clear: Annotated[
            bool,
            typer.Option(
                "--clear",
                help="Strip the file:line markers given (only on a resolve/* branch)",
            ),
        ] = False,
        wake: Annotated[
            bool,
            typer.Option(
                "--wake",
                help="With --clear: also strip the defer notes named, waking them",
            ),
        ] = False,
        retire: Annotated[
            bool,
            typer.Option(
                "--retire",
                help="Delete the solved claims named as file:line (verify pass only)",
            ),
        ] = False,
        restore: Annotated[
            bool,
            typer.Option(
                "--restore",
                help="Reopen the solved claims named as file:line as open feedback",
            ),
        ] = False,
        narrow: Annotated[
            str | None,
            typer.Option(
                "--narrow",
                help="With --restore and one target: the still-outstanding text",
            ),
        ] = None,
        withdraw: Annotated[
            bool,
            typer.Option(
                "--withdraw",
                help="Retract the notes named as file:line; needs --reason",
            ),
        ] = False,
        reason: Annotated[
            str | None,
            typer.Option(
                "--reason",
                help="With --withdraw: why the note should not have been written",
            ),
        ] = None,
    ) -> None:
        """List unresolved `# lup:` feedback comments, or act on specific ones.

        With --clear, removes each `file:line` marker named as an argument; used
        at fork time to strip a concern's own notes from an editor's worktree.
        Deferred notes are skipped unless --wake is passed as well.

        With --retire or --restore, applies the verify-solved pass's verdicts to
        `# lup: solved:` claims — and only to claims: any other note is refused.

        With --withdraw and --reason, retracts notes that should not have been
        written at all. Conversion to `# lup: solved:` is for a note that was
        answered; a note that was mistaken has no answer to claim, and the
        reason is committed alongside the removal in its place.
        """
        if sum([clear, retire, restore, withdraw]) > 1:
            typer.echo(
                "--clear, --retire, --restore, and --withdraw are exclusive", err=True
            )
            raise typer.Exit(2)
        if narrow is not None and (not restore or len(targets or []) != 1):
            typer.echo("--narrow needs --restore and exactly one target", err=True)
            raise typer.Exit(2)
        if (reason is not None) != withdraw:
            typer.echo("--withdraw and --reason require each other", err=True)
            raise typer.Exit(2)
        if withdraw and reason is not None:
            comments.withdraw_notes(targets or [], reason)
            return
        if retire or restore:
            comments.revise_claims(targets or [], retire=retire, narrow=narrow)
            return
        if clear:
            comments.clear_markers(targets or [], wake=wake)
            return
        comments.report(as_json, commit, kind)

    @app.command("todos")
    def todos_cmd(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output as JSON"),
        ] = False,
    ) -> None:
        """List `# lup: template:` markers — a scaffold's open decisions.

        Every place a scaffolded project needs a domain decision carries a
        `# lup: template:` note. Initialization runs this to gather them all
        and walk them one by one, so no customization point depends on someone
        remembering to mention it. An alias for `dev comments --kind template`:
        same scan, same file/line/text/context shape, narrowed to that flavor.
        """
        comments.report(as_json, commit=False, kind=NoteKind.template)

    @app.command("seams")
    def seams_cmd(
        own: Annotated[
            list[str] | None,
            typer.Option("--own", help="Hand a file to its human owner (repeatable)"),
        ] = None,
        disown: Annotated[
            list[str] | None,
            typer.Option("--disown", help="Let the agent write this file again"),
        ] = None,
        retire: Annotated[
            list[str] | None,
            typer.Option("--retire", help="Stop holding this project to a rule id"),
        ] = None,
        keep: Annotated[
            list[str] | None,
            typer.Option("--keep", help="Hold this project to a rule id again"),
        ] = None,
        retire_all: Annotated[
            bool,
            typer.Option("--retire-all", help="Retire every rule the library ships"),
        ] = False,
    ) -> None:
        """Show what this project settled about itself, or settle one of them.

        With no options this prints each seam, its current value and where it
        is written — which is what makes putting them to a person possible at
        all, during initialization or afterwards. A default nobody was shown
        is not a decision, and neither is one whose declaration somebody would
        have to go find.

        The options write that declaration rather than asking anyone to edit
        it, and print what to regenerate. Nothing regenerates here: what
        compiles from a declaration is the project's own set of trees, and a
        command that guessed at them would be answering for a layout it does
        not own.
        """
        project = declared().project
        catalog = project.catalog
        answers = seams.Answers(
            own=own or [],
            disown=disown or [],
            retire=retire or [],
            keep=keep or [],
            retire_all=retire_all,
        )
        if not answers.given():
            for line in seams.survey(catalog, project.seams):
                typer.echo(line)
            return
        if catalog is None:
            raise typer.BadParameter(
                "this project declares no catalog path, so there is nothing to "
                "write a seam into; name one on its `DevProject`"
            )
        # Every id the library ships, not every id this project still keeps:
        # retiring all of them has to name the ones already retired too, or
        # the answer would silently exclude what a previous answer dropped.
        shipped = [rule.id for rule in all_rules()]
        for line in answers.settled(catalog, shipped):
            typer.echo(line)

    @app.command("refutations")
    def refutations_cmd(
        path: Annotated[
            str,
            typer.Option("--path", help="The file the content on stdin belongs to"),
        ],
    ) -> None:
        """Resolve one file's proposed content and report what it refutes.

        The edit gate's route to a checker. It judges a change before anything
        is written, so the text is read from stdin rather than from *path* —
        which names where the content belongs, and is what imports, the
        module's own name, and every declaration reached through either
        resolve against.

        Always JSON: the only caller is a hook, and `resolved` tells it
        whether a checker answered at all. A gate that gets no answer asks
        instead of refusing, so "nothing was refuted" and "nothing could be
        resolved" have to arrive as different replies.
        """
        antipatterns_mod.report_refutations(
            declared().project, Path(path), sys.stdin.read()
        )

    @app.command("directives")
    def directives_cmd(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output as JSON"),
        ] = False,
        limit: Annotated[
            int,
            typer.Option("--limit", help="Column budget the inline placement gets"),
        ] = SUPPRESSION_COLUMN_LIMIT,
        fix: Annotated[
            bool,
            typer.Option(
                "--fix", help="Move each directive to its canonical placement"
            ),
        ] = False,
        retire: Annotated[
            str | None,
            typer.Option(
                "--retire", help="Take one retired rule out of every directive"
            ),
        ] = None,
    ) -> None:
        """Measure every `# lup: ignore` against the canonical inline placement.

        Placement is uniform — a directive sits on the line it guards, or
        stands alone directly above it — and the inline form is the canonical
        one. This reports which sites the column budget lets stay inline and
        which only fit above, so the fallback is sized against the tree rather
        than assumed.
        """
        if retire is not None:
            swept = antipatterns_mod.retire_directives(declared().project, retire)
            lost = sum(len(item.removed) for item in swept)
            typer.echo(f"{len(swept)} file(s) rewritten, {lost} line(s) removed")
            for item in swept:
                lines = ", ".join(str(number) for number in item.removed)
                typer.echo(f"  {item.rel}  {lines or 'rule id dropped'}")
            return
        if fix:
            moved = antipatterns_mod.place_directives(declared().project, limit)
            typer.echo(f"{len(moved)} file(s) replaced")
            for rel in moved:
                typer.echo(f"  {rel}")
            return
        antipatterns_mod.report_directives(declared().project, as_json, limit)

    @app.command("report-friction")
    def report_friction_cmd(
        summary: Annotated[str, typer.Option("--summary")],
        component: Annotated[str, typer.Option("--component")],
        command: Annotated[str, typer.Option("--command")],
        error: Annotated[str, typer.Option("--error")],
        state: Annotated[str, typer.Option("--state")],
        recovery_cost: Annotated[str, typer.Option("--recovery-cost")],
        issue: Annotated[int | None, typer.Option("--issue", min=1)] = None,
        repository: Annotated[
            str,
            typer.Option("--repo", help="Which tracker, if not the one routing picks"),
        ] = "",
    ) -> None:
        """File or correct workflow friction, on the tracker that owns the fix.

        Routed by the component the report names rather than by where the
        session was standing. A project consuming a library as a dependency
        meets most of its friction in machinery it cannot edit, and a report
        filed here about code that is not here is worse than misplaced: the
        resolver takes every open issue in this repository as evidence, so
        the next run plans a repair it cannot make. A component no declared
        tracker claims stays here, which is every defect this tree owns.
        """
        routes = tracker_routes()
        report = issues_mod.FrictionReport(
            summary=summary,
            component=component,
            command=command,
            error=error,
            state=state,
            recovery_cost=recovery_cost,
        )
        try:
            target = routes.chosen(
                ["issue", "create", "--title", summary],
                named=repository,
                component=component,
            )
            url = report.file(repository=target, issue=issue)
        except RuntimeError as refused:
            typer.echo(str(refused), err=True)
            raise typer.Exit(1) from refused
        except sh.ErrorReturnCode as failure:
            spoken = decode_stderr(failure)
            advice = issues_mod.disabled_issues_advice(spoken, routes)
            typer.echo(spoken if not advice else f"{spoken}\n{advice}", err=True)
            raise typer.Exit(1) from failure
        typer.echo(url)

    @app.command("undo")
    def undo_cmd(
        take: Annotated[
            str,
            typer.Option("--take", help="Snapshot the tree now, naming why"),
        ] = "",
        expire_days: Annotated[
            int | None,
            typer.Option("--expire", help="Drop snapshots older than this many days"),
        ] = None,
        keep_most: Annotated[
            int | None,
            typer.Option("--keep", help="Keep at most this many snapshots"),
        ] = None,
    ) -> None:
        """List the recoverable snapshots of this tree, or take and expire them.

        Restoring is deliberately not offered here. Putting a snapshot back
        overwrites present work with past work -- the same class of act as
        the destruction it undoes -- so each entry prints the command that
        would do it and leaves running it to somebody who can see what is
        currently there.
        """
        root = project_root()
        if take:
            taken = undo.snapshot(root, take)
            typer.echo(
                f"{taken.ref}  {taken.commit[:12]}"
                if taken is not None
                else "No snapshot taken — this checkout could not be written to."
            )
            return
        if expire_days is not None or keep_most is not None:
            days = undo.DEFAULT_RETENTION_DAYS if expire_days is None else expire_days
            most = undo.DEFAULT_RETENTION_COUNT if keep_most is None else keep_most
            for gone in undo.expire(root, days, keep_most=most):
                typer.echo(f"expired {gone.ref}")
            return
        found = undo.points(root)
        if not found:
            typer.echo("No snapshots. `--take <reason>` writes one.")
            return
        for item in found:
            typer.echo(f"{item.taken_at:%Y-%m-%d %H:%M}  {item.reason}")
            typer.echo(f"    {item.restore_command()}")

    @app.command("history")
    def history_cmd(
        text: Annotated[str, typer.Argument(help="The symbol or literal to trace")],
        regex: Annotated[
            bool,
            typer.Option("--regex", help="Read the text as a regular expression"),
        ] = False,
        path: Annotated[
            list[Path] | None,
            typer.Option("--path", help="Limit the search to these paths"),
        ] = None,
        as_json: Annotated[bool, typer.Option("--json", help="Emit JSON")] = False,
    ) -> None:
        """Trace a symbol through every branch, past this tree's own snapshots.

        `git log --all -S <symbol>` cannot answer this in a guarded checkout.
        The permission dispatcher snapshots the tree before every command
        under `refs/lup/undo`, each snapshot a parentless commit whose whole
        tree reads as an addition -- so the pickaxe matches every symbol the
        checkout holds, once per snapshot, and the first match is the one
        taken in front of the search. Those refs are left out of the
        traversal here and nothing they recorded is disturbed.

        Examples::

            $ uv run lup-devtools dev history undo_retention_count
            $ uv run lup-devtools dev history 'def parse' --path packages/lup
            $ uv run lup-devtools dev history 'Hook(Set|Rule)' --regex
        """
        found = history.commits_matching(project_root(), text, regex, path)
        if as_json:
            output_json([hit.model_dump(mode="json") for hit in found])
            return
        for hit in found:
            typer.echo(hit.line())
        typer.echo(
            f"{len(found)} commit(s), snapshots under {history.SNAPSHOT_REFS} aside"
        )

    @app.command("issues")
    def issues_cmd(
        excluded: Annotated[
            str,
            typer.Option("--excluded", help="Label that withholds an issue"),
        ] = issues_mod.EXCLUDED_LABEL,
        repository: Annotated[
            str,
            typer.Option("--repo", help="Which repository, if not this checkout's"),
        ] = "",
    ) -> None:
        """List the open issues a resolver run would take as evidence.

        Answerable without starting a run, which is the whole point: a run
        leases a worktree per concern, so "what would this plan from?" should
        not cost one.

        A declared tracker can be read the same way. Reading somebody else's
        issues is a read wherever it points, and asking what is open upstream
        is how a session finds out that the defect in front of it is already
        filed.
        """
        routes = tracker_routes()
        try:
            slug = routes.chosen(["issue", "list", "--state", "open"], named=repository)
        except RuntimeError as refused:
            typer.echo(str(refused), err=True)
            raise typer.Exit(1) from refused
        found = issues_mod.fetch_open_issues(excluded, repository=slug)
        typer.echo(f"{len(found)} open issue(s) in {slug or 'this repository'}")
        for issue in found:
            typer.echo(f"  {issue.reference()}  {issue.title}")

    @app.command("rules")
    def rules_cmd(
        check_only: Annotated[
            bool,
            typer.Option("--check", help="Fail when docs/rules.md is stale"),
        ] = False,
    ) -> None:
        """Generate the Lup rule and typed-suppression reference.

        Rendered against the selection this repository holds itself to, which
        is the same one the edit hook and the sweep read. Rendering the whole
        library table instead writes a reference naming rules the gate here
        does not enforce — and a project that retired one then has two
        documents disagreeing about what it is held to, the generated file
        saying it still applies.
        """
        try:
            destination = rules.write_rule_reference(
                check=check_only, selection=declared().hooks.rules
            )
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        verb = "verified" if check_only else "written"
        typer.echo(f"Lup rule reference {verb}: {destination}")

    @app.command("modules")
    def modules_cmd(
        verbose: Annotated[
            bool,
            typer.Option("--verbose", "-v", help="What each module is and contributes"),
        ] = False,
    ) -> None:
        """Report which modules this project takes, and what each one's prose costs.

        The roster is the one selection with no surface of its own: a retired
        sub-app is missing from `--help` and a retired rule from the rule
        reference, but a module is five surfaces at once, so what a project
        settled is otherwise readable only out of its catalog against defaults
        held in the reader's head.
        """
        project = declared().project
        modules.report(project.coverage.modules, project.modules, verbose)

    @app.command("guidance")
    def guidance_cmd(
        by_size: Annotated[
            bool,
            typer.Option("--by-size", help="Heaviest section first, not reading order"),
        ] = False,
    ) -> None:
        """Report what each section of the always-loaded guidance costs."""
        guidance.report(
            compositions=native_targets.resolve(native_targets.every, project_root()),
            scaffold=is_template_scaffold(project_root()),
            by_size=by_size,
        )

    @app.command("relocate")
    def relocate_cmd(
        moves: Annotated[
            list[str],
            typer.Argument(
                help="Module relocations, each spelled old.module=new.module"
            ),
        ],
        root: Annotated[
            list[Path] | None,
            typer.Option("--root", help="Source root to rewrite (repeatable)"),
        ] = None,
    ) -> None:
        """Move a module and repoint every import of it."""

        def parsed(move: str) -> relocate_mod.Relocation:
            # This CLI's own flag grammar, not structured data with a parser.
            old, separator, new = move.partition("=")  # lup: ignore[string-split]
            sides = [relocate_mod.name_parts(old), relocate_mod.name_parts(new)]
            if not separator or any(side is None for side in sides):
                typer.echo(f"expected old.module=new.module; got {move!r}", err=True)
                raise typer.Exit(2)
            return relocate_mod.Relocation(old=sides[0] or [], new=sides[1] or [])

        declared = [parsed(move) for move in moves]
        roots = [path for path in root or relocate_roots if path.exists()]
        # The module's own file first, so every import repointed below is
        # pointed at something already there. Leaving this to the caller is
        # what made the command's name a lie: it reported success over a tree
        # where nothing resolved, and the type check named the wreckage
        # somewhere else entirely.
        for move in declared:
            carried = relocate_mod.carry_module(roots, move)
            if carried is not None:
                typer.echo(f"moved {carried.old} -> {carried.new}")
        for edit in relocate_mod.relocate(roots, declared):
            typer.echo(f"{edit.path}: {edit.imports} import(s)")
        for mention in relocate_mod.surviving_mentions(roots, declared):
            typer.echo(f"still mentions a moved module: {mention}", err=True)

    # -- preservation capture --

    def walked(ctx: typer.Context) -> preservation.SurfaceCapture:
        """The surface the tree offers right now, as this CLI can see it."""
        return preservation.capture(preservation.operations(ctx), declared().project)

    def against(ctx: typer.Context, capture: Path) -> preservation.Divergence:
        """What the live tree does and does not still answer for a capture."""
        return preservation.compare(
            preservation.SurfaceCapture.read(capture), walked(ctx)
        )

    @preserve_app.command("capture")
    def preserve_capture_cmd(
        ctx: typer.Context,
        capture: Annotated[
            Path, typer.Option("--capture", help="The capture to read or write")
        ] = preservation.CAPTURE_FILE,
    ) -> None:
        """Record the surface this repository offers, as a checked-in fixture.

        Run before a reorganisation, and again after one whose removals were
        deliberate: what leaves the fixture leaves it in a diff somebody
        reads, which is the only place a dropped capability is ever noticed.
        """
        captured = walked(ctx)
        captured.write(capture)
        exports = sum(len(surface.declares) for surface in captured.modules)
        typer.echo(
            f"{capture}: {len(captured.commands)} operation(s), {exports} export(s) "
            f"across {len(captured.modules)} module(s), at {captured.revision}"
        )

    @preserve_app.command("check")
    def preserve_check_cmd(
        ctx: typer.Context,
        capture: Annotated[
            Path, typer.Option("--capture", help="The capture to read or write")
        ] = preservation.CAPTURE_FILE,
        as_json: Annotated[bool, typer.Option("--json", help="Emit JSON")] = False,
    ) -> None:
        """Resolve every captured capability against the tree as it stands.

        A capability the tree no longer declares anywhere fails the run. One
        declared somewhere else is reported and does not: a move is what a
        reorganisation is, and telling the two apart is the whole point.
        """
        divergence = against(ctx, capture)
        if as_json:
            output_json(divergence)
        else:
            for capability in divergence.disappeared:
                typer.echo(f"disappeared: {capability.spelled()}", err=True)
            for relocation in divergence.relocated:
                typer.echo(f"relocated:   {relocation.spelled()}")
            for capability in divergence.arrived:
                typer.echo(f"arrived:     {capability.spelled()}")
        if not divergence.intact():
            raise typer.Exit(1)

    @preserve_app.command("migration")
    def preserve_migration_cmd(
        ctx: typer.Context,
        capture: Annotated[
            Path, typer.Option("--capture", help="The capture to read or write")
        ] = preservation.CAPTURE_FILE,
    ) -> None:
        """Print the relocation that repoints an importer of the captured tree.

        The command an adopter runs to follow this repository's move, derived
        from the same difference that proved nothing was lost. Add `--root` to
        aim it at the checkout being migrated.
        """
        moves = against(ctx, capture).module_moves()
        if not moves:
            typer.echo("no module moved since the capture")
            return
        pairs = " ".join(f"{old}={new}" for old, new in sorted(moves.items()))
        typer.echo(f"uv run lup-devtools dev relocate {pairs}")

    @app.command("policy")
    def policy_cmd(
        subjects: Annotated[
            list[str],
            typer.Argument(help="Commands, URLs, or paths to classify"),
        ],
        kind: Annotated[
            str,
            typer.Option("--kind", help="What the inputs are: shell, fetch, or edit"),
        ] = "shell",
        sandbox: Annotated[
            bool | None,
            typer.Option(
                "--sandbox/--no-sandbox",
                help="Show only this placement's answer (default: show both)",
            ),
        ] = None,
        autonomous: Annotated[
            bool,
            typer.Option(
                "--autonomous", help="Judge as a self-reviewing identity would"
            ),
        ] = False,
        as_json: Annotated[bool, typer.Option("--json", help="Emit JSON")] = False,
    ) -> None:
        """Show what the declared permission policy decides about an input, and why."""
        if kind not in ("shell", "fetch", "edit"):
            typer.echo(
                f"unknown kind {kind!r}: expected shell, fetch, or edit", err=True
            )
            raise typer.Exit(2)
        # Every placement, not this session's. The guidance sends a reader here
        # before they spend a turn, and one answer leaves them holding a guess
        # about which session it described -- an invisible guess, which is the
        # worst kind. Both answers cost one extra composition and end the guess.
        policy_explain.explain(
            subjects,
            kind,
            autonomous,
            as_json,
            declared().hooks,
            sandbox,
        )

    @app.command("vocabulary")
    def vocabulary_cmd(
        offered: Annotated[
            bool,
            typer.Option("--offered", help="Survey lup's offered defaults instead"),
        ] = False,
        as_json: Annotated[bool, typer.Option("--json", help="Emit JSON")] = False,
        output: Annotated[
            Path | None,
            typer.Option("--output", help="Write the survey here instead of stdout"),
        ] = None,
        provenance: Annotated[
            bool,
            typer.Option(
                "--provenance", help="List rules and where each axis came from"
            ),
        ] = False,
    ) -> None:
        """Show every shell form the declared vocabulary judges, and how."""
        rules = (
            default_vocabulary() if offered else declared().hooks.resolved_shell_rules()
        )
        policy_explain.survey(rules, as_json, output, provenance)

    # -- plugin commands --

    @plugin_app.command("name")
    def plugin_name_cmd(
        name: Annotated[
            str | None,
            typer.Argument(help="Marketplace name (default: pyproject [project].name)"),
        ] = None,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", "-n", help="Show changes without writing"),
        ] = False,
    ) -> None:
        """Name this repo's plugin marketplace uniquely (the plugin entry is kept).

        Marketplace names share one global namespace, so a shared name collides
        across repos and worktrees and installs shadow each other. Naming the
        marketplace after the project fixes that.
        """
        plugin_mod.name_marketplace(declared().plugin, name, dry_run)

    return app
