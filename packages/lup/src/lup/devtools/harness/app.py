"""Typer command tree for ``lup-devtools harness``: wiring only, no bodies.

Each command delegates to the module owning its concern: ``drift`` for
generation and checking, ``reconcile`` for local-difference workflows,
``doctor`` for runtime evidence, ``resolve`` for the persisted resolver,
and ``launch`` for the native launchers. Every one of them works on already
concrete compositions, so the targets a project declares are what this tree
operates on and no command names a runtime of its own.

A launch command exists exactly when its adapter is among those targets: a
project generating one native tree is not offered a launcher for the other.
"""

from pathlib import Path
from typing import Annotated

import typer

import lup.devtools.harness.doctor as doctor
import lup.devtools.harness.drift as drift
import lup.devtools.harness.launch as launch
import lup.devtools.harness.reconcile as reconcile
import lup.devtools.harness.resolve as resolve
from lup.harness.codescan.registry import every_rule_retired
from lup.devtools.harness.composition import NativeTargets, claude_profile_directory
from lup.devtools.harness.contained import (
    image_tag,
    report_egress,
    retire_images,
    superseded_images,
)
from lup.harness.image import detected_client
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.devtools.harness.profile_app import create_profile_app
from lup.harness.models import Resumption
from lup.harness.releases import resolved_agent_clis
from lup.harness.requirements import Manifest
from lup.providers.profiles import ProfileDirectory
from lup.devtools.harness.drift import RepositoryWriter
from lup.workspace.paths import project_root


