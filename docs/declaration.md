# The declaration: what a project declares in `lup_project.py`

A project says what lup does for it in one file, `lup_project.py` at its root: a `Project` holding the modules it's made of. Every part lup has (path roles, code rules, gate steps, guidance, the room's packages, session settings, the limits on the operator's credentials, the tools a session gets, requirements) comes from a selected module, lup's own included, so a module brings everything it needs and takes it away when it's dropped (`DESIGN.md`, *Modules*). The code is in `packages/lup-dev/src/lup_dev/declaration/`.

A word on words: a **module** here is a `Module` (`Core`, `Python`). A Python source file is a **file**, and its import path a **Python module** where it matters.

## What we have

### A project is its modules

lup's own declaration, abridged (`lup_project.py`):

```python
from pathlib import Path

from lup_dev import (
    CodeRules, Exemption, Exemptions, Gate, Guidance, Module, Modules, Package,
    Packages, Paths, Project, Pytest, Python, Requirement, Rules, Section, Step,
    TestRoots,
)


class LupDevelopment(Module):
    """What only lup's repository needs: building lup's engine, guarding its policy, its guidance."""

    name = "lup-development"
    requirements = [
        Requirement(tool="npm", why="installs the engine's bundler", install="it comes with Node", package="npm")
    ]

    packages: Packages = Packages.of(Package(name="chromium", why="Playwright drives it to look at the dashboard"))
    paths: Paths = Paths.of(protected=["packages/lup-dev/src/lup_dev/catalog/**"])
    gate: Gate = Gate.of(
        Step(
            name="engine",
            command=["python", "packages/lup-dev/checker/build.py"],
            builds="packages/lup-dev/src/lup_dev/codescan/bundle/engine.js",
            sources=["packages/lup-dev/checker/src/**/*", "uv.lock", …],
        ),
        before="rules",
    )
    guidance: Guidance = Guidance.of(Section(name="lup", path=Path("AGENTS.md")))


project = Project(
    modules=Modules.default()
    .edit(
        Python(tests=TestRoots.of(Pytest(root=Path("packages/*/tests")))),
        why="each package's tests are in its own `tests/`",
    )
    .edit(
        CodeRules(rules=Rules().add("runtime-mention")),
        why="a rule about lup's own architecture, which lup's default leaves out",
    )
    .edit(CodeRules(exempt=Exemptions().add(
        Exemption(rule="constant-home", paths=["packages/lup-dev/src/lup_dev/catalog/**"], why=…),
    )))
    .add(LupDevelopment()),
)
```

Read from the top:
- **Every name comes from `lup_dev`,** the front door (`lup_dev/__init__.py`), which binds what a declaration imports, lup's modules among them.
- **`Modules.default()` is lup's default modules:** `Core`, `Python`, `CodeRules`, `GitHub`, `Transcripts` and `Private` (*lup's modules*). `.edit` puts a layer on one of them that names only what it changes: `Python(tests=…)` changes `Python`'s test roots and leaves everything else as it was. `.add` brings in a module that isn't there yet, lup's own module here.
- **A collection changes by operations on what's below it.** `Rules().add("runtime-mention")` means `CodeRules`' rules as they stand, plus one. `Exemptions().add(…)` likewise adds an exemption to those already there. So the second `.edit(CodeRules(…))` keeps what the first one did, and no layer restates another (*The verbs on modules*).
- **`why` is optional** on `.edit`, `.drop` and `.replace`, and is kept with the change for whoever reads the project later. An `Exemption` always carries its own.
- **`LupDevelopment` is a module written the way lup's own are:** a `Module` subclass whose name and requirements are class attributes and whose docstring is its one sentence. Its parts are fields whose defaults are its own. `before="rules"` puts its step ahead of `Python`'s `rules` step. That works because names are per kind and shared across modules.
- **`held` and `flagged` are the fields of `Project` that aren't a module's** (`declaration/project.py`). They name what a change asks that waits for the operator's answer, and what lands flagged for their review, in one vocabulary: a path's role (`protected`, `operator`), a kind of change (`new-file`, `whole-file`, `public-api`, `ignore`, and `private`, a value never published on a line it touches), or one of lup's rules by its id. lup's own declaration takes the defaults, `held=["protected", "operator", "ignore"]` and `flagged=["new-file", "whole-file", "public-api", "private"]`; a project holding a rule's findings adds its name, as `held=["protected", "operator", "ignore", "regex"]`. A name in both lists, or one that's neither a role, a kind nor shaped like a rule's id, fails the load; a rule's id is checked against the engine's table when the judge first reads it (`docs/judging-writes.md`, *What each change gets*).

A project without a `lup_project.py` gets `Project()`, which equals `Project(modules=Modules.default())`.

### Where it lives

