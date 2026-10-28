"""A module's commands on the command line, `lup-dev <module> <command> …`: each `@lup.command` method and each view, built with typer from its method and run in the terminal's own process.

`docs/declaration.md`, *Commands*. Typer prints help and errors to its
process's standard output, with no stream of a command's own, so a module's
command runs in the process its words were typed in, never in the repository's
process, which serves every session at once:
- on the host, the installed `lup-dev` hands it over to the repository's
  approved copy (`handed_over`), so only code the operator approved runs a
  project's module there, and it runs as the operator (`Operator`);
- in a room, the room's own `lup-dev` runs it from the worktree's declaration,
  which the room contains, as the room (`Room`).

Each command is built from its method's model (`signature`): a field with no
default an argument, one with a default an option named for its alias, else
its name, its description the help; the method's docstring the command's. A
view's command prints its text form (`Blocks.text`).
"""

import asyncio
import inspect
import os
from functools import reduce
from pathlib import Path
from types import UnionType
from typing import TYPE_CHECKING, NoReturn, TypeAliasType, get_args, override

import typer

from lup.blocks import Blocks, OfAgent
from lup.doors import Method, served
from lup.types import Model
from lup_dev.declaration.serving import Asker, ModuleServing, ask
from lup_dev.errors import LupDevError
from lup_dev.host.client import RoomClient
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.protocol import Exchanged, ListItems
from lup_dev.inbox.store import Conversation as Party

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel
    from pydantic.fields import FieldInfo

    from lup_dev.declaration.resolve import Served


class CommandError(LupDevError):
    """A module's command can't run: no module of the repository has its name, or nothing approved runs it on the host."""


def unaliased[T](annotation: T) -> T:
    """Return `annotation` with each type alias in it, whole or one of a union's, as the type it names: typer knows no alias, so a field typed `Format | None`, `type Format = Literal[…]`, would stop the module's every command.

    >>> from typing import Literal
    >>> type Shade = Literal["dark", "light"]
    >>> unaliased(Shade | None) == (Literal["dark", "light"] | None)
    True
    """
    match annotation:
        case TypeAliasType():
            return unaliased(annotation.__value__)
        case UnionType():
            parts = [unaliased(each) for each in get_args(annotation)]
            return reduce(lambda left, right: left | right, parts)
        case _:
            return annotation


def parameter(name: str, field: FieldInfo) -> inspect.Parameter:
    """Return the typer parameter a model's field is on the command line: an argument where it has no default, else an option named for its alias, else its name, its description the help; its type with no alias in it (`unaliased`)."""
    if field.is_required():
        given = typer.Argument(..., help=field.description, show_default=False)
    else:
        named = [f"--{field.alias}"] if field.alias else []
        given = typer.Option(
            field.get_default(call_default_factory=True),
            *named,
            help=field.description,
        )
    return inspect.Parameter(
        name,
        inspect.Parameter.KEYWORD_ONLY,
        annotation=unaliased(field.annotation),
        default=given,
    )


def signature(model: type[BaseModel]) -> inspect.Signature:
    """Return the command line a model's fields make, each a typer parameter (`parameter`), in their order."""
    return inspect.Signature(
        [parameter(name, field) for name, field in model.model_fields.items()]
    )


def command(
    method: Method,
    owner: Served,
    made: Callable[[Served], ModuleServing],
    asker: Callable[[], Asker],
) -> Callable[..., None]:
    """Return `method`, of `owner`'s class, as a typer command run by whoever `asker` says: the values parsed into its model, the method run on it, and the text it returns printed, a view's text form for a view.

    Who runs it, and whether they may (`ask`), is found as it runs, so `--help`
    asks nothing and lists what they can't run.
    """
    model = method.taken.model.annotation

    # lup: ignore("bare-object", why="typer hands each value its parameter parsed, of the type its field gives, which the model validates at once")
    def run(**values: object) -> None:
        by = asker()
        ask(owner.serving, method.taken.name, by)
        asked = model.model_validate(values, by_name=True)
        answer = asyncio.run(method.called(made(owner), asked, by))
        text = answer.text() if isinstance(answer, Blocks) else str(answer)
        typer.echo(text, nl=not text.endswith("\n"))

    vars(run)["__signature__"] = signature(model)
    return run


def commands(
    module: str,
    owners: list[Served],
    made: Callable[[Served], ModuleServing],
    asker: Callable[[], Asker],
) -> typer.Typer:
    """Return the commands of the module named `module`: each `@lup.command` method of its classes, and each view, under its method's name.

    Raise `CommandError` where no class of the repository's is the module's.
    """
    its = [owner for owner in owners if owner.module.name == module]
    if not its:
        named = sorted(dict.fromkeys(owner.module.name for owner in owners))
        message = (
            f"no module of this repository is `{module}`, and lup-dev has no such "
            f"command: its modules are {', '.join(named) or 'none'}"
        )
        raise CommandError(message)
    app = typer.Typer(
        no_args_is_help=True, help=type(its[0].module).__doc__, add_completion=False
    )
    for owner in its:
        for name, method in served(owner.serving).items():
            if method.commanded() or method.viewing() is not None:
                app.command(name, help=method.taken.description)(
                    command(method, owner, made, asker)
                )
    return app


def run(
    words: list[str],
    owners: list[Served],
    made: Callable[[Served], ModuleServing],
    asker: Callable[[], Asker],
) -> None:
    """Run the module command `words` names, its module's name first, as whoever `asker` says once it runs: typer parses the rest, and prints."""
    module, *rest = words
    app = commands(module, owners, made, asker)
    app(args=rest, prog_name=f"lup-dev {module}")


# lup: defer(issue=298, why="a module's command handed over to the approved copy by an exec, watched for the friction a process per command brought before")
def handed_over(words: list[str], command: Path | None, repository: Path) -> NoReturn:
    """Hand the module command `words` names over to the repository's approved copy, its `command`, on the host: this process becomes it, same words, same terminal.

    The copy knows it's the one to run it by its own path, `command` (`approved`).
    Raise `CommandError` where nothing is approved for the repository.
    """
    if command is None:
        message = (
            f"nothing is approved for {repository}, so its modules' commands don't "
            "run on the host: `lup-dev trust` approves it"
        )
        raise CommandError(message)
    # lup: ignore("os-shell", why="the agreed hand-over: this process becomes the approved copy, the terminal and the exit status its own, which a child process lup.programs runs would sit between")
    os.execv(command, [str(command), *words])


def approved(running: Path, command: Path | None) -> bool:
    """Say whether the `lup-dev` running, by the path it was started as, is the repository's approved copy, its `command`, which runs a module's command itself rather than handing it over."""
    return command is not None and running.resolve() == command.resolve()


class RoomExchanges(Model, Exchanges, arbitrary_types_allowed=True):
    """The items of lup's inbox a conversation exchanged, as a room's command reads them: from the host service, on the launch's request socket, for its repository alone."""

    room: RoomClient
    repository: Path
    """The repository's git directory, at its host path, as the room sees it."""

    @override
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        """Ask the host service as `inbox-list-items` is asked from a room, off the event loop."""
        conversation = Party(
            repository=self.repository,
            runtime=viewed.runtime,
            session=viewed.session,
            agent=viewed.agent,
        )
        return await asyncio.to_thread(
            self.room.ask, ListItems(conversation=conversation), Exchanged
        )
