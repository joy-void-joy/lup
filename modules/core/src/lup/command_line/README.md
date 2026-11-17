# The command line

One command line for developing with lup, the one universal interface: `lup <module> <name> …` runs any of a module's tools, commands and views by name, as whoever types it may. A project's own command (`harmon …`) is the same command line over the project's modules. Its library side (`lup.command_line`) is what typing does: parsing words into a call that crosses (`lup.running.wire`), handing it to an answerer, and printing the reply. Answering in this process, `lup`'s own script and a project's are the environment's (`lup.environment.command_line`).

## Typing

`lup jot jot-down "milk" --tags=shop --loud` runs the method `jot_down` of the module `jot`: a method's `_` is a `-`, typer's way. The fields of the model it takes are its arguments and options:
- a field with no default is an argument;
- one with a default is an option, named for its alias, else its name (`--dry-run` for `dry_run`), left out where it isn't given, so the model's own default applies;
- a `bool` is a flag, a `list` is repeated (`--tags=a --tags=b`), and a field limited to some words takes one of them;
- a field a word can't say (a model, a mapping) is written as JSON;
- a field's docstring is its help, as it's its description in the model's JSON Schema (`lup.types`), and the method's docstring is the command's.

A command takes everything as arguments: one missing is refused as the words are read, nothing runs, and nothing is ever asked for, so an agent or a test typing it fails rather than hangs. Words starting with `-` that aren't options go after `--`.

What a run prints: a view's text (`Blocks.text`), what the operator sees said in lines; a tool's or a command's answer, words as they are and a model as its JSON; a refusal's reason, on standard error. Its exit status is 0 where it ran or showed help, 1 where the call was refused, and 2 where the words didn't parse.

## Who calls, and what they may run

Who calls isn't the command line's to say. It hands each call to an answerer (`Answerer`), which says who the calls are by and offers the project's plan (`offered`), then sends each call and returns its reply (`answered`). The call itself carries no `by`: whoever carries it adds one. The command line offers, and `--help` lists, only what the plan's doorways let that party call: the operator's commands in their terminal, an agent's tools and the commands and views their `by` admits in their room. `lup --help` lists the modules with something the party may run, and `lup <module> --help` lists those methods.

Its help is typer's rich layout where it prints to a terminal, as the operator's command line does, and plain where its output is piped, as an agent's always is.

It builds its parser from the plan alone, the JSON Schema of what each method takes (`lup/running/README.md`, *The plan*), never from the modules' code. That lets the program on the operator's machine answer a terminal there from a plan made in a container, so a branch's code never runs on the operator's machine to say what may be typed. Only the module named is built, so help and a run cost what one module's methods do.

## Answering in this process

`InProcess` answers over the project's parts, started here at the first call (help starts nothing) and stopped once the call is answered. Each call is answered as their container answers it (`lup.environment.running.container.answered`), by the party whoever made the answerer names. It starts the parts that hold nothing beyond secrets, every one of which is given. A call to any other part is refused, saying which secret it needs or that it runs apart, from approved code, through lup's program on the operator's machine.

## `lup`

`lup` is the core's script. It reads the declaration of the worktree it runs in with its layers (`RepositoryLayout.found`, `lup.environment.declaration.read`) and answers in this process, as the operator, until lup's program on the operator's machine answers a room and the operator's terminal (#3). Bare `lup` will open the dashboard (#7); until then it shows the help.

## A project's own command

A project names its command in its `[project.scripts]`, on its environment side, since it imports `lup.environment`:

```python
# harmon/environment/command_line.py
from lup.environment.command_line import command_line

from harmon import Harmon
from lup_discord import Discord

main = command_line("harmon", Discord(), Harmon())
```

Whoever installs the project gets a plain command: lup's default modules and those given, answered in this process by whoever runs it (`Operator`). Each secret a part holds is read from the environment variable named after the command and the secret, in capitals, each `-` a `_` (`HARMON_TOKEN`), or a line of `.env` or `.env.local` in the current directory setting it; the environment wins over `.env.local`, which wins over `.env`. In development, where one of the modules given is code that a worktree holding a declaration tracks, the command reads that declaration with its layers instead, so it offers what the dashboard does. It goes by where the code lives, never the current directory, so an installed command run inside another project's worktree never reads that project's declaration.

## Promises

`promises.py`, through the harness, whose `Started.typed(words, by)` types on `lup` as a party does and answers what it did (`Typed`): what its help listed, the call it made, what it printed and how it ended. The call goes through the harness's doors, every law checked over it. A promise checks those, never the words of help or of a refusal.