- **The file:** `lup_project.py` at the worktree's root, binding `project`, or the package `lup_project/` whose `__init__.py` binds it. Having both fails the load. Nothing points at the declaration; the loader looks there (`declaration/load.py`, `load`; the paths are `CheckoutLayout`'s, `layout.py`). Without either, the defaults apply. A declaration that can't be imported, or binds no `Project`, raises `ProjectError` and never falls back to the defaults, which would judge with the wrong roles.
- **Outside the package:** the declaration sits outside the project's own package, so it isn't shipped in the wheel and production code can't import it. That matters because a declaration imports `lup_dev`, and production code never does.
- **How it's imported:** with `import_roots` on the path, which are the root and its `src/`, plus each uv workspace member and its `src/`. The judge runs from its own installed copy, without the project's environment. So a shared base kept in a package of its own is found only when it's a workspace member. `importable` undoes the imports afterwards, so a second worktree's declaration loads fresh in the same process, and it writes no bytecode into the worktree.
- **Who reads which copy:** the declaration's file has the protected role (`policy/roles.py`, `Declaration.source`), so every change to it reaches the operator. The judge reads it at the commit the operator last approved through trust on launch, and the gate reads it from the worktree (`docs/judging-writes.md`, *The declaration, from the approved commit*). Trust on launch approves it together with every file it imports (`launch/trust.py`; `docs/launch.md`, *Trust on launch*). Only the declaration's own file is protected by role, though: the other files of a `lup_project/` package are judged as code, and take effect once approved.
- **A person's own layer, `lup_project.local.py`:** one per repository, in its main worktree, which is a clone's root or a bare repository's own directory (`person_layer`). It's gitignored and protected (`catalog/paths.py`).
  - It binds `project` too: a `Project` written as a layer on the project's, in the same grammar. `Project(modules=Modules().add(…))` adds a module, and `Modules().edit(Transcripts(data=Mounted(always=False)))` changes one.
  - It runs after the declaration, in the same import, so it can import the project's own modules from `lup_project`. Its name holds a dot, so it's run from its path (`executed`). `Declared.local` names it.
  - It holds what a person sets up for themselves, the other repositories they relate above all (`docs/related-repositories.md`, *A person's own layer*).
  - The host runs it, so trust on launch approves it by its content (`docs/related-repositories.md`, *Trusted by its content*). The judge and a launch read the approved copy, put beside the commit's export. A commit that holds one anyway has it left out of every export (`read_by_import`). The gate reads the main worktree's copy.

### The verbs on modules

Everything a declaration writes is a layer on what's below it, naming only what it changes. Below a project are lup's default modules, and below a person's layer is the project. One rule holds for every value, `applied` in `declaration/grammar.py`:
- **A module, wherever it's written** (in `.add` or `.edit`, or bound to a name), means "that module below, with these changes". The fields it set (pydantic's `model_fields_set`) apply, and every other field stays as below has it. A field given, even at its default value, counts as set. Where nothing is below, as for a module just added, the module's own defaults are below.
- **A selection starting from `Kind()`** keeps below's start and records its operations after below's. One that starts over, from `Kind.default()`, `.all()`, `.only(…)` or `.of(…)`, replaces below's whole (*One grammar for every kind*).
- **A `Layer`** is a model of settings holding several values (`Paths`, `Session`, `Credentials`). It applies the fields it set, as a module does, and each selection inside it composes over below's. So `Core(session=Session(auto_memory=True))` keeps lup's removed tools.
- **Any other value replaces below's,** whether it's a scalar or a model that isn't a `Layer`, such as a runner. Merging two runners of one class field by field would surprise a reader who expects the later one to replace the first.

What this costs: a scalar can't be put back to lup's default above a base that changed it, short of a `.replace` with a fresh module.

Each field a layer set is credited to that layer, by its place in the chain and its `why` (`Module.origins`). That record is there for an overview to show where every value came from.

The verbs on `Modules` (`declaration/module.py`):

| Verb | Means |
|---|---|
| `Modules.default()` | lup's default modules (`declaration/modules/shipped.py`) |
| `Modules.all()` | every module lup ships; no optional module ships yet, so it's the default |
| `Modules.only(*modules)` | exactly these, each with its settings: a module a later release adds to the default doesn't come in |
| `Modules()` | the modules below, to change: lup's default in a project, the project's in a person's layer |
| `.add(*modules)` | a module that isn't there; one already there is an error, steering to `.replace` |
| `.drop(name, why=…)` | without the module of that name |
| `.edit(module, why=…)` | the module of `module`'s name, with `module` as a layer on it |
| `.replace(name, module, why=…)` | another module in its place, from its own defaults: a project in another language replacing `Python` with its own |

- **`.edit` takes the class of the module it edits.** Another class fails and steers to `.replace`, so a swap is visible in the declaration.
- **A module has `.edit` too:** `ours.edit(CodeRules(…))` is `ours` with that layer on it. Modules and selections are plain values, so a project can bind one to a name, import it, and build on it.
- **A name that isn't there,** given to `.drop`, `.edit` or `.replace`, fails the load and names the modules that are.
- **`Core` is required.** Modules that leave it out fail the load (`resolve.py`, `checked`).

