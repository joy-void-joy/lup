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
            models.TextPart(
                text=rf"""# Status: Feedback Loop Entry Point

Get the current state of the agent and select analysis targets.

## Process

### 1. Agent version and data overview

```bash
uv run lup-devtools version
uv run lup-devtools feedback status
```

### 2. Previous session

`feedback status` above reports the analysis state. For what the last pass
actually concluded, read the most recent `*_analysis.md` under
`{ANALYSIS_DIRECTORY}` with your own file tools — the directory may not exist
yet in a project that has never run this loop, and that is an answer rather
than an error.

Note what was already fixed, and don't re-investigate it. What the last pass
deliberately parked is not in that file: it is a `# lup: defer:` note at the
site it concerns, which `uv run lup-devtools dev comments` lists.

### 3. Select targets

Find sessions to analyze:

```bash
uv run lup-devtools feedback unanalyzed
uv run lup-devtools feedback errors
```

Prioritize: sessions with errors, sessions with poor outcomes (if outcome data exists), recent sessions from the current version.

### 4. Gate

Show:
- Agent version and session count
- Selected target sessions with key stats
- What was done last session (if applicable)

Then """
            ),
            models.AskUser(
                question="whether to proceed with these targets or change the selection"
            ),
            models.TextPart(
                text=r"""
"""
            ),
        ],
    ),
)
