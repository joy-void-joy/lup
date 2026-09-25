"""Opening a session in a declared mode: the plugin it runs on, and what it is told.

A mode that drops the plugin's hooks, or its scan rules, needs a plugin the
committed trees do not hold. Writing one over them would change what every
other session opens against — the next normal session included — and a
commit made in between would carry a plugin nobody declared, which is the
cost ``--ignore-antipatterns`` names at every launch. So the variant is
compiled for the launch into a directory outside the checkout, content
addressed so two launches of one mode share it and a running session's copy
is never rewritten under it, and mounted read-only into the container: the
session runs on it and cannot change it, and the committed trees never move.

Each runtime is pointed at the variant in its own way. Claude Code takes a
plugin directory for one session, and its documentation says a copy loaded
that way replaces the installed plugin of the same name. Codex installs a
plugin into its home, so the variant is installed from its own root into a
home kept for the mode alone — sharing the normal home would leave whichever
revision was installed last registered for the next session of either kind.
"""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import typer
from pydantic import BaseModel

from lup.devtools.dev.git_guards import STANDDOWN_VARIABLE
from lup.harness.codescan.registry import every_rule_retired
from lup.harness.models import Artifact, ArtifactTree, Harness, SessionMode
from lup.harness.notice import Notice
from lup.providers.harness import compile_claude, compile_codex, guidance_artifacts
from lup.providers.login import NativeHomeScope
from lup.types import EnvVars

# lup: ignore[constant-declaration] — the one spelling of the variable a
# launch sets and anything inside the session reads, an identity between them
MODE_VARIABLE = "LUP_SESSION_MODE"
"""The name of the mode a session was launched in, in that session's environment."""

# lup: ignore[constant-declaration] — the marker this module writes last into a
# variant and reads back to know the directory is whole, an identity it owns
COMPLETE_MARKER = ".lup-variant"
"""Written last into a compiled variant, so a half-written one is never reused."""


def variant_of(harness: Harness, mode: SessionMode) -> Harness:
    """The harness a mode's session is compiled from, for that launch alone.

    The same copies a launch already knows how to make — without the hooks,
    with every scan rule retired — taken in whichever combination the mode
    names, with the mode's own guidance in place of the project's where it
    carries one, so a variant is never a third kind of harness.
    """
    ungated = harness if mode.hooks else harness.ungated()
    ruled = ungated if mode.scan_rules else ungated.holding(every_rule_retired())
    if mode.guidance is None:
        return ruled
    return ruled.model_copy(update={"guidance": mode.guidance})


class CompiledMode(BaseModel, frozen=True):
    """What a launch in one mode was compiled into, for one runtime.

    ``plugin`` is where the runtime is pointed instead of the committed
    plugin — Claude Code's plugin directory, Codex's root offering its
    plugin — or nothing where the mode keeps the committed one.
    ``overlays`` are the mode's rendered guidance, each keyed by the file on
    the host and naming the committed file's path inside the container it
    is mounted over.
    """

    plugin: Path | None = None
    overlays: dict[Path, str] = {}

    def mounts(self) -> dict[Path, str]:
        """Every read-only mount this compiled mode needs, host path to inside path."""
        return {
            **({self.plugin: self.plugin.as_posix()} if self.plugin else {}),
            **self.overlays,
        }