### One grammar for every kind

Every collection a module holds is a selection (`Selection`, `declaration/grammar.py`): where its entries start from, and the operations that change them. Both are recorded as written and resolved only when the declaration is read.

| Start or verb | Means | Example |
|---|---|---|
| `Kind()` | the value below, to change; nothing, where nothing is below | `Rules().drop("tuple-shape")` |
| `Kind.default()` | the defaults: lup's for `Modules`, the module's own inside a module | `Rules.default()` |
| `Kind.all()` | every entry lup knows | `Rules.all()` |
| `Kind.only(*names)` | these known entries, by name, and no other | `Rules.only("regex")` |
| `Kind.of(*entries, before=…, after=…)` | these entries, with no defaults: a module's own | `Gate.of(Step(…), before="rules")` |
| `.add(*entries, before=…, after=…)` | beside the entries there; a name already there is an error | `Exemptions().add(Exemption(…))` |
| `.drop(*names, why=…)` | without these; a name not there is an error, naming those that are | `Rules().drop("tuple-shape", why=…)` |
| `.replace(name, entry, why=…)` | `entry` in place of the one named, which must be there | `Guidance().replace("core", Section(…))` |

`only` and `of` belong to `Named`, the base of every kind except `Modules`, whose `only` takes modules because a module carries its settings.

- **Recorded, resolved at load.** `Rules.default().drop(…)` takes the rules a later release adds to the default, and `Rules.only(…)` doesn't. Every layer is composed first, each module over its own defaults and the project's modules over lup's, and only then is a selection resolved. So `Kind.default()` starts from the module's own default, resolved, and `Kind()` from nothing beneath it, since the default's operations are already in its chain.
- **Names are per kind and shared across modules.** A step can go `before="rules"` though `rules` is `Python`'s step. One name from two modules fails the load, naming both (`resolve.py`, `distinct`). Some kinds merge instead of clashing:
  - a path pattern given by two modules is one pattern;
  - a package given by two modules, or by a module and a requirement, is one package, the first's;
  - a related repository named twice is one repository where both give the same path;
  - two modules exempting one rule each keep their exemption, for their own paths;
  - a requirement is checked for each module that needs it.
- **Order across modules** comes from `before=` and `after=`, which name another entry of the kind, whichever module holds it. Entries with neither keep the order of their modules (`Selection.ordered`).
- **Methods, not set arithmetic.** The declaration is ruled code, so `Rules.all() - {"regex"}` would meet lup's own `set-shape` rule there.

The kinds (`declaration/kinds.py`):

| Kind | Entries, named by | Held by lup's |
|---|---|---|
| `Rules` | rule ids | `CodeRules.rules` |
| `Paths` | a `Layer` of one `Patterns` per role: `protected`, `operator_documents`, `excluded`, `scratch`, `docs`, `data`, `source_trees`, `python`, `conftest`. A pattern is its own name, and the verbs take roles as keywords: `Paths().add(protected=[…])` | `Core.paths`, `Python.paths` |
| `Gate` | `Step`s (`catalog/gate.py`), by name | `Python.gate` |
| `Exemptions` | `Exemption`s, by rule: one per rule within a module, listing every path | `CodeRules.exempt` |
| `TestRoots` | `Pytest` roots, by path | `Python.tests` |
| `Packages` | `Package`s of the room's image, which is Arch's, by name | `Core.packages` |
| `Session` | a `Layer`: `subagent_cache`, `auto_memory`, `idle_compaction`, `removed_tools` (a `RemovedTools` of names), `account_connectors` | `Core.session` |
| `Credentials` | a `Layer`: `actions`, an `Actions` of the names `host/protocol.py`'s `Action` lists; `protected` and `gated`, each a `Refs` of patterns over full ref names | `Core.credentials` |
| `Guidance` | `Section`s, by name: a file from the root, or one a Python package ships | each of lup's modules but `GitHub` |
| `Repositories` | `Repository`s, by name | none: a person's layer holds them |
| `Toolsets`, `Handlers`, `Hooks` | `ModuleTools`, `ModuleHandler` and `ModuleHooks` classes, by class name | `GitHub`, `Transcripts`, `Private` |
| `Details`, `Values` | the details lup reads on the host, by name; the person's own values, each a plain string (`private/module.py`) | `Private` |

`Actions` refuses a name that isn't an action, and `Refs` a pattern that doesn't start with `refs/`, where they're written. Two fields aren't selections. `Mounted` says whether a module's own data is mounted in rooms. Every module has `conditions`: the Python module declaring the conditions a `defer` waits on, by dotted name.

### What a module is

A module is a `Module` subclass (`declaration/module.py`):
- **Class attributes:** `name`, `requires` (the modules it can't work without) and `requirements` (tools from outside the project's environment). They aren't fields, so no layer can blank them out.
- **One sentence:** the first paragraph of its docstring (`Module.sentence`).
- **Fields:** its parts and its own settings (`Python.runner`, `GitHub.limit`), each defaulting to the module's own value. A module declares a field for each part it fills.
- **No unknown fields:** `Module` forbids fields it doesn't know (`extra="forbid"`), as `Project` does, so a misspelled field fails the load. `lup.types.Model` alone would drop it without a word.

