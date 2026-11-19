"""The command line: words typed parsed into a call through a door, handed to an answerer, and its reply printed.

`<name> <module> <method> …` runs a module's tool, command or view by its
method's name, typer's way (`-` for `_`), the fields of the model it takes its
arguments and options (`lup.command_line.parameters`); the methods of the one
module a command line puts at its top level are typed without its name, as
`lup`'s core's are (`lup init`). What it offers, and parses words for, is what
the answerer's plan lets the party it names call; `--help` lists that alone,
and a module only where it has some. A command takes everything as arguments:
one missing is refused as the words are parsed, and nothing runs; nothing is
ever asked for. Only the module named is built, and the top level's where no
other module is named, so help and a run cost what one module's methods do.

A view's run prints its text (`Blocks.text`); a tool's or a command's, what it
answered, words as they are and a model as JSON; a refusal, why, on standard
error. The exit status says which: 0 where it ran or showed help, 1 where the
call was refused, 2 where the words didn't parse.
"""

import inspect
import io
from contextlib import redirect_stderr, redirect_stdout
from itertools import takewhile
from typing import TYPE_CHECKING, TextIO

import typer
from pydantic_core import to_json
from typer.main import get_command

from lup.command_line.answering import Answerer, Offered, Runnable, Typed
from lup.command_line.parameters import Parameter, Parsed, parameters, sent
from lup.running.wire import (
    Answered,
    Call,
    CommandCalled,
    Declined,
    ServiceCalled,
    ToolCalled,
    ViewCalled,
)
from lup.shell.blocks import Blocks
from lup.types import MutableModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import JsonValue
    from typer.core import MarkupMode


class Parsing(MutableModel):
    """What parsing the words came to: the call they make, once a method's command takes them."""

    call: Call | None = None


def called(runnable: Runnable, given: JsonValue) -> Call:
    """Return the call `runnable` is made by, given `given`: saying nobody makes it, which only whoever carries it says."""
    way = runnable.doorway
    match way.door:
        case "tool":
            return ToolCalled(tool=way.name, given=given)
        case "service":
            return ServiceCalled(service=way.name, given=given)
        case "command":
            return CommandCalled(module=runnable.module, command=way.name, given=given)
        case "view":
            return ViewCalled(module=runnable.module, view=way.name, given=given)


def command(runnable: Runnable, parsing: Parsing) -> Callable[..., None]:
    """Return the function typer builds `runnable`'s command from: its signature the fields of what it takes, and its body keeping the call they make in `parsing`, made once parsing is done."""
    taken: list[Parameter] = parameters(runnable.doorway.input_schema)

    def parsed(**values: Parsed) -> None:
        parsing.call = called(runnable, sent(taken, values))

    vars(parsed)["__signature__"] = inspect.Signature(
        [each.parameter() for each in taken]
    )
    return parsed


def modules() -> None:
    """Run a module's tool, command or view by its name, the fields of what it takes its arguments and options."""


def grouped(offered: Offered, top: str | None) -> list[str]:
    """List the modules typed by their name: each with something the party may call, but the one at the top level, named `top`."""
    return [each for each in offered.modules() if each != top]


def built(
    name: str,
    offered: Offered,
    module: str | None,
    parsing: Parsing,
    markup: MarkupMode = None,
    *,
    top: str | None = None,
) -> typer.Typer:
    """Return the command line `offered` makes, called `name`: each method of the module named `top` its party may call, at the top level, and each other module with something they may call, by its name, with each method they may call of the one named `module`, each command keeping the call it parses in `parsing`.

    The top level's methods are built only where `module` names no other
    module. Its help is plain, or, with `markup`, typer's rich layout,
    docstrings read as that markup.
    """
    line = typer.Typer(
        name=name,
        add_completion=False,
        pretty_exceptions_enable=False,
        rich_markup_mode=markup,
    )
    line.callback()(modules)
    runnable = offered.runnable()
    groups = grouped(offered, top)
    if module not in groups:
        for one in runnable:
            if one.module == top:
                line.command(one.doorway.typed(), help=one.doorway.description)(
                    command(one, parsing)
                )
    for each in groups:
        methods = typer.Typer(
            help=offered.described(each) or None,
            add_completion=False,
            rich_markup_mode=markup,
        )
        if each == module:
            for one in runnable:
                if one.module == each:
                    methods.command(one.doorway.typed(), help=one.doorway.description)(
                        command(one, parsing)
                    )
        line.add_typer(methods, name=each)
    return line


