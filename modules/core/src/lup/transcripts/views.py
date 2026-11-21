"""What transcripts shows, as the shell's blocks: the conversations kept, a conversation's steps, and what a search found.

Each view is a method of the part holding the index; what it lays out is made
here, from what the index answered, the view a block opens handed in. A block
keeps an id naming what it shows (`hit-412`, `step-412`, `conversation-…`), so
it stays put from one answer to the next. Every view is a command too, which
prints these blocks as text: what an agent in a room reads.
"""

import itertools

from lup.doors.door import Method
from lup.shell.blocks import Block, Blocks, Fold, Line, Markdown, Span, Viewing
from lup.shell.kinds import FoldKind
from lup.transcripts.index import (
    Conversation,
    Hit,
    Listed,
    Searched,
    Showing,
    Shown,
    Stepping,
)
from lup.types import Model

FOLDS = [
    FoldKind(
        name="hit",
        letter="h",
        called="hit",
        level=1,
        starts_open=True,
        colour="info",
    ),
    FoldKind(
        name="conversation",
        letter="v",
        called="conversation",
        level=1,
        colour="cyan",
        outlined=True,
    ),
    FoldKind(name="calls", letter="k", called="calls", level=3),
]
"""The fold kinds transcripts' views name: a search's hit, open, a conversation
listed, read as it opens, and a run of calls, closed."""


class Opens(Model, arbitrary_types_allowed=True):
    """The views a block opens: a conversation's steps."""

    show: Method


def heard(by: str | None) -> str:
    """Say who said a step's words, as a line heading them reads."""
    match by:
        case "operator":
            return "you"
        case "agent":
            return "the agent"
        case "lup":
            return "lup"
        case "conversation":
            return "another conversation"
        case _:
            return "the runtime"


def first_line(text: str) -> str:
    """Return the first line of `text` that says something, marked where more follows."""
    lines = [each for each in text.splitlines() if each.strip()]
    if not lines:
        return ""
    return lines[0] if len(lines) == 1 else f"{lines[0]} …"


def where(conversation: Conversation | Hit) -> str:
    """Say where a conversation is: its runtime and session, its subagent's id where it's one, and the directory it ran in, or its repository."""
    subagent = f" subagent {conversation.subagent}" if conversation.subagent else ""
    ran = (
        f" in {conversation.directory}"
        if conversation.directory
        else f" of {conversation.repository}"
        if isinstance(conversation, Hit) and conversation.repository
        else ""
    )
    return f"{conversation.runtime or ''} {conversation.session or ''}{subagent}{ran}".strip()


def searched_blocks(searched: Searched, opens: Opens, *, whole: bool) -> Blocks:
    """Return a search's hits, the latest first, each its words whole under the start of what they answered, or all of it where `whole`; then how many more it found."""
    hits: list[Block] = [hit_fold(each, opens, whole=whole) for each in searched.hits]
    if not hits:
        hits = [Line(id="nothing", spans=[Span(text="Nothing found.", tone="muted")])]
    more = (
        [
            Line(
                id="more",
                spans=[
                    Span(
                        text=f"{searched.more} more found: a larger `--limit` lists them, "
                        "or narrow the search (`--under`, `--since`, `--until`).",
                        tone="muted",
                    )
                ],
            )
        ]
        if searched.more
        else []
    )
    return Blocks.of(*hits, *more)


def hit_fold(hit: Hit, opens: Opens, *, whole: bool) -> Fold:
    """Return a hit as a fold: when and where, what it answered, its words, and, for a record's step, the view showing the conversation around it."""
    name = hit.step if hit.step is not None else f"{hit.source}-{hit.number}"
    title = hit.title or "untitled"
    item = f"@{hit.number} " if hit.number is not None else ""
    answering = f"on @{hit.on}: " if hit.on is not None else "answering: "
    answered = (
        [
            Line(id=f"hit-{name}-answered", spans=[Span(text=answering, tone="muted")]),
            Markdown(
                id=f"hit-{name}-answered-text",
                text=hit.answered if whole else first_line(hit.answered),
                tone="muted",
            ),
        ]
        if hit.answered
        else (
            [
                Line(
                    id=f"hit-{name}-on",
                    spans=[Span(text=f"on @{hit.on}", tone="muted")],
                )
            ]
            if hit.on is not None
            else []
        )
    )
    said = (
        heard(hit.by)
        if hit.kind == "said" or hit.source != "record"
        else hit.tool or hit.kind
    )
    kind = f" ({hit.kind})" if hit.source != "record" else ""
    around = (
        [
            Line(
                id=f"hit-{name}-around",
                spans=[
                    Span(text="around it: ", tone="muted"),
                    Span(
                        text=f"step {hit.step}",
                        refers=Viewing.of(
                            opens.show,
                            Showing(
                                session=hit.session, subagent=hit.subagent, at=hit.step
                            ),
                        ),
                    ),
                ],
            )
        ]
        if hit.step is not None and hit.session is not None
        else []
    )
    return Fold(
        id=f"hit-{name}",
        kind="hit",
        summary=[
            Span(text=f"{item}{title}", tone="strong"),
            Span(
                text=f"  {hit.at or ''}  {where(hit)}, from {hit.whose or hit.source}",
                tone="muted",
            ),
        ],
        content=[
            *answered,
            Line(
                id=f"hit-{name}-by", spans=[Span(text=f"{said}{kind}:", tone="muted")]
            ),
            Markdown(
                id=f"hit-{name}-text",
                text=hit.text,
                tone="operator" if hit.by == "operator" else "plain",
            ),
            *around,
        ],
    )