Defining the class checks it (`__pydantic_init_subclass__`). Each failure raises `ProjectError`, naming the module and the field:
- **no `name`, or no docstring;**
- **a field with no default:** a module added with nothing set has to stand on its own defaults;
- **a plain collection:** a field typed `list`, `dict` or any other plain collection, optional or not. A layer would replace it whole, so a base couldn't be extended without restating it; it takes a selection instead;
- **a default starting from `Kind.default()`,** directly or inside a `Layer`: nothing is beneath a module's own default, so it would start from itself. `Kind()` and `Kind.of(…)` start from nothing there.

The class then completes the classes its defaults list (`Selection.complete`). That way a tools class that narrows `module` to a module defined after it, in the same file, needs nothing more.

At load, every module a selected module `requires` must be selected too, and no modules may require each other in a cycle (`resolve.py`, `checked`). lup never adds or drops a module behind the project's back.

**What a module serves a launch** (`declaration/serving.py`). It all runs on the host, in a process of the launch's own, from the repository's approved copy (`lup_dev/worker.py`). The host service passes it each call, request and moment (`host/workers.py`); the core's tools, the inbox's, and git's helper stay in the service.
- **Tools,** `tools: Toolsets = Toolsets.of(GitHubTools)`: classes of `ModuleTools`, each tool a method decorated with the library's `@lup_tool`. A class narrows `module` to its module's class (`module: GitHub`), so a tool reads its module's settings through `self.module`, beside `self.launch` and `self.caller`.
- **Handlers,** `handlers: Handlers = Handlers.of(Stating)`: `ModuleHandler`s, each narrowing `request` to the model of the room's requests it answers. A request's `kind` routes it to its handler, which reaches its module, the launch, the module's own data directory and the other repositories the declaration names, as the host finds them (`related`), through `self`.
- **Hooks,** `hooks: Hooks = Hooks.of(TranscriptsHooks)`: `ModuleHooks` classes, each method marked with `@lup_hook`.
  - A method runs at the moment its name names, or at those its `on` names. lup's moments are `launched`, `stopped` (once the launch's session has fully stopped), `publishing` (before anything leaves under the operator's name), and the five each runtime's hooks are read as: `session_started`, `call_started`, `call_finished`, `turn_ended` and `conversation_ended`.
  - A hook observes a `Moment`, returning nothing, except at `publishing`, the one moment a hook answers (`ANSWERED`): there it returns its refusals (`list[Refusal]`, `host/publishing.py`), each naming what it found and where, and one refusal keeps the push or the post from leaving. A hook failing there refuses too, since what wasn't checked doesn't leave; a hook refusing at a moment it only observes has failed. lup fires `publishing` with what would leave (`Moment.published`): a push through git's remote helper, with each ref it updates and what the remote holds already (`Push`), or a post through a module's tool, each of its parts (`Post`), which the tool puts through its `door` first (`ModuleTools.publish`; `docs/private.md`).
  - Through `self` it reaches its module, the launch, the runtime's session records (`Records`), the module's own data directory, and the other repositories the declaration names, as the host finds them (`related`, each a `Related`).
- **Data,** `data: Mounted = Mounted()`: the module's own data directory for the repository, mounted at its host path, read-only unless it says otherwise.
  - It's mounted in every room with `Mounted(always=True)`, or only in a room whose launch lends it by the module's name (`lup-dev launch <runtime> --mount transcripts`) with `Mounted()`.
  - A guidance section names where with `{{ data("transcripts") }}`, and asks whether it's there with `{% if mounted("transcripts") %}` (`launch/guidance.py`).
  - `Transcripts` mounts its copies of past sessions in every room, so a session reads the operator's own words on why the work is shaped as it is, with `lup-dev transcripts` (`list`, `show`, `search`; `lup/transcripts/views.py`), each runtime's records read by its adapter (`Reader`, `host/records.py`). Its guidance says what's read there is what was said then, not a decision for now. A project or a person's layer keeps them out with `Transcripts(data=Mounted(always=False))`.
- **Checked at load:**
  - a tool's name and a request's kind are shared across modules, so the same one from two modules fails;
  - a class narrowed to another module's class fails;
  - a tool or hook named like a field of its class (`module`, `launch`, `caller`, `records`, `data`) is refused when the class is defined, since pydantic would drop it without a word (`lup/tools/tool.py`, `refuse_taken`).

### lup's modules

`Modules.default()`, in order (`declaration/modules/shipped.py`):

| Module, name | Where | What it holds |
|---|---|---|
| `Core`, `core` | `declaration/modules/core.py` | `paths`: every protected path but the Python tools' files, plus the operator's documents, scratch, docs and data (`catalog/paths.py`, `CorePaths`). `packages`: the standard machine (`catalog/room.py`). `session`: lup's defaults (`SessionDefaults`). `credentials`: every action but `force-push` and `delete-ref`; `refs/heads/main` and `refs/tags/*` protected, `refs/heads/dev` gated (`catalog/credentials.py`). Guidance `core` |
| `Python`, `python` | `declaration/modules/python.py` | `paths`: the Python tools' manifests, lockfiles and configuration files (protected), source trees, Python files and `conftest.py` (`PythonPaths`). `runner`: `Uv()`. `tests`: `TestRoots.of(Pytest(root=Path("tests")))`. `gate`: `rules`, `format`, `pytest`, `lint-imports` (`catalog/gate.py`). Guidance `python` |
| `CodeRules`, `code-rules` | `declaration/modules/code_rules.py` | `rules`: `Rules.all()` with a `.drop` for each rule `catalog/rules.py` leaves out, with its reason (`runtime-mention` alone today). `exempt`: none. Guidance `code-rules`. Requires Node `>=22.18` for the engine |
| `GitHub`, `github` | `lup/github/module.py` | `tools`: `GitHubTools`. `handlers`: `Stating`, which tells a room's gate whether an issue is open. `limit`: the most matches `find_issues` asks for |
| `Transcripts`, `transcripts` | `lup/transcripts/module.py` | `hooks`: `TranscriptsHooks`, copying the runtime's session records when a launch opens and when it stops. `data`: `Mounted(always=True)`. Guidance `transcripts`, naming `lup-dev transcripts` |
| `Private`, `private` | `lup_dev/private/module.py` | `details`: `Details.all()`, what lup reads on the host never published. `values`: none, the person's own. `hooks`: `PrivateHooks`, refusing at `publishing`. `handlers`: `Scanner`, the gate's step in a room. `gate`: `private`. Guidance `private` (`docs/private.md`) |

- **`Core` is every project's.** It's the part of the core a project can change. `Python` and `CodeRules` stay apart from it so each is one line to drop: dropping `CodeRules` turns off all of lup's code rules.
- **The `rules` step is `Python`'s.** It runs `lup-dev rules check`, which also runs pyright's and ruff's checks, so neither is a step of its own (`catalog/gate.py`).
- **`Core`, `Python` and `CodeRules` are data,** read from the catalog: lup's defaults, made of the same entry types a project writes (`catalog/`). Their guidance sections are files `lup_dev` ships (`declaration/modules/guidance/`).
- **`GitHub` and `Transcripts` live beside their machinery,** in the library's packages. The import contract keeping the library off `lup_dev` lets those two packages import it (`pyproject.toml`, `[tool.importlinter]`). `Private` lives beside its machinery in `lup_dev`, which the judge reads too; `lup_dev.private` isn't one of the layers the import contract orders.

### lup declares itself the same way

lup's own `lup_project.py` (*A project is its modules*) uses only the surface any project uses. What only lup's repository needs lives in its module `LupDevelopment`:
- **the engine's build step,** ahead of every other step. Trust on launch builds the copy it installs with the same step, through the same runner (`launch/trust.py`, `engine`);
- **`catalog/**` protected,** since that's where lup's policy data lives;
- **`AGENTS.md`** as the project's own section of the guidance, after the sections of lup's modules;
- **Chromium in the room,** and npm as a requirement.

`runtime-mention` fires on a runtime's name outside that runtime's adapter. That's a rule about lup's own architecture: in a project that picks its runtime by a setting, it would fire on every choice. So lup's default leaves it out, and lup's declaration adds it back. lup's import contracts stay in its `pyproject.toml`, as a project's own contracts do.

### Resolving it

`resolve(project)` (`declaration/resolve.py`) applies every layer, then reads each kind from the modules that hold it, by the kind's type. The result, `Resolved`, holds:
- the modules, in order, with their origins;
- each role's patterns (`PathRoles`);
- the gate's steps, in the order they run;
- each module's rule selection, as recorded (`Selected`);
- the exemptions, the test roots, and the conditions modules;
- the runner, and every requirement, the runner's among them;
- the image's packages, the session settings, the credentials' limits, the guidance sections, and the related repositories;
- what's held and what's flagged;
- what's served: tools, handlers, hooks, and which modules' data rooms mount.

A few things come from a single module:
- **The runner** comes from the one module holding a `Runner`, or is `Plain()` where none does. Two runners fail, since a project runs its tools one way.
- **The session settings and the credentials** come from the one module holding them, `Core`. A second holder fails, naming both: a project's sessions run one way, and a launch has one set of limits.

**What judging reads** is kept apart, as a `Declaration` of plain values: the declaration's file, the path roles, the test roots, the exemptions, the conditions, the rule selections, the runner as `Prefixed`, and what's held and flagged. The test roots are none where they're lup's default, and then pytest's configuration says where tests are (`policy/roles.py`).

Plain values matter because a module or a runner may be a class of the project's own, which JSON can't bring back. The judge keeps the last declaration that loaded as JSON, to stand in for one that can't (`docs/judging-writes.md`, *The declaration, from the approved commit*). `ProjectError` is the one error for every way a declaration is wrong, so a reader catches it alone to put the stand-in in place.

### What a launch reads

A launch reads the declaration at the approved commit (`launch/session.py`, `approved_declaration`), resolved:
- **Packages:** every module's own, in module order, then each requirement's `package`, which comes in with the requirement's reason.
- **Session settings:** `Core`'s `session`, as `SessionChoices`, in neutral terms that each runtime's adapter spells.
  - Its `declared` names the fields some layer set. Those are imposed over the person's own runtime settings; the rest are lup's defaults, which theirs outrank (`docs/launch.md`, *The settings compiled for each runtime*).
  - `declared` is read off the final value's `model_fields_set`. `applied` makes each layer a copy of the one below with its fields updated, which pydantic counts as set, so a field set to lup's own value still counts as declared.
- **The limits on the operator's credentials:** `Core`'s `credentials`, resolved to a `Limits` (`host/protocol.py`). That's the actions allowed, in `Action`'s order, plus the protected and the gated ref patterns. It's sent with the launch's registration, and the host's handlers hold each action to it (`docs/host-tools.md`, *What the declaration allows*). Each selection changes where it stands, so allowing force pushes is an `.add`, with its reason:

  ```python
  .edit(
      Core(credentials=Credentials(actions=Actions().add("force-push"), protected=Refs().add("refs/heads/release/*"))),
      why="feature branches are rebased before review; release branches are the operator's",
  )
  ```
- **Guidance:** each module's sections, rendered into one document (`launch/guidance.py`; `docs/launch.md`, *Guidance*). A `Section` is either `path` from the project's root, or `package` and `path` for a file a Python package ships. They're given apart, since a single entry-point string would need parsing and refuses a hyphen in a file name.
- **The rest:** the related repositories, each mounted read-only; the runner's `room()` (*The runner*); the tools, handlers and hooks each module serves; and which modules' data rooms mount.

### Selecting the rules

`CodeRules.rules` is a `Rules` selection. Its default is `Rules.all()` with a `.drop(…, why=…)` for each rule `catalog/rules.py` leaves out. So `Rules.default()` in a layer on `CodeRules` means lup's default, the reason for each rule left out travels with it, and a rule a later release adds runs unless it's left out too.

Python only composes and records a selection. Each check request carries every module's selection with the module's own default (`Selected`), and the engine, which holds the tables, resolves them (`checker/src/catalog.ts`) and runs their union:
- **Unknown ids** fail in the engine, which names the ids it has.
- **A module's own default starting from `Rules.default()`** is refused there, as `Module` refuses it when the class is defined.
- **`Rules.of(…)`** picks lup's rules by id, as `Rules.only(…)` does, since no module has a table of its own yet.

The judge, the turn's end and `lup-dev rules check` all send the same selection: the one from the declaration the worktree is judged by (`Declaration.rules`), so a stand-in sends its own. Exemptions and `# lup: ignore` apply afterwards, in Python.

**Listing what a selection runs** goes through the same resolution, with no project loaded: the engine's `rules` command, given the selections on its input, prints the rules their union runs, in the table's order, and refuses what a check would; given nothing, the whole table (`Checker.rules`). `lup-dev rules list` lists the worktree's own declaration's rules that way, and `--all` the whole table, each it doesn't run marked `(left out)`. A launch asks for the approved declaration's, which a section of the guidance lists (`docs/launch.md`, *Guidance*).

### The runner

`Python.runner` says how the project runs its tools (`declaration/runner.py`). Everything that runs a tool in the project's environment derives its command from it, so uv is spelled once, in `Uv`.

```python
class Runner(Model, ABC):
    def command(self, tool: list[str]) -> list[str]: ...   # the gate's: it may make or sync the environment
    def judging(self, tool: list[str]) -> list[str]: ...   # the judge's: it never writes the project's files
    def environment(self) -> list[str]: ...                # the files whose change means another environment
    def room(self, root: Path, tools: Tools) -> RoomNeeds: ...  # what a room mounts and sets for it
```

- **`Uv()`,** the default:
  - `command`: `uv run …`.
  - `judging`: `env -u VIRTUAL_ENV uv run --frozen --quiet …`. It never relocks, so the judge never writes `uv.lock`, a protected path the checkpoint would then judge as the agent's write. `VIRTUAL_ENV` is unset so the judge's own environment isn't taken for the project's.
  - `environment`: `pyproject.toml`, `uv.toml`, `uv.lock` and `.python-version`.
  - It requires uv.
- **`Plain()`:** each tool as the `PATH` finds it, for a project with no environment manager, and the runner wherever no module holds one. It has no environment files, no requirement, and mounts nothing.
- **`Prefixed`:** a runner kept as its commands, which is how judging holds one. Its `room()` refuses.
- **A project's own runner** is a subclass of a few lines: `poetry run`, `conda run -n …`.

The gate and the judge get separate commands because the gate may lock and sync (plain `uv run` relocks a stale lock), while the judge must never write the project's files.

**Its contract:** a runner runs a tool by putting its own command before it, so `command(tool)` is `command([])` followed by the tool, and likewise for `judging`. That contract is what lets `Prefixed.of(runner)` keep any project's runner as plain data that a stand-in judges with.

**What a room needs,** `room(root, tools)`. A launched session works in the worktree's own environment, shared with the host (`docs/launch.md`, *The project's environment, shared with the host*). So the runner says what the room mounts and sets for it: a `RoomNeeds` of mounts, variables, and the environment's `Interpreter` with the remedy to give when it resolves outside every mount. The launch refuses an interpreter outside the room's mounts (`launch/room.py`).
- **What `Uv` asks:** it asks uv from the worktree, with `VIRTUAL_ENV` unset, through `Tools`, which tests stub.
  - `uv python dir`, mounted read-only.
  - `uv cache dir`, mounted read-write, and made if missing, since a mount needs its source.
  - `uv python find`, the interpreter.
