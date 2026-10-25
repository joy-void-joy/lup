# The declaration: what a project declares in `lup_project.py`

A project says what lup does for it in one file, `lup_project.py` at its root: a `Project` holding the modules it's made of. Every part a project can change (path roles, code rules, gate steps, guidance, the room's packages, session settings, the limits on the operator's credentials, a module's tools, requirements) comes from a selected module, lup's own included, so a module brings what it needs and takes it away when it's dropped (`DESIGN.md`, *Modules*). What every project gets alike, such as the inbox's and the judge's tools and the host's own requirements, is the host service's. The code is in `lup_dev/declaration/`.

A word on words: a **module** here is a `Module` (`Core`, `Python`); a Python source file is a **file**.

## An example

lup's own declaration, abridged (`lup_project.py`):

```python
from pathlib import Path

from lup_dev import (
    CodeRules, Exemption, Exemptions, Gate, Guidance, Module, Modules, Paths,
    Project, Pytest, Python, Rules, Section, Step, TestRoots,
)


class LupDevelopment(Module):
    """What only lup's repository needs: building lup's engine, guarding its policy, its guidance."""

    name = "lup-development"
    paths: Paths = Paths.of(protected=["packages/lup-dev/src/lup_dev/catalog/**"], operator_documents=[…])
    gate: Gate = Gate.of(Step(name="engine", command=["python", "packages/lup-dev/checker/build.py"], …), before="rules")
    guidance: Guidance = Guidance.of(Section(name="lup", path=Path("AGENTS.md")))


project = Project(
    modules=Modules.default()
    .edit(Python(tests=TestRoots.of(Pytest(root=Path("packages/*/tests")))), why="each package's tests are in its own `tests/`")
    .edit(CodeRules(rules=Rules().add("runtime-mention")), why="a rule about lup's own architecture, which lup's default leaves out")
    .edit(CodeRules(exempt=Exemptions().add(Exemption(rule="constant-home", paths=["packages/lup-dev/src/lup_dev/catalog/**"], why=…))))
    .add(LupDevelopment()),
)
```

- **Every name comes from `lup_dev`,** the front door (`lup_dev/__init__.py`), but the modules living outside `lup_dev`: `GitHub` is imported from `lup.github.module`, and `Transcripts` from `lup_transcripts.environment.module`.
- **`Modules.default()` is lup's default modules** (*lup's modules*). `.edit` puts a layer on one of them naming only what it changes: `Python(tests=…)` changes `Python`'s test roots and leaves the rest. `.add` brings in a module that isn't there yet.
- **A collection changes by operations on what's below it:** `Rules().add("runtime-mention")` is `CodeRules`' rules as they stand, plus one. The second `.edit(CodeRules(…))` sets only `exempt`, so the rules the first set stay, and no layer restates another.
- **`why`** is optional on `.edit`, `.drop` and `.replace`, and is kept with the change for whoever reads the project later. An `Exemption` always carries its own.
- **A module of the project's own** is written the way lup's are: a `Module` subclass whose name is a class attribute, whose docstring is its one sentence, and whose parts are fields defaulting to its own values. `before="rules"` puts its step ahead of `Python`'s `rules` step, since names are shared across modules.
- **`held` and `flagged`** are the fields of `Project` that aren't a module's: what a change asks that waits for the operator, and what lands flagged, named by a role, a kind of change or a rule's id (`docs/judging-writes.md`, *What each change gets*). A name in both, or one that's neither a role, a kind nor shaped like a rule's id, fails the load; whether a rule of that id exists is checked at the judge's first judgement.

A project without a `lup_project.py` gets `Project()`, which is `Project(modules=Modules.default())`.

## Where it lives

