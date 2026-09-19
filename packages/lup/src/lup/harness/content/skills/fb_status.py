"""Canonical declaration for the fb-status skill.

The analysis directory is read from
:func:`lup.workspace.paths.checkout_feedback_path` rather than spelled, so the
prose cannot name a directory the code stopped writing to — and read from the
checkout's tree rather than the override-aware one, so a session regenerating
this artifact under its own notes override names the directory every session
shares instead of its own.
"""

import lup.harness.models as models
from lup.workspace.paths import checkout_feedback_path, project_root

ANALYSIS_DIRECTORY = checkout_feedback_path().relative_to(project_root()).as_posix()
"""Where an analysis lands, relative to the checkout, as prose names it."""

SKILL = models.Skill(
    id="skill.fb-status",
    name="fb-status",
    description="Feedback loop entry point \u2014 status, targets, and previous session context",
    tools=["Bash(uv run lup-devtools:*)", "Read", "Grep", "Glob", "AskUserQuestion"],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "ask": models.AskUser(
                        question="whether to proceed with these targets or change the selection"
                    ),
                    "analysis_directory": models.code(ANALYSIS_DIRECTORY),
                },
            ),
        ],
    ),
)