- **In the room,** `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` name the same two places, and `UV_PYTHON_DOWNLOADS=never` keeps uv from fetching an interpreter (`docs/field-notes.md`, *Rooms*).
- **The remedy** for an environment on a system interpreter is `uv sync --managed-python`.
- **Four abstract methods:** `room()` takes `Runner` past the three that `interface-shape` allows, which the class's `ignore` names. Putting it on the runner means each project's runner says what its environment needs in a room.

Where it's used:
- **The gate:** each step's command is the tool alone, run as `runner.command(…)`, or as written for a step with `in_environment=False` (`Step`, `catalog/gate.py`). The gate uses the worktree's own declaration's runner. Its own seam for running a process is `Processes` (`gate.py`), so `Runner` means one thing in `lup_dev`.
- **ruff in the judge:** `runner.judging(["ruff", "check", …])` (`codescan/ruff.py`).
- **The engine:** it's started with `judging(["python"])` and `environment()` as `--interpreter` and `--environment-files`. Every request carries the same pair (`EngineEnvironment`, `codescan/engine.py`), so an engine started with another runner is replaced.
- **Passed with each call:** ruff and the engine get the runner with each call (`Linter.findings`, `Checker.check`, `Checker.importers`) rather than holding one, because the judge's services are built once per hook, before it knows which worktrees it judges.