def create_harness_app(
    targets: NativeTargets,
    repository_writers: list[RepositoryWriter],
    model: resolve.ConfiguredModel | None = None,
    profiles: ProfileDirectory | None = None,
    launch_modes: list[launch.LaunchMode] | None = None,
    checkpoint: launch.LaunchCheckpoint | None = None,
) -> typer.Typer:
    """Wire the harness command tree over the targets one project declares.

    A project that keeps Claude accounts of its own supplies ``profiles``
    over that origin, so one name selects the same account for a launch here
    as it does everywhere else in that project. Supplying none falls back to
    the personal registry, which is the answer for a project keeping none.

    ``launch_modes`` are that project's own kinds of session. Each adds a flag
    to every launcher; selecting one compiles the tree it declares instead of
    the default, so the mode reaches the artifacts a runtime reads at startup
    rather than only the command line this tree assembles.

    ``checkpoint`` saves application data before generation and after closing.
    """
    directory = profiles or claude_profile_directory()
    modes = launch_modes or []
    app = typer.Typer(no_args_is_help=True, help="Generate and launch a native harness")
    selector = f"{', '.join(targets.builders)}, or {targets.every}"

    def repository_wide(target: str) -> list[RepositoryWriter]:
        """The writers a selector reaches: every one of them, or none.

        A generated file outside a native tree belongs to no single target,
        so only the selector naming all of them is answerable for it.
        """
        return repository_writers if target == targets.every else []

    @app.command("generate")
    def generate_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
    ) -> None:
        """Deterministically generate owned native artifacts without launching."""
        drift.generate_targets(
            targets.resolve(target, project_root()), repository_wide(target)
        )

    @app.command("check")
    def check_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
    ) -> None:
        """Read-only ownership and generated-artifact drift check for CI."""
        drift.check_targets(
            targets.resolve(target, project_root()), repository_wide(target)
        )

    @app.command("reconcile")
    def reconcile_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
    ) -> None:
        """Classify local differences without rewriting canonical Python source."""
        reconcile.classify_targets(targets.resolve(target, project_root()))

    @app.command("apply-reconciliation")
    def apply_reconciliation(
        proposal_id: Annotated[str, typer.Argument(help="Persisted proposal id")],
    ) -> None:
        """Apply a stale-base-checked source patch, then regenerate every target."""
        reconcile.apply_proposal(
            proposal_id, targets.resolve(targets.every, project_root())
        )

    @app.command("propose-reconciliation")
    def propose_reconciliation(
        patch: Annotated[
            Path,
            typer.Argument(help="Git-format patch against canonical Python source"),
        ],
    ) -> None:
        """Persist a source patch for separate review and stale-base-checked apply."""
        reconcile.propose_patch(patch)

    @app.command("doctor")
    def doctor_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
        strict_evidence: Annotated[
            bool,
            typer.Option(
                "--strict-evidence",
                help="Exit nonzero when an installed component is newer than the "
                "evidence ledger (the nightly lane's re-probe trigger)",
            ),
        ] = False,
    ) -> None:
        """Report installed native runtime evidence without updating either CLI."""
        doctor.run_doctor(targets.resolve(target, project_root()), strict_evidence)

    @app.command("requirements")
    def requirements_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
        launch_only: Annotated[
            bool,
            typer.Option(
                "--launch-only",
                help="Run only startup checks; omit setup-only checks",
            ),
        ] = False,
        inside: Annotated[
            bool,
            typer.Option(
                "--inside",
                help=(
                    "Check inside the session container. Build its image and "
                    "start its network if needed"
                ),
            ),
        ] = False,
    ) -> None:
        """Check dependencies on the host, or in the session container with --inside.

        Host checks include the commands an agent needs when running on the
        host. A normal container launch checks those commands inside instead.
        Every result names the environment checked.

        --inside uses the session's image, mounts, credentials and network.
        It builds the image if needed. Full checks include a test model turn;
        add --launch-only to run only the checks used at startup.

        Exits nonzero if a needed capability fails a check. Optional
        conveniences alone do not cause failure.
        """
        compositions = targets.resolve(target, project_root())
        # The two halves span the targets differently, because they answer
        # differently-scoped questions. What the image must carry is the
        # image's own, so it is asked once per target; what the host must
        # carry is the machine's, and asking it per target exercises one
        # roster twice -- a container probe paid for twice, printed twice,
        # with nothing on screen saying the second was the same question.
        findings = (
            [
                finding
                for composition in compositions
                for finding in launch.report_inside_requirements(
                    composition,
                    composition.recipe.source.plugins[0],
                    launch.ambient_config_home(
                        directory.login, Path.home() / ".claude"
                    ),
                    directory.login,
                    setting_up=not launch_only,
                )
            ]
            if inside
            else launch.report_requirements(
                Manifest.across(
                    [
                        composition.recipe.source.requirements
                        for composition in compositions
                    ]
                ),
                setting_up=not launch_only,
            )
        )
        if not findings:
            typer.echo(
                "No container requirements selected."
                if inside
                else "No host requirements selected."
            )
            return
        if any(
            not finding.working and finding.requirement.absence.costly()
            for finding in findings
        ):
            raise typer.Exit(1)

    @app.command("image")
    def image_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
        prune: Annotated[
            bool,
            typer.Option(
                "--prune", help="Remove images no checkout is pointing at any more"
            ),
        ] = False,
    ) -> None:
        """Render the container image this project's sessions run in.

        Printed rather than written, because a Dockerfile on disk is a second
        place the toolchain is stated and the first thing to drift from the
        declaration. A build reads this on stdin -- ``harness image | docker
        build -f - .`` -- so what is built is what is declared, every time,
        with nothing in between to edit.

        ``--prune`` sweeps instead of printing. An image is named after the
        declaration it was built from, which is what lets two checkouts share
        one -- and means editing the declaration leaves the old image
        standing rather than replacing it. What goes is every digest tag with
        no checkout tag on it; what stays is anything a checkout still points
        at, and the image this declaration would build right now.
        """
        for composition in targets.resolve(target, project_root()):
            source = composition.recipe.source
            # Everything resolution says goes to stderr: stdout is the
            # Dockerfile a build reads, and a progress line in the pipe is a
            # parse error inside `docker build -f -`.
            resolution = resolved_agent_clis(
                source.image,
                say=lambda notice: typer.echo(notice.painted(), err=True),
            )
            for notice in resolution.said:
                typer.echo(notice.painted(), err=True)
            rendered = resolution.image.dockerfile(source.requirements)
            if not prune:
                typer.echo(rendered)
                continue
            client = detected_client()
            if client is None:
                typer.echo("No container client answered, so nothing was swept.")
                return
            finished = superseded_images(client.engine(), image_tag(rendered))
            if not finished:
                typer.echo("Nothing superseded — every image has a checkout on it.")
                return
            for tag in retire_images(finished, client.engine()):
                typer.echo(f"removed {tag}")

    @app.command("egress")
    def egress_command(
        target: Annotated[str, typer.Argument(help=selector)] = targets.every,
        down: Annotated[
            bool,
            typer.Option("--down", help="Remove the proxy and its network"),
        ] = False,
    ) -> None:
        """Report or remove the network boundary this project's sessions run behind.

        The proxy outlives a session deliberately -- starting one costs a
        second and every launch would pay it -- which means something has to
        be able to say what is running and take it away. Without that the
        only answer is a raw engine command against a name the operator has
        to know, which is the friction this whole harness exists to remove.
        """
        for composition in targets.resolve(target, project_root()):
            report_egress(composition.recipe.source.image.egress, project_root(), down)

    def selected_target(
        mode: launch.LaunchMode | None,
        runtime: str,
        allowance: int,
        relaxed: bool = False,
    ) -> NativeHarnessComposition:
        """The composition to generate and open, under whichever mode is in force.

        A mode carries its own targets, so this is where "the tree differs by
        mode" actually happens: everything downstream takes an already
        concrete composition and cannot tell which declaration produced it.

        ``relaxed`` is the other thing that differs by launch, and it reaches
        the same place for the same reason: the anti-pattern table is
        projected into each plugin's hermetic edit policy at generation time,
        so a switch that stopped at this command line would leave the session
        judged by the tree it opened against rather than by what was asked
        for.
        """
        source = mode.targets_at(allowance) if mode is not None else targets
        build = source.builder(runtime)
        if build is None:
            named = f"--{mode.name} " if mode is not None else ""
            raise typer.BadParameter(f"{named}declares no {runtime} tree")
        return build(project_root(), every_rule_retired() if relaxed else None)

    def companion_targets(
        mode: launch.LaunchMode | None, runtime: str, allowance: int
    ) -> list[NativeHarnessComposition]:
        """The trees a launch regenerates without opening, which is all the others.

        What makes launching one runtime mean what `generate all` means. A
        shared source moves both trees, so a launcher that generated only its
        own left the other stale until somebody ran the selector by hand --
        and what surfaced it was `dev check` failing on drift the session had
        not introduced.

        Never relaxed. Relaxation is a statement about the session being
        opened, and projecting it into a tree nobody is opening would leave
        that runtime on disk judged by rules its source never declared.
        """
        source = mode.targets_at(allowance) if mode is not None else targets
        return [
            composition
            for composition in source.resolve(source.every, project_root())
            if composition.recipe.label != runtime
        ]

    def launch_help(subject: str) -> str:
        """One launcher's help, with whatever modes this project declares."""
        flags = "".join(f"  --{mode.name}: {mode.help}" for mode in modes)
        return f"{subject}{flags}"

    claude_target = targets.builder("claude")
    if claude_target is not None:
        app.add_typer(create_profile_app(directory), name="profile")

        @app.command(
            "claude",
            context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
            help=launch_help(
                "Generate/reconcile Claude artifacts and launch the verified plugin."
            ),
        )
        def claude(
            ctx: typer.Context,
            profile: Annotated[
                str | None,
                typer.Option("--profile", "-p", help="Claude config-directory profile"),
            ] = None,
            model: Annotated[
                str | None,
                typer.Option("--model", "-m", help="Native model override"),
            ] = None,
            generate_only: Annotated[
                bool,
                typer.Option("--generate-only", help="Generate without launching"),
            ] = False,
            continue_latest: Annotated[
                bool,
                typer.Option(
                    "--continue", "-c", help="Reopen the most recent session here"
                ),
            ] = False,
            resume: Annotated[
                bool,
                typer.Option("--resume", help="Pick a session to reopen"),
            ] = False,
            session: Annotated[
                str | None,
                typer.Option("--session", help="Reopen this session by id"),
            ] = None,
            ignore_antipatterns: Annotated[
                bool,
                typer.Option(
                    "--ignore-antipatterns",
                    help="Open a session the anti-pattern gate leaves alone",
                ),
            ] = False,
            sandbox: Annotated[
                launch.LaunchSandbox,
                typer.Option(
                    "--sandbox",
                    help="Which sandbox holds the session: the verified "
                    "container (outer), the runtime's own on the host "
                    "(inner), or the semantic policy alone (none)",
                ),
            ] = launch.LaunchSandbox.OUTER,
            mount: Annotated[
                list[Path],
                typer.Option(
                    "--mount",
                    exists=True,
                    file_okay=False,
                    resolve_path=True,
                    help="Extra folder this session may read and write "
                    "(repeatable); registered for this launch only",
                ),
            ] = [],
            mount_ro: Annotated[
                list[Path],
                typer.Option(
                    "--mount-ro",
                    exists=True,
                    file_okay=False,
                    resolve_path=True,
                    help="Extra folder this session may read and must not "
                    "write (repeatable)",
                ),
            ] = [],
            max_recursive_agent: Annotated[
                int | None,
                typer.Option(
                    "--max-recursive-agent",
                    min=-1,
                    help="Maximum child-agent depth; -1 allows unlimited recursion",
                ),
            ] = None,
            transcribe_session: Annotated[
                bool,
                typer.Option(
                    "--transcribe-session",
                    help="Mirror the native CLI transcript when this mode disables it",
                ),
            ] = False,
        ) -> None:
            selection = launch.extract_launch_mode(modes, ctx.args)
            allowance = (
                selection.mode.recursive_agent_limit(max_recursive_agent)
                if selection.mode is not None
                else -1
                if max_recursive_agent is None
                else max_recursive_agent
            )
            launch.launch_claude(
                selected_target(
                    selection.mode, "claude", allowance, ignore_antipatterns
                ),
                selection.arguments,
                directory,
                profile,
                model,
                generate_only,
                selection.mode,
                Resumption(latest=continue_latest, pick=resume, session=session),
                ignore_antipatterns,
                sandbox,
                checkpoint=checkpoint,
                max_recursive_agent=allowance,
                transcribe_session=transcribe_session,
                companions=companion_targets(selection.mode, "claude", allowance),
                repository_writers=repository_writers,
                mounts=launch.declared_mounts(mount, mount_ro),
            )

    codex_target = targets.builder("codex")
    if codex_target is not None:

        @app.command(
            "codex",
            context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
            help=launch_help(
                "Generate/reconcile Codex artifacts and launch without updating the CLI."
            ),
        )
        def codex(
            ctx: typer.Context,
            codex_home: Annotated[
                Path | None,
                typer.Option(
                    "--codex-home", help="Override the worktree-scoped Codex home"
                ),
            ] = None,
            profile: Annotated[
                str | None,
                typer.Option("--profile", "-p", help="Codex named config overlay"),
            ] = None,
            model: Annotated[
                str | None,
                typer.Option("--model", "-m", help="Native model override"),
            ] = None,
            generate_only: Annotated[
                bool,
                typer.Option("--generate-only", help="Generate without launching"),
            ] = False,
            force_install: Annotated[
                bool,
                typer.Option(
                    "--force-install",
                    help="Reinstall even when the cached digest matches",
                ),
            ] = False,
            continue_latest: Annotated[
                bool,
                typer.Option(
                    "--continue", "-c", help="Reopen the most recent session here"
                ),
            ] = False,
            resume: Annotated[
                bool,
                typer.Option("--resume", help="Pick a session to reopen"),
            ] = False,
            session: Annotated[
                str | None,
                typer.Option("--session", help="Reopen this session by id"),
            ] = None,
            ignore_antipatterns: Annotated[
                bool,
                typer.Option(
                    "--ignore-antipatterns",
                    help="Open a session the anti-pattern gate leaves alone",
                ),
            ] = False,
            sandbox: Annotated[
                launch.LaunchSandbox,
                typer.Option(
                    "--sandbox",
                    help="Which sandbox holds the session: the verified "
                    "container (outer), the runtime's own on the host "
                    "(inner), or the semantic policy alone (none)",
                ),
            ] = launch.LaunchSandbox.OUTER,
            mount: Annotated[
                list[Path],
                typer.Option(
                    "--mount",
                    exists=True,
                    file_okay=False,
                    resolve_path=True,
                    help="Extra folder this session may read and write "
                    "(repeatable); registered for this launch only",
                ),
            ] = [],
            mount_ro: Annotated[
                list[Path],
                typer.Option(
                    "--mount-ro",
                    exists=True,
                    file_okay=False,
                    resolve_path=True,
                    help="Extra folder this session may read and must not "
                    "write (repeatable)",
                ),
            ] = [],
            max_recursive_agent: Annotated[
                int | None,
                typer.Option(
                    "--max-recursive-agent",
                    min=-1,
                    help="Maximum child-agent depth; -1 allows unlimited recursion",
                ),
            ] = None,
            transcribe_session: Annotated[
                bool,
                typer.Option(
                    "--transcribe-session",
                    help="Mirror the native CLI transcript when this mode disables it",
                ),
            ] = False,
        ) -> None:
            selection = launch.extract_launch_mode(modes, ctx.args)
            allowance = (
                selection.mode.recursive_agent_limit(max_recursive_agent)
                if selection.mode is not None
                else -1
                if max_recursive_agent is None
                else max_recursive_agent
            )
            launch.launch_codex(
                selected_target(
                    selection.mode, "codex", allowance, ignore_antipatterns
                ),
                selection.arguments,
                codex_home,
                profile,
                model,
                generate_only,
                force_install,
                selection.mode,
                Resumption(latest=continue_latest, pick=resume, session=session),
                ignore_antipatterns,
                sandbox,
                checkpoint=checkpoint,
                max_recursive_agent=allowance,
                transcribe_session=transcribe_session,
                companions=companion_targets(selection.mode, "codex", allowance),
                repository_writers=repository_writers,
                mounts=launch.declared_mounts(mount, mount_ro),
            )

    return app
