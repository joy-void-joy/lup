# The declaration: a project is its modules, and extends lup as lup extends itself

**One sentence:** a project writes one `Project` in `lup_project.py` at its root, holding its modules: lup's (`Core`, `Python`, `CodeRules`, and the rest as their pieces are built) with the project's changes, and its own, written as lup's are. Every kind lup has (path roles, rules, gate steps, commands, skills, guidance, rooms, requirements) is filled by the selected modules, so a module brings everything it needs and takes it away when it's dropped. lup's settings for ruff and pyright go in files of lup's own, which the project's `pyproject.toml` extends and overrides as it would any shared configuration.

This note details `DESIGN.md`'s *The environment: core and modules* and *How lup reaches a project*. It covers #36 (the runner), and gives #33 the selection grammar its round needs. The declaration is built only as large as the steps of `DESIGN.md`'s *Build order* need, in the slices below.

Each choice is stated once, in the section it shapes, with the alternative it was chosen over where a reader might otherwise propose it. A choice the operator hasn't confirmed is marked **(leaning)**, as in `DESIGN.md`; one still open says so.

A word on words: in this note a **module** is one of lup's or a project's `Module`s (`Core`, `Narration`). A Python source file is a **file**, and its import path a **Python module** where it matters.

**The slices, in their order, one branch each (leaning):**
- **A, the declaration:** `Project` as modules, the grammar, lup's modules (`Core`, `Python`, `CodeRules`), the runner (#36), the rule selection reaching the engine, and requirements.
- **E, a project's own rules:** a rule table per module, loaded when the engine starts, `rules new` and `rules check`.
- **B, the tool settings:** lup's own files under `.lup/settings/`, the pointers to them, the settings step, the `compiled` role, and the overview.
- **C, the command line:** one lazy `lup` built from the modules' commands, the rename, and `lup new`.
- **D, rules and conventions:** each rule names its conventions section, which gives rules their families.

The letters name the slices, not their order (*Building it*).

## A project is its modules

### Where it lives

A file named `lup_project.py` at the worktree's root, binding `project`. Nothing points at it: the loader looks there. The `[tool.lup] project` pointer, which `lup_dev/project.py` reads, goes. Without the file, the defaults apply; a file that can't be imported, or binds no `Project`, is an error, never the defaults.

The fixed file is chosen over a module named in `pyproject.toml` on three counts:
- the operator finds every project's declaration in the same place;
- there's no pointer to keep right, or to repoint from a branch;
- it sits outside the project's package, so it isn't shipped in the wheel and production code can't import it. A declaration imports `lup_dev`, and production code importing it would make the environment a production dependency, which the split forbids (`DESIGN.md`, *Two packages*).

**(leaning)** When a project's own modules outgrow one file, the declaration becomes the package `lup_project/`, its `__init__.py` binding `project` (*A project's own module*). Both at once fail the load.

The declaration is protected (`DESIGN.md`, *Policy*): every change to it reaches the operator. The judge reads it from the integration branch's tip, the gate from the worktree.

### The declaration

```python
from lup_dev import Budgets, CodeRules, Ledger, Modules, Project, Rules

project = Project(
    modules=Modules.default()
    .add(Narration(), Budgets(share=0.5))
    .edit(Ledger(directory="work"))
    .edit(CodeRules(rules=Rules().drop("collection-loop", why="the pipeline's stages are loops by design")))
    .drop("coordination", why="one agent at a time here"),
)
```

`Narration` is the project's own module (*A project's own module*, below); `Ledger`, `Coordination` and `Budgets` are written as they'll be once their pieces exist.

- **`lup new` writes `Project(modules=Modules.default())`,** so nothing is retyped; `Project()` means the same.
- **`Modules.only(Core(), Python(), CodeRules())`** gives an exact list, for a project that wants one: a module a later release adds to the default doesn't come in.
- **`Project` holds `modules`, and what isn't a module's (leaning).** Every part lives in a module, so reading one module says what it does; cross-cutting parts at the top (`paths`, `runner`) would each be changeable in two places. `Project` stays a model rather than the bare `Modules` so that what isn't a module's has a place. `asks`, which of the judge's asks reach the operator (`"every"` by default, or `"protected"`; `declaration/project.py`), is one; it's a temporary switch for lup's own build, and goes when the judge's asks become proposals (`DESIGN.md`, *Sessions*). Upstream candidates (`DESIGN.md`, open question 6) may follow.
- **`lup project`** (`lup-dev project` until C) shows the resolved list: every module that's on, its parts, and the project's changes with their reasons (*One page for the whole project*).

### The verbs on modules

**Everything a base or a project writes is a layer on what's below it,** naming only what it changes. The layers are lup's defaults, then a shared base if the project uses one, then the project, in the order of the chain. One rule holds for every value:
- **A module, wherever it's written** (in `.add` or `.edit`, or bound to a name), means "that module below, with these changes": the fields it sets (pydantic's `model_fields_set`) apply, and every other stays as it was below, earlier layers included. A field given, even at its default value, counts as set. Where nothing is below, as for a module just added, below is the module's own defaults.
- **A collection changes by operations on what's below.** `Rules().drop("x")` is the rules below minus `x`, and `Exemptions().add(…)` the exemptions below plus one. `Kind.default()`, `Kind.only(…)` and `Kind.of(…)` start over (*One grammar for every kind*).
- **Every collection is a selection; there are no plain lists.** `exempt`, `tests` and `doctests` are `Exemptions`, `TestRoots` and `Doctests`, so a layer adds to them without a handle on the base.
- **A scalar given replaces what's below,** and the later layer wins.
- **The overview shows, for every value, which layer set it** (*One page for the whole project*), so nothing implicit has to be decoded by hand.

The verbs on `Modules`:

| Verb | Means | Example |
|---|---|---|
| `.add(*modules)` | a module that isn't in the defaults: one of lup's optional ones, or the project's own; one already there is an error | `.add(Narration(), Budgets(share=0.5))` |
| `.drop(name, why=…)` | not this one of lup's | `.drop("coordination", why="one agent at a time here")` |
| `.edit(module, why=…)` | the module already there, with `module` as a layer on it; a module that isn't there is an error | `.edit(Ledger(directory="work"))` |
| `.replace(name, module, why=…)` | a different module in place of lup's, starting from its own defaults: a project in another language replacing `Python` | `.replace("python", Lean())` |

- **`.edit` takes the same class as the module it edits**; a different class is `.replace`, which says so in the declaration.
- **`.edit` exists on a module too,** with the same meaning: `ours.edit(CodeRules(rules=Rules().drop("tuple-shape", why=…)))` is `ours` with that layer on it.
- **`why` is optional on `.drop`, `.edit` and `.replace`,** as on every kind's verbs (*One grammar for every kind*): shown on the overview when given, "no reason given" otherwise.
- **`Core` is required:** dropping or replacing it, or a `Modules.only(…)` without it, fails the load, naming it.
- **`Modules.only` takes modules, not names,** since a module carries its settings; `Rules.only` takes ids, which carry none.

```python
ours = CodeRules(
    rules=Rules().drop("collection-loop"),
    exempt=Exemptions().add(Exemption(rule="set-shape", paths=["**/schedule/**"])),
)

project = Project(
    modules=Modules.default()
    .edit(ours)
    .edit(CodeRules(
        rules=Rules().drop("tuple-shape"),
        exempt=Exemptions().add(Exemption(rule="tuple-shape", paths=["src/legacy/**"])),
    )),
)
```

The result is lup's rules minus `collection-loop` and `tuple-shape`, with both exemptions. Nothing of `ours` is restated, and whatever `ours` gains later comes along. `.edit(ours)` doesn't name `CodeRules` where it's called; `ours` is typed, so the editor and pyright show it, and a name such as `our_code_rules` says it in the source.

**Modules and selections are plain values.** A project can bind one to a name, import it from elsewhere, and build on it. For example, a base shared by several of the operator's projects, kept in a small package of their own:

```python
# joy_lup/__init__.py, the operator's own package
BASE = Modules.default().edit(CodeRules(rules=Rules().drop("collection-loop", why=…))).add(Budgets(share=0.5))

# a project's lup_project.py
from joy_lup import BASE

project = Project(
    modules=BASE.add(Narration()).edit(CodeRules(rules=Rules().drop("tuple-shape", why=…))),
)
```