It doesn't cover `PythonAvailable`'s `uv python list` (`codescan/conditions.py`), which asks uv as a provider of Pythons. It doesn't cover trust on launch's `uv tool install` either, which installs lup itself.

### Requirements

A requirement is a tool from outside the project's Python environment (`declaration/requirements.py`). Each module declares its own as a class attribute, and a runner brings its own: `Uv` needs uv, `Plain` nothing. Being a class attribute, a requirement can't be blanked out by an `.edit`.

```python
Requirement(tool="node", version=">=22.18", probe=["node", "-p", "process.versions.node"],
            why="runs the rule engine", install="https://nodejs.org/en/download", package="nodejs")  # CodeRules
```

- **Fields:**
  - `tool`, or `any_of` for alternatives;
  - `version`, a specifier, with `probe`, the command printing the tool's bare version;
  - `optional`;
  - `why` and `install`, shown when it's missing;
  - `package`, the Arch package providing it in lup's room, which joins the image, so a module names it once.
- **Versions are read with `packaging`** from what the probe prints, so nothing parses a tool's banner. Without `version`, the check is only that the tool is on the `PATH`.
- **The gate checks them,** every selected module's at once, before any step (`gate.py`). A required one missing stops the gate, naming every one missing, the module needing it and how to install it (`RequirementError`). An optional one missing is said once, at the head of the report.
- **A launch checks the host's own needs** the same way (`launch/room.py`, `host_needs`): podman and git, plus `gh` and `notify-send` as optional. The modules' requirements reach the room as packages of its image.
- **Node is installed on the system,** not shipped as a Python package. `>=22.18` is the oldest Node that strips TypeScript types without a flag, which a project's own rule tables will need (`docs/field-notes.md`, *The declaration*).

