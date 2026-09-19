"""One log per repository, separate types in it, and standing read not stored."""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(module=__name__),
    ],
)
