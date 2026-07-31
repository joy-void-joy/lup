# The library/application placement criterion

`packages/lup` is a framework someone else's project imports. `src/lup_template`
is this project, built on it. The guidance states the placement test in prose —
*would another project built on lup want this?* — and this document is the
criterion that makes the test decidable, the classification of every library
module against it, and the target the relocation work executes against.

## The criterion

A library owns **mechanism**. An application supplies **data**. The line between
them is not how many constants a module holds — density measures the wrong
thing. `lup.resolver.core` holds the most quoted text in the library and is pure
mechanism (docstrings and one prompt contract); `lup.policy.kernel.words` holds
the pinned vocabulary the kernel exists to hold. What separates them is whether
the value was *chosen*.

> **A library may declare a value only when it could not have chosen otherwise.**
>
> Ask: *could a reasonable second implementer, given the same intent, have
> written a different value?*
>
> - **No — the value is canonical.** It is dictated by something outside this
>   repository: a language's file suffixes, a tool's own flag names, a
>   provider's wire spelling, a grammar, or a closed enum this library itself
>   defines. Writing it down is recording a fact. Getting it wrong is a bug, not
>   a difference of opinion.
> - **Yes — the value is application data.** It is a judgement, and the library
>   must accept the caller's judgement instead. Baking it in decides for every
>   adopter.

The test discriminates inside a single file. In `lup.policy.kernel.commands`,
`CURL_VALUE_FLAGS` is canonical — curl decides which of its flags consume the
next word, and misreading one shifts the whole argument scan. `CURL_SAFE_FLAGS`,
five lines away, is application data — another implementer could admit `--data`
or refuse `-v` and be equally right.

### What the library does with application data

It takes it as an **overridable default**. Shipping a default is not the defect;
shipping a choice with no parameter to replace it is. The harness already works
this way: `HookSet` is a pydantic surface with `Field(default_factory=list)`, and
the template's `portable_harness()` supplies the fetch scopes, protected roots,
and human-owned files. The engine is generic; the vocabulary arrives from
outside.

## What is mechanically checked, and what is not

The `library-default` rule (`lup.codescan.boundaries`, run by
`lup-devtools dev check` and `dev check --placement`) checks the **overridable**
half:

Every module-level shouty constant under `packages/lup/src/lup/`, outside
`lup/adapters/`, bound to a **collection display of two or more entries** must
be reachable somewhere in the library as a caller-replaceable default. Exactly
four spellings count:

| Spelling | Example |
|---|---|
| parameter default | `def compile(rules: list[Rule] = BASE_RULES)` |
| pydantic field default | `rules: list[Rule] = Field(default=BASE_RULES)` |
| field default factory | `Field(default_factory=lambda: BASE_RULES)` |
| mutable-default sentinel | `BASE_RULES if rules is None else rules`, or `rules or BASE_RULES` |

Reachability is a property of the library as a whole, so the names callers can
replace are collected across every library module — adapters included — before
any one module is judged. `BASE_SHELL_RULES` is not flagged for this reason:
`ShellPolicy` takes it through the sentinel spelling. Its five component tables
are flagged, because nothing does.

The rule **cannot** check the **canonicity** half. Whether "another implementer
could have written a different value" is a judgement about the world outside the
source — that curl defines its own flags, that `.py` is Python's suffix, that
allowing `rg` but not `sed -i` is a preference. No AST reaches those facts.

So canonicity is *declared at the site*, where it cannot drift from the value:

```python
# lup: ignore[library-default] — curl's own value-taking flags; misreading one shifts the argument scan
```

The reason must say **why the value is fixed outside this repository**. A bare
marker is the failure mode the conventions warn about: it silences the rule
without recording the judgement, and the next reader cannot tell a canonical
table from an unexamined one.

Two further things the rule does not see, both deliberate:

- **Scalars.** A single string or number is one fact, not a table. This is why
  `ASK_PREAMBLE` and `WAIT_CONTRACT` — prompt contracts that are library
  mechanism — never surface.
- **Derived collections.** A comprehension is computed from something else,
  which is where the judgement actually lives; the rule follows it there.

## Classification: every table under `packages/lup`

Thirty-one tables are in scope. Twenty-one are canonical and carry their reason
at the site. Ten are application data with no parameter — these are the
violations, and `dev check` stays red naming them until they move.

### Canonical — recorded, suppressed at the site

