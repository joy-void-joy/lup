# The declaration: one place a project says what it is, extending lup as lup extends itself

**One sentence:** a project writes one `Project` in `lup_project.py` at its root; lup reads it to know which paths are what, which rules and modules apply, how the project runs its tools, which commands it serves, and every tool's settings, which are compiled from it; and a project adds to or overrides anything lup declares with the same grammar and the same types lup uses for its own defaults.

This is the build order's step 2 (`DESIGN.md`, *Build order*): `Project` and its selections, and a command line built from it. It answers `DESIGN.md`'s open questions 8 (one overseeable place), 9 (how rules and conventions link) and 10 (a project's own rules), #36 (the runner), and gives #33 the selection grammar it needs.

**What this piece builds now (the first slice, two branches):**
- **Branch A, the declaration:** where it lives, `Project` with its fields, the one grammar, the rule selection reaching the engine, the runner (#36), the gate's steps from the declaration.
- **Branch B, compiled tool settings:** ruff's, pyright's, pytest's and import-linter's settings compiled from lup's defaults and the declaration, their own role in the judge, the drift step in the gate, and `lup-dev project`, the one page showing everything about a project.

**What it designs now and builds in later slices** (*Building it*, below):
- the command line: one lazy `lup` command built from the declaration, and `lup new`;
- each rule naming its conventions section, which gives rules their families (open question 9);
- a project's own rules (open question 10);
- modules, guidance, skills and runtimes as kinds a project selects and extends, each built with the piece that first reads it.

## What's there today

Checked against `dev` at `b51c538`:
- **`Project`** (`lup_dev/project.py`) holds what judging reads: `tests`, `protected` (`Protected.default().add(…)`), `excluded`, `exempt` (`Exemption`: a rule lifted from some paths, with its reason) and `conditions` (the module declaring `Condition`s, by dotted name). It derives from `lup.types.Model`, which ignores fields it doesn't know, so a misspelled field in a declaration is dropped without a word.
- **Where it's found:** `[tool.lup] project = "lup_project:project"` in `pyproject.toml`, loaded as an entry point, importing from the root, `src/` and each uv workspace member. The judge reads it from the integration branch's tip; the gate reads the worktree's (`docs/judging-writes.md`, *The declaration, from the integration branch*).
- **Rule selection:** the engine's client has `selected: list[str] | None` (`codescan/engine.py`), and the engine refuses an id it lacks (`checker/src/catalog.ts`, `selected`), but nothing sets it: every rule runs on every production file.
- **`uv run` is spelled in three places** (#36): the gate's steps (`catalog/gate.py`), ruff in the judge (`codescan/ruff.py`, `UV_RUN`), and the engine asking for its interpreter (`checker/src/program.ts`, `environmentOf`). Two more are out of the runner's reach: the narrow `Bash` allow rules in `.claude/settings.json`, which the launch piece compiles, and `PythonAvailable`'s `uv python list` (`codescan/conditions.py`), which asks uv as a Python provider, not as the project's runner.
- **The gate's steps** (`catalog/gate.py`) begin with building lup's own engine, a step only lup's repository has; the installer finds that step there too (`install.py`).
- **Tool settings** are hand-written in the root `pyproject.toml`: ruff's `select = ["ALL"]` and the 80 entries it turns off, each reason a comment beside it; pyright's; pytest's; the four import-linter contracts. Some say the same thing twice: the engine's bundle is excluded once for pyright and once for pytest, `.claude` once for ruff and once (as `.claude/hooks/**`) in `lup_project.py`.
- **Tool configuration files the tools read before `pyproject.toml`** (`ruff.toml`, `.ruff.toml`, `pyrightconfig.json`, `pytest.toml`, `.pytest.toml`, `uv.toml`) take the `data` role, so an agent can write one at any size without asking, and turn pyright's strict mode off unseen. Filed as #38.
- **The command line** is `lup-dev` (`cli.py`), a Typer app importing every subsystem at startup. Measured on this machine (one run each): `python -X importtime -c "import lup_dev.cli"` 246 ms, of which `lup_dev.policy.checkpoint` 112 ms; `lup-dev --help` 0.33 s; `lup_dev.project` alone 103 ms, mostly pydantic. Every hook call pays the whole import.
- **`runtime-mention`** fires on any name holding `claude` or `codex` outside `lup_dev.adapters` (`catalog/rules.ts`). It's a rule about lup's own architecture: in live-translator, which picks a runtime by setting, it would fire on every choice.
- `docs/conventions.md` and `docs/judging-writes.md` say the engine checks each file's imports against the import-linter contracts at the edit; nothing in the engine reads them. Filed as #39.

## What the first lup did, and what projects changed

From `lup-legacy` and the four projects that used it as their environment (nori, live-translator, swarm-search, and adlib in `test-animation`), read for this note. The first lup's library paths are under its `packages/lup/src/lup/`; a project's are in its own checkout.

| Area | The first lup | Here | Why |
|---|---|---|---|
| Where a project declared itself | A copied `harness/catalog.py` of 800 to 1,160 lines in each project, a `[tool.lup]` table with no model (each reader matched its own key: `workspace/paths.py`, `devtools/review/app.py`, `devtools/dev/git_guards.py`), `sync.json` | **Reshaped:** one `Project` in `lup_project.py`, a pydantic model, nothing copied | The copied half was the graveyard's first entry; a table with no model can't say what's misspelled |
| The grammar | `Selection[RuleT]`: `retired` ids plus `overrides` replacing a default of the same id (`seams.py:72-105`), for skills, agents, guidance, sub-apps. Code rules could only be retired; families were labels | **Kept and widened:** `.drop`, `.add`, `.replace` on every kind, families selectable | It worked where it existed; projects needed it for rules too |
| Declining a module | Its commands were still served: adlib declined `conversation` and `lup-devtools setup conversation chatgpt` stayed (`tmp/adlib-report.md` §13); prose in one module named another's commands, dangling once declined | **Reshaped:** a module's commands, skills and guidance are its contributions, so they leave with it | Subtracting from a full copy leaked |
| A project's own code rules | `DevProject.anti_patterns`, Python rules merged into the catalog (`devtools/project.py:148`) | **Designed for later**, written as lup's are | No project used it: nori wrote its architecture checks as pytest tests reading the AST (`tests/unit/test_verifier_boundary.py`) |
| Tool settings | Copied into each project and edited there; lup also wrote into `pyproject.toml` with tomlkit (pyright's `executionEnvironments`, `harness generate all`) | **Reshaped:** compiled whole from the declaration, into files of their own | ruff's settings were copied verbatim everywhere and went stale: live-translator still ignores `F401` for a `packages/lup/…` file it doesn't track (`pyproject.toml:119-125`). "Declaring any of this means hand-editing `[tool.pyright]`" (`tmp/adlib-report.md:247`) |
| Running tools | `uv run` hard-coded (about 55 literals), `.venv-contained` | **Reshaped:** the project's runner, `uv run` by default | pyright's `venv` was set by hand in three of the four projects to find the environment |
| The command line | Typer, built whole at import; about 10 s a call (`tmp/direction-research/DECISIONS.md:33`, never profiled), `import lup` alone 199 ms | **Reshaped:** built from the declaration, loading only the command invoked | |
| Dependency on lup | A branch pin each, all different: `dev`, a fix branch, a tag, a branch made for one project | Releases only (`DESIGN.md`) | nori 6197ef1f: "The pinned branch … was deleted upstream … re-resolving it failed outright" |

**What the projects actually changed**, which the extension surface has to make easy:
- **modules declined:** six to ten each;
- **rules:** none retired (live-translator, adlib), three (nori: `set-shape` and two others, for "worklist algorithms over genuine sets"), or about sixty, every one (swarm-search, `content/catalog.py:51`). In their own code the most suppressed rule was `constant-declaration`, 15 to 48 times per project, evidence for #33;
- **path roles:** extra test roots (nori's kernel suite, adlib's `studio`), data (`ledger/`, `design/evidence/`), scratch (`bench-out/`), protected additions;
- **one or two command groups** (adlib's `studio`: preview, listen, start fresh);
- **skills and guidance chapters of their own** (swarm-search's `ingest`; nori's "Witness-Only Trust", "What Counts As Progress");
- **nested projects with their own environment** (adlib's `studio/`: Python 3.13, torch, bun);
- **fetch scopes, sandbox exclusions, a gate-free "free" mode, edit gates relaxed** (nori's `.lean` proofs written whole): these are the launch piece's and rooms', not the declaration's core.

## Modules

In `packages/lup-dev/src/lup_dev/`. The declaration grows into several modules, so it becomes a subsystem of its own (`docs/conventions.md`, *Package layout*), between the catalog it reads and the subsystems that read it: `adapters` > `policy` > `codescan` > `declaration` > `catalog`.

| Module | What it's for | Branch |
|---|---|---|
| `__init__.py` | The front door for a declaration: every name `lup_project.py` imports, in `__all__`. It imports only the declaration's models, so loading a declaration costs pydantic and nothing more | A |
| **`declaration/`** | **What a project declares, and reading it** | |
| `declaration/grammar.py` | `Selection`: the one grammar, a kind's defaults plus the project's recorded operations (`.drop`, `.add`, `.replace`, `only`), resolved when the declaration is loaded | A |
| `declaration/project.py` | `Project` and its kinds, each a `Selection` whose `default()` reads the catalog: `Rules`, `Paths`, `Gate`; with `Pytest` and `Exemption`; moved from `lup_dev/project.py` | A |
| `declaration/runner.py` | `Runner`, the ABC saying how the project runs its tools; `Uv`, the default; `Plain`, the tool as the `PATH` finds it | A |
| `declaration/load.py` | Finding `lup_project.py` at a worktree's root or in a commit's export, and importing it (`importable`, `import_roots`, moved from `project.py`); `ProjectError` | A |
| `declaration/tools.py` | Compiling the tools' settings from lup's defaults and the declaration, writing them, and saying which are stale; the models of each tool's settings (`Ruff`, the import contracts) | B |
| `declaration/overview.py` | Everything about a project on one page, for `lup-dev project` | B |
| **`catalog/`** | **lup's defaults, made of the entries a project's own additions are made of** | |
| `catalog/paths.py` | The default path patterns, one list per role (exists; gains `compiled`) | A, B |
| `catalog/gate.py` | `Step` (exists), and the default steps, without lup's engine build, which moves to lup's own declaration; gains the `settings` step | A, B |
| `catalog/rules.py` | The rules lup's default leaves out, each with its reason: `runtime-mention` | A |
| `catalog/tools.py` | `RuffRule` (a code, why it's off, and the lup rule owning its concern, if one does), and lup's default tool settings: ruff's selection and every rule it turns off, pyright's and pytest's options | B |

The catalog stays the lowest layer, as today: it holds the entry types and lup's values, and imports nothing of lup's but `lup.types`. The kinds above it (`Gate.default()`, `Paths.default()`) read it.

Elsewhere:
- **`policy/roles.py`** reads `Project.paths`, and in B the `compiled` role (*How compiled settings are judged*).
- **`policy/checkpoint.py`**, **`policy/judge.py`**, **`cli.py`** pass the rule selection to the engine.
- **`codescan/engine.py`** sends the selection, and starts the engine with the runner's interpreter command; **`checker/src/catalog.ts`** resolves a selection; **`checker/src/program.ts`** takes the interpreter command and the environment's files from its start arguments.
- **`codescan/ruff.py`** runs ruff through the runner; `UV_RUN` goes.
- **`gate.py`** runs each step through the runner.
- **`install.py`** finds the engine's build step in lup's declaration.

## `Project`

### Where it lives

A file named `lup_project.py` at the worktree's root, binding `project`. Nothing points at it: the loader looks there, and `[tool.lup]` goes. Without the file, the defaults apply; a file that can't be imported, or binds no `Project`, is an error, never the defaults (as today).

The question was open (8): this, or a module named in `pyproject.toml` (`[tool.lup] project = "audiobook.lup_project:project"`), as today. The fixed file wins on three counts:
- the operator finds every project's declaration in the same place, which is the overseeable part;
- there's no pointer to keep right, or to repoint from a branch;
- it sits outside the project's package, so it isn't shipped in the wheel and production code can't import it. A declaration imports `lup_dev`; production code that imported it would make the environment a production dependency, which the split forbids (`DESIGN.md`, *Two packages*).

The declaration is protected, as today: every change asks. The judge reads it from the integration branch's tip, the gate from the worktree.

### Its fields

```python
from lup_dev import Exemption, ForbiddenImports, Gate, Paths, Project, Pytest, Rules, Ruff, Step, Uv

project = Project(
    paths=Paths.default().add(protected=["tests/spec/**"], data=["ledger/**"], excluded=["vendor/**"]),
    tests=[Pytest(root="tests"), Pytest(root="studio/tests")],
    doctests=["src"],
    rules=Rules.default().drop("collection-loop", why="the pipeline's stages are loops by design"),
    exempt=[Exemption(rule="set-shape", paths=["src/audiobook/schedule/**"], why="worklist algorithms over genuine sets")],
    runner=Uv(),
    gate=Gate.default().add(Step(name="lean", command=["lake", "build"], in_environment=False), after="pytest"),
    ruff=Ruff.default().drop("T201", why="the command line prints its progress"),
    contracts=[ForbiddenImports(name="the core never imports the studio", source=["audiobook.core"], forbidden=["audiobook.studio"])],
    conditions="audiobook.conditions",
)
```

| Field | What it says | Default | Branch |
|---|---|---|---|
| `paths` | Which paths are what: one pattern list per role (protected, operator's documents, excluded, scratch, docs, data, source trees) | `Paths.default()`, lup's patterns (`catalog/paths.py`) | A (replaces `protected` and `excluded`) |
| `tests` | The test roots: the test role, and pytest's `testpaths` and `python_files` | none, read from pytest's own configuration as today, until B compiles that configuration; then `[Pytest(root="tests")]` | exists; compiled in B |
| `doctests` | Source roots pytest reads for their doctests only, which stay production | `["src"]` | B |
| `rules` | Which of lup's code rules run | `Rules.default()` | A |
| `exempt` | A rule lifted from some paths, with its reason | `[]` | exists |
| `runner` | How the project runs its tools | `Uv()` | A |
| `gate` | The gate's steps, in order | `Gate.default()` | A |
| `ruff`, `pyright` | The project's changes to lup's tool settings | `Ruff.default()`, `Pyright.default()` | B |
| `contracts` | The project's import-linter contracts | `[]` | B |
| `conditions` | The module declaring the conditions a `defer` waits on | none | exists |
| `commands` | The project's own commands, and lup's it replaces or drops | `Commands.default()` | the command line's slice |
| `modules`, `guidance`, `skills`, `runtimes`, `rooms` | Below, *Later* | | with the pieces that read them |

`Project` forbids fields it doesn't know (`extra="forbid"`), so a misspelled field fails the load, naming it, instead of vanishing. That's a fix to today's model, made in A.

**References to the project's own code are strings,** in entry-point form (`"audiobook.conditions"`, `"adlib.studio.cli:app"`), as `conditions` is today. Loading the declaration then imports none of the project's code, which every `lup` call and every hook does; the gate imports each reference and fails on one that doesn't resolve. `DESIGN.md`'s example passes objects (`studio_cli`), which would import the project's command line, and whatever it imports, at every call, as the first lup's command line imported everything.

## One grammar for every kind

Every kind lup has defaults for (rules, path roles, gate steps, tool settings, commands, later modules, guidance, skills, runtimes) is a set of named entries the project starts from and changes with the same verbs:

| Verb | Means | Example |
|---|---|---|
| `Kind.default()` | lup's defaults: what a project gets by saying nothing | `Gate.default()` |
| `Kind.all()` | every entry lup ships, where that's more than the default | `Rules.all()` |
| `Kind.only(*names)` | these and no other | `Rules.only("regex", "string-split")` |
| `Kind.none()` | nothing of lup's, for what declares only its own | `Paths.none().add(data=["ledger/**"])` |
| `.drop(*names, why=…)` | everything but these | `Rules.default().drop("tuple-shape", why=…)` |
| `.add(*entries, before=…, after=…)` | the project's own, beside lup's; an existing name is an error | `Gate.default().add(step, after="pytest")` |
| `.replace(name, entry, why=…)` | the project's own in place of lup's; a missing name is an error | `Commands.default().replace("check", …, why=…)` |

- **Methods, not set arithmetic.** `DESIGN.md`'s example writes `Rules.all() - {"tuple-shape"}`, and lup's own `set-shape` refuses that set literal in `lup_project.py`, which is protected and ruled. Operators on lup's own type taking a list (`Rules.all() - ["tuple-shape"]`) would pass, but would be a second spelling of `.drop`.
- **A `.drop` or `.replace` of lup's defaults carries `why`.** The overview shows it, an update reads it when it asks whether to bring back what was dropped, and an upstream candidate starts from it. `.add` needs none: it's the project's own.
- **Recorded, resolved at load.** A selection keeps its starting point and its operations, and is resolved against the installed lup's defaults each time it's loaded. So `Rules.default().drop(…)` takes the rules a later release adds, and `Rules.only(…)` doesn't, as `DESIGN.md` asks; and an update can tell the two apart when it lists a new rule's findings.
- **Validated at load:** dropping or replacing a name lup doesn't have fails, naming the names it has. A rule renamed by a release comes with a migration that renames it in the declaration.
- **A field with no lup defaults is a plain list** (`exempt`, `contracts`, `tests`): there's nothing to select from.
- **Path roles are one field**, each role a pattern list: `Paths.default().add(protected=[…], data=[…]).drop(data=["*.yaml"], why=…)`. A pattern is its own name.

`Selection` is generic over the entry; each kind is a subclass binding its defaults: `Rules` (ids), `Paths` (patterns per role), `Gate` (`Step`s), `Commands` (`Command`s), later `Modules`, `Skills`, `Guidance`, `Runtimes`.

**lup declares its own defaults through the same surface.** Each default in `catalog/` is made of the entries a project adds: `catalog/gate.py` is a list of `Step`s, `catalog/paths.py` lists of patterns, `catalog/tools.py` a list of `RuffRule`s, `catalog/rules.py` rule ids with their reasons, each what `.drop`, `.add` and `.replace` take. What only lup's repository needs is in lup's own `lup_project.py`, written as a project's is (once A and B land):

```python
project = Project(
    paths=Paths.default().add(
        protected=["packages/lup-dev/src/lup_dev/catalog/**"],
        excluded=[
            ".claude/hooks/**",
            "packages/lup-dev/checker/pyright/**",
            "packages/lup-dev/src/lup_dev/codescan/bundle/**",
        ],
    ),
    tests=[Pytest(root="packages/*/tests")],
    doctests=["packages/*/src"],
    rules=Rules.default().add("runtime-mention"),
    exempt=[...],  # as today
    gate=Gate.default().add(
        Step(name="engine", command=["python", "packages/lup-dev/checker/build.py"], builds=…, sources=[…]),
        before="ruff",
    ),
    ruff=Ruff.default().drop("INP001", paths=["packages/lup-dev/checker/build.py"], why="the engine's build runs on its own, beside the TypeScript it builds"),
    contracts=[...],  # the four contracts in `pyproject.toml` today
)
```

The test of the principle: nothing in lup's core reads a default that isn't in a catalog a project can change. Building lup's engine, `runtime-mention`, and lup's import contracts are lup's own, declared where a project declares its own.

## Extending lup, kind by kind

What a project can add and override, with the slice that builds each.

- **Rules (A):** select with `Rules.default()`, `.drop`, `Rules.only`; lift one from some paths with `exempt`; keep one finding with `# lup: ignore`. Families (`.drop(family="data-shapes", why=…)`) come with open question 9's link. A project's own rules come later (*A project's own rules*).
- **Path roles and protected paths (A):** `Paths.default().add(protected=["tests/spec/**"], data=["ledger/**", "design/evidence/**"], scratch=["bench-out/**"])`, nori's roles. Dropping one of lup's protected patterns is possible and asks, since the declaration is protected.
- **Gate steps (A):** `Gate.default().add(Step(name="lean", command=["lake", "build"], in_environment=False), after="pytest")`, nori's Lean project. Every step runs through the project's runner unless it says it runs outside the environment.
- **The runner (A):** `runner=Plain()`, or a project's own `Runner` subclass (*The runner*).
- **Conditions (exists):** `conditions="audiobook.conditions"`, a module whose `Condition` instances a `defer(when=…)` names; a project subclasses `Condition` beside lup's stock `PythonAvailable` and `PackageReleased`.
- **Tool settings (B):** `ruff=Ruff.default().drop("T201", why=…)`, or for some files only, `.drop("T201", paths=["src/audiobook/cli.py"], why=…)`; `.add("PLR2004")` to check one lup turns off; `contracts=[…]` for import-linter.
- **Commands (the command line's slice):** `Commands.default().add(Command(name="studio", target="adlib.studio.cli:app", help="Preview, listen, start fresh."))`, `.replace("check", …, why=…)`, `.drop("verdicts", why=…)`. The hook command is fixed: a project can't patch the core hook (`DESIGN.md`, *How lup reaches a project*).
- **Modules, guidance, skills, runtimes (later):** *Later*, below.

## The runner

`Project.runner` says how the project runs its tools (#36). Everything that runs a tool in the project's environment derives from it, so `uv` is spelled once, in `Uv`.

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

- **`Uv()`, the default:** `command` is `uv run …`, as the gate runs today; `judging` is `env -u VIRTUAL_ENV uv run --frozen --quiet …`, as the judge runs ruff and the engine asks for its interpreter today (decisions 129 to 131 in `docs/judging-writes.md`); `environment` is `pyproject.toml`, `uv.toml`, `uv.lock`, `.python-version`.
- **`Plain()`:** the tool as the `PATH` finds it, for a project with no environment manager; no environment files.
- **Anything else is a project's own subclass**, a few lines: `poetry run`, `conda run -n …`. lup adds one to its own when a second project needs it.

Two methods because the judge and the gate differ: the gate may lock and sync (plain `uv run` relocks a stale lock), while the judge must never write `uv.lock`, a protected path the checkpoint would then judge as the agent's shell write (decision 131).

Where it's used:
- **the gate:** each step's command is the tool alone (`["ruff", "check", "--ignore-noqa"]`), run as `runner.command(…)`, or as written for a step with `in_environment=False`;
- **ruff in the judge:** `runner.judging(["ruff", "check", …])`;
- **the engine:** started with the runner's interpreter command (`judging(["python"])`, as a JSON list) and its environment files, so `program.ts` runs that command to name the interpreter, and stamps those files with pyright's own configuration. An engine started with another runner is replaced, as one from another build is.

What it doesn't cover: the `Bash` allow rules (the launch piece compiles them from the runner and the gate's steps), `uv tool install` in the installer (how lup installs its judge, not how a project runs its tools), and Windows (lup runs in a Linux container).

## Compiled tool settings

ruff's, pyright's, pytest's and import-linter's settings are compiled from lup's defaults (`catalog/tools.py`) and the declaration, never written by hand (`DESIGN.md`, settled). `lup-dev settings` writes them; `lup-dev settings --check` says which are stale and fails.

### What compiles from what

| Setting | Compiled from | In lup's `pyproject.toml` today |
|---|---|---|
| ruff's `select` and `ignore` | lup's selection (`select = ["ALL"]` and the rules it turns off, each with its reason), minus the ruff rules whose owning lup rule the project dropped, plus the project's `ruff` changes | `[tool.ruff.lint]`, reasons as comments |
| ruff's `src` | where the project's packages live: `src/`, and each uv workspace member's `src/` | `["packages/*/src"]` |
| ruff's `extend-exclude`, pyright's `exclude`, pytest's `--ignore-glob` | `paths` excluded | three lists, by hand |
| ruff's per-file ignores for tests (`S101`, `D`, `ARG`, `INP001`) | lup's defaults, on the declared test roots | `"packages/*/tests/**"` |
| ruff's `task-tags`, `runtime-evaluated-base-classes`; the formatter leaving Markdown alone | lup's defaults | as today |
| ruff's target version, pyright's Python version | not written: ruff reads `requires-python` beside its `ruff.toml` (checked), pyright reads the interpreter it's given | `py314`, `"3.14"` |
| pyright's strict mode, `enableTypeIgnoreComments = false` | lup's defaults | as today |
| pyright's `include` | the code and test roots | `["packages"]` |
| pytest's `testpaths`, `python_files` | `tests` and `doctests` | as today |
| pytest's `addopts` | lup's defaults (`--doctest-modules`, `--import-mode=importlib`) | as today |
| import-linter's `root_packages` and contracts | the project's packages and `contracts` | four contracts, by hand |

**Ruff rules owned by a lup rule follow it.** Each ruff rule lup turns off says why, and most say which lup rule owns the concern (`PLR5501` "steers an `else` holding an `if` to `elif`": owner `elif`). When a project drops that lup rule, its ruff rules come back on, so dropping a rule never leaves its concern without an owner: drop `regex`, and ruff's checks on `re` calls return. That's the comments in `pyproject.toml` made data.

**Writing them** takes `tomlkit`, so each ruff rule turned off carries its reason as a comment in the compiled file, as it does in `pyproject.toml` today. It's a new dependency, the operator's to approve; `tomli-w` writes TOML without comments, and building TOML text by hand is what lup's parsing rules exist to stop.

### Where they go

Each tool's own file, at the root:
- `ruff.toml` (ruff reads it before `pyproject.toml`: checked with `ruff check --show-settings`);
- `pyrightconfig.json` (pyright looks for `pyproject.toml` only where it finds no `pyrightconfig.json`, and parses it as JSON with comments: `analyzer/service.ts` at 1.1.414);
- `pytest.toml` (pytest 9 reads it first: `locate_config` in `_pytest/config/findpaths.py`);
- `.importlinter` (import-linter reads it without a flag; its format is INI).

Each opens with a comment saying it's compiled from `lup_project.py` by `lup-dev settings`, and that the declaration is what to edit. The drift check also fails while `pyproject.toml` still holds one of these tools' tables, which would be shadowed, or would shadow.

The alternative is `pyproject.toml`'s `[tool.*]` tables: one file, but compiled tables beside what uv and the operator edit, so a write to `pyproject.toml` would be partly compiled and partly not, and the judge would have to tell which tables a change touched. Separate files are compiled whole: equal to the compile, or not. A third option, compiled and never committed (as runtime trees are), needs no drift check, but a fresh clone, CI and the operator's editor see no settings until a `lup` command runs, and a declaration change no longer shows its effect on the settings in its diff.

### How compiled settings are judged

They get a role of their own, `compiled`, after protected:
- **a write equal to what the judge compiles from the integration branch's declaration is allowed**, so an agent runs `lup-dev settings` after a declaration change lands on `dev` and nothing asks twice for one decision;
- **any other write is judged as a protected path's:** it asks, and made through the shell it's refused with the pointer to the file tools. A hand edit, or settings compiled by a lup version other than the installed judge's, reaches the operator and never lands unseen.

It's the integration branch's declaration for the same reason the judge reads only that one (decision 94 in `docs/judging-writes.md`): a branch never changes what judges it. A declaration change lands on `dev` first, as one does today, and its settings follow it there. The role closes #38 for the four compiled files; #38's own fix protects `uv.toml` and the rest.

The alternatives: protected outright, where `lup-dev settings` run by an agent is refused as a shell write to a protected path, so only the operator could recompile; or unguarded at the edit, the gate's drift step the only check, so a weakened `pyrightconfig.json` reads as the project's settings for the rest of the session.

**The drift step:** `settings`, a default gate step running `lup-dev settings --check` before ruff, failing with the files stale and the command that writes them. It does for the settings what the test of `docs/rules.md` does for the rule reference.

### Dependencies

They stay in `[project]` and `[dependency-groups]`, uv's and the packaging standard's (open question 8's (ii)). Declaring them in the declaration and compiling `pyproject.toml` whole (i) would make the declaration the one source, at the cost of a tool editing Python source, a changed habit, and every tool that edits `pyproject.toml` (dependency bots, `uv add`) stopping. The overview below gives (ii) the one place to read.

**The tools lup runs come with lup.** ruff, pyright, pytest and import-linter become requirements of `lup-dev`, pyright pinned to the release the engine is built against; a project lists `lup-dev` alone in its development group. lup's defaults are written against those versions (ruff's `select = ["ALL"]` turns on whatever a later ruff adds), and a project whose pyright drifted from the engine's would see its type errors judged by one release and gated by another. Today lup's own development group lists them, and the engine's build reads pyright's release from `uv.lock`, which keeps working: the lock then holds `lup-dev`'s pin.

### One page for the whole project

`lup-dev project` prints everything about a project, read from the declaration and `pyproject.toml`:
- the declaration's file, and the runner;
- dependencies, from `[project]` and `[dependency-groups]`;
- each path role: lup's patterns, then the project's additions and drops with their reasons;
- the rules: how many of lup's run, which are dropped and why, each exemption;
- the gate's steps, in order;
- the compiled files, each current or stale, and every ruff rule the project changed, with its reason.

The dashboard shows the same page once it exists (`DESIGN.md`, *The dashboard*).

## The rules

### Selecting them

`Project.rules` is a `Rules` selection; `Rules.default()` is every rule but those `catalog/rules.py` leaves out (`runtime-mention`, which lup's own declaration adds back), and `Rules.all()` every rule. The judge sends the selection, recorded as it is (a starting point, the names dropped, the names added), in each check request, and **the engine resolves it**: it holds the table, so nothing asks it for its rules first, and an unknown name fails there with the names it has, as today. `lup-dev rules check` and the judge send the same selection; exemptions and `ignore` apply after, as today.

#33 changes lup's defaults: which ruff rules `catalog/tools.py` turns off, and which lup rules `catalog/rules.py` leaves out of the default. Both are data the operator reviews, made of the entries a project uses to change its own.

### Rules and conventions

Open question 9. Today `docs/conventions.md` lists each section's rules by hand under *Enforced by:*, and a test checks only that each id it names exists (`tests/test_reference.py`), so a rule can run with no written decision behind it. The table already says which section each rule belongs to, in a comment heading each group of entries, naming the section.

**Lean (i), as the agent's earlier lean:** each entry in `catalog/rules.ts` names its section (`convention: 'parsing'`, the heading's anchor); `docs/rules.md` is generated grouped by section, each group linked to its why; each conventions section points to its group instead of listing ids, and names ruff's, pyright's and import-linter's part by hand as before; a test fails when a rule names a section `docs/conventions.md` lacks. The link is kept once, in the table, and a rule can't be added without the decision it serves.

It also gives rules their families: a section is a family, so `Rules.default().drop(family="data-shapes", why=…)` selects by it, and #33's round can go section by section. The alternatives: (ii) the hand-written lists, checked both ways, redundant but policed; (iii) the *Enforced by:* lines generated into the conventions, generated text inside a hand-written document.

A small branch of its own (D), whenever the operator answers; families in the grammar arrive with it.

### A project's own rules

Open question 10, designed now, built later (E).

**Where they live:** `lup_rules.ts` at the project's root, beside `lup_project.py`, found the same way: a table written as lup's is, each entry with its mistake, steer, check and examples, its `convention` naming a section of the project's own conventions document. Its ids join lup's, and a clash fails. To change one of lup's rules, a project drops it and adds its own under another id, and that's an upstream candidate. `Rules.default()` includes the project's table; `runtime-mention` moves into lup's own table, its first entry.

**How they reach the engine.** Options:
- **(a) A bundle per project:** the project's table compiled with lup's engine source, as lup's build does now. Type-checked against the real helpers, but every project needs pyright's source at the pinned release and its dependencies installed with pnpm (minutes the first time, cached per machine), and a rebuild when its table changes.
- **(b) Loaded when the engine starts (lean):** the engine shipped in `lup-dev` imports the project's table itself. Node runs TypeScript by stripping its types: checked here, Node 26.10 imported a `.ts` table with an interface and a typed constant, no flag, no build. The table imports only types, and the `python` helper, from a module the engine provides. The project's gate type-checks it (`tsc` against declaration files `lup-dev` ships) and runs its examples as lup's tests do: each of `flags` gets a finding from its rule alone, each `rewritten` passes every selected rule, ruff and pyright, each of `passes` gets none.
- **(c) Python rules asking the engine by position:** the spike rejected it (two trees to keep in agreement, 10 to 20 times the cost; `docs/judging-writes.md`, *How a rule is declared*).
- **(d) None:** a project's architecture checks stay pytest tests, as nori's were, and anything general is an upstream candidate. That's what every project of the first lup did, with the feature available.

Either (a) or (b) makes the engine's helpers (`File` and what it returns) lup's public API, versioned, with migrations when one changes. (b) costs no build per project; a mistake in a check shows at the project's gate rather than at a build. A check that throws is reported as that rule's finding, naming the error, never swallowed and never failing the file's other rules.

**How they're reviewed before they run.** A rule is code the judge runs, on the host while the judge runs there.
- **Now: as the declaration is.** `lup_rules.ts` is protected by default, so every change to it asks, and the judge reads it from the integration branch's tip, so a branch's rule runs only once it's on `dev`. The declaration is already code the judge imports and runs, reviewed this way.
- **With trust on launch (`DESIGN.md`, *Policy*):** the engine runs a project's table only at a content the operator approved, its diff since the last approval shown as the judge's own install review shows its source, the last approved table judging meanwhile; the same for the declaration and its conditions module, which are project code the judge runs too.

## The command line

Designed now, built as the second slice (C). Today's `lup-dev` stands in.

- **One command, `lup`, shipped by `lup-dev`.** `DESIGN.md` says both "One CLI, from the library" and that "the environment serves their commands (`run monitor` and the like)"; this reads the second as the decision: the library ships no command, and the environment's `lup` serves the library's features' commands to a project that uses them. The alternative is a `lup` in the library that finds its groups through entry points, the environment registering its own.
- **Built from the declaration, loading only what's invoked.** The root is a click group (Typer's base) whose entries are data: a name, a target in entry-point form (`"lup_dev.commands.holds:app"`), a one-line help. Listing commands (`lup --help`) reads the data and imports nothing; invoking one imports its target alone, a Typer app turned into a click command. click's own help listing calls `get_command` for every entry (`click/core.py`, `format_commands`), so the group lists from its data instead. Typer's eager tree is the alternative: today's 246 ms of imports in every hook call.
- **What's in it:** lup's core commands; the groups of the selected modules, so a dropped module's commands are absent by construction; the project's own commands, replacements and drops (`commands`). The hook command is fixed. A command found among lup's core ones runs without loading the declaration; `--help` and a project command load it.
- **Today's commands, there:** `hook claude|codex`, `check [--fix]`, `rules list|check`, `holds [approve|decline]`, `verdicts`, `settings [--check]`, `project`, the hidden `importers`; `submit`, `wait` and `drafts` once the review flow lands (#37). `install` (installing the judge from a checkout of lup) and `rules docs` (writing lup's `docs/rules.md`) are lup's own: lup's declaration adds them, as a project adds its own.
- **`lup new <name>`** makes a project: `uv init --lib --build-backend uv --vcs git` (checked: it writes `pyproject.toml`, `src/<name>/__init__.py` and `py.typed`, `.python-version`, `.gitignore`, a README, and a git repository), then lup's part: the package's `__init__.py` rewritten to a module docstring (uv's `hello()` has none, which ruff refuses), `lup_project.py` binding `Project()`, `tests/` with one test, `.lup/` and `tmp/` in `.gitignore`, `uv add --dev lup-dev` at the running lup's release, the compiled settings, and a first commit. It passes the gate as made. The alternative, lup's own templates for every file, is the first lup's scaffold again, and Jinja would be a new dependency.
- **`lup docs rules [<rule>]`** prints the reference from the installed engine (`codescan/reference.py`), which refusals already point at. The hand-written docs (`conventions`, `declaration`) need packaging, since they live outside the package, and come with guidance.
- **The rename:** the package's script becomes `lup`. The hooks in `.claude/settings.json` and `.codex/hooks.json` call the installed `lup-dev` by path, so they switch in a commit landed once the operator has installed the judge carrying `lup`; switched first, every hook would fail open until then. `AGENTS.md` (`uv run lup-dev check`) is the operator's to change, and CI's command switches with the script.
- **A test, not a timer:** the command line's tests check which modules `lup --help` and `lup hook` import (`sys.modules` after the call), so no test depends on wall-clock time.

Modules: `cli.py` becomes the lazy root; each command group a module of `lup_dev/commands/`, the top layer; the list of adapters moves into `commands/runtimes.py`, which the import contract keeping the adapters behind one place then names.

## Later: what the rest of the declaration holds

Each built with the piece that first reads it; its shape is here so the grammar holds for it.

- **Modules (the coordination and ledger pieces):** `modules=Modules.default().drop("ledger", why=…)`, `Modules.all()` for every module including those off by default (budgets, resolver, release, …). A module is an entry declaring what it contributes, each part a reference loaded when used:
  ```python
  Module(
      name="ledger",
      purpose="The one place for open work.",
      commands=[Command(name="ledger", target="lup_dev.modules.ledger.cli:app", help="Open work: list, add, close.")],
      skills=[Skill(name="ledger", path="lup_dev.modules.ledger:skill.md")],
      guidance=[Section(name="ledger", path="lup_dev.modules.ledger:guidance.md")],
      paths=Paths.none().add(data=["ledger/**"]),
      requires=[],  # the modules it needs, by name
  )
  ```
  A selected module's contributions join the project's catalogs; a dropped one's leave with it. A project's own module is the same `Module`, added with `.add`. "Dropping each module is tested" (`DESIGN.md`) becomes one test per module: the declaration with it dropped serves none of its commands, skills or sections, and lup's tests pass.
- **Guidance and skills (the launch piece, which renders them):** `guidance=Guidance.default().add(Section(name="pipeline", path="guidance/pipeline.md")).replace("code", Section(…), why=…)`, rendered into one template at launch; `skills=Skills.default().add(Skill(name="ingest", path="skills/ingest.md")).drop("release", why=…)`. Rendering checks that no section names a command the project doesn't serve, the first lup's dangling prose.
- **Runtimes and their spellings (the launch piece):** `runtimes=Runtimes.default().add(Runtime(name="…", adapter="…:Adapter"))`, the list in today's `cli.py` becoming lup's defaults, so a project can bring an adapter of its own.
- **Rooms (the library's rooms slice):** a room is the library's `Room`, declared in the project's code, which production code imports from the project's package; the declaration references it (`rooms=["audiobook.rooms:narrator"]`) so the environment can launch and show it. `DESIGN.md` says a room is "declared in `lup_project.py` and used from code", which would make production code import the declaration and through it `lup_dev`.
- **Nested projects (the gate's nested environments):** a test root in a project of its own runs through the runner from that project's directory (`Pytest(root="studio/tests", project="studio")`), and pyright's settings get an execution environment for it, as adlib needed for `studio/` on Python 3.13.
- **pyright per path** (nori's `reportMissingImports = "none"` under one directory): `Pyright.default()` grows those changes, each with `why`, when a project needs one.
- **Personal config** (`~/.config/lup/config.toml`): accounts, theme, budget shares; between lup's defaults and the project in precedence (`DESIGN.md`). Not a project's, and read by launch, the dashboard and budgets.
- **Upstream candidates** (open question 3): the `why` on each `.drop` and `.replace` is where one starts.

## Building it

**Branch A, `feat-declaration`:**
1. `declaration/` with the grammar, `Project` (moved, `extra="forbid"`, `paths` replacing `protected` and `excluded`, `rules`, `runner`, `gate`), loading `lup_project.py` from the root.
2. The rule selection, recorded, sent by the judge and `lup-dev rules check`, resolved by the engine.
3. The runner, used by the gate, ruff and the engine; `UV_RUN` and `environmentOf`'s spelling of uv go.
4. lup's own declaration rewritten in the new fields, the engine's build step among its gate steps, and `runtime-mention` added back.

Order matters for lup itself, since the installed judge reads `dev`'s tip with its own, older code:
- **`lup_project.py` moves to the new fields in A,** since A's gate loads it with A's `Project`. Once A lands, the judge installed before can't load it, so the last declaration that loaded judges instead, and the agent is told once (#21), until the operator installs the judge from A.
- **`[tool.lup]` stays until then,** and goes in a commit on `dev` after the install. Removed with A, the judge installed before would find no pointer and judge by the defaults, losing `catalog/**`'s protection without a word: a missing pointer isn't a failure to load, so no stand-in covers it.

**Branch B, `feat-tool-settings`:** `catalog/tools.py` (the ignores from `pyproject.toml`, each with its reason and owner), compiling and writing the four files, the drift step, the `compiled` role, `lup-dev project`, the tools as `lup-dev`'s requirements; lup's `pyproject.toml` loses its four tools' tables, its import contracts move into `lup_project.py`. #33's broadening can then run on lup's catalog.

**Then:** C, the command line and `lup new`; D, rules naming their conventions section, with families; E, a project's own rules. The rest with the pieces that read them.

**Tests:** the grammar's operations and their errors; the declaration loaded from a root and from an export, unknown fields refused; the runner's commands for the gate, the judge and the engine, with uv stubbed through the runner; the engine resolving a selection, and refusing an unknown name; the compile of a sample declaration, byte for byte; the `compiled` role allowing what the compile gives and asking otherwise; the drift step failing on a stale file and on a shadowed `pyproject.toml` table.

## Checks owed

- **Node's type stripping in the engine's bundle:** the engine is bundled for Node 20 as CommonJS (`build.py`); that its `import()` of a project's `.ts` table works there as it did from a plain `.mjs`.
- **`uv tool install` of `lup-dev` with the tools as its requirements:** the judge's tool environment grows by ruff, pyright, pytest and import-linter; whether that matters for the install's time.
- **`ruff` inferring its target version from `requires-python` beside `ruff.toml`:** checked for one directory; to check for a uv workspace whose root `pyproject.toml` has no `[project]`, as lup's.

## Decisions

Each with its alternatives, the lean, and where it lives. All are the operator's to answer; none is taken.

*Where things are:*
1. **The declaration is `lup_project.py` at the worktree's root, binding `project`, found without a pointer; `[tool.lup]` goes.** *Alternative:* a module named in `[tool.lup] project = …`, as today. *Lean:* the fixed file: one place in every project, no pointer to repoint, and outside the package, so production code can't import it. *Where:* `declaration/load.py`.
2. **Dependencies stay in `[project]` and `[dependency-groups]`, with `lup-dev project` showing them beside everything else.** *Alternative:* (i), declared in the declaration with `pyproject.toml` compiled whole. *Lean:* (ii), as the operator's light lean. *Where:* `declaration/overview.py`.
3. **ruff, pyright, pytest and import-linter are `lup-dev`'s requirements, pyright pinned to the engine's release; a project lists `lup-dev` alone.** *Alternative:* each project lists and pins them, as lup's development group does today, letting its pyright drift from the engine's. *Lean:* `lup-dev`'s. *Where:* `packages/lup-dev/pyproject.toml`.
4. **Compiled settings go in each tool's own file at the root** (`ruff.toml`, `pyrightconfig.json`, `pytest.toml`, `.importlinter`). *Alternatives:* `pyproject.toml`'s `[tool.*]` tables, partly compiled and partly not; compiled and never committed, with no drift but nothing to read on a fresh clone or in a diff. *Lean:* their own files. *Where:* `declaration/tools.py`.
5. **Compiled files have a role of their own: a write equal to the compile of the integration branch's declaration is allowed, any other is judged as a protected path's.** *Alternatives:* protected outright, which refuses an agent's recompile as a shell write; unguarded, with the drift step alone. *Lean:* the role. *Where:* `policy/roles.py`, `catalog/paths.py`.
6. **Writing TOML with `tomlkit`, a new dependency,** so each ruff rule turned off keeps its reason as a comment. *Alternatives:* `tomli-w`, which drops the reasons; TOML built as text. *Lean:* `tomlkit`. *Where:* `declaration/tools.py`.

*The grammar:*

7. **One generic `Selection`, with methods: `default()`, `all()`, `only()`, `.drop`, `.add`, `.replace`.** *Alternatives:* Python set arithmetic as `DESIGN.md`'s example writes it, which `set-shape` refuses in `lup_project.py`; operators on lup's own type taking lists, a second spelling. *Lean:* methods. *Where:* `declaration/grammar.py`.
8. **A selection is recorded and resolved at load,** so `default()` takes what later releases add and `only()` doesn't. *Alternative:* resolved into a list when built, which loses which one the project meant. *Lean:* recorded. *Where:* `declaration/grammar.py`.
9. **A `.drop` or `.replace` of lup's defaults carries `why`.** *Alternatives:* optional; required only for rules. *Lean:* required for both verbs on every kind. *Where:* `declaration/grammar.py`.
10. **Path roles are one field, `paths`, a pattern list per role, replacing `protected` and `excluded`.** *Alternative:* a field per role, as `protected` and `excluded` are today. *Lean:* one field. *Where:* `declaration/project.py`, `policy/roles.py`, `lup_project.py`.
11. **References to the project's code are strings in entry-point form, checked at the gate.** *Alternative:* objects, as `DESIGN.md`'s `studio_cli`, importing the project's code at every call. *Lean:* strings. *Where:* `declaration/project.py`.
12. **The declaration's names are at `lup_dev`'s front door,** importing only the declaration's models. *Alternative:* imported from `lup_dev.declaration.project` and its neighbours. *Lean:* the front door. *Where:* `lup_dev/__init__.py`.
13. **The declaration is a subsystem, `lup_dev/declaration/`, layered between `codescan` and `catalog`.** *Alternative:* `project.py` stays at the root, with `runner.py`, `grammar.py` and `tools.py` beside it. *Lean:* the subsystem. *Where:* `lup_dev/declaration/`, the `layers` contract.
14. **lup's own defaults are made of the public entry types (`Step`, patterns, `RuffRule`, rule ids), and lup-only parts (the engine's build step, `runtime-mention`, lup's import contracts, `install`, `rules docs`) move into lup's own declaration.** *Alternative:* lup's specifics stay in the catalog and the command line. *Lean:* lup's declaration. *Where:* `catalog/`, `lup_project.py`.

*The runner:*

15. **`Project.runner`, an ABC with `command` (the gate's), `judging` (the judge's: never writes the project's files) and `environment` (the files whose change means another environment); `Uv()` by default, `Plain()`, others a project's own.** *Alternatives:* a prefix string (`runner="poetry run"`), one command for both the judge and the gate; the tools' commands spelled per tool in the declaration. *Lean:* the ABC. *Where:* `declaration/runner.py`, `gate.py`, `codescan/ruff.py`, `codescan/engine.py`, `checker/src/program.ts`.

*The rules:*

16. **The engine resolves the selection, sent recorded in each request.** *Alternative:* Python lists the engine's rules, resolves, and sends ids. *Lean:* the engine. *Where:* `codescan/engine.py`, `checker/src/catalog.ts`.
17. **lup's default selection leaves out `runtime-mention`; lup's declaration adds it back,** until it moves to lup's own table with (E). *Alternative:* in every project's default, each project dropping it. *Lean:* out of the default. *Where:* `catalog/rules.py`, `lup_project.py`.
18. **A ruff rule lup turns off because a lup rule owns its concern comes back on when the project drops that rule.** *Alternative:* the two selections independent, so dropping a lup rule leaves its concern unowned. *Lean:* derived. *Where:* `catalog/tools.py`, `declaration/tools.py`.
19. **Rules and conventions: (i), each rule names its conventions section; `docs/rules.md` grouped by section; sections are families.** *Alternatives:* (ii) the hand-written lists checked both ways; (iii) *Enforced by:* lines generated into the conventions. *Lean:* (i). *Where:* `catalog/rules.ts`, `codescan/reference.py`, `docs/conventions.md`, `tests/test_reference.py`.
20. **A project's own rules live in `lup_rules.ts` at its root, written as lup's; ids unique across both tables.** *Alternatives:* a table named in the declaration; ids namespaced by project. *Lean:* the fixed file and one namespace. *Where:* later, (E).
21. **They reach the engine by being loaded when it starts (b).** *Alternatives:* (a) a bundle per project; (c) Python rules; (d) none, architecture checks as tests. *Lean:* (b). *Where:* later, (E).
22. **They're reviewed as the declaration is now (protected, read from the integration branch's tip), and approved by content once trust on launch is ported, with the declaration.** *Alternative:* approval by content from the start, a review of its own before trust on launch exists. *Lean:* as the declaration. *Where:* later, (E).

*The command line:*

23. **One command, `lup`, shipped by `lup-dev`; the library ships none.** *Alternative:* `lup` in the library, finding the environment's groups through entry points. *Lean:* the environment's, reading `DESIGN.md`'s "the environment serves their commands". *Where:* `packages/lup-dev/pyproject.toml`, `cli.py`.
24. **A lazy click group whose entries are data; `--help` imports nothing; tests check imported modules, not time.** *Alternative:* Typer's tree, built at import. *Lean:* lazy. *Where:* `cli.py`, `lup_dev/commands/`.
25. **The hook command is fixed; every other command is an entry a project can replace or drop.** *Alternative:* every command overridable, the hook included; or none. *Lean:* the hook fixed. *Where:* `cli.py`.
26. **`lup-dev` becomes `lup` in the command line's branch, the hooks switching in a commit after the operator installs.** *Alternative:* keep `lup-dev` until the launch piece compiles the hooks, a second rename later. *Lean:* rename then. *Where:* `packages/lup-dev/pyproject.toml`, `.claude/settings.json`, `.codex/hooks.json`, CI, `AGENTS.md` (the operator's).
27. **`lup new` runs `uv init --lib`, then writes lup's part.** *Alternative:* lup's own templates for every file. *Lean:* uv's. *Where:* `lup_dev/commands/new.py`.

*Scope:*

28. **Rooms are declared in the project's code and referenced by the declaration,** so production code never imports it. *Alternative:* in `lup_project.py`, as `DESIGN.md` says, imported by production code, which makes `lup-dev` a production dependency. *Lean:* the project's code. *Where:* the library's rooms slice.
29. **The first slice is A (the declaration, the runner, the rule selection) and B (compiled settings, their role, the overview); the command line is next.** *Alternative:* A and the command line first, compiled settings after, which leaves `lup new` without settings to compile. *Lean:* A and B. *Where:* *Building it*.