def reached(words: list[str]) -> list[str]:
    """Return the words `words` start with before an option: the module they name, then the method, then its arguments.

    >>> reached(["notes", "clear", "3"]), reached(["notes", "--help"]), reached(["--help"])
    (['notes', 'clear', '3'], ['notes'], [])
    """
    return list(takewhile(lambda word: not word.startswith("-"), words))


def listed(offered: Offered, named: list[str], top: str | None) -> list[str] | None:
    """Return what the help shown where `named` reaches lists, as each is typed: at the top, the methods of the module named `top` and the other modules; under a module, its methods; none for a method's own."""
    groups = grouped(offered, top)
    match named:
        case []:
            return [
                *(
                    each.doorway.typed()
                    for each in offered.runnable()
                    if each.module == top
                ),
                *groups,
            ]
        case [module] if module in groups:
            return [
                each.doorway.typed()
                for each in offered.runnable()
                if each.module == module
            ]
        case _:
            return None


def said(output: JsonValue) -> str:
    """Return what a tool or a command answered as it's printed: words as they are, nothing as nothing, and anything else as JSON."""
    match output:
        case str():
            return output
        case None:
            return ""
        case _:
            return to_json(output).decode()


def printed(call: Call, output: JsonValue) -> str:
    """Return what's printed of what `call` answered: a view's text, else what it answered (`said`), a line ended."""
    text = (
        Blocks.model_validate(output).text()
        if isinstance(call, ViewCalled)
        else said(output)
    )
    return text if not text or text.endswith("\n") else f"{text}\n"


async def typed(
    words: list[str],
    answerer: Answerer,
    name: str,
    out: TextIO | None = None,
    error: TextIO | None = None,
    *,
    top: str | None = None,
) -> Typed:
    """Run the command line called `name` on `words`, its calls handed to `answerer`, and say what it did.

    The methods of the module named `top` are typed at its top level, without
    its name, as `lup`'s core's are; every other module's under its name.
    What it prints goes to `out` and `error`, or, where they're left out, is
    kept in what it answers. Typer's own help and messages are written to
    them as it parses: in typer's rich layout where `out` is a terminal, as
    the operator's is, and plain where it's piped, as an agent's always is.
    """
    offered = await answerer.offered()
    # lup: defer(issue=7, why="`lup` alone opens the dashboard, which is #7's: until then it shows the help")
    asked = words or ["--help"]
    named = reached(asked)
    if len(asked) == 1 and named in [[each] for each in grouped(offered, top)]:
        asked = [*asked, "--help"]
    kept_out, kept_error = io.StringIO(), io.StringIO()
    printing = out or kept_out
    erring = error or kept_error
    parsing = Parsing()
    markup: MarkupMode = "markdown" if printing.isatty() else None
    module = named[0] if named else None
    line = get_command(built(name, offered, module, parsing, markup, top=top))
    with redirect_stdout(printing), redirect_stderr(erring):
        try:
            line.main(args=asked, prog_name=name, standalone_mode=True)
            status = 0
        except SystemExit as ended:
            status = ended.code if isinstance(ended.code, int) else 1
    call = parsing.call
    if call is None:
        return Typed(
            status=status,
            output=kept_out.getvalue(),
            error=kept_error.getvalue(),
            listed=listed(offered, named, top) if status == 0 else None,
        )
    reply = await answerer.answered(call)
    match reply:
        case Answered(output=output):
            printing.write(printed(call, output))
            status = 0
        case Declined(rejection=rejection):
            erring.write(f"{name}: {rejection.reason}\n")
            status = 1
    return Typed(
        status=status,
        output=kept_out.getvalue(),
        error=kept_error.getvalue(),
        call=call,
        reply=reply,
    )
