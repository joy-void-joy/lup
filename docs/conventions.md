# Conventions: how code in lup is written

**One sentence:** every convention lup's code follows is decided once, here, with its reason and what enforces it, so no session has to pick between two ways of doing the same thing.

## Why this comes first

The first lup's main problem was inconsistent conventions: many ways of doing one thing, each session applying a different one. Its own code shows where that came from:
- **Where a rule existed, the code complied completely.** No private names, no `elif`, no `typing.Any`, no fixed-length tuples, no `model_config =` assignment, across 241k lines.
- **Where only prose existed, the code split:**
  - 1,511 pydantic models frozen and 329 mutable, none saying `frozen=False`: mutability by omission;
  - 47 exception names ending in `Error` and 35 not, under 67 separate root classes;
  - inline code in docstrings spelled three ways;
  - ABC or `Protocol` never stated anywhere as a rule, which is how the second lup's first draft wrote its adapter contract as a `Protocol` against the first lup's ABCs.

So each entry below names what enforces it. "Convention only" is the exception and says why.

**Scope.** These apply to production code, in lup and in every project that takes lup's rules. Tests are exempt (see *Tests*). The import boundaries apply to lup itself.

**How each entry reads:** the decision; why; what the first lup did (evidence from its code, its rule catalog `docs/rules.md` in `lup-legacy`, and its friction); what enforces it.

## Who owns each concern

Every concern has exactly one owner, so two tools never report the same thing in two ways or steer in opposite directions.

