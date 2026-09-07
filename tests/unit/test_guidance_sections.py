"""What identity buys the always-loaded document, and what it must not cost.

The document was a hand-ordered splice of constants across two packages: it
rendered correctly and nothing could name a piece of it. What these pin is
that naming the pieces changed the declaration and not the output — the same
bytes reach a session — and that a name is now worth something, because the
same algebra that retires a skill retires a section.
"""

import pytest

import lup.harness.models as models
from lup.harness.content import conventions
from lup.harness.codescan.common import RuleSelection
from lup.seams import Selection
from lup_template.harness.content.guidance import (
    guidance_parts,
    guidance_sections,
)

SECTIONS = guidance_sections(RuleSelection())
"""This repository's document, resolved against a project retiring nothing."""


def test_every_section_is_named_once() -> None:
    """Two sections under one id is the ambiguity a selection cannot survive.

    Retiring an id that names two stretches of the document would take out
    whichever the resolution reached, and which that is would depend on the
    order the composition happened to build.
    """
    ids = [section.id for section in SECTIONS]

    assert sorted(ids) == sorted(set(ids))


def test_the_parts_are_the_sections_read_end_to_end() -> None:
    """Identity is a layer over the document, never a second copy of it."""
    assert guidance_parts(RuleSelection()) == [
        part for section in SECTIONS for part in section.parts
    ]


def test_a_retired_section_leaves_the_document() -> None:
    """The point of the name: a project declines a section it does not want.

    Nothing declines one today — every section here is this repository's own
    answer — so what is pinned is that the seat works, against the algebra
    every other table in the repository already resolves through.
    """
    resolved = Selection(retired=["configuration"]).over(SECTIONS)

    assert "configuration" not in [section.id for section in resolved]
    assert len(resolved) == len(SECTIONS) - 1


def test_a_declared_section_replaces_the_one_of_its_id_in_place() -> None:
    """A project rewriting one section says so where it would have added it."""
    mine = models.GuidanceSection(
        id="configuration",
        chapter="tooling",
        parts=[models.TextPart(text="## Configuration\n\nSomewhere else.\n")],
    )

    resolved = Selection(overrides=[mine]).over(SECTIONS)

    assert [section for section in resolved if section.id == "configuration"] == [mine]
    assert len(resolved) == len(SECTIONS)


def test_a_sections_text_is_the_prose_it_carries() -> None:
    """What a weigher reads, without knowing which kinds of part hold words."""
    section = models.GuidanceSection(
        id="worked-example",
        chapter="code",
        parts=[
            models.TextPart(text="before "),
            models.SkillInvocation(plugin="lup", skill="commit"),
            models.TextPart(text=" after"),
        ],
    )

    assert section.text == "before  after"


@pytest.mark.parametrize("retired", [[], ["own-model-dispatch"]])
def test_the_built_section_answers_to_its_id_whatever_it_says(
    retired: list[str],
) -> None:
    """The one section whose contents depend on the reading project's rules.

    Its prose changes with the selection and its name does not, which is what
    lets a project retire or replace it by the same id as every other.
    """
    built = conventions.design_principles(RuleSelection(retired=retired))

    assert built.id == "design-principles"
