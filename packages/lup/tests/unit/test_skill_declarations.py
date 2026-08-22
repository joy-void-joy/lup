"""Invariants a skill declaration answers before any tree renders it.

A skill declares what it tells its reader to do and what it lets them do, in
two lists that sit beside each other. Nothing made them agree, so a skill
could instruct a step its own grant forbids — which is a failure the author
never sees and the agent meets mid-run, as a denial while following correct
instructions. These pin the agreement at declaration time instead.
"""

import pytest
from pydantic import ValidationError

from lup.harness.models import (
    BashGrant,
    PromptDocument,
    Skill,
    TextPart,
    WatchOutput,
)


def skill_watching(command: str, tools: list[str]) -> Skill:
    """A minimal skill that watches ``command`` under ``tools``."""
    return Skill(
        id="skill.example",
        name="example",
        description="A skill declared for this test",
        tools=tools,
        prompt=PromptDocument(
            parts=[TextPart(text="Run it:"), WatchOutput(command=command)]
        ),
    )


class TestBashGrant:
    def test_an_unscoped_grant_admits_every_command(self) -> None:
        grant = BashGrant.read("Bash")
        assert grant == BashGrant(prefixes=[])
        assert grant is not None
        assert grant.admits("anything at all")

    def test_a_scoped_grant_admits_only_its_own_prefixes(self) -> None:
        grant = BashGrant.read("Bash(git:*, uv run lup-devtools:*)")
        assert grant is not None
        assert grant.admits("uv run lup-devtools dev check")
        assert grant.admits("git status")
        assert not grant.admits("ls -t notes")

    def test_a_grant_for_another_tool_is_not_bash_coverage(self) -> None:
        assert BashGrant.read("Read") is None
        assert BashGrant.read("Skill(lup:commit)") is None


class TestWatchedCommandsAreGranted:
    def test_a_watched_command_under_a_covering_grant_declares(self) -> None:
        declared = skill_watching(
            "uv run lup-devtools dev check", ["Bash(uv run lup-devtools:*)", "Read"]
        )
        assert declared.prompt.parts[1].shell_command == (
            "uv run lup-devtools dev check"
        )

    def test_a_watched_command_with_no_shell_granted_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="grants no Bash that runs it"):
            skill_watching("uv run lup-devtools dev check", ["Read", "Write"])

    def test_a_watched_command_outside_every_prefix_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="grants no Bash that runs it"):
            skill_watching("ls -t notes/feedback_loop", ["Bash(git:*)"])

    def test_an_empty_grant_list_restricts_nothing(self) -> None:
        """No grant list renders no frontmatter, so the session's tools stand."""
        assert (
            skill_watching("uv run lup-devtools harness resolve status", []).tools == []
        )

    def test_a_part_naming_no_command_declines_the_question(self) -> None:
        assert TextPart(text="prose naming nothing").shell_command is None
