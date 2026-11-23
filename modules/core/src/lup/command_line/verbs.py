"""Verbs on the command line: `lup <verb> <thing>` runs what the thing's block offers under the verb, as the verb's key on that block runs it on the dashboard; `lup <verb>` alone runs the command its verb runs with nothing cited.

A thing is cited as `@` cites it, `@12`, `@dashboard-usable`, `@frictions/keys`,
and the view showing what's cited (`Inboxes.cited`) answers its block, with what
it offers under each verb; the command line runs the offer, given what the block
gives it. So the command line holds no table of what a verb does to which
thing: one block says it, for both. `show` runs nothing, and prints the view the
block opens.

What's typed after what's cited is said with the verb: it goes to the field the
offered command takes the words in (`lup.Words`), a comment's words or a
decline's reason, and a command taking none refuses it. `--lines` quotes lines
of what's cited, as a comment written on them on the dashboard does.
"""

import inspect
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import JsonValue

from lup.command_line.answering import SHOW, Answerer, Offered, Runnable
from lup.command_line.filled import TypedIn
from lup.command_line.parameters import Parameter, Parsed, parameters, sent
from lup.doors.door import Rejection
from lup.running.wire import (
    Answered,
    Call,
    CommandCalled,
    Declined,
    Reply,
    ViewCalled,
)
from lup.shell.blocks import Blocks, Fold, Line, Markdown, Span, Viewing
from lup.shell.kinds import Verb
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from collections.abc import Callable

    from lup.command_line.line import Parsing

TELL = "tell"
"""The verb whose offer takes a comment: what's said is its words, and what the
block gives it is what the comment is on, as the dashboard sends one."""


class Lines(Model):
    """The lines of what's cited that what's said quotes, counted from 1: the first and the last."""

    first: int
    last: int


class Verbing(Model):
    """A verb typed: the verb, what's cited, the words said with it, the lines it quotes, the repository the thing is in, and, with nothing cited, what the command it runs alone was given."""

    verb: str
    cite: str | None = None
    words: list[str] = []
    lines: Lines | None = None
    repository: str | None = None
    alone: JsonObject = {}


class Acted(Model):
    """What a verb typed came to: the last call it made, and its reply, a refusal the command line made itself among them."""

    call: Call
    reply: Reply


def ranged(typed: str) -> Lines:
    """Return the lines `typed` names, `10` or `10-12`, counted from 1.

    Raise `typer.BadParameter` where they aren't one number, or two joined by
    `-`, the first no later than the last.

    >>> ranged("10-12"), ranged("3")
    (Lines(first=10, last=12), Lines(first=3, last=3))
    """
    # lup: ignore("string-split", why="a range of lines typed by hand, `10-12`, whose two sides `int` reads and refuses otherwise")
    first, _, last = typed.partition("-")
    try:
        lines = Lines(first=int(first), last=int(last or first))
    except ValueError as unread:
        message = f"`{typed}` isn't a line, `10`, or a range of them, `10-12`"
        raise typer.BadParameter(message, param_hint="'--lines'") from unread
    if lines.first < 1 or lines.last < lines.first:
        message = f"`{typed}` counts lines from 1, the first no later than the last"
        raise typer.BadParameter(message, param_hint="'--lines'")
    return lines


def verb_command(
    verb: Verb, offered: Offered, parsing: Parsing, typed_in: TypedIn
) -> Callable[..., None]:
    """Return the function typer builds `lup <verb>` from: what's cited, the words said with it, and, where the verb runs a command with nothing cited, that command's own fields, keeping what's typed in `parsing`."""
    alone = offered.alone(verb.name)
    taken: list[Parameter] = (
        [] if alone is None else parameters(alone.doorway.input_schema)
    )
    cites = verb.name == SHOW or any(
        each.doorway.verb == verb.name and not each.doorway.alone
        for each in offered.runnable()
    )

    def parsed(
        lup_cite: str | None = None,
        lup_words: list[str] | None = None,
        lup_lines: str | None = None,
        lup_repository: str | None = None,
        *,
        lup_json: bool = False,
        **values: Parsed,
    ) -> None:
        parsing.data = lup_json
        parsing.verbing = Verbing(
            verb=verb.name,
            cite=lup_cite,
            words=lup_words or [],
            lines=None if lup_lines is None else ranged(lup_lines),
            repository=lup_repository,
            alone=sent(taken, values, typed_in) if lup_cite is None else {},
        )

    citing = (
        [
            inspect.Parameter(
                "lup_cite",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[
                    str | None,
                    typer.Argument(
                        metavar="THING",
                        help="What's cited: `@12`, `@dashboard-usable`, `@frictions/keys`.",
                        show_default=False,
                    ),
                ],
                default=None,
            ),
            inspect.Parameter(
                "lup_words",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[
                    list[str] | None,
                    typer.Argument(
                        metavar="WORDS",
                        help="What's said with it: a comment, a reason.",
                        show_default=False,
                    ),
                ],
                default=None,
            ),
            inspect.Parameter(
                "lup_lines",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[
                    str | None,
                    typer.Option(
                        "--lines",
                        help="The lines of it what's said quotes: `10`, or `10-12`.",
                        show_default=False,
                    ),
                ],
                default=None,
            ),
            inspect.Parameter(
                "lup_repository",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[
                    str | None,
                    typer.Option(
                        "-r",
                        "--repository",
                        help=(
                            "The repository it's in.  [left out: "
                            f"{typed_in.repository or 'none: name one'}]"
                        ),
                        show_default=False,
                    ),
                ],
                default=None,
            ),
        ]
        if cites
        else []
    )
    data = inspect.Parameter(
        "lup_json",
        inspect.Parameter.KEYWORD_ONLY,
        annotation=Annotated[
            bool,
            typer.Option(
                "--json", help="Print the answer's data as JSON, rather than its lines."
            ),
        ],
        default=False,
    )
    vars(parsed)["__signature__"] = inspect.Signature(
        [*(each.parameter(typed_in) for each in taken), *citing, data]
    )
    return parsed


