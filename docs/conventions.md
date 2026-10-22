# Conventions: how code in lup is written

Every convention lup's code follows is written once, here, with its reason and what enforces it, so no session has to pick between two ways of doing the same thing. Many are a pick between two good ways, made so sessions don't split between them, rather than a claim that the other way is wrong: where one gets in your way, say so, since a convention that costs more than the divergence it prevents is worth changing. They apply to production code, in lup and in every project that takes lup's rules, but for `runtime-mention`, which only lup's own declaration runs; tests are exempt (*Tests*). Each rule, with the code it flags and leaves alone, is in `docs/rules.md`, generated from the engine's table.

## Who owns each concern

Every concern has one owner, so two tools never report the same thing in two ways or steer in opposite directions.
- **lup's rules** own the conventions below, in lup's typed engine (`docs/judging-writes.md`, *The engine: one typed tree*), rather than as ruff `banned-api` entries beside a syntax checker, which would split where they live. Each names the mistake it prevents and where it steers. The rules that pick an approach other code is built on are meant to be told at the edit, and those about spelling at the gate; that timing is #49, and until it's built every rule's findings are told at the edit.
- **ruff** owns generic Python hygiene: `select = ["ALL"]`, minus every rule that overlaps or contradicts another owner, and a few left to review (*ruff's selection*). A finding it fixes safely isn't told to the agent; the session landing the work applies it.
- **pyright,** in strict mode, owns types.
- **import-linter** owns the import boundaries, over the whole import graph at the gate.
- **The formatter,** ruff's, runs when work lands.

## Interfaces

**Decision.** An interface we own is an ABC; `Protocol` is for the shape of something we don't own, a third-party object or a callback's signature. A class declaring abstract members lists `ABC` in its bases, since pydantic's metaclass makes such a model abstract silently. No class inherits two of our ABCs. An ABC is small: one to three abstract methods and no concrete behaviour, which a plain class composed over it holds.

**Why.** An ABC is inherited, so a missing method stops the class being made; a `Protocol` is matched by shape and checked only by pyright. With ABCs alone, "how do I declare an interface?" has one answer, and nothing in lup needs matching by shape: `Claude`, `Codex` and the test fake are all ours. A small ABC keeps its seam small, and a small seam holds while the code filling it changes.

**Enforced by:** `protocol` (a `Protocol` definition is a finding; one for a shape we don't own carries an `ignore` with its reason, which asks the operator), `interface-shape` (`ABC` named in the bases of any class with abstract members; no class inheriting two of our ABCs; one to three abstract methods and no concrete behaviour). pyright's `reportAbstractUsage` covers instantiating an abstract class.

## Data shapes

**Decision.** pydantic models for every shape we declare: no `dataclass`, no `NamedTuple`, no `TypedDict` of our own (one appears only where a third-party API is typed with it, and then it's theirs). Configuration as class keywords (`class Turn(Model, extra="forbid")`), never a `model_config =` assignment, which reads like a field. A list default is a literal (`steps: list[Step] = []`, which pydantic copies per instance). Every model derives from `lup.types.Model`, which is frozen; one that must change derives from `MutableModel`, so mutability is a choice written in the header; settings from `lup.types.Settings`. No model writes `frozen` itself: `Model`'s metaclass tells pyright its subclasses are frozen by default (PEP 681's `frozen_default`), so silence means frozen and pyright still refuses `point.x = 2`. The one exception to both is `lup.types.Settings`, which freezes through `model_config`, since pyright refuses a frozen class over pydantic-settings' base.

**Why.** One way to declare a shape, validated where it's declared, its configuration read with the class.

**Enforced by:** `dataclass`, `namedtuple`, `model-config`, `default-factory`, `model-mutability` (a model deriving straight from pydantic's `BaseModel` or `BaseSettings` instead of lup's bases, or writing `frozen` in its header), `typed-dict` (a `TypedDict` class we define).

## Names

**Decision.** Nothing is private: no leading underscore at any scope. A helper that shouldn't reach the module namespace nests inside its only caller, and a wrapper around one call is inlined where it's used; an unused parameter keeps its underscore, a linting convention rather than privacy. `__all__` appears only at a package's root, declaring its public API; elsewhere a name is imported from the module defining it.

**Why.** One rule for visibility, public or nested, so a reviewer never wonders whether `_x` is really private.

**Enforced by:** `private-name` (classes, functions and variables alike), `all-export`.

## Dispatch

**Decision.** No `elif`: a decision on a value's structure is a `match`, and a comparison with no pattern to write is a guard clause that returns. A `match` decides through its patterns: a guard on a wildcard (`case _ if …`) is an `if` chain dressed as one, while a guard on a real pattern that binds what it reads is fine. No chain of `isinstance` narrowing one subject: a `match` on its class. An implementation of one of our ABCs is called through the ABC, never switched on: a `match` over the subclasses of one of our ABCs steers to a method each implementation answers. Plain data told apart by a field isn't a seam, and is matched on like any data.

**Why.** A `match` names its subject once and makes each arm a pattern of it, where a chain hides which value decides; guard clauses keep comparisons flat; and choosing by which implementation of a seam you hold defeats having the seam.

**Enforced by:** `elif`, `wildcard-guard`, `isinstance-chain`, `own-model-dispatch`. ruff's `PLR0911` (too many returns) and `SIM116` (an `if` chain to a dict lookup) are off: they fight guard clauses and `match`.

## Constants

**Decision.** Every module-level constant has a home, decided by its type:

| Constant | Its home |
|---|---|
| A number or a duration: a retry count, a timeout, a size limit | an overridable default: a parameter's or a field's |
| A list a caller might change: the statuses retried, the editors tried | a field's default, on the model that uses it |
| A closed set of options | a `Literal` type, its members read with `typing.get_args` |
| A fixed table from one vocabulary to another | a function that `match`es, its key a `Literal` |
| An environment variable's name | the package's `settings.py`, whose pydantic-settings model's fields are the variables |
| A path or a file name | the package's `layout.py`, which says where everything is stored |
| A runtime's wire spelling: a tool name, a hook event, a protocol field | its runtime's adapter: a field of the adapter's model, or a `Literal` for a closed set |

The rule reads a constant's type, and how a collection is written: a number or a duration is a finding anywhere; a path outside the package's `layout.py`; and a list, tuple, set or dict holding plain string or number literals alone, written out or handed whole to its constructor, anywhere but `__all__` and `layout.py`, whose file names a collection may hold as strings. A lone `str` constant, such as a variable's name or a single wire spelling, isn't read, so its home is review's. The direction for wire spellings is a `Spellings` ABC each adapter implements, one member per word of lup's own vocabulary, so adding a word forces every adapter to answer it, where a dict would miss an entry until something broke (#52). Until then each adapter holds its own: a closed set as a `Literal`, its real home, and a spelling waiting for `Spellings` as a field of the adapter's model, marked `# lup: defer(issue=52, why=…)` so the gate lists it once #52 closes.

**Why.** A number or a list is a judgement a caller may want to change, which a module constant would freeze; names and paths spread across files leave nobody able to find where things are stored or which variables are read; and a set of options kept as a list, or a table kept as a dict, is data pyright can't check a use against, where a `Literal` is a type it checks, and a `match` over one fails the type check once a member goes unanswered. One home per kind answers all three.

**Enforced by:** `constant-home` (typed: the constant's type, or the literals a collection holds, decides its home). ruff's `PLR2004` (magic values pushed into module constants) is off: it steers the opposite way.

## Collections and loops

**Decision.** No tuple types: `tuple[str, int]` becomes a model naming each field, and `list[X]` is the one spelling of a sequence; where a third-party API takes a tuple, an `ignore` says so. No sets as records: a dict keyed by the members, or a list of models; a set that truly records nothing (things already seen) takes an `ignore`. No collection filled in a loop: a comprehension, or a nested function that `yield`s where the loop's control flow can't fit one. Dicts are for tables, not records: one read by a literal key (`payload["name"]`) is a record whose keys are known, so it's validated once into a model; a dict read by a computed key is a real table.

**Why.** Positional data makes review a puzzle ("what is field 5?"), a set throws away what a dict keeps, a loop mutating several variables is harder to follow than a comprehension, and a dict read by literal keys hides its schema in the places reading it.

**Enforced by:** `tuple-shape`, `set-shape`, `collection-loop`, `dict-literal-key`. ruff's `PERF401`–`PERF403` are off: they overlap `collection-loop`.

## Parsing

**Decision.** Structured data is read with its format's parser or a pydantic model: no `re` or `regex`; no `.split(sep)`, `.partition`, slicing, `.strip(chars)` or `.replace` to take a `str` or `bytes` apart (`.split()`, `.splitlines()` and `.strip()` with no argument are fine). An agent's output is never hand-parsed: typed answers come through lup's `submit` (`docs/library.md`). The parsers to reach for: `json`, `tomllib` (`tomlkit` to edit), `csv`, `urllib.parse`, `pathlib`, `email`, `shlex`, `ast`, `datetime.fromisoformat`, `packaging`, `trafilatura` or `beautifulsoup4` for web pages; XML through `defusedxml`. A grammar of our own gets a parser library.

**Why.** Quick regex and split patches match the cases tried and fail quietly on the rest, and the bugs they leave are hard to find; a parser fails loudly.

**Enforced by:** `regex`, `string-split`, `string-slice`, `string-strip`, `string-replace`.

## Truncation and comments

**Decision.** Don't truncate: cutting a sequence at a fixed bound, a literal or a constant (`rows[:200]`, `rows[:LIMIT]`), to make it fit is refused; where a format forces a limit, keep the full copy and point at it, in an `ignore` saying so. A limit on what reaches a caller is the caller's to set, with a default: a field of a tool's input, an option of a command. An answer that stops short says so, and how to reach the rest: a larger limit, a narrower query. Code reads as if it was always this way: no "new", "now", "fixed", "previously" or "no longer" in comments and docstrings, since "the call now waits" means something only against how it used to be; history belongs in commit messages.

**Why.** A cut nobody mentions reads as the whole: an agent handed the first 100 matches takes them for all there are, and one that can't raise the limit can't reach the rest.

`historical-voice` is a heuristic over prose: a misfire is the rule's bug, rewritten when one shows up.

**Enforced by:** `silent-truncation`; `fixed-tool-limit` (in a function serving a tool of lup's library, and the functions of its file it names, a cut or a `limit`-style argument whose bound is a literal, a constant or a field of what the tool is bound to, rather than the call's input); `historical-voice`.

## Types

**Decision.** No `typing.Any`, no `cast`, no bare `object` annotation: JSON whose schema lives elsewhere is pydantic's `JsonValue`, or `lup.types.JsonObject` for an object, and everything else gets its real type or a type parameter. pyright strict, with modern spellings (PEP 695 type parameters, `X | None`, builtin generics), and Python 3.14's lazily evaluated annotations, so no `from __future__ import annotations` and no quoted annotations.

**Enforced by:** `any-type`, `cast`, `bare-object` (which accepts the `object` parameters Python's own protocols require, as in `__eq__` and `__exit__`); modern spellings by ruff's `UP` rules; return types by ruff's `ANN2xx`.

## Errors

**Decision.** Exception names end in `Error`. One root exception per package, named for it (`LupError` in `lup`, `LupDevError` in `lup_dev`), with a tree per area below it, so a caller can catch everything a package raises. Errors are classified from structured data, never from message text. Never swallow an error: no `contextlib.suppress`, no bare `except:`, no `except BaseException`; raise on what can't be recovered, and retry what's transient, with `tenacity`.

**Why.** A message gets reworded without notice, so a decision read from its text breaks quietly.

**Enforced by:** `error-root` (typed: an exception class not descending from its package's root), `suppress`, `bare-except`, `except-baseexception`; names by ruff's `N818`. `error-text` refuses deciding on an exception's message (`"x" in str(exc)`). ruff's `SIM105` (which steers *to* `contextlib.suppress`), `B022`, `E722` and `BLE001` are off: the first contradicts `suppress` and the second overlaps it, the other two overlap lup's rules and `BLE001` contradicts the steer to `Exception`.

## Libraries per job

**Decision.** One library per job:

| Job | Use | Not |
|---|---|---|
| Running a program | `lup.programs` (`run`, `detached`), which starts a program from C, as `subprocess` does, never by forking Python, so it's safe beside threads | `sh`, `subprocess`, `os.system`, `os.popen`, `os.exec*` |
| A command line | `typer` | `argparse` |
| Paths and files | `pathlib` | `os.path`, `os`'s file functions |
| Configuration and environment | `pydantic-settings` | `os.environ`, `os.getenv`, `dotenv` for reading |
| Progress bars | `tqdm` | `rich.progress` |
| Retries | `tenacity` | a hand-written loop |
| Shapes | `pydantic` | `dataclasses`, `NamedTuple` |
| PDFs | the document read whole | `pypdf` and other text extractors, whose empty text reads as an empty document |

**Why.** Two libraries for one job are two ways of doing it, which sessions split between.

**Enforced by:** `subprocess`, `os-shell`, `argparse`, `os-path`, `os-file-ops`, `os-environ`, `rich-progress`, `pdf-extraction`. ruff's `PTH` rules and the `S6xx` subprocess rules are off: they overlap.

## Docstrings and comments

**Decision.** Prose, not `Args:` and `Returns:` sections, which repeat the signature. A function's first line is in the imperative ("Return the saved path."), as PEP 257 and ruff's `D401` say. Required on modules, classes, and module-level functions and methods; nested helpers are exempt. Inline code in single backticks, as in Markdown, never double backticks or Sphinx roles. Examples as doctests, which run in the gate, so an example that stops being true fails instead of rotting.

**Enforced by:** ruff's `D1` rules, with one of each conflicting pair chosen (`D211` over `D203`, `D212` over `D213`) and `D417` off; `docstring-code`, which refuses double backticks and Sphinx roles in docstrings; the doctests by the gate.

## Suppressions and directives

**Decision.** One suppression, for every finding from every owner: `# lup: ignore("tuple-shape", why="…")`, on the finding's line or alone above it, which asks the operator. `# noqa`, `# ruff: noqa`, `# type: ignore`, `# pyright: ignore` and pyright's file-level comments are refused. ruff runs with `--ignore-noqa` and pyright with `enableTypeIgnoreComments = false`, so a `# noqa` or a `# type: ignore` hides nothing; pyright's setting doesn't reach `# pyright: ignore` or a file-level `# pyright: basic`, which the refusal alone keeps out. lup filters every owner's findings through its own `ignore`. The rest of the `# lup:` grammar is `docs/judging-writes.md`'s (*The `# lup:` directives*).

**Why.** Several suppression syntaxes, read in several places, disagree on what's suppressed, and a misplaced one sits silently inert.

**Enforced by:** `suppression-comment`; ruff's `ERA001` (commented-out code) takes `lint.task-tags = ["lup"]` so it doesn't flag directives.

## Imports and boundaries

**Decision.** Declared as import-linter contracts in `pyproject.toml`: the library never imports the environment (`lup` never `lup_dev`, but for the environment sides kept in its directory, `lup.github` and `lup.transcripts`; `lup_dev` never `lup_dashboard`); a runtime's SDK is imported only in its adapter; the hook adapters (`lup_dev.adapters`) only by `lup_dev.cli`, which lists them; nothing inside `lup` imports its front door; git's remote helper, which runs on a room's own Python, imports the standard library alone, each module it uses listed. **In lup's own code, a runtime is named only in its adapter:** the rest of lup speaks its own words and sees a runtime through an interface (`Runtime`), in capabilities ("a runtime that can't ask before a call holds at the checkpoint"), the evidence behind each in the adapter that declares it. That's how features stay on both runtimes by construction: built per runtime above the adapter, a feature rots on the other one (`AGENTS.md`, *lup's code*). An import contract can't see a name in a string or a comment, so a rule does, in prose too. These contracts are lup's; a project declares its own.

**Why.** Import rules hand-written over a syntax scanner let a library layer reach into the environment unnoticed; import-linter checks the whole graph.

**Enforced by:** import-linter at the gate; `runtime-mention` for names, in lup's own declaration.

## Package layout

**Decision.** A subpackage is named for the subsystem it implements, reusing the first lup's name where it had the same one (`codescan`, `policy`), so what's read in `lup-legacy` maps onto the same place; a word means the same in the library and the environment (`adapters`). Every subpackage's `__init__.py` docstring says in one line what it is. Package-wide modules stay at the root: errors, settings, layout, the clock, the command line, the front door, and the tools more than one subsystem needs (`git.py`, `stored.py`, `approval.py`). Subsystems import downwards only, declared as a `layers` contract in `pyproject.toml`: in `lup_dev`, from the top, `adapters`, `launch`, `policy`, `codescan`, `declaration`, `catalog`, then `remote`, `forge` and `clipboard` side by side, `inbox`, and `host` lowest.

**Why.** A flat package hides which modules belong together. A subpackage per subsystem says what a module is part of before it's opened, and the layer order says which subsystem may know about which.

**Enforced by:** the `layers` contract in `pyproject.toml`; the names and docstrings by review.

## ruff's selection

`select = ["ALL"]`, minus each rule that overlaps or contradicts an owner above. The list is in the root `pyproject.toml`, each rule beside a comment naming the owner of its concern, so it isn't repeated here. Beyond the rules the sections above name: return types are ruff's (`ANN201`–`ANN206` stay); layout is the formatter's (`E501` and the trailing-comma rules off); rules firing only on what a lup rule refuses are off, so a finding comes once; rules steering against a convention are off (`PLR5501` to `elif`, `ASYNC109` against a `timeout` parameter, `TD` against `defer`); size thresholds are off, since they measure size rather than mistakes and spend an agent's turns (#33); `CPY001` is off until a copyright header is chosen, and `PLC0415` and `INP001` are left to review. ruff's flake8-type-checking configuration names lup's model bases and FastAPI's decorators as evaluated at runtime, so `TC001`–`TC003` never move a model's field types into a `TYPE_CHECKING` block, which would break the model.

## Tests

Tests are exempt from lup's rules, though not from ruff and pyright (with ruff's test-only exemptions). A file is a test where it's a module under a test root matching that root's file patterns (`test_*.py` and `*_test.py` by default), or a `conftest.py` under one: the roots the declaration names (`docs/declaration.md`), or, where it keeps lup's default, those pytest's configuration gives. A source module collected only for its doctests stays production code.

## Keeping the rules cohesive

- **Each rule's suggested fix passes every other rule,** and ruff and pyright: the rules' tests run each rule's rewritten example through the whole catalog.
- **Every rule names the mistake it prevents and where it steers;** a rule that can't name one goes.
- **A rule that misfires is that rule's bug,** rewritten until it fires only where a design choice is at stake.
- **Every rule named under *Enforced by:* is in the engine's table,** which a test checks (`packages/lup-dev/tests/test_reference.py`).