- **The file:** `lup_project.py` at the worktree's root, binding `project`, or the package `lup_project/`; both fails the load. Without either, the defaults apply. A declaration that can't be imported, or binds no `Project`, raises `ProjectError` and never falls back to the defaults, which would judge with the wrong roles.
- **Outside the project's package,** so it isn't shipped in the wheel and production code can't import it, since a declaration imports `lup_dev`.
- **Imported** with the root, its `src/`, and each uv workspace member and its `src/` on the path, since the judge runs from its own installed copy, without the project's environment; a shared base kept in a package of its own is found only as a workspace member. It writes no bytecode into the worktree.
- **Who reads which copy:** the judge and a launch read it at the commit the operator approved (`docs/trust.md`), the gate from the worktree. The declaration's own file is protected, so every change to it reaches the operator; the other files of a `lup_project/` package are judged as code, and take effect once approved.

**A person's own layer, `lup_project.local.py`:** one per repository, in its main worktree (a clone's root, or a bare repository's own directory), so every worktree shares it. It's gitignored and protected. It binds `project` too, a `Project` written as a layer on the project's in the same grammar, and runs after the declaration, so it can import the project's own modules. It holds what a person sets up for themselves, the other repositories they relate above all (`docs/launch.md`, *Related repositories*), and their private values (`docs/private.md`). The host runs it, so trust approves it by its content (`docs/trust.md`, *Trusted by its content*).

## The verbs on modules

Everything a declaration writes is a layer on what's below it, naming only what it changes: below a project are lup's default modules, and below a person's layer is the project. One rule holds for every value (`applied`, `declaration/grammar.py`):
- **A module, wherever it's written,** means "that module below, with these changes": the fields it set (pydantic's `model_fields_set`) apply, every other field stays as below has it. A field given, even at its default value, counts as set.
- **A selection** starting from `Kind()` keeps below's start and adds its operations after below's; one that starts over (`.default()`, `.all()`, `.only(…)`, `.of(…)`) replaces below's whole.
- **A `Layer`,** a model of settings holding several values (`Paths`, `Session`, `Credentials`), applies the fields it set, each selection inside composing over below's.
- **Any other value replaces below's,** a runner among them: merging two runners field by field would surprise a reader expecting the later one to win.

What it costs: a field a base set can't be unset. Writing lup's default back sets it again, so it's imposed as a set field is (a session setting over the person's own) and doesn't follow a later release's default; only a `.replace` with a fresh module unsets it.

| Verb | Means |
|---|---|
| `Modules.default()` | lup's default modules (`declaration/modules/shipped.py`) |
| `Modules.only(*modules)` | exactly these, so a module a later release adds to the default doesn't come in |
| `Modules()` | the modules below, to change: lup's default in a project, the project's in a person's layer |
| `.add(*modules)` | a module that isn't there; one already there steers to `.replace` |
| `.drop(name, why=…)` | without the module of that name |
| `.edit(module, why=…)` | the module of that name, with `module` as a layer on it; another class steers to `.replace`, so a swap is visible |
| `.replace(name, module, why=…)` | another module in its place, from its own defaults: a project in another language replacing `Python` with its own |

A name that isn't there fails the load, naming those that are, and `Core` is required.

## One grammar for every kind

Every collection a module holds is a selection (`Selection`, `declaration/grammar.py`): where its entries start from, and the operations that change them, recorded as written and resolved only when the declaration is read.

| Start or verb | Means | Example |
|---|---|---|
| `Kind()` | the value below, to change | `Rules().drop("tuple-shape")` |
| `Kind.default()` | the defaults: lup's for `Modules`, the module's own inside a module | `Rules.default()` |
| `Kind.all()` | every entry lup knows | `Rules.all()` |
| `Kind.only(*names)` | these known entries, and no other | `Rules.only("regex")` |
| `Kind.of(*entries, before=…, after=…)` | these entries, with no defaults: a module's own | `Gate.of(Step(…), before="rules")` |
| `.add(*entries, before=…, after=…)` | beside the entries there; a name already there is an error | `Exemptions().add(Exemption(…))` |
| `.drop(*names, why=…)` | without these; a name not there is an error | `Rules().drop("tuple-shape", why=…)` |
| `.replace(name, entry, why=…)` | `entry` in place of the one named | `Guidance().replace("core", Section(…))` |

