# The doors

What a module's methods are reached through. A module is made of parts, classes deriving from `Part` it lists in its `parts` field; each part puts its methods behind doors, each door saying who calls the method, what it takes and what it returns, and is made once where it runs:

```python
import lup
from lup import Agent, Model, Module, Operator, Part, Parts, Secret


class Said(Model):
    """What to post."""

    text: str


class Bot(Part):
    """The bot, connected as long as it runs."""

    module: Chat
    token: Secret
    posted: int = 0

    @lup.on(lup.Starting)
    async def connect(self, starting: lup.Starting) -> None:
        """Connect, and stay connected while the part runs."""
        await connected(self.token.value)

    @lup.service
    async def post(self, said: Said) -> None:
        """Post what's said."""
        self.posted += 1

    @lup.tool
    async def say(self, said: Said, by: Agent) -> str:
        """Say something, as the bot."""
        await self.post(said)
        return "sent"


class Commands(Part):
    """What the operator runs."""

    @lup.command
    async def announce(self, said: Said, by: Operator) -> str:
        """Announce something, through the bot."""
        await Bot.post(said)
        return said.text


class Chat(Module):
    """Talking in a channel."""

    name = "chat"
    parts: Parts = Parts.of(Bot, Commands)
```

Its library side (`lup.doors`, re-exported by `lup`) is what a module's code imports; resolving what the modules serve, starting it, and calling through a door is the environment's (`lup.environment.doors`), which nothing on the library side imports.

## The doors

| Door | Who calls it | It takes | It returns | Who may call it, unsaid |
|---|---|---|---|---|
| `@lup.tool`, `@lup.tool(reads=True, idempotent=True)` | an agent, through MCP | a model, its arguments | a model, or `str` | `Agent` |
| `@lup.service` | code, as a plain call | a model | a model, `str`, or nothing | `Codebase` |
| `@lup.command`, `@lup.command(verb=…, says=…)`, `@lup.command(here=True)` | whoever runs the command line, and, given a verb, the operator's key on what a view offers | a model, its fields the arguments and options, or, given a verb, a list of it, every mark of a send | a model, `str`, or nothing | nobody: it says |
| `@lup.on(Event)` | lup, at the event | the event | nothing | nobody calls it |