def compiled_for(
    compiled: ArtifactTree,
    mode: SessionMode,
    root: Path,
    runtime: str,
    plugin_tree: list[Path],
    pointed: Path,
) -> CompiledMode:
    """Keep the part of a compiled tree a mode needs, written outside the checkout.

    The plugin's own tree — every path under ``plugin_tree`` — where the
    mode opens on its own plugin, and the always-loaded document where it
    carries its own, both rendered by the renderer generation uses and held
    to the budget generation holds, since the tree came through the same
    compile. ``pointed`` is where in the kept tree the runtime is pointed.
    The document is mounted over the committed one at the path the renderer
    names for it, which is the path that runtime reads, rather than a path
    spelled here.
    """
    guidance = guidance_artifacts(compiled) if mode.guidance is not None else []
    kept = [
        artifact
        for artifact in compiled.artifacts
        if (
            mode.compiles_plugin()
            and any(artifact.path.is_relative_to(prefix) for prefix in plugin_tree)
        )
        or artifact in guidance
    ]
    if not kept:
        return CompiledMode()
    base = materialized(kept, variants_home(root) / mode.name / runtime)
    return CompiledMode(
        plugin=base / pointed if mode.compiles_plugin() else None,
        overlays={
            base / artifact.path: (root / artifact.path).as_posix()
            for artifact in guidance
        },
    )


def variants_home(root: Path, cache: Path | None = None) -> Path:
    """Where one checkout's compiled mode variants are kept, outside the checkout.

    Outside it because a directory inside it is one a session can write,
    and a variant a session could rewrite is a mode that session could
    widen for the next launch of it. Keyed per checkout, the way a
    container's environment directory is.
    """
    held = cache or Path.home() / ".cache" / "lup" / "modes"
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return held / f"{root.name}-{digest}"


def snapshots_home(root: Path) -> Path:
    """Where one checkout's launch-time snapshots are kept, outside the checkout.

    Beside the mode variants and for their reason: what a session runs on
    is kept where no session can write it.
    """
    return variants_home(root, Path.home() / ".cache" / "lup" / "snapshots")


def materialized(artifacts: list[Artifact], parent: Path) -> Path:
    """Write these artifacts under a directory named for their content.

    Reused whole when present, because the name is the content: a launch of
    an unchanged mode finds the directory the last one wrote. Written aside
    and moved into place, with the marker last, so a directory without the
    marker is one an interrupted launch left and is never opened. Nothing is
    ever deleted here — a running session may still be reading an older one.
    """
    record = [
        [artifact.path.as_posix(), artifact.content, artifact.executable]
        for artifact in sorted(artifacts, key=lambda artifact: artifact.path)
    ]
    digest = hashlib.sha256(json.dumps(record).encode()).hexdigest()[:16]
    target = parent / digest
    if (target / COMPLETE_MARKER).is_file():
        return target
    staging = parent / f".staging-{uuid4().hex}"
    for artifact in artifacts:
        destination = staging / artifact.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content, encoding="utf-8")
        if artifact.executable:
            destination.chmod(0o755)
    (staging / COMPLETE_MARKER).write_text(digest + "\n", encoding="utf-8")
    try:
        staging.rename(target)
    except OSError:
        # Another launch of the same mode finished first, which leaves the
        # same content under the same name: take it, and drop this copy.
        shutil.rmtree(staging)
        if not (target / COMPLETE_MARKER).is_file():
            raise
    return target


def claude_variant(harness: Harness, mode: SessionMode, root: Path) -> CompiledMode:
    """What a mode's Claude Code session loads in place of the committed tree.

    The plugin directory it is pointed at with ``--plugin-dir``, which the
    vendor documents as replacing the installed plugin of the same name, and
    its guidance, mounted over the committed document. The project's
    settings and everything else stay the checkout's own.
    """
    plugin = Path(".claude") / "plugins" / harness.plugins[0].name
    return compiled_for(
        compile_claude(variant_of(harness, mode)),
        mode,
        root,
        "claude",
        [plugin],
        plugin,
    )


def codex_variant(harness: Harness, mode: SessionMode, root: Path) -> CompiledMode:
    """What a mode's Codex session installs and reads in place of the committed tree.

    A root rather than a plugin directory, because Codex finds a project's
    plugin through the marketplace document it offers: the variant's root
    carries that document and the plugin it names. The marketplace document
    is kept only where the plugin is, since without the plugin there is
    nothing for it to offer.
    """
    return compiled_for(
        compile_codex(variant_of(harness, mode)),
        mode,
        root,
        "codex",
        [Path(".codex") / "plugins" / harness.plugins[0].name, Path(".agents")],
        Path("."),
    )


