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
        models.Passage(
            module=__name__,
            name="discovery-parts",
            values={
                "ask_user": models.AskUser(
                    question="the usecase itself — who runs this and on what occasion, "
                    "what one run is, one worked example (a real input and the output "
                    "they wish it produced), and what makes a run a success"
                ),
            },
        ),
    ]