A door exists only where the contract differs: who calls a method, what it takes, what it returns. A module's promises are behind a door of their own too, `@lup.promise`, which the harness checks (`lup/testing/README.md`).
- **A tool's name is its method's,** and its docstring's first line, standing alone, is its summary, 50 characters at most, which a session that searches for tools lists. Its marks say whether a call may be sent again: `reads`, it changes nothing; `idempotent`, a call sent again adds nothing (MCP's hints).
- **A service is called as a plain call,** read through its part's class: `await Bot.post(said)` runs where the part runs, its own container where it holds something, the project's otherwise, carried there by lup (`CARRYING`, set wherever lup runs a module's code). A refusal raises `RefusedError` at the caller, as a plain call's failure would; outside lup, the call raises `UncarriedError`. Read through an instance, as the part's own code reads it, it's that instance's method.
- **A command is one door for what someone does, wherever it's offered:** the command line runs it by its name, and one given a `verb` is also what that key does on what a view offers it, the line of keys saying what it `says`. Who may run it is its `by` alone, checked before every run wherever it's run from, so a command for the operator alone refuses an agent running it in their room; where it's offered is a setting, not a door of its own. It takes everything as arguments, so one run without an argument it needs is refused at once rather than waiting on input that may never come, and an agent or a test running it fails rather than hangs. One taking a list of its model, every mark of a send, is given one from the command line. One that acts on the worktree it's typed in, as the gate runs a branch's own checks, says `here=True`: `lup` answers it in its own process, over that worktree's declaration, by the party lup's program on the machine names, rather than carrying it to where the project runs, which runs the commit the operator approved and never sees the worktree (`lup/command_line/README.md`, *Who calls, and what they may run*). It's the command line's alone, so it takes no `verb`.
- **A hook runs at an event** (`lup.doors.events`). The core's are a part's own: `Starting`, as it's made where it runs, where a method may go on as long as the part runs, and `Stopping`, before it stops, after which what it started is cancelled. A part's code fires an event of its project's own, one whose class says `fired`, with `await lup.heeded(event)`: every part of the project hearing it is told it, wherever each runs, and what they answered comes back, their words and the first refusal (`Heeded`); an event only lup tells, a session's, is refused. A session's are `lup.sessions.events`, carried to every part hearing them wherever it runs (`lup/sessions/README.md`). An event that says it's `answered` takes a method returning words (`str | None`), told to whoever it's about beside it, or raising `RefusedError` to refuse what it's about; what all its methods answered is `Heeded`.

## A method behind a door

A method is async, takes `self`, one model, then `by` where it needs who calls it, says what it returns, and has a docstring, which describes it to whoever its door brings. One taking `by` alone, or nothing, takes no model, and only a door of that shape takes it, as a promise's scenario and a section of guidance are. It's behind one door, in a part: a door on a method of any other class, which nothing would serve, fails as the class is made. Each door is a decorator typed with its contract, so pyright holds the method to it, and it checks the method again as it's put on, for code pyright doesn't hold: a failure names the method, and fails the declaration's load.

A door reads the method's annotations at run time. Where one names a class defined further down its file, as Python allows, what needs that type is checked once the declaration resolves, which reads every method its modules serve. A name imported under `TYPE_CHECKING` alone is never defined where a door reads it, so ruff is told the doors are runtime-evaluated decorators (`pyproject.toml`), and steers such an import out of that block.

Read through its class, a method is a `Method`, saying its door and what it takes, but a service, which is its plain call (`Reach`, whose `method` is the `Method`); read through an instance, it's that instance's method, called as any and typed as written (`await part.shout(said, by=agent)`). Adding a door is adding a class deriving from `Door` (`door.py`): its settings as fields, what it holds a method to (`contract`), who may call a method leaving `by` out (`default`), whether its methods' names are shared across every module (`named_across`), and a `__call__` typed with its contract; a door whose methods take another shape than one model then `by` says so too (`shaped`), as the promise's door does, taking an invariant that isn't async.

## Who calls

A method's `by` is typed as the parties who may call it, `by: Agent` or `by: Agent | Operator`, and is handed the one calling. A party is a class deriving from `Party`, which any module may declare; the core's are `Agent`, an agent, identified by lup's id for them and the session they're in, `Operator`, and `Codebase`, a project's own code, identified by its repository. Whoever carries a call vouches for its caller from where the call came, never what the caller says of itself: a service called from a part's method is by its project's `Codebase`, and a program in a session's room calls for that session's agent, or a subagent of that session it names (`Agent.of`), never another session's, so a service it may call says `by: Agent | Codebase`. Left out, a method may be called by its door's default parties; a command has none, so each says who may run it. Who calls is checked as the door is put on, `by` naming parties' classes alone, and again before each call.

## Parts

A part's class declares `module`, typed as its module's class (`module: Echo`), where its methods read the module's settings, every layer applied; it may name the module before the module is defined. Its other fields are what it keeps while it runs, each with a default, since lup makes it with its module and its secrets alone: it's made once where it runs, as its container starts, and lives as long as that does. What must outlast it, or be read by others, goes in the core's store. A field with no default, or a method named as one of its fields, which the field would hide, fails as the class is defined, but for what lup gives where it makes the part: a field typed `Data` is a directory it keeps what it writes in, kept across its restarts; one typed `Runtime` a directory in memory, for what lasts only while it runs, a socket or a value handed over to be read once, gone when the machine restarts. A field typed `Declared` holds the project's every module, every layer applied, in the declaration's order, for a part reading what every module declares of a kind (`self.declared.held(Steps)`), as the gate reads each module's steps: a part is otherwise given its own module alone. A field typed `Program`, its default saying which, is a program the part runs from outside its project's environment, through the field (`await self.podman.ran(…)`, from the directory `cwd=` names, else where the part runs), never through `lup.programs` itself, so a promise stands it in. It's checked before the part is made (`Program.checked`): where it isn't there, or isn't at a version the part takes, an optional one keeps its part from being made, the others starting, a call to it refused naming the program in its `about`, and any other refuses the start, saying how to install it. Where a part runs in a container, its image installs the package each of its programs names (`Program(name="gh", package="github-cli")`), so a part says once what it runs and its image follows.

**What a part holds says where it runs.** A field typed `Secret` is a secret it holds, filled where it runs with the value the operator stored under the field's name, and never shown or written out with the part. What the operator's machine lends a part acting for agents with their credentials is a field too, each filled as the part's container starts (`lup/hosting/README.md`, *Lending*): `GitDirectory`, the project's common git directory, read-write but its `config` and `hooks/`; `SshAgent`, the operator's SSH agent, with their ssh configuration read-only and no key of theirs readable; and `GitHubLogin`, their GitHub login, as `gh auth token` prints it on their machine. `machine=True` in its header runs it on the operator's machine itself, and `approved=True` says it holds something else only approved code may, as the store holds the operator's acts (`Part.holds`). A part holding nothing runs in its project's container; one holding anything runs in a container of its own, from a commit the operator approved, with what it holds alone, or on the machine. `room=True` runs a part holding nothing in each session's own room instead, made from the worktree's own code, so it sees the worktree as it stands, uncommitted files and environment among it: the room is the wall already.

A module lists its parts in `parts`, a selection (`Parts`) naming each by its class's name: a project drops one with `Echo(parts=Parts().drop("EchoPart"))`. Resolving a declaration (`lup.environment.declaration.resolve`) lists every part each module serves (`Resolved.doors`), and refuses:
- a part whose `module` is typed as another module's class, which can't be made with the module listing it;
- a method that can't be behind its door, once every class its annotations name is defined;
- a name two methods behind one kind of door share: across modules where the door names its methods so (`Door.named_across`), as an agent names a tool and code a service without its module, else within a module, which names them, naming both.

## Starting, calling and stopping

`Doors.started(repository, secrets)` makes each part once, with its module and the value of each secret it holds, refusing one whose secret isn't given, and runs each method at `Starting` as a task that goes on as long as the part runs: the parts `Running`, as `repository`'s code. `tools()` says what a session is told of each tool; `call(tool, arguments, by)`, `serve(service, given, by)` and `run(module, command, arguments, by)` find the method, check who calls, read what's given as the model it takes, and run it on its part. Each answers `Accepted`, with what was given, as its model, and what the method answered, or `Refused`, with what was sent, why, and what it's about by name (`Rejection.about`, which a caller reads rather than the words): no such method, a caller it isn't for, what it doesn't take, or the method raising `RefusedError`, whose `about` it carries. Nothing a caller sends makes a call raise, so whatever relays a call relays a refusal rather than catching errors; what a method raises otherwise goes up as raised. A service a part's method calls is carried to the part serving it, here, by the project's `Codebase`. `stopped()` runs each method at `Stopping`, one after another, then cancels what each part started, and waits for it.