def compiled_mode(
    compile_for: Callable[[Harness, SessionMode, Path], CompiledMode],
    harness: Harness,
    mode: SessionMode,
    root: Path,
) -> CompiledMode:
    """One runtime's compile of a mode, refused in the mode's name where it fails.

    The renderers refuse what generation would refuse — a document over the
    always-loaded budget, prose naming one runtime — and a launch is where a
    mode is first compiled, so the refusal is said as the launch's, naming
    the mode, before anything is opened.
    """
    try:
        return compile_for(harness, mode, root)
    except ValueError as refusal:
        raise typer.BadParameter(f"--mode {mode.name}: {refusal}") from refusal


def mode_home_scope(mode: SessionMode, base: NativeHomeScope | None) -> NativeHomeScope:
    """The home a mode's Codex sessions keep, apart from every normal session's.

    Derived from the scope the launch would otherwise use, so a mode keeps
    the partition by selected settings a normal session has and adds its own
    beside it. The mode's name enters as a digest, because a scope key is
    restricted to the characters a volume name takes.
    """
    named = hashlib.sha256(mode.name.encode()).hexdigest()[:12]
    stem = base.key if base is not None else "codex"
    return NativeHomeScope(key=f"{stem}-mode-{named}")


def mode_environment(mode: SessionMode | None) -> EnvVars:
    """What a session launched in a mode carries so what runs inside can tell."""
    if mode is None:
        return {}
    return {
        MODE_VARIABLE: mode.name,
        **({STANDDOWN_VARIABLE: "off"} if not mode.git_guards else {}),
    }


def refuse_on_host(mode: SessionMode, contained: bool) -> None:
    """Refuse a mode whose postures only a container may stand in for, on the host.

    Three kinds of mode are the container's. One switches something off that
    the host would then be without — see :meth:`SessionMode.switched_off`.
    One opens on a plugin compiled for it, which only a contained launch
    keeps apart from the home a normal session on this host uses. And one
    reads its own guidance, which is put in the committed document's place
    by a mount the host tree never sees — and on the host there is no mount.
    """
    if contained:
        return
    off = mode.switched_off()
    if off:
        raise typer.BadParameter(
            f"--mode {mode.name} switches off {', '.join(off)}, which only the "
            "container may stand in for. Launch it with --sandbox outer."
        )
    if mode.compiles_plugin():
        raise typer.BadParameter(
            f"--mode {mode.name} opens on a plugin compiled for it, which only a "
            "contained launch keeps apart from this host's normal sessions. "
            "Launch it with --sandbox outer."
        )
    if mode.guidance is not None:
        raise typer.BadParameter(
            f"--mode {mode.name} reads its own guidance in place of the "
            "project's, which only a contained launch can put there without "
            "changing the tree on the host. Launch it with --sandbox outer."
        )


def mode_notices(mode: SessionMode | None) -> list[Notice]:
    """The lines saying which mode a session opens in and what it set aside."""
    if mode is None:
        return []
    off = mode.switched_off()
    return [
        Notice(text=f"Mode: {mode.name} — {mode.description}", urgency="boundary"),
        *(
            [
                Notice(
                    text="Switched off for this session: " + ", ".join(off),
                    urgency="boundary",
                    indent=1,
                )
            ]
            if off
            else []
        ),
        *(
            [
                Notice(
                    text=(
                        "Scan rules: retired for this session; the committed "
                        "trees still hold the repository to them"
                    ),
                    urgency="boundary",
                    indent=1,
                )
            ]
            if not mode.scan_rules and mode.hooks
            else []
        ),
        *(
            [
                Notice(
                    text=(
                        "Git guards: stand down for this session's commits; "
                        "a normal session cleans up after it"
                    ),
                    urgency="boundary",
                    indent=1,
                )
            ]
            if not mode.git_guards
            else []
        ),
    ]