### Where the code is

In `packages/lup-dev/src/lup_dev/`:

| File | What it holds |
|---|---|
| `__init__.py` | The front door: every name a declaration imports, in `__all__`. It imports the declaration's models and what they're typed by (the library's tools, sessions and rooms, the host's protocol), never the judge's or the gate's machinery |
| `declaration/grammar.py` | `Selection` with its starts and operations, `Named`, `Placed` and the ordering by anchors; `Layer`, and `applied`, the one layering rule |
| `declaration/module.py` | `Module`, the checks on its class, `.edit` and `Origins`; `Modules` |
| `declaration/kinds.py` | Every kind and its entries |
| `declaration/project.py` | `Project` |
| `declaration/errors.py` | `ProjectError` |
| `declaration/load.py` | `load` and `Declared`; `import_roots`, `importable`, `person_layer`, `read_by_import` |
| `declaration/resolve.py` | `resolve` and `Resolved`; `Selected`, `SessionChoices`; `Declaration`, what judging reads |
| `declaration/runner.py` | `Runner`, `Uv`, `Plain`, `Prefixed`; `RoomNeeds`, `Interpreter` |
| `declaration/requirements.py` | `Requirement`; `Tools` and `Machine`; `check` and its `Report` |
| `declaration/serving.py` | `ModuleTools`, `ModuleHandler`, `ModuleHooks`, `Moment`; `Door`, which a tool publishes through (`UnpublishedError`); `ANSWERED` |
| `declaration/modules/` | `Core`, `Python` and `CodeRules`; `shipped.py`, the default list and every module shipped; `guidance/`, their sections |
| `catalog/` | lup's defaults, which the modules read: `paths.py`, `gate.py` (`Step`), `rules.py`, `room.py`, `credentials.py` |