- **Recorded, resolved at load:** `Rules.default().drop(…)` takes the rules a later release adds to the default, and `Rules.only(…)` doesn't.
- **Names are per kind and shared across modules,** so a step can go `before="rules"` though `rules` is `Python`'s; one name from two modules fails the load, naming both. Some kinds merge instead: a path pattern or a package given twice is one, and a related repository given twice with one path; two modules exempting one rule each keep theirs.
- **Methods, not set arithmetic,** since the declaration is ruled code: `Rules.all() - {"regex"}` would meet lup's own `set-shape`.

**The kinds** (`declaration/kinds.py`):

| Kind | Entries | Held by |
|---|---|---|
| `Rules` | rule ids | `CodeRules` |
| `Paths` | a `Layer` of patterns per role (`protected`, `operator_documents`, `excluded`, `tests`, `scratch`, `docs`, `data`, `source_trees`, `python`, `conftest`), the verbs taking roles as keywords | `Core`, `Python` |
| `Gate` | `Step`s, by name | `Python`, `Private` |
| `Exemptions` | an `Exemption` per rule, listing every path it lifts the rule from | `CodeRules` |
| `TestRoots` | `Pytest` roots | `Python` |
| `Packages` | `Package`s of the room's image | `Core` |
| `Session` | a `Layer` of session settings (`docs/launch.md`, *The settings compiled for each runtime*) | `Core` |
| `Credentials` | a `Layer`: the actions allowed, and the protected and gated refs (`docs/credentials.md`) | `Core` |
| `Guidance` | `Section`s: a file from the root, or one a Python package ships | each of lup's modules but `GitHub` |
| `Repositories` | `Repository`s | a person's layer |
| `Serving` | `ModuleServing` classes, by name | `GitHub`, `Transcripts`, `Private` |
| `Details`, `Values` | what lup reads on the host never published, and the person's own values | `Private` |

## What a module is

A `Module` subclass (`declaration/module.py`):
- **Class attributes:** `name`, `requires` (modules it can't work without) and `requirements` (tools from outside the project's environment), which no layer can blank out.
- **One sentence:** its docstring's first paragraph.
- **Fields:** its parts and its own settings, each defaulting to the module's own value. Unknown fields are refused, so a misspelled one fails the load rather than vanishing.

Defining the class checks it, each failure naming the module and the field: a module with no `name` or docstring; a field with no default, since a module added with nothing set stands on its own defaults; a plain `list` or `dict`, which a layer would replace whole, so it takes a selection; a default starting from `Kind.default()`, which would start from itself. At load, every module a selected one `requires` must be selected too, with no cycle: lup never adds or drops a module behind the project's back.

