"""The decision walk the design-facing skills share.

Brainstorm, distill, and meta each turn a pile of claims — the user's ask, a
prior session's notes, a worked example — into decisions the user has made
rather than inherited. The walk is the same in all three: read and verify
before asking, put every decision to the user whole and numbered, rebuild a
concept from its failure when asked, check what can be checked now, and
close with a briefing the user did not have to watch being written.
"""

import lup.harness.models as models


def deciding_parts() -> list[models.PromptPart]:
    """Walk every decision from scratch and leave each one the user's."""
    return [
        models.Passage(
            module=__name__,
            name="deciding-parts",
            values={
                "project_settings": models.NativePath(location="project_settings"),
                "nested_run": models.NestedRun(prompt="<the kit's first prompt>"),
            },
        ),
    ]
