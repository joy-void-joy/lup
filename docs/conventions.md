# Conventions: how code in lup is written

**One sentence:** every convention lup's code follows is decided once, here, with its reason and what enforces it, so no session has to pick between two ways of doing the same thing.

## Why this comes first

A convention a rule enforces is followed; one written only in prose splits, each session applying a different way of doing the same thing. So each entry below names what enforces it. "Convention only" is the exception and says why.

**Scope.** These apply to production code, in lup and in every project that takes lup's rules. Tests are exempt (see *Tests*). The import boundaries apply to lup itself.

**How each entry reads:** the decision, with the alternative it turns down where a reader might otherwise propose it; why; what enforces it.

## Who owns each concern

Every concern has exactly one owner, so two tools never report the same thing in two ways or steer in opposite directions.

- **lup's rules** own the conventions in this document. They live only in lup's typed engine (`docs/judging-writes.md`, *The engine*) and read one typed tree, not as ruff `banned-api` entries beside a syntax checker, which would split where they live and grow into a patchwork. Each rule names the mistake it prevents and where it steers, and has a timing (`DESIGN.md`, *Code rules and the gate*):
  - **at the edit,** the rules that pick an approach other code gets built on (parsers over regex and splitting, named fields over tuples and sets, the library for each job, errors and types, suppressions, truncation, historical voice): a finding on the lines an edit touches refuses it before it lands;
  - **at the gate,** the rules about how a correct thing is spelled (`elif`, `collection-loop`, `private-name`, `docstring-code`, `constant-home`): reported once before landing, and fixed silently where ruff has a fixer. A gate rule still blocks landing.

  The timing is issue #49; until it's built, every rule refuses at the edit.