| Table | Why it could not have been chosen otherwise |
|---|---|
| `codescan/antipatterns.py` `PY_SUFFIXES` | Python's own source suffixes |
| `codescan/antipatterns.py` `TS_SUFFIXES` | the suffixes those ecosystems compile |
| `codescan/boundaries.py` `NATIVE_PREFIXES` | the adapter packages this library ships |
| `codescan/boundaries.py` `NATIVE_SPELLINGS` | each key is literally what the provider calls the thing |
| `codescan/markers.py` `PYTHON_SUFFIXES` | Python's own source suffixes |
| `codescan/markers.py` `MARKDOWN_SUFFIXES` | Markdown's own suffixes |
| `codescan/markers.py` `JS_SUFFIXES` | the suffixes where `#` opens no comment |
| `codescan/registry.py` `STRUCTURAL_RULES` | one card per rule the library's own scanners define |
| `harness/environment.py` `NON_INTERACTIVE_SHELL_ENV` | the variable and off-value git, ssh, gh, and keyring document |
| `policy/kernel/commands.py` `SED_SAFE_LONG_OPTIONS` | sed's own long spellings of its short flags |
| `policy/kernel/commands.py` `CURL_VALUE_FLAGS` | curl's own value-taking flags |
| `policy/kernel/decision.py` `KERNEL_IMPORT_ALLOWLIST` | the stdlib the kernel actually imports |
| `policy/kernel/lex.py` `SENTINEL_OPS` | POSIX shell grammar operators |
| `policy/kernel/shell.py` `CASE_TERMINATORS` | POSIX shell `case` clause terminators |
| `policy/kernel/words.py` `PASS_THROUGH_WORDS` | real wrappers that exec the argument after them |
| `policy/kernel/words.py` `DANGEROUS_ENV_NAMES` | variables the shell and language runtimes read to redirect execution |
| `policy/kernel/words.py` `DANGEROUS_ENV_PREFIXES` | loader and interpreter prefixes fixed by the OS |
| `policy/kernel/words.py` `GENERATED_PLUGIN_ROOTS` | the native runtimes' own plugin directory names |
| `policy/kernel/words.py` `INTERPRETERS` | real interpreter executables; omitting one is a hole, not a preference |
| `resolver/state.py` `PHASE_TRANSITIONS` | the successor of each phase in this library's own closed enum |
| `resolver/state.py` `CONCERN_TRANSITIONS` | the legal successors of each status in that same enum |

### Violations — application data the library decided

| Table | Entries | Why it is a choice |
|---|---|---|
| `policy/shell_rules.py` `READ_ONLY_COMMANDS` | 62 | which shell tools are safe to run unattended; no canonical form |
| `policy/shell_rules.py` `JUDGED_ASK_COMMANDS` | 36 | which commands need approval, with this repo's reasons |
| `policy/shell_rules.py` `GIT_READ_ONLY_SUBCOMMANDS` | 19 | a judgement about which git subcommands only read |
| `policy/shell_rules.py` `GIT_REVERSIBLE_SUBCOMMANDS` | 8 | a judgement about which git writes are reversible |
| `policy/shell_rules.py` `REDIRECTED_DENY_COMMANDS` | 2 | "use uv add instead of pip" is this repo's package-manager policy |
| `policy/kernel/words.py` `UV_RUN_ALLOWED_TARGETS` | 4 | names this repo's own CLI (`lup-devtools`) and chosen toolchain |
| `codescan/antipatterns.py` `PYTHON_ANTI_PATTERNS` | 42 | this repo's Python conventions; another project's differ |
| `codescan/antipatterns.py` `TS_ANTI_PATTERNS` | 14 | the same, for TypeScript |
| `policy/kernel/commands.py` `CURL_SAFE_FLAGS` | 19 | which curl flags are *safe* is a judgement, not curl's grammar |
| `telemetry/display.py` `TOOL_COLORS` | 12 | a terminal palette — presentation, and a theme or accessibility concern |

The note that opened this audit landed on `policy/shell_rules.py`, and the
classification confirms it: that module is the largest concentration of decided
vocabulary in the library. It is not wholly misplaced, though — its three rule
models and `erase_shell_rules` are the mechanism that gives the vocabulary
meaning. The split runs *through* the module, not around it.

## The reverse direction: application modules the library wants

The audit runs both ways. These are general mechanisms sitting in
`src/lup_template` that another project built on lup would want unchanged; each
mixes in a small amount of this project's data, so the move is "lift the
mechanism, pass the data in" rather than a relocation.