**What a module serves a launch** (`declaration/serving.py`). It runs on the host, in the repository's process of its approved copy, which serves each of its launches, the launch travelling with each request (`docs/host.md`, *Each repository's judge and modules*):
- **its methods,** grouped in `ModuleServing` classes the module lists in its `serving` (`Serving.of(GitHubServing)`), each behind one of the library's doors (*The doors*, below), reading the module's own context through `self`: its settings (`self.module`, which the class narrows to its module's class), its data directory for the repository (`self.data`), the other repositories the declaration names (`self.related`), where each runtime keeps its records (`self.records`), and the publishing door (`self.publish`, below);
- **data,** `Mounted`: the module's own data directory for the repository, mounted at its host path in every room (`always=True`), or only where a launch lends it by name (`--mount transcripts`), read-only unless the module says. A guidance section names where with `{{ data(…) }}` and asks whether with `{% if mounted(…) %}`.

```python
import lup
from lup_dev import Agent, Lup, Module, ModuleServing, Room, Serving


class EchoServing(ModuleServing):
    """Echo's tool, its answer to a room's `ping`, and what it keeps at a launch's bounds."""

    module: Echo

    @lup.tool(reads=True)
    async def shout(self, said: Said, by: Agent) -> str:
        """Shout what you're told."""
        return f"{said.text.upper()}, for {by.conversation.id}"

    @lup.request
    async def ping(self, asked: Ping, by: Room) -> Pong:
        """Answer a room's `ping`."""
        return Pong(text=f"{asked.text} to {by.launch.launch}")

    @lup.on(lup.Launched)
    @lup.on(lup.Stopped)
    async def keep(self, event: lup.Launched | lup.Stopped, by: Lup) -> None:
        """Note each launch's bounds in the module's own data."""


class Echo(Module):
    """Shouting what it's told."""

    name = "echo"

    serving: Serving = Serving.of(EchoServing)
```

**The doors** (`lup/doors.py`). A door exists only where the contract differs: who calls a method, what it takes, what it returns. Each is a decorator in the library's namespace, typed with its contract, so pyright holds the method behind it to what the door takes and returns:

| Door | Who calls it | It takes | It returns | Who asks, by default |
|---|---|---|---|---|
| `@lup.tool` | an agent, through MCP | a model | a model, or `str` | `Agent` |
| `@lup.request` | code in a room | a `Request`, whose `kind` routes it | a `Reply` | none: it says |
| `@lup.on(Event)` | lup, at the event | the event | nothing, or `list[Refusal]` at `Publishing` | `Lup` |
| `@lup.view` | the dashboard, kept live, and its command | what's viewed | `Blocks` (*Views and blocks*) | `Operator \| Room` |
| `@lup.command` | whoever runs the command line | a model, its fields the arguments and options | the text it prints, `str` | none: it says |

- **A method takes one model,** then, where it needs whoever asks it, `by`; its docstring describes it, to the agent for a tool, whose summary line is 50 characters at most. A tool's name is its method's; a request is routed by the `kind` of the model it takes, since code in a room sends that typed model whichever module answers it. One method is reached through one audience's doors: a hook through several events, stacked, the method taking a union of them.
- **Who asks is the method's** (`Asker`): `Agent`, a conversation of the launch's session, with its launch and conversation; `Room`, code in one of the repository's rooms, untrusted, with its launch, as the host recorded it; `Lup`, lup itself running a hook, with the launch the event is of and, for a session's events, its conversation; `Operator`, the operator, from the dashboard or a terminal on the host. `by`'s type narrows who may ask the method to those it names, and hands it its caller; left out, the method is for its door's default askers. Defining a class checks each method, the failure naming it: a `by` naming someone its door never brings (a tool for a `Room`), or a request leaving it out. Who actually asks is checked again before each call, so a room never reaches a method meant for another, and a room is offered only the kinds of request it may send.
- **lup's events** (`lup/events.py`), one class each, are what a hook names: `Launched`; `Stopped`, once the launch's session has fully stopped; `Publishing`, before anything leaves under the operator's name; and a session's, which each runtime's hooks are read as, `SessionStarted`, `TurnStarted`, `CallStarted`, `CallFinished` (each with its `call` and `tool`), `TurnEnded` and `ConversationEnded`. An event carries its own facts; the launch and conversation come with `by: Lup`. Where an event crosses a wire, it's named in kebab case derived from its class (`call-started`), and nowhere else is it spelled as a string.
- **`Publishing` is the one event a hook answers,** returning its refusals (`lup/publishing.py`), each naming what it found and where, never the value; one refusal keeps what would leave from leaving, and a hook failing there refuses too. A hook taking `Publishing` beside another event is refused as it's declared. A method that would publish puts it through every module's hooks first, `await self.publish(post, "this issue", by)`, which raises `UnpublishedError` listing the refusals.

A tool's name and a request's kind are shared across modules, so the same one from two fails the load.

## Views and blocks

A module's Python lays out each of its views from lup's building blocks (`lup/blocks.py`), and the dashboard's page only draws them, so a module needs no TypeScript for what it shows, the page has one way of drawing, and an agent reading a view's text form reads what the operator saw.

- **The blocks:** a `Line`, text in spans, each in a tone (`Span`); `Markdown`, in a tone; a `Fold`, a summary line and what folds under it, of one of the module's fold kinds, open or closed, its content set off by a bar where it's `barred`, and given, or read from another of the module's views as it opens (`Load.of(view, argument)`), so a long view sends only what's open. A view answers `Blocks`: its blocks, the summary line a drawer shows under its banner, and whether it holds what waits on the operator, which makes that line bold.
- **Each block has an id** the module chooses and keeps from one answer to the next, as a step's number or a call's id: the page keeps folds open, the cursor and comments where they were, by it.
- **The text form** (`Blocks.text`) is what a view's command prints: a closed fold as its summary line, an open one with its content indented, and a fold read as it opens with the view it reads and what it gives it beyond the agent it's of (`▸ you: first words  [exchange step=12]`), so a reader knows which view's command opens it.
- **Tones and colours:** a span names a tone, the shell's (`plain`, `muted`, `strong`, `operator`; `SHELL_TONES`) or one its module declares (`Tones`), which takes another tone's look (`like=`), or a colour of the shell's palette (`colour=`, as the page names them: `fg`, `muted`, `link`, `ok`, `err`, `warn`, `info`, `purple`, `cyan`, `orange`), bolder or dimmer (`weight=`); never a colour of its own, so every module reads in one palette. A tone taking a shell tone's name or an unknown tone's look fails the load, and a view naming a tone none declares fails its answer.
- **Fold kinds** (`Folds`, `lup.FoldKind`): a letter, which the page's fold keys take (`zf` and it closes the one the cursor is in, Space `z` `f` and it opens every one), what they're called, a level `zr` and `zm` open and close them at, how they open (`together`; `back`, one at a time, the latest first; `deep`, only by their own keys, for content read as it opens), and a colour. Two of a repository's modules taking one letter, a fold kind's or a drawer's, fail the load.
- **Where a view goes:** `@lup.view(place=Drawer(letter="v", called="the conversation", colour="cyan"))` puts it in a drawer under each agent's banner, and it takes the agent it's of (`OfAgent`); with no place, a fold reads it as it opens, or its command prints it. `watch=Watch(on=[…], longest=…)` says when a view the page shows is answered again: at those events of its agent, and that long apart at most.
- **Who answers it:** the repository's process, of its approved copy, for the operator or a room (`Viewing`, `RepositoryModules.view` in `lup_dev/worker.py`), checking who asks and the tones its answer names. A view weaving in the items of lup's inbox a conversation exchanged reads them from the core (`self.exchanges`), which keeps them.

`Transcripts`' conversation is the first: the drawer (`conversation`), one earlier exchange (`exchange`) and one call read whole (`call`), laid out in `packages/lup-transcripts/src/lup_transcripts/environment/conversation.py`.

## Commands

A module's commands come under its name on the command line, `lup-dev transcripts show abc --all`: each `@lup.command` method, and each view, whose command prints its text form (`lup_dev/commanding.py`). A first word that isn't one of `lup-dev`'s own commands names a module, and `lup-dev --help` ends naming the modules that have commands, read from the declaration the operator approved on the host and from the worktree's in a room.

- **Each is built with typer from its method's model:** a field with no default is an argument, one with a default an option named for its alias, else its name (`Field(default=False, alias="all")` is `--all`), a `bool` a flag, a `list` repeated; each field's description is its help, and the method's docstring the command's. Who runs it is found only as it runs, so `--help` asks nothing, and lists what they couldn't run.
- **It runs in the terminal's own process,** never in the repository's: typer prints help and errors to its process's standard output, which the repository's process shares among every session it serves. On the host, the installed `lup-dev` hands a module's command over to the repository's approved copy, becoming it (`exec`), so only code the operator approved runs a project's module there, as the operator (`Operator`); the copy knows it's the one to run it by its own path. Before any approval, the host runs no module's command. In a room, the room's own `lup-dev` runs it from the worktree's declaration, which the room contains, as the room (`Room`), its launch as the host recorded it (`room-launch`). A command in a room is room code: what needs the host, the operator's credentials or the inbox, it asks the host for, as any room code does. The hand-over costs a second start of Python on the host, about 0.9 s (#298 watches it).

## lup's modules

`Modules.default()`, in order (`declaration/modules/shipped.py`):

| Module | What it holds |
|---|---|
| `Core` | every protected path but the Python tools', the operator's documents, TypeScript's tests (`*.test.ts`, `*.test.tsx`), scratch, docs and data; the standard machine; lup's session defaults; the credentials' limits; guidance `core` |
| `Python` | the Python tools' files (protected), source trees, Python files and `conftest.py`; the runner, `Uv()`; the test roots, `tests/`; the gate's `rules`, `format`, `pytest` and `lint-imports`; guidance `python` |
| `CodeRules` | every rule but those `catalog/rules.py` leaves out, each with its reason (`runtime-mention` alone today); no exemptions; guidance `code-rules`. Requires Node `>=22.18` for the engine |
| `GitHub` | the GitHub tools; the answer to a room's gate asking an issue's state |
| `Transcripts` | copying the runtime's session records when a launch opens and stops; its data, mounted in every room; its commands reading them; each agent's conversation, live, as a view; guidance `transcripts` (`packages/lup-transcripts/README.md`) |
| `Private` | what lup reads on the host never published, and the person's own values; refusing at `publishing`; the gate's `private` step; guidance `private` (`docs/private.md`) |

- **`Core` is every project's,** the part of the core a project can change. `Python` and `CodeRules` stay apart from it so each is one line to drop: dropping `CodeRules` turns off all of lup's code rules.
- **`Core`, `Python` and `CodeRules` are data,** read from the catalog (`catalog/`), made of the same entry types a project writes; their guidance sections are files `lup_dev` ships. `GitHub` and `Private` live beside their machinery; `Transcripts` is a distribution of its own, `packages/lup-transcripts/`, its environment side in a subpackage its library side never imports (`packages/lup-transcripts/README.md`, *Layout*).

**lup declares itself the same way,** through the surface any project uses (*An example*). What only lup's repository needs is its module `LupDevelopment`: the engine's and the dashboard's builds ahead of every other step, the catalog protected since lup's policy data lives there, its modules' guidance among the operator's documents since every project's sessions read it, `AGENTS.md` as its own section, and Chromium in the room, with a virtual display to type into it. `runtime-mention` is a rule about lup's own architecture, which would fire on every choice in a project picking its runtime by a setting, so lup's default leaves it out and lup's declaration adds it back.

## What reads it

**Resolving it** (`resolve`, `declaration/resolve.py`) applies every layer, then reads each kind from the modules holding it: the modules with their origins, each role's patterns, the gate's steps in order, each module's rule selection, the exemptions, test roots and conditions, the runner and every requirement, the packages, session settings, credentials, guidance, related repositories, what's held and flagged, and what's served. The runner, the session settings and the credentials each come from one module; a second holder fails the load, naming both, since a project runs one way.

**What judging reads** is kept apart as plain values (`Declaration`): the declaration's file, the roles, the test roots, the exemptions, the conditions, the rule selections, the runner as the commands it puts before a tool, and what's held and flagged. Plain values, since a module or a runner may be a class of the project's own, which JSON can't bring back, and the judge keeps the last declaration that loaded to stand in for one that can't (`docs/judging-writes.md`, *A declaration that can't load has a stand-in*).

**What a launch reads,** at the approved commit (`approved_declaration`, `launch/session.py`): the packages; the session settings, with which fields some layer set, so those are imposed over the person's own runtime settings and the rest are lup's defaults theirs outrank; the credentials' limits, sent with the registration (`docs/credentials.md`, *What the declaration allows*); the guidance sections (`docs/launch.md`, *Guidance*); the related repositories; the runner's `room()`; and what each module serves.

**Selecting the rules.** `CodeRules.rules` is a `Rules` selection, by default `Rules.all()` with a `.drop(…, why=…)` for each rule lup's default leaves out, so a rule a later release adds runs unless it's left out too. Python only composes and records a selection: each check request carries every module's, and the engine, which holds the table, resolves them and runs their union, refusing an id it doesn't have. Exemptions and `# lup: ignore` apply afterwards, in Python. `lup-dev rules list` lists what the worktree's declaration runs, resolved the same way, and a launch lists the approved one's in the guidance. A project's own rule tables are #175.

## The runner

`Python.runner` says how the project runs its tools (`declaration/runner.py`), so uv is spelled once, in `Uv`, for everything run in the project's environment; a deferral's conditions asking uv for Pythons, and trust installing lup itself, ask uv for themselves:

```python
class Runner(Model, ABC):
    def command(self, tool: list[str]) -> list[str]: ...   # the gate's: it may make or sync the environment
    def judging(self, tool: list[str]) -> list[str]: ...   # the judge's: it never writes the project's files
    def environment(self) -> list[str]: ...                # the files whose change means another environment
    def room(self, root: Path, tools: Tools) -> RoomNeeds: ...  # what a room mounts and sets for it
```

- **`Uv()`,** the default: `uv run …` for the gate, and `env -u VIRTUAL_ENV uv run --frozen --quiet …` for the judge, which never relocks, so the judge never writes `uv.lock`, a protected path the checkpoint would judge as the agent's. Its environment files are `pyproject.toml`, `uv.toml`, `uv.lock` and `.python-version`.
- **`Plain()`:** each tool as the `PATH` finds it, for a project with no environment manager; the runner wherever no module holds one.
- **A project's own runner** is a subclass of a few lines: `poetry run`, `conda run -n …`.
- **Its contract:** a runner puts its own command before the tool, so `command(tool)` is `command([])` and the tool. That's what lets the judge keep any project's runner as plain commands (`Prefixed`).
- **What a room needs** (`room()`): a launched session works in the worktree's own environment, shared with the host (`docs/launch.md`, *The project's environment, shared with the host*), so the runner says what the room mounts and sets: for `Uv`, uv's interpreters read-only and its cache read-write, at their host paths, with `UV_PYTHON_DOWNLOADS=never`, and the interpreter, which a launch refuses where it resolves outside every mount. Four abstract methods put `Runner` past what `interface-shape` allows, which its `ignore` names.

The gate's steps, ruff in the judge and the engine all take their commands from the runner, the engine stamped with its environment files so a lock arriving with a merge is synced before the next check.

## Requirements

A requirement is a tool from outside the project's Python environment (`declaration/requirements.py`), a class attribute of the module needing it, so an `.edit` can't blank it out; a runner brings its own (`Uv` needs uv):

```python
Requirement(tool="node", version=">=22.18", probe=["node", "-p", "process.versions.node"],
            why="runs the rule engine", install="https://nodejs.org/en/download", package="nodejs")  # CodeRules
```

- **Its version is read with `packaging`** from what the probe prints, so nothing parses a tool's banner; without `version`, the check is only that the tool is on the `PATH`.
- **The gate checks them all at once,** before any step, naming every missing one, the module needing it and how to install it; an optional one missing is said once.
- **`package`** is the Arch package providing it in lup's room, which joins the room's image, so a module names it once. A launch checks the host's own needs the same way (`docs/launch.md`, *The command*).
- **Node `>=22.18`** is the oldest Node that strips TypeScript types without a flag, which a project's own rule tables will need (#175).