- **ruff** owns generic Python hygiene: its own catalog, `select = ["ALL"]`, minus every rule that overlaps or contradicts another owner (*ruff's selection*). Its findings arrive as information at each checkpoint, like type errors, and must be clean when the turn ends and at the gate. A finding it fixes safely isn't reported to the agent: the session landing the work applies the fix (`lup-dev check --fix`), and the gate fails on it until then.
- **pyright**, in strict mode, owns types. Same channel as ruff.
- **import-linter** owns the import boundaries, over the whole import graph at the gate. The engine reads the same contracts to check each file's own imports at the edit; that's issue #39 until built, and until then the gate alone catches a wrong import.
- **The formatter** (ruff's) runs when work lands, with ruff's safe fixes (`lup-dev check --fix`); the gate checks it.

## Interfaces

**Decision.** An interface we own is an ABC. `Protocol` is avoided: it's for the shape of something we don't own, such as a third-party object or a callback's signature.
- A class declaring abstract members lists `ABC` in its bases. Pydantic's metaclass makes a model with an `@abstractmethod` abstract silently; naming `ABC` says so where the reader looks.
- No class inherits two of our ABCs.
- **An ABC is small:** one to three abstract methods and no concrete behaviour. Behaviour shared by its users lives in a plain class composed over it.

**Why.** Python has two ways to declare an interface. An ABC is inherited: forget a method and the class can't be created. A `Protocol` is matched by shape and checked only by pyright. Two ways means each session picks one. With ABCs only, "how do I declare an interface?" has one answer. Nothing in lup needs matching by shape: `Claude`, `Codex` and the test fake are all ours and can inherit, so a `Protocol` for what callers hold, to let test doubles fit by shape, would bring back the second way and gain nothing. A small ABC keeps its seam small, and a small seam holds while the code filling it changes.

**Enforced by:** `protocol` (a `Protocol` definition is a finding; one for a shape we don't own carries an `ignore` with its reason, which asks the operator), `interface-shape` (`ABC` named in the bases of any class with abstract members; no class inheriting two of our ABCs; one to three abstract methods and no concrete behaviour). pyright's `reportAbstractUsage` covers instantiating an abstract class.

## Data shapes

**Decision.**
- **pydantic models** for every shape we declare. No `dataclass`, no `NamedTuple`.
- **Model configuration as class keywords** (`class Turn(Model, extra="forbid")`), never a `model_config =` assignment, which reads like a field. The one exception is `lup.types.Settings` (below).
- **A list default is a literal** (`steps: list[Step] = []`, which pydantic copies per instance), not `Field(default_factory=list)`. A factory that does real work stays.
- **Frozen by default, without saying so.** Every model derives from `lup.types.Model`, which is frozen. A model that must change derives from `lup.types.MutableModel` instead, so mutability is a choice written in the header. Settings derive from `lup.types.Settings`, also frozen. No model writes `frozen` itself.
  - **Why the bases are built this way.** pyright reads a model's frozenness from its own header, defaulting to not frozen, and refuses a not-frozen class inheriting a frozen one, so without help every model would have to write `frozen=True`. `Model`'s metaclass tells pyright that its subclasses are frozen by default (PEP 681's `frozen_default`), so silence means frozen and pyright still refuses `point.x = 2`. The metaclass extends pydantic's own, from a private module: the lockfile pins pydantic, and `lup`'s tests fail at once if an upgrade moves it.
  - **Why `Settings` differs.** pyright also refuses a frozen class over pydantic-settings' base, so `Settings` freezes through `model_config`, the one place it's set. pyright doesn't see that freeze; pydantic enforces it.
- **`BaseModel` everywhere; no `TypedDict` of our own,** not even where pydantic feels too heavy. A `TypedDict` appears only where a third-party API is typed with one, and then it's theirs: Anthropic's SDK, for one, takes its request parameters as `TypedDict`s (`MessageParam`) and returns pydantic models.

**Why.** One way to declare a shape, validated where it's declared. Configuration in the class header reads with the class.

**Enforced by:** `dataclass`, `namedtuple`, `model-config`, `default-factory`, `model-mutability` (a model deriving straight from pydantic's `BaseModel` or `BaseSettings` instead of lup's bases, or writing `frozen` in its header), `typed-dict` (a `TypedDict` class we define).

## Names

**Decision.**
- **Nothing is private.** No leading underscore at any scope. A helper that shouldn't reach the module namespace is nested inside its only caller. A wrapper around one call is inlined where it's used. An unused parameter keeps its underscore: that's a linting convention, not privacy.
  - **The rule of thumb:** a function called from a single other function folds into it, as long as the caller stays a reasonable size. It's tested through its caller.
- **`__all__` only at a package's root**, where it declares that package's public API. Everywhere else a name is imported from the module that defines it.

**Why.** One rule for visibility: public, or nested. A reviewer never wonders whether `_x` is "really" private.

**Enforced by:** `private-name` (classes, functions and variables alike), `all-export`.

## Dispatch

**Decision.**
- **No `elif`,** however short the chain. A decision on a value's structure is a `match`. A comparison with no pattern to write is a guard clause that returns:
  ```python
  if seconds < 60:
      return "s"
  return "m"
  ```
- **A `match` decides through its patterns.** A guard on a wildcard (`case _ if seconds < 60:`) is an `if` chain dressed as a `match`. A guard on a real pattern that binds what it reads is fine: `case Lease(reason=str() as reason) if reason:`.
- **No chain of `isinstance` narrowing the same subject:** a `match` on the subject's class.
- **An implementation of one of our ABCs is called through the ABC, never switched on.** The shape this stops is `match runtime: case Claude(): call_claude(…) case Codex(): call_codex(…)`: choosing by which implementation of a seam you hold, where calling the ABC's method is the point of having it. A `match` or `isinstance` over the subclasses of one of our ABCs steers to a method on the ABC, which each implementation answers. Plain data told apart by a field (the four `# lup:` comment kinds, by `kind`) isn't an implementation of a seam, and is matched on like any data. Scoped to ABCs, the rule fires only where there's a seam to call through, and never steers a lower layer to call a higher one: an ABC's method is answered by each implementation by definition.

**Why.** A `match` names the subject once and makes each arm a pattern of it; a chain hides which value decides. Guard clauses keep comparisons flat.

**Enforced by:** `elif`, `wildcard-guard`, `isinstance-chain`, `own-model-dispatch`. ruff's `PLR0911` (too many returns) and `SIM116` (an `if` chain to a dict lookup) are off: they fight guard clauses and `match`.

## Constants

**Decision.** Every module-level constant has a home, and the rule's steer depends on what the constant is:

| Constant | Its home |
|---|---|
| A number or duration: a retry count, a timeout, a size limit | an overridable default: a parameter default or a model field default |
| An environment variable's name | the package's `settings.py`: its one pydantic-settings model, whose fields are the variables |
| A path or file name | the package's `layout.py`, which says where everything is stored, as a model's fields |
| A runtime's wire spelling: a tool name, a hook event, a protocol field | that adapter's `Spellings` |

In its home, a constant needs no suppression. The rule reads the constant's type: a number or a duration (`timedelta`) at module level is a finding anywhere, and a path (`pathlib`) anywhere but the package's `layout.py`, each finding naming the home. A constant held in a `str`, such as a variable's name or a wire spelling, isn't read by the rule.

**Wire spellings map lup's own words.** lup declares its own vocabulary once: its tool names, hook events and the like. A `Spellings` ABC has one abstract member per word, and each adapter implements it with its runtime's spelling. Adding a word forces every adapter to answer it, so the runtimes can't drift apart silently, where a dict would miss an entry until something broke at runtime.

**Tables of choices** (an allowlist, a set of subcommands) aren't checked; they're added if review shows misses.

**Why.** A number like `AGENT_RETRIES = 2` is a judgement a caller may want to change; frozen as a constant, they'd have to edit lup. Names and paths are a different problem: spread across files, nobody can find where things are stored or which variables are read. One home per kind answers both. Steering every module-level constant and table to an overridable default, whatever it holds, would leave each canonical value (a variable's name, a wire spelling) carrying a suppression.

**Enforced by:** `constant-home` (typed: the constant's type decides its home). ruff's `PLR2004` (magic values pushed into module constants) is off: it steers the opposite way.

## Collections and loops

**Decision.**
- **No tuple types; `list[X]` is the one spelling of a sequence.** `tuple[str, int]` becomes a model naming each field, and `tuple[X, ...]` becomes `list[X]`. Two spellings of "a sequence" would be one more fork for each session to pick. Where a third-party API takes a tuple (`sh`'s positional keywords) or hashing needs one, an `ignore` says so. A frozen model's list field can still be appended to; that's left to review. Aliases are caught where they're defined.
- **No sets as records.** `set`, `frozenset` and their aliases, declared or built, steer to a dict keyed by the members or a list of models. A set that truly has nothing to record (things already seen) takes an `ignore` with its reason.
- **No collection filled in a loop.** A collection created empty and then filled by `append`, `add`, `extend`, `update` or item assignment in a loop steers to a comprehension, or to a nested function that `yield`s when the loop has control flow a comprehension can't hold. The rule fires on the loop, not on the empty literal, which can't tell a seed from an object's state or a model default.
- **Dicts are for tables, not records.** Reading a dict or mapping by a literal key (`payload.get("name")`, `payload["name"]`) is refused: the keys are known, so it's a record; validate it once into a model and read its fields. The rule tells a mapping by its type, rather than spotting `.get("literal")` by syntax alone. A dict read by a computed key is a real lookup table and is fine. Declaring dicts is fine, `dict[str, object]` and `dict[str, <scalar>]` included: how a dict is read, not how it's typed, says whether it's a record. A `TypedDict` read by its keys is fine, since it's already the typed shape.
- `frozendict` (Python 3.15) is deferred to issue #7.

**Why.** Positional data makes review a puzzle ("what is field 5?"). A set throws away what a dict keeps. A loop mutating several variables is harder to follow than a comprehension. A dict read by literal keys hides its schema in the call sites.

**Enforced by:** `tuple-shape`, `set-shape`, `collection-loop`, `dict-literal-key`. ruff's `PERF401`–`PERF403` are off: they overlap `collection-loop`.

## Parsing

**Decision.** Structured data is read with its format's parser or a pydantic model:
- **No regular expressions:** `re` and `regex` are refused at the import, once per module, since using them is one decision.
- **No hand-splitting a `str` or `bytes`:** `.split(sep)`, `.rsplit(sep)`, `.partition`, `.rpartition`. `.split()` with no separator and `.splitlines()` are fine.
- **No slicing a `str` or `bytes`** to take it apart by position.
- **No `.strip(chars)` or `.replace` on a `str` or `bytes`** to take it apart or rewrite it: same reason. `.strip()` with no argument trims whitespace and is fine.
- An agent's output is never hand-parsed: typed answers come through lup's `submit` tool (`DESIGN.md`, *The library*; `docs/library.md`).

The parsers to reach for: `json`, `tomllib` (`tomlkit` to edit), `csv`, `urllib.parse`, `pathlib`, `email`, `shlex`, `ast`, `datetime.fromisoformat`, `packaging.version` and `packaging.requirements`, `trafilatura` or `beautifulsoup4` for web pages. A grammar of our own gets a parser library.

**XML is read with `defusedxml`.** ruff's `S313`–`S319` flag the standard library's XML parsers, and stay on: Python 3.14's docs say Expat below 2.7.2 may be vulnerable, and the interpreter uv installed carries 2.6.3. `defusedxml` is a dependency only where a project reads XML.

**Why.** Quick regex and split patches match the cases tried and fail quietly on the rest, and the bugs they leave are hard to find. A parser fails loudly.

**Enforced by:** `regex`, `string-split`, `string-slice`, `string-strip`, `string-replace`.

## Truncation and comments

**Decision.**
- **Don't truncate.** Cutting a sequence at a literal bound (`rows[:200]`) to make it fit is refused. Where a format forces a limit, keep the full copy and point at it, and say so in an `ignore`. (Slicing a `str` falls under `string-slice` above, so the two rules never fire on the same slice.)
- **Code reads as if it was always this way.** No "new", "newly", "now", "fixed", "previously", "formerly", "anymore" or "no longer" in comments and docstrings; history belongs in commit messages. "The call now waits" means something only against how it used to be, so it says "the call waits"; "a new production file" says "a production file being created". Code in backticks (the `Edit` tool's `new_string`), quoted text and doctest examples are skipped.

`historical-voice` is a heuristic over prose: a misfire is the rule's bug, rewritten when one shows up.

**Enforced by:** `silent-truncation`, `historical-voice`.

## Types

**Decision.**
- **No `typing.Any`, no `cast`, no bare `object` annotation.** JSON whose schema lives elsewhere is pydantic's `JsonValue`, or `lup.types.JsonObject` for an object; everything else gets its real type or a type parameter.
- **pyright strict.** Modern spellings: PEP 695 type parameters, `X | None`, builtin generics.
- **Python 3.14's lazily evaluated annotations**, so no `from __future__ import annotations` and no quoted annotations.

**Enforced by:** `any-type`, `cast`, `bare-object` (which accepts the `object` parameters Python's own protocols require, as in `__eq__` and `__exit__`); modern spellings by ruff's `UP` rules; return types by ruff's `ANN2xx`.

## Errors

**Decision.**
- **Exception names end in `Error`** (ruff's `N818`), never an event's name (`LaunchRefused`).
- **One root exception per package:** `LupError` in `lup`, `LupDevError` in `lup_dev`, with a tree per area below it (`TurnError`, then `OutputMissingError`). A caller can catch everything a package raises. The root is named for its package, the package's name in CamelCase plus `Error`, which is how `error-root` finds it; a file declares as many exceptions as it needs, each below the root.
- **Errors are classified from structured data**, never from message text.
- **Never swallow an error:** no `contextlib.suppress`, no bare `except:`, no `except BaseException` (catch `Exception` or something narrower). Raise on what can't be recovered; retry what's transient, with `tenacity`.

**Why.** A message gets reworded without notice, so a decision read from its text breaks quietly.

**Enforced by:** `error-root` (typed: an exception class not descending from its package's root), `suppress`, `bare-except`, `except-baseexception`; names by ruff's `N818`. `error-text` refuses deciding on an exception's message (`"x" in str(exc)`). ruff's `SIM105` (which steers *to* `contextlib.suppress`), `E722` and `BLE001` are off: the first overlaps and contradicts `suppress`, the other two overlap lup's rules and `BLE001` contradicts the steer to `Exception`.

## Libraries per job

**Decision.** One library per job:

| Job | Use | Not |
|---|---|---|
| Running a program | `sh` | `subprocess`, `os.system`, `os.popen`, `os.exec*` |
| A command line | `typer` | `argparse` |
| Paths and files | `pathlib` | `os.path`, `os` file functions |
| Configuration and environment | `pydantic-settings` | `os.environ`, `os.getenv`, `dotenv` for reading |
| Progress bars | `tqdm` | `rich.progress` |
| Retries | `tenacity` | a hand-written loop |
| Shapes | `pydantic` | `dataclasses`, `NamedTuple` |
| PDFs | read the document whole | `pypdf` and other text extractors, whose empty text reads as an empty document |

**Why.** Two libraries for one job are two ways of doing it, which sessions split between.

**Enforced by:** `subprocess`, `os-shell`, `argparse`, `os-path`, `os-file-ops`, `os-environ`, `rich-progress`, `pdf-extraction`. ruff's `PTH` rules and the `S6xx` subprocess rules are off: they overlap.

## Docstrings and comments

**Decision.**
- **Prose,** not Google-style `Args:`/`Returns:` sections, which repeat what the signature says.
- **A function's first line is in the imperative** ("Return the saved path.", not "The saved path."), as ruff's `D401` checks: a checked, uniform answer, and PEP 257's own convention.
- **Required on modules, classes, and module-level functions and methods.** Nested helpers are exempt (ruff's `D1` rules don't reach them).
- **Inline code in single backticks,** as in Markdown and these docs. Not double backticks (reStructuredText) and not Sphinx roles.
- **Examples as doctests.** A docstring may show a call and its result:
  ```python
  >>> Usage(input_tokens=3) + Usage(input_tokens=4)
  Usage(input_tokens=7)
  ```
  They run as tests in the gate (pytest's `--doctest-modules`), so an example that stops being true fails instead of rotting. Being tests, they're exempt from lup's rules.

**Enforced by:** ruff's `D1` rules, with one of each conflicting pair chosen (`D211` over `D203`, `D212` over `D213`) and `D417` off; `docstring-code`, which refuses double backticks and Sphinx roles in docstrings; the doctests by the gate.

## Suppressions and directives

**Decision.** One suppression syntax, for every finding from every owner:

```python
# lup: ignore("tuple-shape", why="sh takes its redirections as positional tuples")
```

- On the finding's line, or alone on the line above.
- **Every rule accepts it.** Adding one asks the operator.
- `# noqa`, ruff's own `# ruff: noqa` and `# ruff: disable`, `# type: ignore`, `# pyright: ignore`, and pyright's file-level comments that set its checks (`# pyright: basic`, `# pyright: standard`, `# pyright: report…`) are refused. ruff runs with `--ignore-noqa`, pyright with `enableTypeIgnoreComments = false`, and lup filters their findings through its own `ignore`.
- The rest of the `# lup:` grammar (`defer`, notes, removing a note) is in `docs/judging-writes.md`, *The `# lup:` directives*.

**Why.** Several suppression syntaxes, read in several places, disagree on what's suppressed, and a misplaced one sits silently inert. `# noqa` kept for ruff's codes alone would already be a second.

**Enforced by:** `suppression-comment`; ruff's `ERA001` (commented-out code) takes `lint.task-tags = ["lup"]` so it doesn't flag directives.

## Imports and boundaries

**Decision.** Declared as import-linter contracts in `pyproject.toml`:
- the library never imports the environment (`lup` never imports `lup_dev`, and `lup_dev` never imports `lup_dashboard`);
- a runtime's SDK is imported only in its adapter (`lup.adapters.claude`, `lup.adapters.codex`);
- a runtime's adapter is imported only where the adapters are listed: in `lup_dev`, the hook adapters (`lup_dev.adapters`) only by `lup_dev.cli`;
- nothing inside `lup` imports from its front door (`lup/__init__.py`).

import-linter checks the whole graph at the gate. The engine reads the same contracts and checks each edited file's own imports at the edit, so a wrong import is refused when it's written; that's issue #39 until built. These contracts are lup's; a project declares its own.

**A runtime is named only in its adapter.** Everything a runtime spells its own way (its hook events and payload fields, its tool names, how it hears a report, the variables it sets in the commands it runs) lives in its adapter; the rest of lup speaks its own words and sees a runtime through an interface (`lup_dev.policy.runtime.Runtime`). That's how features stay on both runtimes by construction: a feature built per runtime above the adapter rots on the other runtime (`AGENTS.md`, *Both runtimes*). An import contract can't see a name in a string or a comment, so a rule does: a runtime's name outside its adapter is a finding, in prose too. lup isn't tied to these two runtimes, so the core speaks in capabilities ("a runtime that can't ask before a call holds at the checkpoint"), and the evidence behind a capability (the vendor's docs, a measurement) sits in the adapter that declares it. Data that names a runtime's own files (`.claude/`, `.codex/` among the protected paths) and the one place listing the adapters carry an `ignore` saying so; the library's front door, where `Claude` and `Codex` are the public names a caller chooses between, is exempted in lup's declaration.

**Why.** Import rules hand-written over a syntax scanner let a library layer reach into the environment unnoticed; import-linter checks the whole graph, so the engine reads its contracts rather than carrying import rules of its own.

**Enforced by:** import-linter, and the engine at the edit (#39); `runtime-mention` for names.

## Package layout

**Decision.**
- **A subpackage is named for the subsystem it implements.** Where the first lup had the same subsystem, its name is reused, so what's read in `lup-legacy` maps onto the same place: `codescan` (its `harness/codescan`), `policy`.
- **A word the library uses means the same thing in the environment:** `adapters` holds each runtime's adapter in `lup` and in `lup_dev` alike.
- **Every subpackage's `__init__.py` docstring says in one line what it is.**
- **Package-wide modules stay at the root:** errors, settings, layout, the clock, the command line, and the front door a project's declaration imports (`__init__.py`).
- **Subsystems import downwards only,** declared as an import-linter `layers` contract. In `lup_dev`: `adapters` > `policy` > `codescan` > `declaration` > `catalog`, so the runtimes' adapters sit on judging, judging on reading code, both on what a project declares, and everything on the catalog's data.

| `lup_dev` | What it is |
|---|---|
| root | `errors.py`, `settings.py`, `layout.py`, `clock.py`, `cli.py`; the front door for a project's declaration (`__init__.py`); the gate as one command (`gate.py`); installing the judge (`install.py`); what reviews share (`review.py`) and the bridge parking them in the first lup's dashboard (`legacy_dashboard.py`) |
| `declaration/` | what a project declares, and reading it: the grammar, `Module`, the kinds, lup's modules, loading `lup_project.py` and resolving it (`docs/declaration.md`) |
| `catalog/` | the data that sets lup's policy, protected: path patterns (`paths.py`), the gate's steps (`gate.py`), the rule table (`rules.ts`) |
| `codescan/` | reading code: the engine's contract and client, the `# lup:` directives, conditions, ruff, and `docs/rules.md` compiled from the rule table |
| `policy/` | judging every write: roles, the judgement, the checkpoint and its store, holds, verdicts, reports |
| `adapters/` | each runtime's hooks, the only code naming a runtime |

**Why.** A flat package hides which modules belong together. A subpackage per subsystem says what a module is part of before it's opened, and the layer order says which subsystem may know about which.

**Enforced by:** the `layers` contract in `pyproject.toml`; the names and docstrings by review.

## ruff's selection

`select = ["ALL"]`, minus each rule that overlaps or contradicts an owner in this document. **The list lives in the root `pyproject.toml`,** each rule beside a comment naming the owner of its concern, grouped by this document's sections; it isn't repeated here, so the two can't disagree. The reason for each rule, and for the rules considered and kept on, is in the merge commit that made the selection (`2baa4b3`).

Beyond the rules this document names:
- **Return types are ruff's.** pyright strict reports a parameter without a type, but not a function without a return type, so only `ANN001`–`ANN003` and `ANN401` are off; `ANN201`–`ANN206` stay, nested helpers and tests included.
- **Layout is the formatter's.** `ISC001` stays on: ruff's formatter doesn't conflict with it. `COM812` and `COM819` are off for the formatter. `E501` (line too long) is off: line length is layout, which the formatter owns, and what it can't wrap (a long string or comment) goes unflagged.
- **Rules that fire only on what a lup rule refuses are off,** so a finding comes once, from its owner: the named-tuple, dataclass, private-name, `re`, string-slice, `Any`, `cast`, `contextlib.suppress`, subprocess and `os.environ` rules among them.
- **Rules that steer against a convention are off:** `PLR5501` (steers to `elif`), `PLR1714` (to a set literal), `ASYNC109` (flags a `timeout` parameter, the home of a duration), `TD` (TODO comments, where deferred work is `defer`).
- **Size thresholds are off:** `C901`, `PLR0912`, `PLR0913`, `PLR0915`, `PLR1702` (complexity, branches, arguments, statements, nesting) measure size, not mistakes, and #33 counts them among the findings an agent spends turns on that change nothing a reader cares about. Whether a function is too big is review's, until #33 settles what's worth an agent's attention. Raising their limits instead would still spend an agent's turns at the raised limit.
- **`CPY001` is off** until a copyright header is chosen.
- **Configured rather than off:** `ERA001` takes `lint.task-tags = ["lup"]`; `TC003` takes `lint.flake8-type-checking.runtime-evaluated-base-classes`, listing pydantic's `BaseModel` and `BaseSettings` and lup's `Model`, `MutableModel` and `Settings`, so a field's type isn't moved into a `TYPE_CHECKING` block, which would break the model at runtime.
- **The gate runs `ruff check --ignore-noqa`:** ruff has no setting for it.

Each lup rule says which ruff rules it turns off, in `pyproject.toml`.

## Tests

Tests are exempt from lup's rules. A file is a test if it's a module under a test root matching that root's file patterns (`test_*.py` and `*_test.py` by default), or a `conftest.py` under one. The test roots are the ones the declaration names (`Python.tests`, `docs/declaration.md`); a project that keeps lup's default names none, and its roots are the ones pytest reads (`testpaths` in the nearest `pyproject.toml` holding pytest's options, nested projects included, with its `python_files` patterns). lup's own declaration names `packages/*/tests`. The patterns matter: the source directories are in `testpaths` too, so pytest runs their doctests, and a source module collected only for its doctests stays production code. Test roles come from the suites the gate runs, so the exemption covers exactly what runs as tests. ruff and pyright still run on tests, with ruff's test-only exemptions (`S101`, `D`, `ARG`, `INP001`).

## Keeping the rules cohesive

- **Each rule's suggested fix passes every other rule,** and ruff and pyright. The rules' tests run each rule's `rewritten` example, its steer applied, through the whole catalog.
- **Every rule names the mistake it prevents and where it steers:** one line in the refusal, the full reason in `docs/rules.md`. A rule that can't name one goes.
- **A rule that misfires is that rule's bug,** rewritten until it fires only where a design choice is at stake.
- **One owner per concern** (*Who owns each concern*); each rule says which ruff rules it turns off.

## The rules

Each rule, with the mistake it prevents, where it steers, and the code it flags and leaves alone, is in [`docs/rules.md`](rules.md). That file is generated from the engine's table (`packages/lup-dev/src/lup_dev/catalog/rules.ts`) by `lup-dev rules docs`, and a test keeps it in step. Every rule named under *Enforced by:* above is in that table, which a test checks too.

Rules of the first lup's catalog (`docs/rules.md` in `lup-legacy`), by what covers their concern here:
- `constant-declaration`, `library-default`: `constant-home`;
- `empty-collection`: `collection-loop`;
- `dict-get`, `dict-str-payload`, `dict-str-object`: `dict-literal-key`;
- `frozenset-shape`: `set-shape`;
- `abc-capability`, `abstract-declaration`: `interface-shape`;
- `private-class`, `private-function`, `private-variable`: `private-name`;
- `import-re`, `re-call`: `regex`, one finding per module;
- `front-door`, `seam-boundary`, `kernel-imports`: import-linter's contracts;
- `generic-base`, `typing-generics`, `typing-union`, `utcnow`, `global-statement`, `eval-exec`: ruff's own rules (`UP`, `DTZ003`, `PLW0603`, `S307`, `S102`).
