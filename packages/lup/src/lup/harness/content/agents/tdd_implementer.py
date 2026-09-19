"""Canonical declaration for the TDD implementer agent.

Named for the discipline rather than the act, because ``implementer`` is
already the resolver's worker skill and the two do different jobs: that one
takes a generalized concern and fixes it wherever it occurs, while this one
takes failing tests as the specification and may not touch them. One name
over two unrelated roles reads as one role to whoever is choosing between
them.
"""

import lup.harness.models as models

AGENT = models.Agent(
    id="agent.tdd-implementer",
    name="tdd-implementer",
    description="Write production code against failing tests, without editing the tests",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
        ],
    ),
    tools=["Read", "Grep", "Glob", "Bash", "Write", "Edit"],
    model="strongest",
    color="green",
)
