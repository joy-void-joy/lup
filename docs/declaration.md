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

- **Every name comes from `lup_dev`,** the front door (`lup_dev/__init__.py`), but the library's own modules: `GitHub` and `Transcripts` are imported from `lup.github.module` and `lup.transcripts.module`.
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
| `Toolsets`, `Handlers`, `Hooks` | classes, by name | `GitHub`, `Transcripts`, `Private` |
| `Details`, `Values` | what lup reads on the host never published, and the person's own values | `Private` |

## What a module is

A `Module` subclass (`declaration/module.py`):
- **Class attributes:** `name`, `requires` (modules it can't work without) and `requirements` (tools from outside the project's environment), which no layer can blank out.
- **One sentence:** its docstring's first paragraph.
- **Fields:** its parts and its own settings, each defaulting to the module's own value. Unknown fields are refused, so a misspelled one fails the load rather than vanishing.

Defining the class checks it, each failure naming the module and the field: a module with no `name` or docstring; a field with no default, since a module added with nothing set stands on its own defaults; a plain `list` or `dict`, which a layer would replace whole, so it takes a selection; a default starting from `Kind.default()`, which would start from itself. At load, every module a selected one `requires` must be selected too, with no cycle: lup never adds or drops a module behind the project's back.

**What a module serves a launch** (`declaration/serving.py`). It runs on the host, in a process of the launch's own, from the repository's approved copy (`docs/host.md`, *Each launch's judge and modules*):
- **tools,** `ModuleTools` classes, each tool a method decorated with the library's `@lup_tool`, reading its module's settings through `self.module`;
- **handlers,** `ModuleHandler`s, each answering one kind of the room's requests;
- **hooks,** `ModuleHooks` classes, each method marked `@lup_hook` and run at a moment of lup's: `launched`, `stopped`, `publishing` (before anything leaves under the operator's name, the one moment a hook answers, with refusals), or the five each runtime's hooks are read as;
- **data,** `Mounted`: the module's own data directory for the repository, mounted at its host path in every room (`always=True`), or only where a launch lends it by name (`--mount transcripts`), read-only unless the module says. A guidance section names where with `{{ data(…) }}` and asks whether with `{% if mounted(…) %}`.

A tool's name and a request's kind are shared across modules, so the same one from two fails the load.

## lup's modules

`Modules.default()`, in order (`declaration/modules/shipped.py`):

| Module | What it holds |
|---|---|
| `Core` | every protected path but the Python tools', the operator's documents, TypeScript's tests (`*.test.ts`, `*.test.tsx`), scratch, docs and data; the standard machine; lup's session defaults; the credentials' limits; guidance `core` |
| `Python` | the Python tools' files (protected), source trees, Python files and `conftest.py`; the runner, `Uv()`; the test roots, `tests/`; the gate's `rules`, `format`, `pytest` and `lint-imports`; guidance `python` |
| `CodeRules` | every rule but those `catalog/rules.py` leaves out, each with its reason (`runtime-mention` alone today); no exemptions; guidance `code-rules`. Requires Node `>=22.18` for the engine |
| `GitHub` | the GitHub tools; the answer to a room's gate asking an issue's state |
| `Transcripts` | copying the runtime's session records when a launch opens and stops; its data, mounted in every room; guidance `transcripts` |
| `Private` | what lup reads on the host never published, and the person's own values; refusing at `publishing`; the gate's `private` step; guidance `private` (`docs/private.md`) |

- **`Core` is every project's,** the part of the core a project can change. `Python` and `CodeRules` stay apart from it so each is one line to drop: dropping `CodeRules` turns off all of lup's code rules.
- **`Core`, `Python` and `CodeRules` are data,** read from the catalog (`catalog/`), made of the same entry types a project writes; their guidance sections are files `lup_dev` ships. `GitHub`, `Transcripts` and `Private` live beside their machinery.

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