One constraint, checked in the loader (`import_roots` in `declaration/load.py`): the judge imports the declaration with its own environment, adding only the worktree's root and `src/`, and each uv workspace member and its `src/`. So a base in a package of its own is found only as a workspace member. **(leaning)** The loader also adds the project's environment's packages, after the judge's own, so the base comes from the project's lock (protected, so a change to it asks), and `lup_dev` and pydantic still come from the judge. The alternative is a base installed beside the judge (`uv tool install lup-dev --with joy-lup`), which every project then shares at one version. This is listed under *Checks owed*.

What layering costs:
- a small selection type per collection;
- a scalar can't be put back to lup's default above a base that changed it, short of `.replace` with a fresh module.

The alternatives, which the operator settled against:
- **The grammar as first written:** a selection started from an explicit point (`Kind.default()` for lup's, `Kind.current()` for the value being edited), a plain list given in an edit replaced the whole list, and `.edit` merged a module by the fields it set. Three behaviours, so `CodeRules(rules=X)` read as a whole module in one place and as a change in another, and a second edit had to say `current()`, or restate `[*ours.exempt, …]`, to keep the first.
- **Nix-style merging:** a merge rule per type of value, with priorities. Composable, but implicit and hard to trace.
- **Changes as functions** (`edit(CodeRules, lambda m: …)`): general, but opaque to the overview and to review, where a recorded operation is data.
- **Subclassing** (`class Ours(CodeRules)`): familiar, but lists still reach into the parent, and overriding pydantic's field defaults is awkward.

### lup's modules

`Modules.default()` is `Core`, `Python` and `CodeRules`, then `Coordination`, `Ledger` and `GitWorkflow` as their pieces are built. `Modules.all()` adds lup's optional ones (`Budgets`, `Resolver`, `Release`, …). Every module lup ships, with its sentence and the modules it requires, is listed in `DESIGN.md` (*The environment: core and modules*).

- **`Core`:** the core's parts a project can change: path roles and protected paths, the hook (fixed), the policy, runtimes, session settings, and lup's core commands. Required: dropping it fails the load, naming it.
- **`Python`:** the runner, test roots, doctests, the gate's ruff, formatter, pyright, pytest and import-linter steps, and lup's settings for ruff and pyright. A project in another language replaces it.
- **`CodeRules`:** lup's rule selection and exemptions, and the `rules` commands. Dropping it turns off all of lup's antipattern rules in one line, which the operator says is a common wish; with it, every ruff rule lup turns off because a lup rule owns its concern comes back on (*What lup writes*).
- `Python` and `CodeRules` stay apart from `Core` so that each is one line to drop, and the core stays small enough to hold alone (`DESIGN.md`).

The core itself is what every module talks through (`DESIGN.md`, *The environment: core and modules*): the declaration and its modules, the one hook, the host service, the inbox and the dashboard's protocol; `Core` is where a project changes what of it is declared. `DESIGN.md` leans to launch, judging writes and worktrees being default modules rather than core (its open question 2); settled that way, the parts they read (the policy's choices, runtimes, session settings) move from `Core` into them.

**Which module holds what:**

| What | Module | Field | Default | Slice |
|---|---|---|---|---|
| The modules | `Project` | `modules` | `Modules.default()` | A |
| Which of the judge's asks reach the operator, until they become proposals | `Project` | `asks` | `"every"` | exists |
| Protected paths, the operator's documents, scratch, docs, data, excluded | `Core` | `paths` | lup's patterns (`catalog/paths.py`) | A |
| The hook command | `Core` | none: fixed | | C |
| Runtimes and their spellings, session settings, the policy's choices | `Core` | `runtimes`, `session`, … | lup's | the launch piece |
| Source trees, Python files, `conftest.py`, the Python tools' configuration files and manifests (protected), `.lup/settings/**` (compiled) | `Python` | `paths` | lup's patterns | A, B |
| How the project runs its tools | `Python` | `runner` | `Uv()` | A |
| Test roots: the test role, and what the gate checks pytest's `testpaths` against | `Python` | `tests` | `TestRoots.of(Pytest(root="tests"))` | A |
| Source roots read for their doctests only, which stay production | `Python` | `doctests` | `Doctests.of("src")` | B |
| ruff, the formatter, pyright, pytest, import-linter, the settings step | `Python` | `gate` | lup's steps | A, B |
| Which of lup's code rules run | `CodeRules` | `rules` | `Rules.all()` less what `catalog/rules.py` leaves out, which `Rules.default()` names there | A |
| A rule lifted from some paths, with its reason | `CodeRules` | `exempt` | `Exemptions()`, none | exists, moved in A |
| A module's own rule table | any module | `rules` | none | E |
| The conditions a `defer` waits on | any module | `conditions` | none | exists, moved in A |
| Commands | any module | `commands` | the module's own | C |
| Skills, guidance | any module | `skills`, `guidance` | the module's own | the launch piece |
| Rooms | any module | `rooms` | none | the rooms slice |
| Requirements | each module | `requirements` (a class attribute) | the module's own | A |
| The modules it depends on | each module | `requires` (a class attribute) | none | with the first module requiring another |

Package dependencies stay in `pyproject.toml` (*Dependencies*), and so do the project's own changes to ruff and pyright (*lup's settings for ruff and pyright*).

### What a module is

A module is a `Module` subclass: its name, its one sentence and the modules it requires as class attributes, its parts as fields, and its own settings as further fields (`Python.runner`, `Ledger.directory`, `Budgets.share`).

- **Its parts are the kinds every module can fill (leaning):** `paths`, `rules`, `gate`, `commands`, `skills`, `guidance`, `rooms`, `conditions`, and `requirements`. Each is a selection, but for `conditions`, an address, and `requirements`, a class attribute (*Requirements*). Inside a module, `Kind.default()` means that module's default for the part, recorded and resolved at load like every selection.
- **Every collection in a module is a selection, and `Module` enforces it:** a field whose type is a plain collection (`list`, `set`, `frozenset`, `tuple`, `dict` or their `collections.abc` forms, optional or not) fails the module's class definition, naming the module and the field, and steering to a selection kind. A layer would replace a plain list whole, so a base couldn't be extended without restating it. The class attributes (`name`, `requires`, `requirements`) aren't fields, so they're exempt. The alternative, a code rule in the engine refusing such a field at the edit, is left for later, if the verdict log shows agents writing them.
- **The conditions a `defer` waits on are a part any module fills, by address (leaning):** `conditions="audiobook.conditions"`, the Python module declaring them; lup's stock `PythonAvailable` and `PackageReleased` stay classes a project instantiates. As a field of `Core`'s or `Python`'s, a project's conditions would be an edit of lup's module.
- **The machinery stays lup's core code:** running a gate, running the engine's rules, judging, checking requirements, rendering guidance. Modules only say what to run.
- **Names are per kind and shared across modules (leaning):** a step goes `after="pytest"` though pytest is `Python`'s. Two modules giving the same name fail the load, naming both. Three exceptions: a path pattern is its own name, and the same pattern from two modules is one pattern; two modules needing the same tool, Node say, are both checked rather than clashing, the stricter version then holding; and two modules exempting the same rule each keep their exemption, since each lifts it from its own paths. Within one module, an exemption is named by its rule: one per rule, listing every path, with one reason.
- **Order across modules (leaning)** comes from `before=` and `after=`, which name another entry of the kind, whichever module holds it; entries with neither keep the order of their modules in `Modules`.
- **A module may depend on another, declared** with `requires` (`Coordination` has `requires = [Ledger]`; `DESIGN.md`, *The environment: core and modules*). The loader refuses a selection missing a module that another requires, whether it was dropped or never added (`.add(Budgets())` without `Accounts`), naming both, and refuses a cycle: it never adds or drops a module behind the project's back.
- **The runner is a kind of the core's (leaning),** with at most one entry: `Python` fills it, and the engine and the gate read it from the core, so `CodeRules` uses the runner without requiring `Python`. Test roots likewise become the core's test role.
- **No cross-module override,** such as `Modules(...).replace(rules=[])`: a part would then be changeable in two places, and reading one module would no longer say what it does.
- **Dropping each module is tested** (`DESIGN.md`): one test per lup module, dropping it together with whatever requires it; the declaration then serves none of their parts, and lup's own tests pass.

### A project's own module

A project's own module is a `Module` subclass, written as lup's are:

```python
class Narration(Module):
    """Turning a page into an episode: the narrator's room, its skill, the studio, the rules on episode paths."""

    name = "narration"
    requirements = [Requirement(tool="ffmpeg", why="encodes the episodes", install="your system's package manager")]

    rooms: Rooms = Rooms.of("audiobook.rooms:narrator")
    skills: Skills = Skills.of(Skill(name="narrate", path="skills/narrate.md"))
    commands: Commands = Commands.of(
        Command(name="studio", target="audiobook.studio.cli:app", help="Preview, listen, start fresh."),
    )
    rules: Rules = Rules.table("rules/narration.ts")
    paths: Paths = Paths.of(data=["episodes/**"], scratch=["renders/**"])
```

