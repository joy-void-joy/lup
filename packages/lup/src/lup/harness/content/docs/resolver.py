"""Resolver lifecycle, mailbox, and recovery."""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(module=__name__),
    ],
)