In `lup_dev`'s layers, the declaration sits below `codescan` and above `catalog` (`pyproject.toml`, the contract "lup_dev's subsystems import downwards"; `docs/conventions.md`, *Package layout*).

## Where it's going

### More of lup in modules

- **More kinds:** commands, skills, rooms, runtimes (the adapters `cli.py` lists, so a project can bring its own), doctest roots, and test roots in nested projects of their own. A module will also be able to declare kinds of its own for other modules to fill.
- **More modules:** lup's further modules, such as a ledger, coordination requiring it, a git workflow, and optional ones like budgets and releases, so `Modules.all()` grows past the default. In time, each module becomes a distribution of its own.
- **Judging decided by modules:** judging a write still decides with its own code rather than its modules'. The aim is that nothing in lup's core reads a default a project can't change (`DESIGN.md`, *Modules*: nothing built in).
- **References by import:** a module refers to its code by importing it, as `Toolsets` do, and the gate checks that loading the declaration imports nothing heavy. Rooms become named selections of modules on top of the project's own (`DESIGN.md`, *Modules*).
- **A change's `why`** is where an upstream candidate starts.

### A project's own rules

- **Tables:** a module names a rule table of its own, TypeScript written the way lup's `catalog/rules.ts` is, each rule with its mistake, steer, check and examples. The engine loads each table when it starts, by stripping its types, with no build per project, and lup's own table is loaded the same way.
- **Names and review:** rule ids are shared across tables, as every kind's names are. A table is protected and read at the approved commit, like the declaration.
- **Writing and checking them:** `rules new` writes a skeleton entry, `rules check` runs on one file, and the gate runs each table's examples and type-checks it. A check that throws is reported as that rule's finding. The engine's helpers become lup's public API, versioned.
- **`runtime-mention`** moves into lup's own table.

The reason to do this early: the first lup was too rigid for projects to get into the habit of writing their own rules.

Each rule will also name the section of `docs/conventions.md` it enforces. That gives rules their families, which can be dropped at once, and groups `docs/rules.md` by section.

### lup's settings for ruff and pyright

- **lup's own files:** lup writes `.lup/settings/ruff.toml` and a pyright file, generated from its defaults and the declaration by `lup settings` and committed. Each ruff rule turned off carries its reason as a comment.
- **The project's `pyproject.toml`** extends them (`[tool.ruff] extend`, `[tool.pyright] extends`) and stays the project's, its own settings layered by the tools themselves. When a project drops a lup rule, the ruff rules that rule owns come back on.
- **A settings step** checks that the files are current, that every ruff and pyright configuration in the worktree extends lup's, and that pytest's `testpaths` covers the declared test roots. Until then, where the declaration keeps lup's default test roots, the judge takes them from pytest's configuration.
- **A `compiled` role** for `.lup/settings/**`: a write equal to what the judge generates is allowed, and any other asks.
- **The tools come with `lup-dev`:** ruff, pyright, pytest and import-linter become its dependencies, pyright pinned to the engine's release. Package dependencies stay in `[project]`.

How the tools layer an extended base is measured in `docs/field-notes.md`, *Tools* and *The declaration*.

### The command line

- **One lazy `lup` command,** shipped by `lup-dev` and built from the selected modules' commands, each an entry of a name, a target and a help line. Listing them reads that data; invoking one imports its target alone. Only the hook command is fixed. Until then, `lup-dev` (`cli.py`) stands in.
- **Published commands** stay the standard `[project.scripts]`.
- **`lup new <name>`** makes a project that passes the gate as made.
- **`lup project`** shows the whole project on one page: the modules on, their parts, the project's changes with their reasons ("no reason given" otherwise), the requirements met or not, the runner, the dependencies, and lup's settings with the project's overrides. The dashboard shows the same page.
- **Guidance sections are checked** against the commands the project serves, once `Commands` say what those are.