- **Its code parts are string addresses** (*One grammar for every kind*), so loading the declaration imports none of the project's code: the room's address is read when a session launches it, the command's when it's invoked.
- **It lives in `lup_project.py`, or in the package `lup_project/` (leaning),** all of which is protected and read from the integration branch's tip. Every file the declaration is made of is code the judge runs, so it has to be reviewed as the declaration is; a fixed place lets the judge protect it without following imports. The alternatives: any file the declaration imports, protected by recording what loading it imported, which a branch can change; or a fixed sibling directory (`lup_modules/`), a second name for one thing.
- **Its rule table** is named by its `rules` part (*A project's own rules*), and protected the same way: the judge reads the declaration from the integration branch's tip and protects each table a selected module names, so the protected list derives from the declaration.

### One page for the whole project

`lup project` (`lup-dev project` until C) prints everything about a project, read from the declaration and `pyproject.toml`:
- the declaration's file, and the modules that are on, each with its one sentence;
- each module's parts: lup's defaults, then the project's changes, each with its reason or "no reason given";
- the requirements, each met or not;
- the runner; dependencies, from `[project]` and `[dependency-groups]`; published commands, from `[project.scripts]`;
- lup's settings files, current or stale, and the project's own tool tables in `pyproject.toml` as its changes to lup's defaults, naming each setting that replaces lup's rather than adding to it (*Layering*, below).

The dashboard shows the same page (`DESIGN.md`, *The dashboard*).

## One grammar for every kind

Every kind lup has defaults for (modules, rules, path roles, gate steps, commands, skills, guidance, runtimes) is a set of named entries the project starts from and changes with the same verbs:

| Verb | Means | Example |
|---|---|---|
| `Kind.default()` | the defaults: lup's for `Modules`, the module's own inside a module | `Rules.default()` |
| `Kind.all()` | every entry lup ships, where that's more than the default | `Modules.all()` |
| `Kind.only(*names)` | these and no other | `Rules.only("regex", "string-split")` |
| `Kind.of(*entries, before=…, after=…)` | a module's own entries, with no defaults | `Rooms.of("audiobook.rooms:narrator")` |
| `Kind()` | the value below, to change: the module's own default where nothing is below (*The verbs on modules*) | `Rules().drop("tuple-shape")` |
| `.drop(*names, why=…)` | everything but these | `Rules().drop("tuple-shape", why=…)` |
| `.add(*entries, before=…, after=…)` | the project's own beside the defaults; an existing name is an error | `Gate.default().add(step, after="pytest")` |
| `.replace(name, entry, why=…)` | the project's own in place of a default; a missing name is an error | `Commands.default().replace("check", …)` |
| `.edit(module, why=…)` | on `Modules` and on a module: `module` as a layer on the one there (*The verbs on modules*) | `.edit(Ledger(directory="work"))` |

- **Methods, not set arithmetic.** Set arithmetic (`Rules.all() - {"tuple-shape"}`) is refused by lup's own `set-shape` in `lup_project.py`, which is protected and ruled. Operators on lup's own type taking a list would pass, but would be a second spelling of `.drop`.
- **`Kind.of(*entries)` gives a module's own entries (leaning),** with no `Kind.none()` beside it, so they have one spelling: `Kind.none().add(…)` and `Kind.of(…)` would say the same thing. `Kind.of()` with nothing is nothing.
- **`why` is optional,** on `.drop`, `.replace` and `.edit` alike: shown on the overview when given, and "no reason given" otherwise. Requiring one, for every kind or for rules alone, would impose lup's needs on downstream projects, which may legitimately prefer otherwise. An update reads a reason when it asks whether to bring back what was dropped, and an upstream candidate starts from it, where there's one.
- **Recorded, resolved at load.** A selection keeps its starting point and its operations, and is resolved against the installed lup's defaults each time it's loaded, rather than into a list when it's built, which would lose which one the project meant. So `Rules.default().drop(…)` takes the rules a later release adds to the default, and `Rules.only(…)` doesn't; and an update can tell the two apart when it lists a new rule's findings.
- **Validated at load:** dropping or replacing a name that isn't there fails, naming the names that are. A rule renamed by a release comes with a migration that renames it in the declaration.
- **A part with no defaults to select from is a selection too** (`Exemptions`, `TestRoots`, `Doctests`): its `Kind()` is the entries below, none where nothing is, so a layer adds to it as to any other.
- **Path roles are one part, `paths`, each role a pattern list:** `Paths.default().add(protected=[…], data=[…]).drop(data=["*.yaml"], why=…)`. It replaces `Project`'s `protected` and `excluded`, rather than giving each role a field of its own. A pattern is its own name.
- **References to the project's own code are strings in entry-point form,** as `[project.scripts]` writes them (`"audiobook.cli:app"`). Loading the declaration then imports none of the project's code, which every `lup` call and every hook does; the gate imports each reference and fails on one that doesn't resolve. Objects (`commands=[studio_cli]`) would import the project's command line, and whatever it imports, at every call.
- **`Project` and every module forbid fields they don't know** (`extra="forbid"`), so a misspelled field fails the load, naming it. `lup.types.Model` keeps pydantic's default and ignores them, so without it a misspelled field is dropped without a word.

`Selection` is generic over the entry; each kind is a subclass binding its entry type: `Modules`, `Rules` (ids), `Paths` (patterns per role), `Gate` (`Step`s), `Commands` (`Command`s), `Rooms` (addresses), later `Skills`, `Guidance`, `Runtimes`.

## lup declares itself the same way

lup's defaults are its modules, made of the public entry types (`Step`, patterns, `RuffRule`, rule ids), each what `.drop`, `.add` and `.replace` take. What only lup's repository needs is declared in lup's own `lup_project.py`, through the surface a project uses, rather than kept in the catalog and the command line: lup uses lup. **(leaning)** It's a module of lup's repository, rather than lup's specifics spread across edits of its own modules (`Core`, `Python`):

```python
class LupDevelopment(Module):
    """What only lup's own repository needs: building the engine, lup's architecture rule, installing the judge."""

    name = "lup-development"
    requirements = [Requirement(tool="npm", why="installs the engine's bundler", install="it comes with Node")]

    paths: Paths = Paths.of(
        protected=["packages/lup-dev/src/lup_dev/catalog/**"],
        excluded=[
            ".claude/hooks/**",
            "packages/lup-dev/checker/pyright/**",
            "packages/lup-dev/src/lup_dev/codescan/bundle/**",
        ],
    )
    gate: Gate = Gate.of(
        Step(name="engine", command=["python", "packages/lup-dev/checker/build.py"], builds=…, sources=[…]),
        before="ruff",
    )
    rules: Rules = Rules.table("rules/lup.ts")  # `runtime-mention`, from E
    commands: Commands = Commands.of(
        Command(name="install", target="lup_dev.commands.install:app", help="Install the judge from this checkout."),
        Command(name="rules-docs", target="lup_dev.commands.reference:app", help="Write docs/rules.md from the rule table."),
    )


project = Project(
    asks="protected",  # while lup is being built (`AGENTS.md`, *How work goes*)
    modules=Modules.default()
    .edit(Python(tests=TestRoots.of(Pytest(root="packages/*/tests")), doctests=Doctests.of("packages/*/src")))
    .edit(CodeRules(exempt=Exemptions().add(...)))  # the front door's `runtime-mention`, the catalog's `constant-home`
    .add(LupDevelopment()),
)
```

- **Building lup's engine** is the first of the gate's default steps (`catalog/gate.py`), and the installer runs the same step (`install.py`), though only lup's repository has an engine to build. It becomes `LupDevelopment`'s, its command the tool alone, and the installer finds it in lup's declaration and runs it through the runner, as the gate does.
- **`runtime-mention` is lup's own.** It fires on any name holding `claude` or `codex` outside that runtime's adapter (`catalog/rules.ts`): a rule about lup's own architecture, which in a project picking a runtime by setting, as live-translator does, would fire on every choice, so it isn't in every project's default for each to drop. Until E it stays in lup's table, out of the default, and lup's declaration adds it back: `.edit(CodeRules(rules=Rules().add("runtime-mention")))`. E moves it into `rules/lup.ts`, its first entry.
- **lup's import contracts stay in lup's `pyproject.toml`,** as a project's own contracts do (*pytest and import-linter*).
- **The test of the principle:** nothing in lup's core reads a default that isn't in a module a project can change. Building lup's engine, `runtime-mention`, `install` and `rules-docs` are lup's own, declared where a project declares its own.

## The runner

`Python.runner` says how the project runs its tools (#36). Everything that runs a tool in the project's environment derives from it, so `uv` is spelled once, in `Uv`, rather than in the three places that spell it: the gate's steps (`catalog/gate.py`, and the fix steps in `gate.py`), ruff in the judge (`codescan/ruff.py`, `UV_RUN`), and the engine asking for its interpreter (`checker/src/program.ts`, `environmentOf`).

```python
class Runner(Model, ABC):
    """How a project runs its tools in its environment."""

    @abstractmethod
    def command(self, tool: list[str]) -> list[str]:
        """Return the command the gate runs `tool` with: it may make or sync the environment."""

    @abstractmethod
    def judging(self, tool: list[str]) -> list[str]:
        """Return the command the judge runs `tool` with: it never writes the project's files."""

    @abstractmethod
    def environment(self) -> list[str]:
        """List the files, from the root, whose change means another environment."""
```

- **`Uv()`, the default:** `command` is `uv run …`, as the gate spells it; `judging` is `env -u VIRTUAL_ENV uv run --frozen --quiet …`, as the judge runs ruff and the engine asks for its interpreter (`docs/judging-writes.md`, *Type errors and ruff's findings* and *The engine: one typed tree*); `environment` is `pyproject.toml`, `uv.toml`, `uv.lock`, `.python-version`. Its requirement is uv (*Requirements*).
- **`Plain()`:** the tool as the `PATH` finds it, for a project with no environment manager; no environment files, no requirement.
- **Anything else is a project's own subclass,** a few lines: `poetry run`, `conda run -n …`. lup adds one to its own when a second project needs it.

Two methods because the judge and the gate differ: the gate may lock and sync (plain `uv run` relocks a stale lock), while the judge must never write `uv.lock`, a protected path the checkpoint would then judge as the agent's shell write (`docs/judging-writes.md`, *The engine: one typed tree*). A prefix string in place of the class couldn't give the judge a command apart from the gate's.

**A runner's contract:** it runs a tool by putting its own command before it, as `uv run`, `poetry run` and `conda run -n …` do, so `command(tool)` is `command([])` followed by the tool, and `judging(tool)` is `judging([])` followed by it (`Runner`'s docstring). The judge keeps what it reads of a declaration as plain data, to stand in for one that can't load (`docs/judging-writes.md`, *The declaration, from the integration branch*), and a project's runner may be a class of its own that the data can't bring back. So the snapshot (`Declaration`, `declaration/resolve.py`) keeps the runner's commands, not the runner: `Prefixed`, lup's own runner holding the gate's and the judge's commands and the environment's files, built with `Prefixed.of(runner)`. By the contract those are the whole runner, so a stand-in judges with the commands the project's runner gave. The alternative, keeping the runner by its class's import path and importing it again, fails exactly when a stand-in is needed: the declaration that can't load is where that class lives.

Where it's used:
- **the gate:** each step's command is the tool alone (`["ruff", "check", "--ignore-noqa"]`), run as `runner.command(…)`, or as written for a step with `in_environment=False` (`Step.in_environment`, `catalog/gate.py`); the `--fix` steps too. The gate reads the worktree's own declaration's runner, resolved;
- **ruff in the judge:** `runner.judging(["ruff", "check", …])`;
- **the engine:** started with the runner's interpreter command (`judging(["python"])`) and its environment files, each as a JSON list (`--interpreter`, `--environment-files`), so `program.ts` runs that command to name the interpreter, and stamps those files with pyright's own configuration. Every request carries the same pair (`EngineEnvironment`, `codescan/engine.py`), so an engine started with another runner answers stale and is replaced, as one from another build is.

ruff and the engine are given the runner with each call (`Linter.findings`, `Checker.check` and `Checker.importers` take it, as they take the root and the rule selection), rather than holding one: the judge's services are built once per hook, before it knows which worktrees it judges, each by its own declaration. The judge passes the runner of the declaration it judges by, a stand-in's included; the turn's end and the background importers pass, the same; `lup-dev rules check`, the worktree's own, as the gate. So `Uv()` is spelled only as `Python.runner`'s default.

`gate.py`'s own seam for running a command, which its tests stub (`Shell` running it as a process), is `Processes`, so `Runner` means one thing in `lup_dev`.

What it doesn't cover: the narrow `Bash` allow rules in `.claude/settings.json` (the launch piece compiles them from the runner and the gate's steps); `PythonAvailable`'s `uv python list` (`codescan/conditions.py`), which asks uv as a Python provider, not as the project's runner; `uv tool install` in the installer (how lup installs its judge, not how a project runs its tools); and Windows (lup runs in a Linux container).

## Requirements

Requirements are a kind, and each module declares its own. They're tools from outside the project's Python environment; the Python tools lup runs are `lup-dev`'s dependencies instead (*Dependencies*).

```python
Requirement(tool="node", version=">=22.18", probe=["node", "-p", "process.versions.node"], why="runs the rule engine")  # CodeRules
Requirement(tool="uv", why="runs the project's tools")                                         # Python, through Uv()
Requirement(tool="podman", why="runs each session's container")                                # Core, once launch exists
Requirement(any_of=["wl-copy", "xclip"], optional=True, why="copies a review to the clipboard")
```

- **Checked strictly, all at once,** when a session launches and when the gate runs, never lazily when a command first needs one. Not on every hook call: a hook runs inside a session already checked.
- **A missing required one** stops the launch or the gate before anything runs, naming every missing tool, the module needing it, and how to install it.
- **A missing optional one** turns its feature off, said once: the gate says it at the head of its report.
- **Each module declares its own:** `ffmpeg` for `Narration`, `npm` for lup's own module.

The shape **(leaning)**:
- **Fields:** `tool`, or `any_of` for alternatives; `version`, a specifier; `probe`, the command printing the tool's bare version, required with `version`; `optional`; `why`; `install`, how to install it, shown when it's missing. Without `version`, the check is that the tool is on the `PATH`.
- **The version is read with `packaging`** (already `lup-dev`'s dependency): the probe prints a bare version, so nothing hand-parses a tool's banner. Checked on this machine: `node -p process.versions.node` prints `26.10.0`, `uv self version --short` prints `0.12.23`, `podman version --format '{{.Client.Version}}'` prints `6.1.3`.
- **A module's requirements are a class attribute,** not a field, since they're what the module needs to work: a project declares its own module's, and can't blank out lup's with an `.edit`. The runner's requirements come with the runner, so `Python` with `Plain()` needs no uv.

**Node, installed on the system, not bun.** The engine is pyright's code, bundled for Node (`packages/lup-dev/checker/build.py`) and run as `node` (`codescan/engine.py`). bun may come later as another runtime for it. Shipping Node as a Python package is the rejected alternative: `nodejs-wheel-binaries` is at 24.19.0 on PyPI, its summary "unoffical Node.js package" (checked on PyPI's JSON API), an unofficial binary in the supply chain.

**Which Node (leaning): `>=22.18`.** A project's rule table is TypeScript loaded by stripping its types (E). Node's own documentation (`api/typescript.html`, checked) gives type stripping as enabled by default in 23.6.0, backported to 22.18.0, without its experimental warning from 24.3.0 and 22.18.0, and stable from 25.2.0 and 24.12.0. The module hooks E uses (`module.registerHooks`) were added in 23.5.0 and 22.15.0 (`api/module.html`). So 22.18 is the oldest Node that runs both without a flag. The alternative is `>=24.12`, where type stripping is marked stable, at the cost of refusing Node 22, which is still maintained.

**The README's list is generated (leaning):** `docs/requirements.md`, generated from lup's modules' requirements and linked from the README, kept in step by a test as `docs/rules.md` is. The alternative is a generated block inside the hand-written README: generated text inside a hand-written document, which *Rules and conventions* turns down as option (iii).

## lup's settings for ruff and pyright

Settings go one way, from lup's defaults and the declaration into lup's own files: lup behaves as ruff and uv do with a hand-edited `pyproject.toml`, never discarding its settings, rather than generating part of its tables, since two-way updating proved brittle in the first lup.

### What lup writes

**lup writes only its own files,** generated from lup's defaults and the declaration by `lup settings`:
- `.lup/settings/ruff.toml`;
- pyright's file, `.lup/settings/pyright.toml` (leaning; *Reasons in pyright's file*).