| Module | Generic mechanism | This project's data mixed in | Library home |
|---|---|---|---|
| `devtools/dev/conflicts.py` | merge/rebase conflict detection, in-scope classification, deletion auditing | none | `lup.workspace` |
| `devtools/layout.py` | resolving the sibling `tree/` worktree root across bare and parent layouts | none | `lup.workspace` |
| `devtools/dev/rules.py` | rendering `codescan.registry` into the checked-in rule reference | the destination path | `lup.codescan` |
| `devtools/dev/boundaries.py`, `dev/antipatterns.py` | walking tracked files through the per-file scanners and aggregating findings | the kernel path prefix | `lup.codescan` |
| `devtools/dev/worktree.py` | worktree create/list/remove, merge-driver registration, gitignored-extras copy | `GITIGNORED_EXTRAS` names this repo's local files | `lup.workspace` |
| `devtools/dev/branches.py` | branch survey, containment, disposition classification | the `gh` correlation is GitHub-specific | `lup.workspace` |
| `devtools/utils.py` | `LazyCommand` deferred binary resolution, command wrappers, output formatting | none | `lup.runtime` |
| `devtools/sync.py` | upstream registry reading, clone, commit-log fetch, sync checkpoints | registry filenames | `lup.workspace` |
| `devtools/version.py` | changelog generation from classified commits, version bump | the commit-type prefixes | `lup.workspace` |
| `devtools/harness/composition.py` | wiring recipe + readiness probe + renderer per adapter | none beyond adapter identity | `lup.harness` |
| `devtools/harness/launch.py` | runtime preflight, non-interactive environment, sandbox activation | Codex sandbox overrides | `lup.harness` |
| `devtools/harness/codex_home.py` | per-worktree Codex homes, state-aware config sanitization | default home paths | `lup.adapters.codex` |

Ruled out after reading: `harness/catalog.py`, `harness/evidence.py`,
`harness/generate.py`, `harness/reconcile.py`, `harness/drift.py`,
`harness/doctor.py`, `dev/plugin.py`, `dev/pr.py`, `dev/resolve_review.py`,
`dev/check.py`, `devtools/main.py`, `devtools/subapps.py`, and all of
`feedback/`, `supervisor/`, `trace/`, `usage/`, and `agent/`. These are this
project's composition roots, CLI wiring, or domain content — a downstream
project writes its own.

## Target layout

Ordered largest first. Each stage stands alone: it names its own tables, its own
seam, and can land without the others.

### 1. The shell policy vocabulary — six tables, `policy/shell_rules.py` and `kernel/words.py`

The mechanism stays: `ShellCommandRule`, `ShellSubcommandRule`,
`ShellOperationRule`, and `erase_shell_rules` are how any vocabulary becomes
kernel rows. The vocabulary leaves.

- The baseline reaches the library as a default the caller replaces. `ShellPolicy`
  already admits one through its sentinel; the generation path does not —
  `policy.bundle.runtime_shell_rules` and `HookSet.shell_rules` only *extend*
  `BASE_SHELL_RULES`, so a generated dispatcher cannot be built on a different
  baseline. Closing that gap is the substance of this stage.
- The entries that name this repo — `REDIRECTED_DENY_COMMANDS` (pip → uv) and
  `UV_RUN_ALLOWED_TARGETS` (`lup-devtools`) — move to the template's `HookSet`,
  beside the fetch scopes and protected roots that already live there.
- `CURL_SAFE_FLAGS` travels with them: it is the same kind of judgement, and
  leaving it in the kernel would keep one policy table behind after the rest
  moved.

### 2. The anti-pattern rule set — two tables, `codescan/antipatterns.py`

`AntiPattern` and the scanner stay. `PYTHON_ANTI_PATTERNS` and
`TS_ANTI_PATTERNS` become a rule set the application supplies, defaulting to
what ships. `codescan.registry.anti_pattern_rules()` takes the set as a
parameter so the rule reference indexes whatever the project actually enforces,
not whatever the library was born with.

### 3. The display palette — one table, `telemetry/display.py`

`ColorAssigner.__init__` takes the palette as a parameter defaulting to
`TOOL_COLORS`. One signature; independent of everything above.

### 4. The reverse direction

The modules in the table above move outward, mechanism first and project data
passed in. Independent of stages 1–3 and of each other.

## Why this is not a tracking file

The classification is not the record of the work — the rule is.
`lup-devtools dev check --placement` prints the live list, and `dev check`
stays red while any entry stands, naming each by file, line, and constant. The
violations table above is that list at the time of the audit, kept here only to
explain *why* those ten and not the other twenty-one. The pressure to act lives
in the check, and lifts on its own when the last table moves.
