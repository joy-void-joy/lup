"""Why the seams sit where they do: capability composition across the repo."""

import lup.harness.models as models

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(module=__name__),
    ],
)