- **lup's rules** own the conventions in this document. They live only in lup's typed engine (`docs/judging-writes.md`, *The engine*), read one typed tree, and **refuse at the edit**: a finding on the lines an edit touches stops it. Each rule names the mistake it prevents and where it steers.
- **ruff** owns generic Python hygiene: its own catalog, `select = ["ALL"]`, minus every rule that overlaps or contradicts a lup rule (listed in *ruff's selection*). Its findings arrive as information at each checkpoint, like type errors, and must be clean when the turn ends and at the gate.
- **pyright**, in strict mode, owns types. Same channel as ruff.
- **import-linter** owns the import boundaries, over the whole import graph at the gate; the engine reads the same contracts to check each file's own imports at the edit.
- **The formatter** (ruff's) runs at commit.

The first lup ran ruff's defaults and pyright's standard mode; its strictness came from its own catalog, which collided with ruff in places (below).

## Interfaces

**Decision.** An interface we own is an ABC. `Protocol` is avoided: it's for the shape of something we don't own, such as a third-party object or a callback's signature.
- A class declaring abstract members lists `ABC` in its bases. Pydantic's metaclass makes a model with an `@abstractmethod` abstract silently; naming `ABC` says so where the reader looks.
- No class inherits two of our ABCs.

**Why.** Python has two ways to declare an interface. An ABC is inherited: forget a method and the class can't be created. A `Protocol` is matched by shape and checked only by pyright. Two ways means each session picks one. With ABCs only, "how do I declare an interface?" has one answer. Nothing in lup needs matching by shape: `Claude`, `Codex` and the test fake are all ours and can inherit.

**The first lup.** 76 ABC classes and 13 `Protocol` classes. ABCs were the seams an adapter fills (`sessions/capabilities.py`, 10 of them); Protocols were what callers held (`Agent`, `Conversation`, `Turn`), so test doubles fit structurally. The split lived only in `docs/patterns.md` and a docstring. The seams held: `sessions/capabilities.py` had 11 commits and no fix, against 131 fixes in the two adapters. Its `abc-capability` rule (5 suppressions, all in one file) and `abstract-declaration` rule enforced the ABC shape.

- **An ABC is small:** one to three abstract methods and no concrete behaviour, as the first lup's capability rule had it (`docs/architecture.md` in `lup-legacy`). It's what kept the seams small. Behaviour shared by its users lives in a plain class composed over it.

**Enforced by:** `protocol` (a `Protocol` definition is a finding; one for a shape we don't own carries an `ignore` with its reason, which asks the operator), `interface-shape` (`ABC` named in the bases of any class with abstract members; no class inheriting two of our ABCs; one to three abstract methods and no concrete behaviour). pyright's `reportAbstractUsage` covers instantiating an abstract class.

## Data shapes

**Decision.**
- **pydantic models** for every shape we declare. No `dataclass`, no `NamedTuple`.
- **Model configuration as class keywords** (`class Turn(Model, extra="forbid")`), never a `model_config =` assignment, which reads like a field. The one exception is `lup.types.Settings` (below).
- **A list default is a literal** (`steps: list[Step] = []`, which pydantic copies per instance), not `Field(default_factory=list)`. A factory that does real work stays.
- **Frozen by default, without saying so.** Every model derives from `lup.types.Model`, which is frozen. A model that must change derives from `lup.types.MutableModel` instead, so mutability is a choice written in the header. Settings derive from `lup.types.Settings`, also frozen. No model writes `frozen` itself.
  - **Why the bases are built this way.** pyright reads a model's frozenness from its own header, defaulting to not frozen, and refuses a not-frozen class inheriting a frozen one; that's why the first lup wrote `frozen=True` on every model. `Model`'s metaclass tells pyright that its subclasses are frozen by default (PEP 681's `frozen_default`), so silence means frozen and pyright still refuses `point.x = 2`. The metaclass extends pydantic's own, from a private module: the lockfile pins pydantic, and `lup`'s tests fail at once if an upgrade moves it.
  - **Why `Settings` differs.** pyright also refuses a frozen class over pydantic-settings' base, so `Settings` freezes through `model_config`, the one place it's set. pyright doesn't see that freeze; pydantic enforces it.
- **`BaseModel` everywhere; no `TypedDict` of our own.** A `TypedDict` appears only where a third-party API is typed with one, and then it's theirs: Anthropic's SDK, for one, takes its request parameters as `TypedDict`s (`MessageParam`) and returns pydantic models.

**Why.** One way to declare a shape, validated where it's declared. Configuration in the class header reads with the class.

**The first lup.** 1,840 pydantic classes, no dataclass and no NamedTuple. 1,559 used class keywords and no class body assigned `model_config` (the rule held fully). 240 `TypedDict` classes, 113 of them in the hook kernel, which couldn't import pydantic. `default-factory`: no suppressions, 2 refusals. It contradicted `empty-collection` (its steer `= []` was flagged by it), which the loop rule below removes.

**Enforced by:** `dataclass`, `namedtuple`, `model-config`, `default-factory`, `model-mutability` (a model deriving straight from pydantic's `BaseModel` or `BaseSettings` instead of lup's bases, or writing `frozen` in its header), `typed-dict` (a `TypedDict` class we define).

## Names

**Decision.**
- **Nothing is private.** No leading underscore at any scope. A helper that shouldn't reach the module namespace is nested inside its only caller. A wrapper around one call is inlined where it's used. An unused parameter keeps its underscore: that's a linting convention, not privacy.
  - **The rule of thumb:** a function called from a single other function folds into it, as long as the caller stays a reasonable size. It's tested through its caller.
- **`__all__` only at a package's root**, where it declares that package's public API. Everywhere else a name is imported from the module that defines it.
- **Exception names end in `Error`.**

**Why.** One rule for visibility: public, or nested. A reviewer never wonders whether `_x` is "really" private.

**The first lup.** No private names anywhere, no suppressions, no friction recorded. `all-export`: 1 suppression. Exception names were split (47 with `Error`, 35 without).

**Enforced by:** `private-name` (the first lup's three private-class, private-function and private-variable rules as one), `all-export`; exception names by ruff's `N818`.

## Dispatch

**Decision.**
- **No `elif`.** A decision on a value's structure is a `match`. A comparison with no pattern to write is a guard clause that returns:
  ```python
  if seconds < 60:
      return "s"
  return "m"
  ```
- **A `match` decides through its patterns.** A guard on a wildcard (`case _ if seconds < 60:`) is an `if` chain dressed as a `match`. A guard on a real pattern that binds what it reads is fine: `case Lease(reason=str() as reason) if reason:`.
- **No chain of `isinstance` narrowing the same subject:** a `match` on the subject's class.
- **An implementation of one of our ABCs is called through the ABC, never switched on.** The shape this stops is the first lup's `match runtime: case Claude: call_claude(…) case Codex: call_codex(…)`: choosing by which implementation of a seam you hold, where calling the ABC's method was the point of having it. A `match` or `isinstance` over the subclasses of one of our ABCs steers to a method on the ABC, which each implementation answers. Plain data told apart by a field (the four `# lup:` comment kinds, by `kind`) isn't an implementation of a seam, and is matched on like any data. Scoping it to ABCs keeps it from the first lup's misfires (it was narrowed twice) and from steering a lower layer to call a higher one: an ABC's method is answered by each implementation by definition.

**Why.** A `match` names the subject once and makes each arm a pattern of it; a chain hides which value decides. Guard clauses keep comparisons flat.

**The first lup.** 491 `match` statements, no `elif` line and no wildcard guard anywhere, 409 single `isinstance` narrowings. `elif-chain`: no suppression, 11 refusals. Its message said "three or more ways" while in practice it refused every `elif`; here it says what it does. `own-model-dispatch` misfired and was narrowed (c5e855170), and it contradicted `isinstance-chain`'s steer.

**Enforced by:** `elif`, `wildcard-guard`, `isinstance-chain`, `own-model-dispatch`. ruff's `PLR0911` (too many returns) and `SIM116` (an `if` chain to a dict lookup) are off: they fight guard clauses and `match`.

## Constants

**Decision.** Every module-level constant has a home, and the rule's steer depends on what the constant is:

| Constant | Its home |
|---|---|
| A number or duration: a retry count, a timeout, a size limit | an overridable default: a parameter default or a model field default |
| An environment variable's name | the package's `settings.py`: its one pydantic-settings model, whose fields are the variables |
| A path or file name | the package's `layout.py`, which says where everything is stored, as a model's fields |
| A runtime's wire spelling: a tool name, a hook event, a protocol field | that adapter's `Spellings` |

In its home, a constant needs no suppression. Anywhere else the rule fires and names the home.

**Wire spellings map lup's own words.** lup declares its own vocabulary once: its tool names, hook events and the like. A `Spellings` ABC has one abstract member per word, and each adapter implements it with its runtime's spelling. Adding a word forces every adapter to answer it, so the runtimes can't drift apart silently, where a dict would miss an entry until something broke at runtime. The first lup had this as its `NativeSpellings` ABC (`docs/patterns.md` in `lup-legacy`, *Closed By Construction*).

**Tables of choices** (an allowlist, a set of subcommands) aren't checked at first: the rule fires on numbers and durations, and tables are added if review shows misses.

**Why.** A number like `AGENT_RETRIES = 2` is a judgement a caller may want to change; frozen as a constant, they'd have to edit lup. Names and paths are a different problem: spread across files, nobody can find where things are stored or which variables are read. One home per kind answers both.

**The first lup.** `constant-declaration` and `library-default` carried 355 of the library's 783 suppressions (45%). Of the 149 suppressions tied to a module-level constant: 69 were strings (file names, variable names, protocol names), 54 sequences of someone else's vocabulary (git's subcommands, loopback hosts), 14 calls such as `Path("join")`, 7 dict tables, and 5 numbers. The rule's value was in the numbers; its noise was names that were already canonical. The second lup's first draft had `_REASKS = 2`, which the first lup's checker caught.

**Enforced by:** `constant-home` (typed: the constant's type decides its home). ruff's `PLR2004` (magic values pushed into module constants) is off: it steers the opposite way.

## Collections and loops

**Decision.**
- **No tuple types; `list[X]` is the one spelling of a sequence.** `tuple[str, int]` becomes a model naming each field, and `tuple[X, ...]` becomes `list[X]`. Two spellings of "a sequence" would be one more fork for each session to pick. Where a third-party API takes a tuple (`sh`'s positional keywords) or hashing needs one, an `ignore` says so. A frozen model's list field can still be appended to; that's left to review. Aliases are caught where they're defined.
- **No sets as records.** `set`, `frozenset` and their aliases, declared or built, steer to a dict keyed by the members or a list of models. A set that truly has nothing to record (things already seen) takes an `ignore` with its reason.
- **No collection filled in a loop.** A collection created empty and then filled by `append`, `add`, `extend`, `update` or item assignment in a loop steers to a comprehension, or to a nested function that `yield`s when the loop has control flow a comprehension can't hold.
- **Dicts are for tables, not records.** Reading a dict or mapping by a literal key (`payload.get("name")`, `payload["name"]`) is refused: the keys are known, so it's a record; validate it once into a model and read its fields. A dict read by a computed key is a real lookup table and is fine. Declaring dicts is fine. A `TypedDict` read by its keys is fine, since it's already the typed shape.
- `frozendict` (Python 3.15) is deferred to issue #7.

**Why.** Positional data makes review a puzzle ("what is field 5?"). A set throws away what a dict keeps. A loop mutating several variables is harder to follow than a comprehension. A dict read by literal keys hides its schema in the call sites.

**The first lup.**
- `tuple-shape`: no suppression, 13 refusals, and no fixed tuple left in the library. Refusing any suppression made `sh`'s positional keywords (`_tty_size`, `_arg_preprocess`) impossible to type; every rule accepts `ignore` here.
- `set-shape` 30 suppressions, `frozenset-shape` 15, folded into one rule.
- `empty-collection` fired on the empty literal, not the loop. It couldn't tell a seed from an object's state or a model default: 89 suppressions, 13 cleanup commits, and one project turned it off.
- `dict-get` had the most bug reports of any rule (#181, #212, #459, #530 in `lup-legacy`), from receivers it couldn't resolve without types. `dict-str-payload` (55 suppressions, mostly "it's an open map") and `dict-str-object` flagged declarations; they're dropped. `set-shape` steered to dicts that `dict-str-payload` then flagged.

**Enforced by:** `tuple-shape`, `set-shape`, `collection-loop`, `dict-literal-key`. ruff's `PERF401`–`PERF403` are off: they overlap `collection-loop`.

## Parsing

**Decision.** Structured data is read with its format's parser or a pydantic model:
- **No regular expressions:** `re` and `regex` are refused at the import, once per module, since using them is one decision.
- **No hand-splitting a `str` or `bytes`:** `.split(sep)`, `.rsplit(sep)`, `.partition`, `.rpartition`. `.split()` with no separator and `.splitlines()` are fine.
- **No slicing a `str` or `bytes`** to take it apart by position.
- **No `.strip(chars)` or `.replace` on a `str` or `bytes`** to take it apart or rewrite it: same reason (7 and 10 suppressions in the first lup). `.strip()` with no argument trims whitespace and is fine.
- An agent's output is never hand-parsed: typed answers come through `lup_submit` (`docs/library.md`).

The parsers to reach for: `json`, `tomllib` (`tomlkit` to edit), `csv`, `urllib.parse`, `pathlib`, `email`, `shlex`, `ast`, `datetime.fromisoformat`, `packaging.version` and `packaging.requirements`, `trafilatura` or `beautifulsoup4` for web pages. A grammar of our own gets a parser library.

**XML is read with `defusedxml`.** ruff's `S313`–`S319` flag the standard library's XML parsers, and stay on: Python 3.14's docs say Expat below 2.7.2 may be vulnerable, and the interpreter uv installed carries 2.6.3. `defusedxml` is a dependency only where a project reads XML.

**Why.** Quick regex and split patches matched the cases tried and failed quietly on the rest; the bugs were hard to find. A parser fails loudly.

**The first lup.** `import-re` and `re-call`: 18 and 20 suppressions. `string-split` was syntax-only: 79 suppressions, and it flagged `shlex.split` and `re.split`. Typed, it reads the receiver's type; the spike confirmed it leaves those out.

**Enforced by:** `regex`, `string-split`, `string-slice`, `string-strip`, `string-replace`.

## Truncation and comments

**Decision.**
- **Don't truncate.** Cutting a sequence at a literal bound (`rows[:200]`) to make it fit is refused. Where a format forces a limit, keep the full copy and point at it, and say so in an `ignore`. (Slicing a `str` falls under `string-slice` above, so the two rules never fire on the same slice.)
- **Code reads as if it was always this way.** No "new", "now", "fixed", "previously" or "no longer" in comments and docstrings; history belongs in commit messages. "The call now waits" means something only against how it used to be, so it says "the call waits"; "a new production file" says "a production file being created". Code in backticks (the `Edit` tool's `new_string`) and quoted text are skipped.

**The first lup.** `silent-truncation`: 6 suppressions. `historical-voice` is a heuristic over comments; expect misfires, and rewrite it when one shows up.

**Enforced by:** `silent-truncation`, `historical-voice`.

## Types

**Decision.**
- **No `typing.Any`, no `cast`, no bare `object` annotation.** JSON whose schema lives elsewhere is pydantic's `JsonValue`, or `lup.types.JsonObject` for an object; everything else gets its real type or a type parameter.
- **pyright strict.** Modern spellings: PEP 695 type parameters, `X | None`, builtin generics.
- **Python 3.14's lazily evaluated annotations**, so no `from __future__ import annotations` and no quoted annotations.

**The first lup.** `typing.Any` never imported, `cast` 7 times; PEP 695 on 53 classes and 76 functions, no `TypeVar`. pyright ran in standard mode, never strict.

**Enforced by:** `any-type`, `cast`, `bare-object` (which accepts the `object` parameters Python's own protocols require, as in `__eq__` and `__exit__`); modern spellings by ruff's `UP` rules; return types by ruff's `ANN2xx`.

## Errors

**Decision.**
- **Exception names end in `Error`** (ruff's `N818`).
- **One root exception per package:** `LupError` in `lup`, `LupDevError` in `lup_dev`, with a tree per area below it (`TurnError`, then `OutputMissingError`). A caller can catch everything a package raises. The root is named for its package, the package's name in CamelCase plus `Error`, which is how `error-root` finds it; a file declares as many exceptions as it needs, each below the root.
- **Errors are classified from structured data**, never from message text.
- **Never swallow an error:** no `contextlib.suppress`, no bare `except:`, no `except BaseException` (catch `Exception` or something narrower). Raise on what can't be recovered; retry what's transient, with `tenacity`.

**The first lup.** 82 exception classes under 67 separate roots, most straight from `RuntimeError` or `ValueError`. It classified runtime faults by matching substrings of messages (`providers/claude/runtime.py:142-290`), against its own principle.

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

**The first lup.** sh in 68 files against `subprocess` in 6 (all in hook assets that couldn't import `sh`); typer 85 against argparse 3; pathlib 401; pydantic-settings 10. `os-environ`: 27 suppressions.

**Enforced by:** `subprocess`, `os-shell`, `argparse`, `os-path`, `os-file-ops`, `os-environ`, `rich-progress`, `pdf-extraction`. ruff's `PTH` rules and the `S6xx` subprocess rules are off: they overlap.

## Docstrings and comments

**Decision.**
- **Prose,** not `Args:`/`Returns:` sections, which repeat what the signature says.
- **A function's first line is in the imperative** ("Return the saved path.", not "The saved path."), as ruff's `D401` checks: a checked, uniform answer, and PEP 257's own convention.
- **Required on modules, classes, and module-level functions and methods.** Nested helpers are exempt (ruff's `D1` rules don't reach them; checked).
- **Inline code in single backticks,** as in Markdown and these docs. Not double backticks (reStructuredText) and not Sphinx roles.
- **Examples as doctests.** A docstring may show a call and its result:
  ```python
  >>> Usage(input_tokens=3) + Usage(input_tokens=4)
  Usage(input_tokens=7)
  ```
  They run as tests in the gate (pytest's `--doctest-modules`), so an example that stops being true fails instead of rotting. Being tests, they're exempt from lup's rules.

**The first lup.** 81% of functions had a docstring, 0.5% used `Args:` sections. Inline code: 1,561 docstrings used double backticks only, 1,076 single only, 721 both, and 863 used Sphinx roles.

**Enforced by:** ruff's `D1` rules, with one of each conflicting pair chosen (`D211` over `D203`, `D212` over `D213`) and `D417` off; `docstring-code`, which refuses double backticks and Sphinx roles in docstrings; the doctests by the gate.

## Suppressions and directives

**Decision.** One suppression syntax, for every finding from every owner:

```python
# lup: ignore("tuple-shape", why="sh takes its redirections as positional tuples")
```

- On the finding's line, or alone on the line above.
- **Every rule accepts it.** Adding one asks the operator.
- `# noqa`, ruff's own `# ruff: noqa` and `# ruff: disable`, `# type: ignore` and `# pyright: ignore` are refused. ruff runs with `--ignore-noqa`, pyright with `enableTypeIgnoreComments = false`, and lup filters their findings through its own `ignore`.
- The rest of the `# lup:` grammar (`defer`, notes, removing a note) is in `docs/judging-writes.md`, *The `# lup:` directives*.

**The first lup.** 783 typed directives in the library, 40 in its application, 112 in its tests (the test exemption didn't apply in lup itself). Placement bugs: a file-wide ignore after the docstring was silently inert (#213), and the edit hook and the audit disagreed on 18 files.

**Enforced by:** `suppression-comment`; ruff's `ERA001` (commented-out code) takes `lint.task-tags = ["lup"]` so it doesn't flag directives.

## Imports and boundaries

**Decision.** Declared as import-linter contracts in `pyproject.toml`:
- the library never imports the environment (`lup` never imports `lup_dev`, and `lup_dev` never imports `lup_dashboard`);
- a runtime's SDK is imported only in its adapter (`lup.adapters.claude`, `lup.adapters.codex`);
- a runtime's adapter is imported only where the adapters are listed: in `lup_dev`, the hook adapters (`lup_dev.adapters`) only by `lup_dev.cli`;
- nothing inside `lup` imports from its front door (`lup/__init__.py`).

import-linter checks the whole graph at the gate. The engine reads the same contracts and checks each edited file's own imports at the edit, so a wrong import is refused when it's written. These contracts are lup's; a project declares its own.

**A runtime is named only in its adapter.** Everything a runtime spells its own way (its hook events and payload fields, its tool names, how it hears a report, the variables it sets in the commands it runs) lives in its adapter; the rest of lup speaks its own words and sees a runtime through an interface (`lup_dev.policy.runtime.Runtime`). That's how features stay on both runtimes by construction: Codex rotted in the first lup because features were built per runtime above the adapter (`AGENTS.md`, *Both runtimes*). An import contract can't see a name in a string or a comment, so a rule does: a runtime's name outside its adapter is a finding, in prose too. lup lives on beyond these two runtimes; they're the two good ones for now. So the core speaks in capabilities ("a runtime that can't ask before a call holds at the checkpoint"), and the evidence behind a capability (the vendor's docs, a measurement) sits in the adapter that declares it. Data that names a runtime's own files (`.claude/`, `.codex/` among the protected paths) and the one place listing the adapters carry an `ignore` saying so; the library's front door, where `Claude` and `Codex` are the public names a caller chooses between, is exempted in lup's declaration.

**The first lup.** `front-door`, `seam-boundary` and `kernel-imports` were custom rules over an AST scanner. Its tool layer still reached into environment packages (`tools/toolsets.py:38-43` imported coordination, ledger and orchestration).

**Enforced by:** import-linter (a new dependency, agreed), and the engine at the edit; `runtime-mention` for names.

## Package layout

**Decision.**
- **A subpackage is named for the subsystem it implements.** Where the first lup had the same subsystem, its name is reused, so what's read in `lup-legacy` maps onto the same place: `codescan` (its `harness/codescan`), `policy`.
- **A word the library uses means the same thing in the environment:** `adapters` holds each runtime's adapter in `lup` and in `lup_dev` alike.
- **Every subpackage's `__init__.py` docstring says in one line what it is.**
- **Package-wide modules stay at the root:** errors, settings, layout, the project declaration, the clock, the command line.
- **Subsystems import downwards only,** declared as an import-linter `layers` contract. In `lup_dev`: `adapters` > `policy` > `codescan` > `catalog`, so the runtimes' adapters sit on judging, judging on reading code, and everything on the catalog's data.

| `lup_dev` | What it is |
|---|---|
| root | `errors.py`, `settings.py`, `layout.py`, `project.py`, `clock.py`, `cli.py` |
| `catalog/` | the data that sets lup's policy, protected: path patterns, and the rule catalog to come |
| `codescan/` | reading code: the engine's contract and client, the `# lup:` directives, conditions, ruff |
| `policy/` | judging every write: roles, the judgement, the checkpoint and its store, holds, verdicts, reports |
| `adapters/` | each runtime's hooks, the only code naming a runtime |

**Why.** A flat package hides which modules belong together: `lup_dev` reached 21 top-level modules with its first piece. A subpackage per subsystem says what a module is part of before it's opened, and the layer order says which subsystem may know about which.

**Enforced by:** the `layers` contract in `pyproject.toml`; the names and docstrings by review.

## ruff's selection

`select = ["ALL"]`, minus each rule that overlaps or contradicts an owner in this document. **The list lives in the root `pyproject.toml`,** each rule beside a comment naming the owner of its concern, grouped by this document's sections; it isn't repeated here, so the two can't disagree. The full pass over ruff's 810 rules (ruff 0.16.10) produced it, and its merge commit (`2baa4b3`) gives each rule's reason and the rules considered and kept.

What the pass settled beyond the rules this document names:
- **Return types are ruff's.** pyright strict reports a parameter without a type, but not a function without a return type, so only `ANN001`–`ANN003` and `ANN401` are off; `ANN201`–`ANN206` stay, nested helpers and tests included.
- **`ISC001` stays on:** ruff's formatter no longer conflicts with it. `COM812` and `COM819` are off for the formatter.
- **Rules that fire only on what a lup rule refuses are off,** so a finding comes once, from its owner: the named-tuple, dataclass, private-name, `re`, string-slice, `Any`, `cast`, `contextlib.suppress`, subprocess and `os.environ` rules among them.
- **Rules that steer against a convention are off:** `PLR5501` (steers to `elif`), `PLR1714` (to a set literal), `ASYNC109` (flags a `timeout` parameter, the home of a duration), `TD` (TODO comments, where deferred work is `defer`).
- **`CPY001` is off** until a copyright header is chosen.
- **Configured rather than off:** `ERA001` takes `lint.task-tags = ["lup"]`; `TC003` takes `runtime-evaluated-base-classes = ["pydantic.BaseModel", "pydantic_settings.BaseSettings"]`, so a field's type isn't moved into a `TYPE_CHECKING` block, which would break the model at runtime.
- **The gate runs `ruff check --ignore-noqa`:** ruff has no setting for it.

A rule added later says which ruff rules it turns off, in `pyproject.toml`.

## Tests

Tests are exempt from lup's rules. A file is a test if pytest collects it as a test module: under a root pytest reads (`testpaths` in the nearest `pyproject.toml`, nested projects included) and matching its `python_files` patterns (`test_*.py` by default), until the project declaration names its tests. The patterns matter: the source directories are in `testpaths` too, so pytest runs their doctests, and a source module collected only for its doctests stays production code. In the first lup the exemption existed but never applied in one project, because test roles came from somewhere other than the suites the gate runs. ruff and pyright still run on tests, with ruff's test-only exemptions (`S101`, `D`, `ARG`, `INP001`).

## Keeping the rules cohesive

- **Each rule's suggested fix passes every other rule,** and ruff and pyright. The rules' tests run every rule's "steer to" example through the whole catalog. The first lup had three such contradictions (`default-factory` against `empty-collection`, `set-shape` against `dict-str-payload`, `isinstance-chain` against `own-model-dispatch`), plus `SIM105`, `PLR2004`, `PLR0911` and `SIM116` against its own catalog.
- **Every rule names the mistake it prevents and where it steers:** one line in the refusal, the full reason in `lup docs rules`. A rule that can't name one goes.
- **A rule that misfires is that rule's bug,** rewritten until it fires only where a design choice is at stake.
- **One owner per concern** (*Who owns each concern*); a new rule says which ruff rules it turns off.

## The rules

Each rule, with the mistake it prevents, where it steers, and the code it flags and leaves alone, is in [`docs/rules.md`](rules.md). That file is generated from the engine's table (`packages/lup-dev/src/lup_dev/catalog/rules.ts`) by `lup-dev rules docs`, and a test keeps it in step. Every rule named under *Enforced by:* above is in that table, which a test checks too.

Dropped from the first lup's catalog, with why:
- `constant-declaration`, `library-default`: replaced by `constant-home`;
- `empty-collection`: replaced by `collection-loop`;
- `dict-get`, `dict-str-payload`, `dict-str-object`: replaced by `dict-literal-key`;
- `frozenset-shape`: folded into `set-shape`;
- `abc-capability`, `abstract-declaration`: folded into `interface-shape`;
- `import-re`, `re-call`: one `regex` finding per module;
- `front-door`, `seam-boundary`, `kernel-imports`: import-linter contracts;
- `generic-base`, `typing-generics`, `typing-union`, `utcnow`, `global-statement`, `eval-exec`: ruff's own rules (`UP`, `DTZ003`, `PLW0603`, `S307`, `S102`);
- `assembly-boundary`, `native-spelling`, `portable-content`, `derived-interpolation`, `stale-reference`: about the first lup's harness and generated docs; reconsidered if the same constructs return.

## Decisions

Each with its alternative and where it lives. **(yours, agreed)** marks what the operator decided in conversation; **(yours)** what still waits on them.

1. **(yours, agreed)** lup's rules live only in its typed engine, from the first rule; ruff keeps its generic checks with every overlapping or contradicting rule off. *Alternative:* lup's bans as ruff `banned-api` entries and a syntax checker first, which splits where rules live and is how the first lup's patchwork started. *Where:* the engine; `pyproject.toml`.
2. **(yours, agreed)** ABCs for every interface we own; `Protocol` avoided. *Alternative:* the first lup's split (ABC for seams, Protocol for what callers hold), never written down. *Where:* `protocol`, `interface-shape`.
3. **(yours, agreed)** An ABC keeps the one-to-three-abstract-methods limit and no concrete behaviour. *Alternative:* no size limit. *Where:* `interface-shape`.
4. **(yours, agreed)** Models frozen by default without saying so: `lup.types.Model` is frozen, `MutableModel` isn't, `Settings` is; no model writes `frozen`. *Alternatives:* `frozen=True` on every model, which pyright demands without the metaclass; freezing through `model_config`, which reads like a field. *Where:* `lup/types.py`, `model-mutability`.
5. **(yours, agreed)** `BaseModel` everywhere; a `TypedDict` only where a third-party API is typed with one, and then theirs. *Alternative:* `TypedDict` anywhere pydantic is too heavy. *Where:* `typed-dict`.
6. **(yours, agreed)** No `elif`; `match` for structure; guard clauses for comparisons; no wildcard guards. *Alternative:* `elif` allowed up to two arms. *Where:* `elif`, `wildcard-guard`.
7. **(yours, agreed)** Keep `own-model-dispatch`, scoped to our own unions. *Alternative:* convention only. *Where:* the engine.
8. **(yours, agreed)** Constants by home: numbers and durations become overridable defaults; variable names go to the package's `settings.py`, paths to its `layout.py`, wire spellings to each adapter's `Spellings`, an ABC mapping lup's own words. Tables of choices wait until review shows misses. *Alternatives:* the first lup's two rules; leaving strings alone; a dict per adapter, which can miss a word silently. *Where:* `constant-home`.
9. **(yours, agreed)** The loop rule fires on the loop, not the empty literal. *Alternative:* the first lup's `empty-collection`, or ruff's `PERF` rules. *Where:* `collection-loop`.
10. **(yours, agreed)** Reading a dict by a literal key is refused; declaring dicts is fine; `frozendict` waits for Python 3.15 (#7). *Alternative:* the first lup's `dict-get` and signature rules. *Where:* `dict-literal-key`.
11. **(yours, agreed)** `.strip(chars)` and `.replace` on a `str` join the parsing rules. *Alternative:* left out. *Where:* `string-strip`, `string-replace`.
12. **(yours, agreed)** `…Error` names (ruff `N818`) and one root exception per package. *Alternative:* names as events (`LaunchRefused`), independent roots. *Where:* `error-root`, `pyproject.toml`.
13. **(yours, agreed)** `error-text`, refusing decisions on an exception's message. *Alternative:* convention only. *Where:* the engine.
14. **(yours, agreed)** Prose docstrings, required on modules, classes and module-level definitions; nested helpers exempt. *Alternative:* Google sections. *Where:* `pyproject.toml` (ruff `D`).
15. **(yours, agreed)** Inline code in single backticks, and examples as doctests run by the gate. *Alternatives:* reStructuredText's double backticks or Sphinx roles; examples as prose only. *Where:* `docstring-code`; the gate's pytest configuration.
16. **(yours, agreed)** One suppression syntax, `# lup: ignore(…)`, for lup, ruff and pyright findings alike. *Alternative:* `noqa` back for ruff codes. *Where:* the engine; `pyproject.toml`.
17. **(yours, agreed)** import-linter for the boundaries, read by the engine at the edit too. *Alternative:* custom import rules in the engine alone. *Where:* `pyproject.toml`.
18. Each rule's suggested fix passes every other rule, as a test over the catalog. *Alternative:* review catching contradictions. *Where:* the engine's tests.
19. **(yours, agreed)** A runtime is named only in its adapter: an import contract keeps the adapters behind the one place listing them, and `runtime-mention` refuses a runtime's name elsewhere. *Alternative:* convention only, which is how the first lup's features came to be built per runtime. *Where:* `pyproject.toml`, the engine.
20. **(yours, agreed)** A subpackage per subsystem, named as in the first lup where the subsystem is the same, with a library word meaning the same in the environment; a one-line `__init__.py` docstring each; package-wide modules at the root; subsystems importing downwards only. *Alternative:* a flat package. *Where:* `pyproject.toml` (the `layers` contract), each package.
21. **(yours, agreed)** XML is read with `defusedxml`, a dependency only where a project reads XML, and ruff's `S313`–`S319` stay on. *Alternative:* the standard library's parsers with those rules off, trusting the bundled Expat. *Where:* `pyproject.toml` (the rules stay selected).
22. **(yours, agreed)** A function's first line is in the imperative, ruff's `D401`. *Alternative:* noun phrases ("The saved path."), which read as well but have no check to keep them uniform. *Where:* `pyproject.toml` (the rule stays selected).
