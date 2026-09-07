"""What this repository is, and what it expects of a session working in it.

The module holding this repository's own framing: the document's opening, how
work moves through it, how its code is written, what its tooling is, how to
report, and where to read further. Every section here is prose lup's library
had no standing to write, because each is a judgement this project made about
itself rather than a rule the framework enforces.

It sits **first** in the composed roster, and that placement is load-bearing
rather than ceremonial. Guidance renders as the chapter spine crossed with the
roster, so a module's position is where its prose lands inside whichever
chapter each section named — and this repository's framing is what opens a
chapter, with the library's general statement of the same subject following.

A project adopting this scaffold rewrites these sections rather than declining
them: the seat is the point, not the words in it.
"""

import lup_template.harness.content.guidance as guidance
from lup.harness.content.docs.catalog import published
from lup.harness.modules import DocumentEntry, Module
from lup_template.harness.content.docs import decisions
from lup_template.harness.content.modules.specs import PROJECT


def module() -> Module:
    """This repository's own framing as one value."""
    return Module(
        spec=PROJECT,
        guidance=[
            guidance.HEADER,
            guidance.DEVELOPMENT_WORKFLOW,
            guidance.CODE_CONVENTIONS,
            guidance.TOOLING,
            guidance.PROCESS_AND_COMMUNICATION,
            guidance.REPORTING_FRICTION,
            guidance.EXTERNAL_RESOURCES,
        ],
        documents=[
            DocumentEntry(
                semantic_id="docs.decisions",
                build=lambda context: published(
                    "decisions",
                    "dev-tooling-decisions.md",
                    decisions.DOCUMENT,
                    context.layout.path("harness", "content", "docs"),
                ),
            )
        ],
        subapps=["agent"],
    )
