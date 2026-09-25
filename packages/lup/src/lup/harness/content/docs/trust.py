"""Trust on launch: what a launch runs on the host, and how its operator approves it."""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(module=__name__),
    ],
)
