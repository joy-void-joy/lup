"""Canonical self-improvement loop guidance.

Rendered to ``docs/self-improvement.md`` rather than the always-loaded
guidance because every step here is only actionable inside a feedback,
review, or meta skill, each of which loads its own instructions.
"""

import lup.harness.content.conventions as conventions
import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(module=__name__),
        *conventions.FAILURE_ANALYSIS.parts,
        models.Passage(module=__name__, name="self_improvement-2"),
    ],
)