They're committed, so editors, CI and fresh clones see them; the rest of `.lup/` stays ignored. Each opens with a banner: "Generated from `lup_project.py` by `lup settings`. Don't edit it: change `lup_project.py`, or override in `pyproject.toml`." They're written with tomlkit, a new dependency, each ruff rule turned off carrying its reason as a comment, as lup's `pyproject.toml` carries them; `tomli-w` would drop the reasons.

**What they hold:** lup's defaults, plus what the declaration implies.

| Setting | From | In lup's `pyproject.toml` |
|---|---|---|
| ruff's `select` and `ignore` | lup's selection (`select = ["ALL"]` and the rules it turns off, each with its reason, `catalog/tools.py`), minus the ruff rules whose owning lup rule isn't selected (below) | `[tool.ruff.lint]`, reasons as comments |
| ruff's `src` | the source roots: `src/`, and each uv workspace member's `src/` | `["packages/*/src"]` |
| ruff's `extend-exclude`, pyright's `exclude` | the excluded role | two lists, by hand |
| ruff's per-file ignores for tests (`S101`, `D`, `ARG`, `INP001`) | lup's defaults, on the test roots | `"packages/*/tests/**"` |
| ruff's `task-tags`, `runtime-evaluated-base-classes`; the formatter leaving Markdown alone | lup's defaults | the same |
| ruff's `target-version` | written only where ruff can't infer it (below), from the workspace members' `requires-python`, the lowest | `py314` |
| pyright's strict mode, `enableTypeIgnoreComments = false` | lup's defaults | the same |
| pyright's `include` | the source and test roots | `["packages"]` |
| pyright's Python version | not written: pyright reads the interpreter it's given | `"3.14"` |