def refusal(call: Call, reason: str) -> Acted:
    """Return the command line's own refusal of what `call` would have done, saying why."""
    return Acted(
        call=call,
        reply=Declined(rejection=Rejection(submitted=call.given, reason=reason)),
    )


async def acted(
    verbing: Verbing, offered: Offered, answerer: Answerer, typed_in: TypedIn
) -> Acted:
    """Do what `verbing` says: with nothing cited, run the command its verb runs alone; else read the block of what's cited, and show what it opens or run what it offers under the verb, given what's said with it."""
    if verbing.cite is None:
        alone = offered.alone(verbing.verb)
        call = CommandCalled(
            module="" if alone is None else alone.module,
            command=verbing.verb if alone is None else alone.doorway.name,
            given=verbing.alone,
        )
        if alone is None:
            return refusal(
                call, f"name what to {verbing.verb}: `lup {verbing.verb} @12`"
            )
        return Acted(call=call, reply=await answerer.answered(call))
    viewing = offered.cited()
    repository = verbing.repository or typed_in.repository
    asked = ViewCalled(
        module="" if viewing is None else viewing.module,
        view="" if viewing is None else viewing.doorway.name,
        given={"cite": verbing.cite, "repository": repository},
    )
    if viewing is None:
        return refusal(asked, "nothing here shows what's cited")
    if repository is None:
        return refusal(
            asked,
            f"{typed_in.directory} is in no repository's worktree: name it with `-r`",
        )
    shown = await answerer.answered(asked)
    if not isinstance(shown, Answered):
        return Acted(call=asked, reply=shown)
    blocks = Blocks.model_validate(shown.output)
    if verbing.verb == SHOW:
        return await opened(blocks, viewing, answerer, asked, shown)
    return await offering(verbing, blocks, viewing, offered, answerer, asked)


async def opened(
    blocks: Blocks,
    viewing: Runnable,
    answerer: Answerer,
    asked: ViewCalled,
    shown: Answered,
) -> Acted:
    """Show what `blocks`, the block of what's cited, open: the view a fold of it reads as it opens, where it's one such fold; else the blocks themselves, each of a text's lines numbered, as `--lines` counts them."""
    match blocks.blocks:
        case [Fold(content=Viewing() as reads)]:
            call = ViewCalled(
                module=reads.module or viewing.module,
                view=reads.view,
                given=reads.given,
            )
            return Acted(call=call, reply=await answerer.answered(call))
        case _:
            numbered = Blocks(
                blocks=[
                    line
                    for block in blocks.blocks
                    for line in (
                        counted(block) if isinstance(block, Markdown) else [block]
                    )
                ],
                summary=blocks.summary,
            )
            return Acted(
                call=asked,
                reply=shown.model_copy(
                    update={"output": numbered.model_dump(mode="json")}
                ),
            )


def counted(text: Markdown) -> list[Line]:
    """Return a text's lines, each after its number, set back, as `--lines` counts them from 1."""
    lines = text.text.splitlines()
    width = len(str(len(lines)))
    return [
        Line(
            id=f"{text.id}-{at}",
            spans=[
                Span(text=f"{at:>{width}}  ", tone="muted"),
                Span(text=line, tone=text.tone),
            ],
        )
        for at, line in enumerate(lines, start=1)
    ]


async def offering(
    verbing: Verbing,
    blocks: Blocks,
    viewing: Runnable,
    offered: Offered,
    answerer: Answerer,
    asked: ViewCalled,
) -> Acted:
    """Run what the block of what's cited offers under `verbing`'s verb, given what the block gives it and what's said with it; refused where it offers nothing under that verb, or the command takes no words and some were said."""
    first = next(iter(blocks.blocks), None)
    offers = [] if first is None else first.offers
    offer = next((each for each in offers if each.verb == verbing.verb), None)
    if offer is None:
        verbs = ", ".join(dict.fromkeys(each.verb for each in offers)) or "nothing"
        return refusal(
            asked, f"{verbing.cite} offers no {verbing.verb}: it offers {verbs}"
        )
    module = offer.module or viewing.module
    command = offered.offered(module, offer.command)
    call = CommandCalled(module=module, command=offer.command, given=offer.given)
    if command is None:
        return refusal(call, f"{verbing.cite}'s {verbing.verb} isn't yours to run")
    words = " ".join(verbing.words)
    if verbing.verb == TELL:
        if not words:
            return refusal(call, f'say something: `lup {TELL} {verbing.cite} "…"`')
        texts = [each for each in blocks.blocks if isinstance(each, Markdown)]
        lines = next(iter(texts), Markdown(id="", text="")).text.splitlines()
        quoted = (
            []
            if verbing.lines is None
            else lines[verbing.lines.first - 1 : verbing.lines.last]
        )
        given: JsonObject = {
            "words": words,
            "lines": list[JsonValue](quoted),
            "on": offer.given,
        }
    else:
        takes = next(
            (each for each in parameters(command.doorway.input_schema) if each.said),
            None,
        )
        if words and takes is None:
            return refusal(
                call,
                f"{verbing.verb} on {verbing.cite} takes no words: say them with `{TELL}`",
            )
        given = (
            {**offer.given, takes.key: words}
            if takes is not None and words
            else offer.given
        )
    made = call.model_copy(update={"given": given})
    return Acted(call=made, reply=await answerer.answered(made))