def listed_blocks(listed: Listed, opens: Opens) -> Blocks:
    """Return the conversations listed, the latest first, each a fold showing its steps as it opens; then how many more there are."""
    folds: list[Block] = [
        conversation_fold(each, opens) for each in listed.conversations
    ]
    if not folds:
        folds = [
            Line(id="nothing", spans=[Span(text="No conversation kept.", tone="muted")])
        ]
    more = (
        [
            Line(
                id="more",
                spans=[
                    Span(
                        text=f"{listed.more} more: a larger `--limit` lists them.",
                        tone="muted",
                    )
                ],
            )
        ]
        if listed.more
        else []
    )
    return Blocks.of(*folds, *more)


def conversation_fold(conversation: Conversation, opens: Opens) -> Fold:
    """Return a conversation as a fold: its name, when it last moved, where it ran, how many times the operator spoke in it; its steps read as it opens."""
    spoke = (
        f"{conversation.spoken} from you" if conversation.spoken else "nothing from you"
    )
    return Fold(
        id=f"conversation-{conversation.runtime}-{conversation.session}-{conversation.subagent or ''}",
        kind="conversation",
        summary=[
            Span(text=conversation.title or "untitled", tone="strong"),
            Span(
                text=f"  {conversation.last or ''}  {where(conversation)}, {spoke}, "
                f"kept from {conversation.whose}",
                tone="muted",
            ),
        ],
        content=Viewing.of(
            opens.show,
            Showing(session=conversation.session, subagent=conversation.subagent),
        ),
    )


def shown_blocks(shown: Shown, showing: Showing) -> Blocks:
    """Return a conversation's steps as `showing` asked: its words each under who said them, each run of calls a fold of its own, or the operator's words each under what they answered."""
    if showing.at is None and not showing.whole:
        return Blocks.of(
            *(block for each in shown.steps for block in answered_blocks(each))
        )
    before = (
        [
            Line(
                id="before",
                spans=[Span(text=f"{shown.before} steps before", tone="muted")],
            )
        ]
        if shown.before
        else []
    )
    after = (
        [
            Line(
                id="after",
                spans=[Span(text=f"{shown.after} steps after", tone="muted")],
            )
        ]
        if shown.after
        else []
    )
    return Blocks.of(
        *before,
        *(block for run in runs(shown.steps) for block in run_blocks(run)),
        *after,
    )


def answered_blocks(step: Stepping) -> list[Block]:
    """Return the operator's words under the agent's last words before them."""
    answered = (
        [
            Line(
                id=f"step-{step.step}-answered",
                spans=[Span(text="the agent:", tone="muted")],
            ),
            Markdown(
                id=f"step-{step.step}-answered-text", text=step.answered, tone="muted"
            ),
        ]
        if step.answered
        else [
            Line(
                id=f"step-{step.step}-first",
                spans=[Span(text="(the first words)", tone="muted")],
            )
        ]
    )
    return [
        *answered,
        Line(
            id=f"step-{step.step}-by",
            spans=[Span(text=f"you, {step.at or ''}:", tone="muted")],
        ),
        Markdown(id=f"step-{step.step}", text=step.text, tone="operator"),
    ]


def runs(steps: list[Stepping]) -> list[list[Stepping]]:
    """Return `steps` in runs: each step said alone, each run of calls and results together."""
    return [
        run
        for calls, grouped in itertools.groupby(
            steps, key=lambda each: each.kind != "said"
        )
        for run in ([list(grouped)] if calls else [[each] for each in grouped])
    ]


def run_blocks(run: list[Stepping]) -> list[Block]:
    """Return a run of steps: words under who said them, or calls as one fold naming each tool, a line each under it."""
    first = run[0]
    if first.kind == "said":
        return [
            Line(
                id=f"step-{first.step}-by",
                spans=[
                    Span(text=f"{heard(first.by)}, {first.at or ''}:", tone="muted")
                ],
            ),
            Markdown(
                id=f"step-{first.step}",
                text=first.text,
                tone="operator" if first.by == "operator" else "plain",
            ),
        ]
    tools = [each.tool for each in run if each.tool]
    counted = {tool: tools.count(tool) for tool in tools}
    named = ", ".join(
        tool if count == 1 else f"{tool} x{count}" for tool, count in counted.items()
    )
    return [
        Fold(
            id=f"calls-{first.step}",
            kind="calls",
            summary=[Span(text=f"· called {named or 'nothing named'}", tone="muted")],
            content=[
                Line(
                    id=f"step-{each.step}",
                    spans=[
                        Span(text=f"{each.tool or 'returned'}: ", tone="muted"),
                        Span(text=first_line(each.text)),
                    ],
                )
                for each in run
            ],
        )
    ]
