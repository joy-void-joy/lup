# The doors

What a module's methods are reached through. A module groups its methods in classes deriving from `ModuleServing`, lists them in its `serving` field, and puts each method behind one door, which says who calls it, what it takes and what it returns:

```python
import lup
from lup import Agent, Model, Module, ModuleServing, Operator, Serving


class Said(Model):
    """What to shout."""

    text: str


class EchoServing(ModuleServing):
    """Echo's methods."""

    module: Echo

    @lup.tool(reads=True)
    async def shout(self, said: Said, by: Agent) -> str:
        """Shout what you're told."""
        return said.text.upper() * self.module.volume

    @lup.command
    async def echo(self, said: Said, by: Operator) -> str:
        """Print what's said back."""
        return said.text


class Echo(Module):
    """Shouting what it's told."""

    name = "echo"
    volume: int = 1
    serving: Serving = Serving.of(EchoServing)
```

Its library side (`lup.doors`, re-exported by `lup`) is what a module's code imports; resolving what the modules serve and calling through a door is the environment's (`lup.environment.doors`), which nothing on the library side imports.

## The doors

| Door | Who calls it | It takes | It returns | Who may call it, unsaid |
|---|---|---|---|---|
| `@lup.tool`, `@lup.tool(reads=True, idempotent=True)` | an agent, through MCP | a model, its arguments | a model, or `str` | `Agent` |
| `@lup.action(verb=…, says=…)` | the operator's key, on what a view offers | a model, or a list of it, every mark of a send | a model, `str`, or nothing | `Operator` |
| `@lup.command` | whoever runs the command line | a model, its fields the arguments and options | `str`, the text it prints | nobody: it says |

A door exists only where the contract differs: who calls a method, what it takes, what it returns. A module's promises are behind a door of their own too, `@lup.promise`, which the harness checks (`lup/testing/README.md`).
- **A tool's name is its method's,** and its docstring's first line, standing alone, is its summary, 50 characters at most, which a session that searches for tools lists. Its marks say whether a call may be sent again: `reads`, it changes nothing; `idempotent`, a call sent again adds nothing (MCP's hints).
- **An action** names the `verb` whose key reaches it, and what the line of keys `says` it does.
- **A command takes everything as arguments,** so one run without an argument it needs is refused at once rather than waiting on input that may never come, and an agent or a test running it fails rather than hangs.

## A method behind a door

A method is async, takes `self`, one model, then `by` where it needs who calls it, says what it returns, and has a docstring, which describes it to whoever its door brings. One taking `by` alone takes no model, and only a door of that shape takes it, as a promise's scenario is. It's behind one door. Each door is a decorator typed with its contract, so pyright holds the method to it, and it checks the method again as it's put on, for code pyright doesn't hold: a failure names the method, and fails the declaration's load.

A door reads the method's annotations at run time. Where one names a class defined further down its file, as Python 3.14 allows, what needs that type is checked once the declaration resolves, which reads every method its modules serve. A name imported under `TYPE_CHECKING` alone is never defined where a door reads it, so ruff is told the doors are runtime-evaluated decorators (`pyproject.toml`), and steers such an import out of that block.

Read through its class, a method is a `Method`, saying its door and what it takes; read through an instance, it's that instance's method, called as any and typed as written (`await serving.shout(said, by=agent)`). Adding a door is adding a class deriving from `Door` (`door.py`): its settings as fields, what it holds a method to (`contract`), who may call a method leaving `by` out (`default`), and a `__call__` typed with its contract; a door whose methods take another shape than one model then `by` says so too (`shaped`), as the promise's door does, taking a law that isn't async.

## Who calls

A method's `by` is typed as the parties who may call it, `by: Agent` or `by: Agent | Operator`, and is handed the one calling. A party is a class deriving from `Party`, which any module may declare; the core's are `Agent`, an agent, identified by lup's id for them, and `Operator`. Left out, a method may be called by its door's default parties; a command has none, so each says who may run it. Who calls is checked as the door is put on, `by` naming parties' classes alone, and again before each call.

## What a module serves

A `ModuleServing` class narrows `module` to its module's class (`module: Echo`), so its methods read the module's settings with their types; it may name the module before the module is defined. It holds nothing else: it's made afresh, with its module, for each call, so a field of its own fails as it's defined, and what it's set with goes in its module's fields. What a method reaches outside its module, it reaches through another door, so a module's code imports `lup` alone.

A module lists its classes in `serving`, a selection (`Serving`) naming each by its class's name: a project drops one with `Echo(serving=Serving().drop("EchoServing"))`. Resolving a declaration (`lup.environment.declaration.resolve`) lists every class each module serves (`Resolved.doors`), and refuses:
- a class narrowed to another module's class, which can't be made with the module listing it;
- a method that can't be behind its door, once every class its annotations name is defined;
- a tool's name two methods share across modules, since an agent names it without the module, naming both;
- an action's or a command's name two methods share within a module, which names them.

## Calling through a door

`Doors` is how the harness and the services reach a module's methods. `tools()` says what a session is told of each tool served; `call(tool, arguments, by)`, `act(module, action, given, by)` and `run(module, command, arguments, by)` find the method, check who calls, read what's given as the model it takes, and run it on its class made afresh. Each answers `Accepted`, with what was given, as its model, and what the method answered, or `Refused`, with what was sent and why: no such method, a caller it isn't for, what it doesn't take, or the method raising `RefusedError`. Nothing a caller sends makes a call raise, so a service relays a refusal rather than catching errors; what a method raises otherwise goes up as raised.
