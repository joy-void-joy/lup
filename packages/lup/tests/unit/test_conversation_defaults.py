"""Conversation retention is part of Lup's inherited defaults."""

from lup.devtools.harness.content.application import ApplicationLayout
from lup.devtools.harness.content.catalog import library_skills
from lup.devtools.roster import LIBRARY_SPECS


def test_conversation_is_a_library_subapp_default() -> None:
    assert "conversation" in [spec.name for spec in LIBRARY_SPECS]


def test_analyze_is_a_library_skill_default() -> None:
    skills = library_skills(ApplicationLayout(package="example"))

    assert "analyze" in [skill.name for skill in skills]
