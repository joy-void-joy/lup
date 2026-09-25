"""The portable-content rule: prose may not spell what an adapter spells.

Nothing here lists a platform word. Every native word reaches a rendered
artifact through a :class:`NativeSpellings` method, so the vocabulary this rule
forbids is asked for rather than written down — a second copy would drift the
moment a runtime gained a location.

An ``Atom`` contributes its whole text, since every character of it is the
runtime's own. An ``Instruction`` frames text its caller supplied, so its
sentence says nothing about prose; the runtime declares the words within it
instead, and those are checked against what it actually spells.
"""

from collections.abc import Callable
from typing import get_args

from pydantic import BaseModel

from lup.harness.codescan.common import ProjectRuleFamily, Rule, RuleExample
from lup.harness.contracts import NativeSpellings
from lup.harness.models import Harness, PluginLocation, TreeLocation

# lup: ignore[constant-declaration] — the rule's own identity, what a typed
# directive and every deny message name it by
RULE_ID = "portable-content"


class ProseBreach(BaseModel, frozen=True):
    """One native spelling found in prose that every tree renders."""

    declaration_id: str
    spelling: str
    runtime: str


def native_vocabulary(runtime: NativeSpellings, plugins: list[str]) -> list[str]:
    """Every word one runtime spells, which portable prose may not hold.

    The location sets come from their own declared types, so a new location is
    forbidden in prose the moment a runtime learns to spell it.
    """
    spellings = [
        runtime.runtime_name,
        runtime.arguments_ref(),
        *runtime.native_identifiers,
        *(runtime.tree(location) for location in get_args(TreeLocation.__value__)),
        *(
            runtime.plugin(plugin, location, member)
            for plugin in plugins
            for location in get_args(PluginLocation.__value__)
            for member in [None, "name"]
        ),
    ]
    return sorted(dict.fromkeys(spellings), key=len, reverse=True)


def prose_breaches(
    source: Harness, runtimes: list[NativeSpellings]
) -> list[ProseBreach]:
    """Find every native spelling in prose more than one runtime renders.

    Composition is the only place that sees the assembled text: a description
    built elsewhere and folded in reaches every tree without ever appearing in
    a declaration module a file scanner could read.
    """
    plugins = [plugin.name for plugin in source.plugins]
    documents = [
        ("harness.guidance", source.guidance.document()),
        *(
            (declaration.id, declaration.prompt)
            for plugin in source.plugins
            for declaration in [*plugin.skills, *plugin.agents]
        ),
    ]
    prose = [
        (declaration_id, text)
        for declaration_id, document in documents
        for text in document.prose()
    ]
    prose.extend(
        (declaration.id, declaration.description)
        for plugin in source.plugins
        for declaration in [plugin, *plugin.skills, *plugin.agents]
    )
    return [
        ProseBreach(
            declaration_id=declaration_id,
            spelling=spelling,
            runtime=runtime.runtime_name,
        )
        for runtime in runtimes
        for spelling in native_vocabulary(runtime, plugins)
        for declaration_id, text in prose
        if spelling in text
    ]


class CompositionRule(Rule):
    """A rule decided over the assembled harness, which only generation sees.

    ``judge`` is the rule: handed the composed declaration and the runtimes
    that render it, it returns every native spelling the prose holds. The
    composition root refuses to render while any stands, which is the one
    surface that can, since a description built elsewhere and folded into a
    prompt appears in no file a scanner could read.
    """

    family: ProjectRuleFamily
    scope: str
    judge: Callable[[Harness, list[NativeSpellings]], list[ProseBreach]]

    @property
    def defined_in(self) -> str:
        """The module holding the judge, which is where the rule is enforced."""
        return self.judge.__module__


PORTABLE_RULE = CompositionRule(
    id=RULE_ID,
    family="spelling",
    scope="Portable harness declarations",
    examples=[
        RuleExample(code="Edit `.claude/settings.json` by hand", verdict="flagged"),
        RuleExample(code="Edit the settings file by hand", verdict="cleared"),
    ],
    message=(
        "Prose every native tree renders names no platform: the vocabulary is "
        "whatever the adapters spell, so a location, product, or tool a runtime "
        "can spell reaches prose through a typed part instead."
    ),
    judge=prose_breaches,
)
"""The portable-content rule, declared beside the judge that decides it."""