**Ruff rules owned by a lup rule follow it.** Each ruff rule lup turns off says why, and most say which lup rule owns the concern (`PLR5501` "steers an `else` holding an `if` to `elif`": owner `elif`). When a project drops that lup rule, its ruff rules come back on, rather than the two selections staying independent, so dropping a rule never leaves its concern without an owner: drop `regex`, and ruff's checks on `re` calls return. Dropping `CodeRules` brings every one back.

**Every path is written from the file's own directory** (`"../../tests/**"`), since both tools resolve a base file's relative paths from where that file sits. Checked in a scratch project (ruff 0.16.10, pyright 1.1.414): with `"tests/**"` in `.lup/settings/ruff.toml`, ruff resolved the per-file ignore to `.lup/settings/tests/**` and the tests' `S101` findings stayed; with `include = ["src"]` in the extended pyright file, pyright analysed no file. Written as `"../../tests/**"` and `"../../src"`, both applied.

**ruff's target version:** ruff infers it from `requires-python` in the `pyproject.toml` holding `extend` (checked: 3.12 from `>=3.12`). For a uv workspace whose root `pyproject.toml` has no `[project]`, as lup's, it infers none for a member without its own `[tool.ruff]` (checked: `linter.unresolved_target_version = none`, the formatter falling back to 3.10), so lup writes it there.

### Where the project's own settings go

**`pyproject.toml` stays the project's.** lup reads it, and the overview shows its tool tables as the project's changes to lup's defaults; lup never writes it after `lup new`. `lup new` writes one pointer per tool:
- `[tool.ruff] extend = ".lup/settings/ruff.toml"`;
- `[tool.pyright] extends = ".lup/settings/pyright.toml"`.

For an existing project without them, the settings step fails, naming the line to add; lup doesn't add it.

**The project's own settings in `pyproject.toml` win, layered by the tools themselves.** A project changes ruff the way any ruff user does, in `pyproject.toml`, with a comment for its reason. The declaration has no `ruff=`, `pyright=` or `contracts=` field, from which the tools' own files at the root would be generated whole (`ruff=Ruff.default().drop(…)`).

### Layering

Checked in scratch projects with ruff 0.16.10 and pyright 1.1.414 (a base with `select = ["ALL"]` and `ignore = ["E501", "D", "INP001", "COM812"]`, extended from `pyproject.toml`):
- **ruff adds** a project's `ignore`, `extend-select`, `extend-exclude` and `extend-per-file-ignores` to the base's. The project's `ignore = ["T201"]` left no `E501`, `D` or `T201` finding, and `ANN001` was still found.
- **ruff replaces** with a project's `select`, which restarts the selection and drops the base's `ignore` with it (`select = ["D", "ANN"]` brought `D` back though the base ignores it), and with a project's `per-file-ignores`, which drops the base's (the tests' `S101` came back; `extend-per-file-ignores` kept it off).
- **pyright** takes the base's `typeCheckingMode = "strict"`, and a project's setting wins over the base's of the same name: its `reportUnusedVariable = "none"` held, and its `exclude` replaced the base's list rather than adding to it.
- **Workspace members:** ruff uses the nearest `pyproject.toml` holding a `[tool.ruff]` table, or a `ruff.toml`. A member without one gets the root's settings (checked: its settings path is the root's `pyproject.toml`). A member with its own `[tool.ruff]` and no `extend` is cut off from lup's settings entirely, and ruff checks it with its own defaults (checked: no `ANN` or `T201` finding in it, its settings path its own). A member's `extend = "../../pyproject.toml"` chains to the root's and through it to lup's (checked: lup's selection applied, the member's own `ignore` on top, its target version its own `requires-python`).

So **(leaning)**:
- **the settings step checks every ruff and pyright configuration in the worktree,** the root's and each member's, in `pyproject.toml` or the tool's own file: each must extend lup's file, directly or through another, or the step fails naming the line to add (`extend = "../../pyproject.toml"` for a member). Otherwise a member's own table would quietly put it outside lup's settings.
- **A setting that replaces lup's** (a ruff `select` or `per-file-ignores`, any pyright list) is the project's right, so it isn't refused; the overview names it as replacing lup's, so it's never done unknowingly. The alternative, refusing it at the gate, would impose lup's settings on a project that has its reasons.

