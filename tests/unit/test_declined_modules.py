"""Declining any module, with everything that requires it, still composes.

A reach from one module into another is either a step, declared as the other
module in ``requires``, or a pointer that holds only where what it names
ships — a skill in the plugin, a command group in the CLI. Either kind left
undeclared surfaces only when some project declines the module it reaches
into, and this repository takes every module it ships, so nothing here ever
meets one. An adopter met them one failed build at a time: first a skill
invocation naming nothing, then a documented command naming nothing.

So every answer an adopter can give is composed here, through the code the real
composition runs: each module in the roster, declined together with the modules
requiring it, into the harness, its pages, the guidance an installer merges, and
both native trees. What declining promises is checked on what was built — none
of the declined modules' skills, tool groups or command trees survive — and
every command the rendered prose tells a reader to run is one the CLI still
serves, judged the way the documented-commands sweep judges it — and so is
every command the application's own source names, which an adopter keeps and
generation's sweep reads as written. A module every composition stands on is
refused rather than composed, by name.
"""

from pathlib import Path

import pytest

import lup_template.harness.content.catalog as content
from lup.devtools.dev.documented import MENTION, WrittenCommand, written_commands
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.workspace.paths import project_root
from lup_template.harness.catalog import portable_harness
from lup_template.harness.composition import claude_target, codex_target

SPECS = content.MODULE_SPECS
"""The whole roster, the scaffold's own module included."""

APPLICATION = content.LAYOUT.directory()
"""The application source an adopter keeps and renames: its own words, read raw."""

CONTENT = content.LAYOUT.directory("harness", "content")
"""The declarations under it, whose prose is judged where it renders instead."""

SHIPPED = {
    module.spec.id: {skill.name for skill in module.content.skills}
    for module in content.MODULES
}
"""Each module's skills as this repository, taking every module, ships them."""


def declined_with(module: str, reached: frozenset[str] = frozenset()) -> frozenset[str]:
    """One module and every module requiring it, however indirectly."""
    closure = reached | {module}
    for spec in SPECS:
        if module in spec.requires and spec.id not in closure:
            closure = declined_with(spec.id, closure)
    return closure


def grounded(module: str) -> bool:
    """Whether declining this module takes a foundation down with it."""
    return any(spec.foundation for spec in SPECS if spec.id in declined_with(module))


def compiled(composition: NativeHarnessComposition) -> set[str]:
    """Every skill the tree a composition generates ships."""
    return {skill.name for skill in composition.recipe.source.plugins[0].skills}


def unserved(composition: NativeHarnessComposition, served: list[str]) -> list[str]:
    """Every written command in a generated tree whose group the CLI does not serve.

    Read with the documented-commands sweep's own reading of a mention, over
    every Markdown and Python artifact generation would write. The top-level
    word is what a declined module takes away, so it is the one judged.
    """
    return [
        mention.named()
        for artifact in composition.recipe.desired.artifacts
        if artifact.path.suffix in (".md", ".py")
        for number, line in enumerate(artifact.content.splitlines(), start=1)
        for tail in MENTION.findall(line)
        for mention in [
            WrittenCommand(
                file=artifact.path.as_posix(), line=number, spelled=tail.strip()
            )
        ]
        if (words := mention.command_words()) and words[0] not in served
    ]


def unserved_in_source(served: list[str]) -> list[str]:
    """Every written command in the application's own source the CLI does not serve.

    Read as the sweep generation runs reads it, file by file from the tracked
    tree: this source is not rendered, so no composition settles it, and a
    docstring example naming a declined module's command refuses an adopter's
    first regeneration after declining it.
    """
    return [
        mention.named()
        for mention in written_commands([CONTENT])
        if mention.file.startswith(APPLICATION)
        and (words := mention.command_words())
        and words[0] not in served
    ]


@pytest.mark.parametrize("module", [spec.id for spec in SPECS if not grounded(spec.id)])
def test_declining_a_module_and_what_requires_it_still_composes(module: str) -> None:
    """The harness validates, the pages resolve, both trees build, every command runs."""
    declined = declined_with(module)
    composed = content.composed(declined=sorted(declined))
    root: Path = project_root()

    claude = claude_target(root, composed=composed)
    codex = codex_target(root, composed=composed)

    gone = {name for identity in declined for name in SHIPPED[identity]}
    assert compiled(claude).isdisjoint(gone)
    assert compiled(codex).isdisjoint(gone)
    servers = {server.name for server in claude.recipe.source.plugins[0].mcp_servers}
    assert servers.isdisjoint(
        group for spec in SPECS if spec.id in declined for group in spec.tool_groups
    )
    assert set(composed.subapps).isdisjoint(
        name for spec in SPECS if spec.id in declined for name in spec.subapps
    )
    served = [spec.name for spec in composed.subapp_specs]
    assert unserved(claude, served) == []
    assert unserved(codex, served) == []
    assert unserved_in_source(served) == []


@pytest.mark.parametrize("module", [spec.id for spec in SPECS if grounded(spec.id)])
def test_declining_what_every_composition_stands_on_is_refused_by_name(
    module: str,
) -> None:
    """Refused where the roster is built, naming the foundation it would take."""
    with pytest.raises(ValueError, match="foundation every composition stands on"):
        content.composed(declined=sorted(declined_with(module)))


def test_a_declined_resolver_leaves_the_harness_without_a_spec() -> None:
    """The spec's three invocations name skills the declined module no longer ships."""
    composed = content.composed(declined=["resolver"])

    assert portable_harness(composed=composed).resolver is None


def test_a_taken_resolver_still_declares_its_spec() -> None:
    spec = portable_harness().resolver
    assert spec is not None
    assert spec.worker_skill.skill == "implementer"
