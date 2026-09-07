"""The discovery posture the design-facing skills share.

Brainstorm and distill both open a design conversation, and both are pulled
toward proposing architecture the moment an idea sounds concrete enough to
build on. Architecture anchored on an imprecise usecase is precisely wrong,
so both skills fold in the same forced elicitation: the usecase in the open,
confirmed back, before any structure is drawn.
"""

import lup.harness.models as models


def discovery_parts() -> list[models.PromptPart]:
    """Force the usecase into the open before any architecture is proposed."""
    return [
        models.TextPart(
            text=r"""
## Discover Before Designing

An architecture proposed before the usecase is concrete anchors the whole
conversation on a guess. Before proposing structure, sketching a tool, or
reading code, get the usecase into the open: """
        ),
        models.AskUser(
            question="the usecase itself — who runs this and on what occasion, "
            "what one run is, one worked example (a real input and the output "
            "they wish it produced), and what makes a run a success"
        ),
        models.TextPart(
            text=r""" — with concrete candidate answers to react to, not open
prose alone. A vision the user holds precisely deserves precise questions:
probe until you can restate their vision and have them answer "yes, exactly
that" — then restate it and ask. Only after that confirmation do the
architecture forks earn their turn.
"""
        ),
    ]
