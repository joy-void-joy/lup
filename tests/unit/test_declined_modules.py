"""Declining any module, with everything that requires it, still composes.

A reach from one module into another is either a step, declared as the other
module in ``requires``, or a pointer that holds only where the other module's
skill ships. Either kind left undeclared surfaces only when some project
declines the module it reaches into — and this repository takes every module
it ships, so nothing here ever meets one. An adopter met two, one failed build
at a time.

So every answer an adopter can give is composed here, through the code the real
composition runs: each module in the roster, declined together with the modules
requiring it, into the harness, its pages, the guidance an installer merges, and
both native trees. And what declining promises is checked on what was built:
none of the declined modules' skills, tool groups or command trees survive.
"""

from pathlib import Path

import pytest

import lup_template.harness.content.catalog as content
from lup.devtools.harness.generate import NativeHarnessComposition
from lup.workspace.paths import project_root
from lup_template.harness.catalog import portable_harness
from lup_template.harness.composition import claude_target, codex_target

SPECS = content.MODULE_SPECS
"""The whole roster, the scaffold's own module included."""

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


def compiled(composition: NativeHarnessComposition) -> set[str]:
    """Every skill the tree a composition generates ships."""
    return {skill.name for skill in composition.recipe.source.plugins[0].skills}


@pytest.mark.parametrize("module", [spec.id for spec in SPECS])
def test_declining_a_module_and_what_requires_it_still_composes(module: str) -> None:
    """The harness validates, the pages and installer guidance resolve, both trees build."""
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


def test_a_declined_resolver_leaves_the_harness_without_a_spec() -> None:
    """The spec's three invocations name skills the declined module no longer ships."""
    composed = content.composed(declined=["resolver"])

    assert portable_harness(composed=composed).resolver is None


def test_a_taken_resolver_still_declares_its_spec() -> None:
    spec = portable_harness().resolver
    assert spec is not None
    assert spec.worker_skill.skill == "implementer"