lup's own `pyproject.toml` after B keeps `[tool.ruff] extend` with lup's own change, `INP001` off for `packages/lup-dev/checker/build.py`, under `extend-per-file-ignores` (under `per-file-ignores` it would drop the tests' ignores); `[tool.pyright] extends`; `[tool.pytest]` and `[tool.importlinter]` as they are. Its 80 ruff ignores move into `catalog/tools.py`.

### pytest and import-linter

- **pytest has no layering.** `lup new` writes lup's few defaults into `[tool.pytest]` as the project's own: `testpaths` from the test and doctest roots, and `addopts` (`--doctest-modules`, `--import-mode=importlib`). The settings step checks that pytest's `testpaths` covers the declared test and doctest roots, and never rewrites them.
- **import-linter:** lup has no default contracts for a project, so a project's contracts stay in `[tool.importlinter]`, and the gate's `lint-imports` step runs when that table (or `.importlinter`) is present. lup's own contracts stay in lup's `pyproject.toml`.

### Reasons in pyright's file

Every ruff rule lup turns off carries its reason as a comment in `ruff.toml`. pyright parses its configuration as JSON with comments (`JSONC.parse` in `analyzer/service.ts` at 1.1.414), but Python's `json` writes no comments, and building JSON text by hand is what lup's parsing rules exist to stop. pyright also reads a TOML base: `_getExtendedConfigurations` parses any `extends` target ending in `.toml` as a `pyproject.toml` and reads its `[tool.pyright]` table (checked in the source, and in a scratch project, where a `.lup/settings/pyright.toml` with comments was extended and its strict mode applied).

**`.lup/settings/pyright.toml` (leaning),** a `[tool.pyright]` table written by tomlkit with each setting's reason as a comment, as ruff's are. One writer, one format, the reasons beside the settings. The alternatives:
- **`.lup/settings/pyright.json`, the name the operator gave, without comments:** the reasons live only in the catalog and on the overview;
- **JSON with comments built as text:** what the parsing rules stop.

The cost of TOML: a `[tool.pyright]` table in a file that isn't a `pyproject.toml` reads oddly, and an editor's pyright must follow a TOML `extends` (Pylance is pyright; listed under *Checks owed*).

### How lup's settings are judged

`.lup/settings/**` takes the `compiled` role, ahead of scratch (`.lup/**` is otherwise scratch, `catalog/paths.py`), as `DESIGN.md`'s protected paths have it (*Policy*):
- **a write equal to what the judge generates from the integration branch's declaration is allowed,** so an agent runs `lup settings` after a declaration change lands on `dev` and nothing asks twice for one decision;
- **any other write is judged as a protected path's:** it asks, and made through the shell it's refused with the pointer to the file tools. A hand edit, or settings generated by a lup version other than the installed judge's, reaches the operator and never lands unseen.

The alternatives: protected outright, which refuses an agent's regeneration as a shell write; or unguarded, left to the settings step alone.

It's the integration branch's declaration for the same reason the judge reads only that one (`docs/judging-writes.md`, *Every worktree of the repository*): a branch never changes what judges it. The settings also read the workspace members' `pyproject.toml` (their `src/` and `requires-python`), so a branch changing a member's `requires-python` sees its regenerated settings ask until the change is on `dev`.

**The settings step** (`settings`, `Python`'s, before ruff) fails when a generated file is stale (naming `lup settings`), when a pointer is missing (naming the line), or when pytest's `testpaths` misses a declared root. A `pyproject.toml` holding a tool's table doesn't fail it: those tables are the project's legitimate overrides.

**`.gitignore`** takes `/.lup/*` and `!/.lup/settings/`. Checked with git 2.56: `.lup/` followed by `!.lup/settings/` keeps the settings ignored, since git never looks inside an ignored directory.

## Dependencies

A project's package dependencies stay in `[project]` and `[dependency-groups]`, uv's and the packaging standard's. Declaring them in the declaration and generating `pyproject.toml` whole would make the declaration the one source, at the cost of a tool editing Python source, a changed habit, and every tool that edits `pyproject.toml` (dependency bots, `uv add`) stopping. The overview gives the one place to read.

**The tools lup runs come with lup.** ruff, pyright, pytest and import-linter become `lup-dev`'s dependencies, pyright pinned to the release the engine is built against; a project lists `lup-dev` alone in its development group, rather than listing and pinning each. lup's defaults are written against those versions (ruff's `select = ["ALL"]` turns on whatever a later ruff adds), and a project whose pyright drifted from the engine's would see its type errors judged by one release and gated by another. The engine's build reads pyright's release from `uv.lock`, which keeps working: the lock then holds `lup-dev`'s pin.

## The rules

### Selecting them

`CodeRules.rules` is a `Rules` selection. Its own default is every rule but those `catalog/rules.py` leaves out, each with its reason (`runtime-mention` until E moves it to lup's own table), written as a project writes a change: `Rules.all()` with one `.drop(…, why=…)` for each. So `Rules.default()` there names lup's default, the overview shows why each is left out, and `Rules.all()` is every rule.

The judge sends each module's selection, recorded as it is (its starting point and its operations, each with its names), with the module's own default, in each check request (`Selected`, `declaration/resolve.py`), and **the engine resolves it** (`checker/src/catalog.ts`), rather than Python resolving it and sending ids: it holds the tables, so nothing asks it for its rules first, and an unknown name fails there with the names it has. The union of every selected module's rules runs.
- **A module's selection is every layer applied over its own default,** as `Modules` places it, so its operations begin with the default's: `Rules()` starts from nothing beneath them, and a layer's `Rules.default()` from the module's own default, resolved. A module's own default starting from `Rules.default()` would be itself, and the engine refuses it, steering to `Rules.all()`, `Rules.only(…)` or `Rules()`.
- **`Rules.of(…)` resolves as `Rules.only(…)` does** until E: a module has no table of its own yet, so its entries are lup's rules, by id.
- **`lup-dev rules check` and the judge send the same selection,** read from the declaration the worktree is judged by (`Worktree.selected`, `policy/checkpoint.py`), as is the one the turn's end sends; exemptions and `ignore` apply after, in Python.

The alternative was the engine knowing lup's default itself, from a list of ids left out sent with each request or marked in `catalog/rules.ts`: one module's default would then be a notion of the engine's, and `Rules.default()` in a project's module would mean lup's default rather than that module's own.

#33 changes lup's defaults: which ruff rules `catalog/tools.py` turns off, and which lup rules `catalog/rules.py` leaves out of the default. Both are data the operator reviews, made of the entries a project uses to change its own.

### A project's own rules

Built in E, right after A. The reason: the first lup was too rigid, which is exactly why projects never got in the habit of drafting their own rules. Modularity and overriding are a core orientation, and "no project wrote one" is evidence of that rigidity, not an argument for later.

**A rule table belongs to a module,** rather than one `lup_rules.ts` at the root per project. lup's rules are `CodeRules`'s; a project's module names its own table, written as lup's are: each entry with its mistake, steer, check and examples. A project can have several, each going with its module, so dropping the module drops its rules. Ids are shared across tables, as every kind's names are, rather than namespaced by project, and a clash fails the load naming both modules. To change one of lup's rules, a project drops it and adds its own under another id, and that's an upstream candidate.

**Spelled `rules=Rules.table("rules/narration.ts")` (leaning),** a path from the root. The operator's spelling is `rules="rules/narration.ts"`; `Rules.table` keeps one type for the part across modules, so `Rules.default().drop(…)` reads the same in lup's module and a project's, and `CodeRules` is declared the way `Narration` is. With it, **lup's own table is loaded the same way from E:** shipped as `catalog/rules.ts` and loaded when the engine starts, rather than compiled into the bundle. lup then runs the path every project runs, and a change to lup's table needs no engine rebuild. The alternatives: the operator's plain string, with `CodeRules`'s `rules` then a different type from a project's module's; lup's table kept bundled, a path only lup takes.

**They're loaded when the engine starts.** The engine shipped in `lup-dev` imports each selected module's table itself, by stripping its types: no build per project, which would need pyright's source and pnpm in each. Checked: a CommonJS bundle built as `build.py` builds the engine (esbuild 0.28.2, `--platform=node --target=node20`) kept `import()` as it was, and Node 26.10 loaded a `.ts` table with an interface and a typed constant through it, no flag. What the stripping refuses (Node's documentation): enums, namespaces holding values, parameter properties, and any `.ts` under `node_modules`; a table needs none of them. An engine started with other tables is replaced, as one started from another build is. The other alternatives: Python rules asking the engine by position, which a spike rejected; and no project rules, architecture checks written as tests.

**How a table reaches the engine's helpers (leaning):** it imports them by a fixed name, `import type { Catalog } from 'lup-engine'` and `import { python } from 'lup-engine'`, and the engine maps that name to a module it ships, with Node's `module.registerHooks` resolve hook. Checked in the same scratch: the hook, registered from the CommonJS bundle, resolved `lup-engine` for the stripped table, and its `python` examples ran. The table's own imports are types and that one name, so it's written as lup's table is. The alternative, a table exporting a function the engine calls with its helpers, reads differently from lup's.

**Writing and checking them:**
- **`rules new <id>`** writes a skeleton entry, with its examples, into a module's table (the only table, or `--module narration`). The examples are its tests: a skeleton fails until its `flags` example is filled.
- **`rules check <file>`** runs the selected rules, lup's and the project's, on one file.
- **The gate runs each table's examples** as lup's tests run lup's: each of `flags` gets a finding from its rule alone, each `rewritten` passes every selected rule, ruff and pyright, and each of `passes` gets none. It type-checks the table too.
- **A check that throws** is reported as that rule's finding, naming the error, never swallowed and never failing the file's other rules.

Inserting an entry into an existing table, and type-checking one, take a TypeScript parser. **Ship TypeScript's compiler beside the engine (leaning),** from pyright's pinned source tree (pyright 1.1.414 pins `typescript ~6.0.3`; `lib/typescript.js` is 8.8 MB unminified), loaded only by `rules new` and the table check, never by the judge's engine. `rules new` then inserts the entry where the parser places the table's last entry, and the check type-checks against the helpers' declaration files. The alternatives: `tsc` as an optional requirement, with `rules new` writing only new tables and the type check off without it; or one file per rule, which `rules new` writes whole, at the cost of a layout unlike lup's table.

Either way the engine's helpers (`File` and what it returns) become lup's public API, versioned, with migrations when one changes.

**How they're reviewed: as the declaration is.** Each table a selected module names is protected, so every change to it reaches the operator, and the judge reads it from the integration branch's tip, so a branch's rule runs only once it's on `dev`. The declaration is already code the judge imports and runs, reviewed this way; the tables add nothing to the judge. The alternative is approving a table by its content, in a review of its own, from the start or once trust on launch is built.

### Rules and conventions

Built in D. `docs/conventions.md` lists each section's rules by hand under *Enforced by:*, and a test checks only that each id it names exists (`tests/test_reference.py`), so a rule can run with no written decision behind it. The table says which section each rule belongs to in a comment heading each group of entries, naming the section.

**(i), which the operator will look at again:**
- each rule entry in `catalog/rules.ts` names its section, `convention: 'dispatch'` (the heading's anchor), instead of the comment heading each group;
- `docs/rules.md` is generated grouped by section, each group linked to its reason;
- a conventions section's *Enforced by:* line points to its group instead of listing ids; ruff's, pyright's and import-linter's parts stay hand-written;
- a test fails when a rule names a section `docs/conventions.md` lacks;
- a section is a family: `Rules().drop(family="dispatch", why=…)`, and #33's round can go section by section.

The alternatives: (ii) the hand-written lists, checked both ways, redundant but policed; (iii) the *Enforced by:* lines generated into the conventions, generated text inside a hand-written document.

**A project's rule names its section only if it wants to (leaning).** In a project's table, `convention` is optional, naming a section of a conventions document the module declares (`conventions="docs/conventions.md"`), checked the same way when given. Requiring it would impose lup's way of documenting on downstream projects, as requiring a `why` would impose lup's needs (*One grammar for every kind*). lup's own tables, `CodeRules`'s and lup's own module's, require it, by lup's test.

## The command line

Built in C. Until then `lup-dev` (`cli.py`) stands in: a Typer app importing every subsystem at startup, which every hook call pays.

- **One command, `lup`, shipped by `lup-dev`; the library ships none,** rather than a `lup` in the library finding the environment's groups through entry points. `runs` and the outcome loop are the library's and callable from code; making one a command is the project's own wiring, or `lup-dev`'s job.
- **Built from the selected modules' commands, loading only what's invoked,** rather than Typer's tree built at import. The root is a click group (Typer's base) whose entries are data: a name, a target in entry-point form (`"lup_dev.commands.holds:app"`), a one-line help. Listing commands (`lup --help`) reads the data and imports nothing; invoking one imports its target alone, a Typer app turned into a click command. click's own help listing calls `get_command` for every entry (`click/core.py`, `format_commands`), so the group lists from its data instead. A dropped module's commands are absent by construction. A command of `Core`'s runs without loading the declaration; `--help` and any other command load it.
- **Only the hook command is fixed:** the hook is the core's (`DESIGN.md`, *The environment: core and modules*), and a project can't patch it; every other command is an entry a project can replace or drop, by editing the module holding it.
- **A module's commands are top-level entries of its own (leaning):** no module adds a subcommand to another's group, since a module's parts change only through that module (*What a module is*). So lup's own module serves `lup install` and `lup rules-docs` (`lup-dev rules docs`, which writes lup's `docs/rules.md`), not `lup rules docs`. The alternative, a module adding to another's group, would make a group's contents depend on which modules are on.
- **lup's commands, by module:**
  - `Core`: `hook claude|codex` (fixed), `check [--fix]`, `holds [approve|decline]`, `verdicts`, `project`, `new`, `docs`, the hidden `importers`;
  - `Python`: `settings [--check]`;
  - `CodeRules`: `rules list|check|new`;
  - lup's own module: `install`, `rules-docs`.

  `lup-dev`'s `submit`, `wait`, `reviews` and `reply`, and the hidden `review keep` that parks their reviews in the first lup's dashboard, serve the drafts flow, which the design leaves behind (`docs/graveyard.md`), so no module holds them.
- **Published commands are the standard `[project.scripts]`.** They're installed with the package under the project's own name, so its users never need lup. `lup --help` lists them, marked published, read from `pyproject.toml` without importing them. The declaration's commands are development-only. The rejected alternative: `Command(published=True)`, with lup writing `[project.scripts]`, a table the project owns.
- **A published command never imports `lup_dev` (leaning).** A step of `Python`'s builds the import graph with grimp, import-linter's own graph library, and fails when any `[project.scripts]` target's module reaches `lup_dev` (`chain_exists(importer=…, imported="lup_dev", as_packages=True)`), naming the chain (`find_shortest_chain`). Checked: grimp 3.17 comes with import-linter 2.15 in lup's environment, and both calls answered on lup's own packages. Using it directly makes it `lup-dev`'s declared dependency, the operator's to approve. The alternative, a `forbidden` contract lup writes into `[tool.importlinter]`, writes into a table the project owns.
- **`lup new <name>`** makes a project: `uv init --lib --build-backend uv --vcs git` (checked: it writes `pyproject.toml`, `src/<name>/__init__.py` and `py.typed`, `.python-version`, `.gitignore`, a README, and a git repository), then lup's part: the package's `__init__.py` rewritten to a module docstring (uv's `hello()` has none, which ruff refuses), `lup_project.py` binding `Project(modules=Modules.default())`, `tests/` with one test, the two pointers and `[tool.pytest]` in `pyproject.toml` (tomlkit, keeping uv's layout), `/.lup/*`, `!/.lup/settings/` and `tmp/` in `.gitignore`, `uv add --dev lup-dev` at the running lup's release, lup's settings files, and a first commit. It passes the gate as made. The alternative, lup's own templates for every file, is the first lup's scaffold again, and Jinja would be a new dependency.
- **`lup docs rules [<rule>]`** prints the reference from the installed engine (`codescan/reference.py`), which refusals already point at. The hand-written docs (`conventions`, `declaration`) need packaging, since they live outside the package, and come with guidance.
- **The rename:** the package's script becomes `lup`. The hooks in `.claude/settings.json` and `.codex/hooks.json` call the installed `lup-dev` by path, so they switch in a commit landed once the operator has installed the judge carrying `lup`; switched first, every hook would fail open until then. The alternative timing, keeping `lup-dev` until the launch piece compiles the hooks, means a second rename later. `AGENTS.md` (`uv run lup-dev check`) is the operator's to change, and CI's command switches with the script.
- **A test, not a timer:** the command line's tests check which Python modules `lup --help` and `lup hook` import (`sys.modules` after the call), so no test depends on wall-clock time.

`cli.py` becomes the lazy root; each command group is a file of `lup_dev/commands/`, the top layer; the list of adapters moves into `commands/runtimes.py`, which the import contract keeping the adapters behind one place then names.

## Rooms

A room is the library's `Room` (`Room(agent=…, container=…)`, leaning in `DESIGN.md`, *The library*), declared in the project's own code, which production code imports from the project's package (`from audiobook.rooms import narrator`). A module of the declaration references it by address (`rooms=Rooms.of("audiobook.rooms:narrator")`), so the environment can launch it and show it.

The rejected alternative: rooms declared in `lup_project.py` and used from code. `lup_project.py` isn't shipped in the wheel, so production code importing a room from it fails once installed; and it imports `lup_dev`, so where it did import, the environment would become a production dependency.

## Later: what the rest of the declaration holds

Each built with the piece that first reads it; its shape is here so the grammar holds for it.

- **Guidance and skills (the launch piece, which renders them):** each module's `guidance` and `skills` parts: `Guidance.of(Section(name="pipeline", path="guidance/pipeline.md"))` in a project's module, `.edit(Core(guidance=Guidance.default().replace("code", Section(…), why=…)))` for one of lup's. Rendered into one template at launch. Rendering checks that no section names a command the project doesn't serve. A path in a module of lup's is a package resource (`"lup_dev.modules.ledger:skill.md"`).
- **Runtimes and their spellings, session settings (the launch piece):** `Core`'s `runtimes` (the adapters `cli.py` lists becoming lup's defaults, so a project can bring an adapter of its own) and `session` parts.
- **Nested projects (the gate's nested environments):** a test root in a project of its own runs through the runner from that project's directory (`Pytest(root="studio/tests", project="studio")`), and lup's pyright settings get an execution environment for it, as adlib needed for `studio/` on Python 3.13.
- **pyright per path** (nori's `reportMissingImports = "none"` under one directory): the project's own `[tool.pyright]` in `pyproject.toml`, with a comment for its reason.
- **Personal config** (`~/.config/lup/config.toml`): accounts, theme, budget shares, the projects on this machine; between lup's defaults and the project in precedence (`DESIGN.md`). Not a project's, and read by launch, the dashboard and budgets.
- **Upstream candidates** (`DESIGN.md`, open question 6): the `why` on a `.drop`, `.edit` or `.replace` is where one starts, where there's one.

## Where the code goes

In `packages/lup-dev/src/lup_dev/`. The declaration is a subsystem of its own (`docs/conventions.md`, *Package layout*), rather than `project.py` at the package's root with its neighbours beside it, and sits between the catalog it reads and the subsystems that read it: `adapters` > `policy` > `codescan` > `declaration` > `catalog`.

| File | What it's for | Slice |
|---|---|---|
| `__init__.py` | The front door for a declaration: every name `lup_project.py` imports, lup's modules among them, in `__all__`, rather than imported from `lup_dev.declaration.…`. It imports only the declaration's models, so loading a declaration costs pydantic and nothing more | A |
| **`declaration/`** | **What a project declares, and reading it** | |
| `declaration/grammar.py` | `Selection`: a kind's starting point (the value below, or one it starts over from) and its recorded operations, resolved at load | A |
| `declaration/module.py` | `Module`, its parts, its `requires`, and `.edit`; `Modules`, the selection of modules | A |
| `declaration/kinds.py` | Each kind as a `Selection`: `Rules`, `Paths`, `Gate`, `Commands`, `Rooms`, later `Skills`, `Guidance`, `Runtimes` | A |
| `declaration/project.py` | `Project`, holding `modules`, and `asks` until the judge's asks become proposals | A |
| `declaration/runner.py` | `Runner`, `Uv`, `Plain`; `Prefixed`, a runner kept as its commands, as the judge keeps one | A |
| `declaration/requirements.py` | `Requirement`, and checking a declaration's requirements all at once | A |
| `declaration/modules/` | lup's modules as `Module` subclasses, data only: `core.py`, `python.py`, `code_rules.py`, and the default list | A |
| `declaration/resolve.py` | A declaration resolved: each kind's entries from the selected modules, names checked, `Core` present, every required module present and no cycle, every layer applied in order, each value with the layer that set it | A |
| `declaration/load.py` | Finding `lup_project.py` or `lup_project/` at a worktree's root or in a commit's export, and importing it (`importable`, `import_roots`, moved from `project.py`); `ProjectError` | A |
| `declaration/settings.py` | lup's settings files from a resolved declaration; the pointer, drift and `testpaths` checks | B |
| `declaration/overview.py` | Everything about a project on one page | B |
| **`catalog/`** | **lup's defaults, made of the entries a project's own additions are made of** | |
| `catalog/paths.py` | The default path patterns, one list per role, `Core`'s and `Python`'s (exists; gains `compiled`) | A, B |
| `catalog/gate.py` | `Step` (exists), and the default steps without lup's engine build, which moves to lup's own module; gains the `settings` step | A, B |
| `catalog/rules.py` | The rules lup's default leaves out, each with its reason: `runtime-mention` until E | A |
| `catalog/tools.py` | `RuffRule` (a code, why it's off, and the lup rule owning its concern, if one does), and lup's settings for ruff and pyright | B |

**Where lup's modules live (leaning):** in `declaration/modules/`, data only, importing nothing but the declaration's models and the catalog, so loading a declaration stays cheap; each module's machinery is in its own subsystem, reached by address (`"lup_dev.ledger.cli:app"`). `Modules.default()` is recorded, and `resolve.py` reads the default list, so `module.py` never imports lup's modules. The alternative, each module declared beside its machinery, would import that machinery at every load.

The catalog is the lowest layer: it holds the entry types and lup's values, and imports nothing of lup's but `lup.types`.

Elsewhere:
- **`policy/roles.py`** reads the resolved `paths`, and in B the `compiled` role; the protected list gains each selected module's rule table.
- **`policy/checkpoint.py`**, **`policy/judge.py`**, **`cli.py`** pass each module's rule selection to the engine.
- **`codescan/engine.py`** sends the selections, and starts the engine with the runner's interpreter command and, from E, the tables' paths; **`checker/src/catalog.ts`** resolves a selection; **`checker/src/program.ts`** takes the interpreter command and the environment's files from its start arguments, and stamps lup's pyright settings file with pyright's other configuration, so a change to it builds another program.
- **`codescan/ruff.py`** runs ruff through the runner; `UV_RUN` goes.
- **`gate.py`** checks requirements first, then runs each step through the runner; its own `Runner` becomes `Processes`.
- **`install.py`** finds the engine's build step in lup's declaration, and runs it through the declaration's runner as the gate does.

## Building it

**The order (leaning): A, E, B, C, D.**
- **E needs only A:** a table belongs to a module.
- **B needs A:** `Python` holds the settings, and the ruff rules that follow their lup rule read the resolved rule selection. It doesn't need E.
- **C needs A and B:** the command line is built from the modules' commands, and `lup new` writes the pointers to B's files.
- **D needs only A** (a family is one more way to name rules in `Rules`' verbs), and waits on the operator's second look at *Rules and conventions*.

The alternative order, A and B, then the command line, D, E, builds a project's rules last, which *A project's own rules* turns down.

**A, `feat-declaration`:**
1. `declaration/` with the grammar, `Module`, `Modules`, `Project` (`extra="forbid"`), the kinds, loading `lup_project.py` from the root.
2. lup's modules, `Core`, `Python` and `CodeRules`, with the data `Project`, `catalog/paths.py` and `catalog/gate.py` hold moved into them: the path roles split between `Core` and `Python`, the gate's steps, the exemptions.
3. The rule selection, recorded, sent by the judge and `lup-dev rules check`, resolved by the engine.
4. The runner, used by the gate, ruff and the engine; `UV_RUN` and `environmentOf`'s spelling of uv go.
5. Requirements, checked by the gate before its steps; `node` for `CodeRules`, `uv` through `Uv()`, `npm` for lup's own module.
6. lup's own declaration rewritten as modules: `LupDevelopment` with the engine's build step, `runtime-mention` added back to `CodeRules`'s selection.

Order matters for lup itself, since the installed judge reads `dev`'s tip with its own, older code:
- **`lup_project.py` moves to modules in A,** since A's gate loads it with A's `Project`. Once A lands, the judge installed before can't load it, so the last declaration that loaded judges instead, and the agent is told once (`docs/judging-writes.md`, *Every worktree of the repository*), until the operator installs the judge from A.
- **`[tool.lup]` stays until then,** and goes in a commit on `dev` after the install. Removed with A, the judge installed before would find no pointer and judge by the defaults, losing `catalog/**`'s protection without a word: a missing pointer isn't a failure to load, so no stand-in covers it.

**E, `feat-project-rules`:** `Rules.table`; the engine loading tables at start through `lup-engine`, lup's own table among them; `rules new` and `rules check` (as `lup-dev rules …` until C); each table's examples and type check at the gate; tables protected; `runtime-mention` moved into lup's own `rules/lup.ts`.

**B, `feat-tool-settings`:** `catalog/tools.py` (the ignores from `pyproject.toml`, each with its reason and owner); generating `.lup/settings/`; the settings step with its pointer and `testpaths` checks; the `compiled` role; `lup-dev project`; the tools as `lup-dev`'s dependencies; lup's `pyproject.toml` reduced to its pointers and its own changes, and its `.gitignore` taking the two `.lup` lines. #33's broadening can then run on lup's catalog.

**C, `feat-command-line`, then D, `feat-rule-sections`.** The rest with the pieces that read them.

**Tests:** the grammar's operations and their errors, layers stacked across a base and a project among them, with the layer each value came from; the declaration loaded from a root and from an export, unknown fields refused; one test per lup module dropped, with whatever requires it; a required module dropped while one requiring it stays, and a cycle, refused; names clashing across modules; the runner's commands for the gate, the judge and the engine, with uv stubbed through the runner; requirements met, missing and optional, with each probe stubbed; the engine resolving a selection, and refusing an unknown name; a project's table loaded, its examples run, a throwing check reported; lup's settings for a sample declaration, byte for byte; the `compiled` role allowing what the generation gives and asking otherwise; the settings step failing on a stale file, a missing pointer, a member's own `[tool.ruff]`, and a missed test root.

## Checks owed

- **A base imported from another package (*The verbs on modules*):** whether adding the project's environment's packages after the judge's own, when loading the declaration, imports a base without clashing with the judge's own dependencies.
- **`uv tool install` of `lup-dev` with the tools as its dependencies:** the judge's tool environment grows by ruff, pyright, pytest and import-linter; whether that matters for the install's time.
- **Editors and lup's settings:** that Pylance follows a TOML `extends` as pyright 1.1.414 does (*Reasons in pyright's file*), and that ruff's editor server follows `extend` from a member as the command line does.
- **TypeScript beside the engine (*A project's own rules*):** its size once minified by esbuild, and the time to load it for `rules new`.
- **An editor resolving `lup-engine` in a project's table:** a `tsconfig.json` beside the table whose `paths` point into the installed `lup-dev`'s declaration files, written by `rules new`.
