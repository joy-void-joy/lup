"""Canonical code conventions: the lookup behind each guidance rule.

Rendered to ``docs/conventions.md`` rather than the always-loaded guidance.
Each rule has to fire unprompted and so keeps its sentence in the guidance,
while the table a reader consults once the rule already applies — which
library, which typed stand-in, which parser, which resolver tool — is
reference material, and reference material is opened rather than carried on
every turn.
"""

import lup.harness.models as models
from lup.tools.lsp.tools import rendered_tool_declarations

DOCUMENT = models.PromptDocument(
    source=__name__,
    parts=[
        models.Passage(
            module=__name__,
            values={"tools": models.ToolRoster(tools=rendered_tool_declarations())},
        ),
    ],
)
