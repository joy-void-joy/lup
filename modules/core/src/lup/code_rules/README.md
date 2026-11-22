# The code rules

Patterns that are rarely the right choice (a regex, a tuple as a record, `Any`, a second library for a job), caught where they're written, since other code gets built on the choice (`DESIGN.md`, *Keeping the operator in the loop*). Each rule says the mistake it prevents and where it steers instead, and reads pyright's own typed tree, so `tuple-shape` sees through an alias and `string-split` tells `str.split` from `shlex.split`. `CodeRules` is a module of its own, which a playground room leaves out. Its package is `lup.code_rules`, in the core's distribution, though it isn't among lup's default modules: a project adds it.

```python
from lup import Modules, Project
from lup.code_rules import CodeRules, Rules

project = Project(
    modules=Modules.default().add(
        CodeRules(rules=Rules().drop("elif", why="this project's dispatch reads better as chains"))
    )
)
```

## The module

- **`rules`**: which rules run, a selection of the engine's table by name (`lup code-rules rules` lists them). Every rule but `runtime-mention` by default, so a rule a later release adds runs unless a project drops it: `runtime-mention` is lup's own architecture, a runtime named only in its adapter, and fires on every choice of a project choosing its runtime by a setting.
- **`exempt`**: where lup's rules for code don't read, as patterns from the worktree's root (`PurePath.full_match`): tests, whose shapes are a test's own. pyright and ruff still read them.
- **`tests`**: where lup's rules for tests read: a test's files and a module's promises. They're about what makes a promise break when something nobody relied on changes (`lup/testing/README.md`): a message's words asserted (`asserted-words`), an answer compared whole (`whole-answer`), or the whole argument list a stand-in heard (`whole-arguments`).
- **`steps`**: the gate's `rules` step (`lup/gate/README.md`), `lup code-rules check .`, whose fix is `lup code-rules fix .`.

## Categories

Each rule has a category, which says when it's told and whether the gate fails on it:
- **design**: a choice others build on, told right after the write that makes it, and failing the gate;
- **spelling**: how a correct thing is written (`elif`, `wildcard-guard`, `isinstance-chain`, `collection-loop`, `docstring-code`), never told while the agent works, listed at the gate and failing it, so what's being written isn't shaped by them;
- **heuristic**: a guess over prose (`historical-voice`), listed at the gate and never failing it, since a misfire there shouldn't hold a landing.

pyright's and ruff's findings are design's.

## What a check says

`lup code-rules check <paths>` runs where it's typed (`@lup.command(here=True)`), on the worktree's own files and environment, and is refused where a finding fails the gate. Every finding is kept the same way, whichever owns it: an `ignore` naming its rule on the line it covers. So it's the one check deciding whether a finding stands, and the gate runs no `ruff check` or `pyright` step of its own, which would fail on a finding an `ignore` keeps. ruff's F821 repeats pyright's undefined name, and pyright's unused import repeats ruff's F401 where that's on the line, so each is said once.

Its report says lup's findings first, since they're about design, each line `path:line:column - lup tuple-shape: what it saw`, the rule's mistake and steer under its first finding and the line alone after; then pyright's and ruff's; then what `fix` fixes (ruff's safe fixes, and each `ignore` keeping nothing); then the heuristic's guesses. `lup code-rules show <rule>` shows one rule whole, with its examples.

## Told after a write

`Findings`, a part run in each session's own room on the worktree as it stands (`room=True`), hears each file tool's call (`lup/sessions/`): before it, it keeps the text of each file it's about to write; after it, it checks those files with the engine kept running for the worktree, on a socket, so a check costs what pyright's re-check of them does, a third of a second rather than the project's load. What it tells beside the call's result (`telling.py`):
- **what the write introduced** on the lines it changed: lup's design rules' findings, pyright's and ruff's, each once in a conversation, by its file, rule and the text of its line, so an edit above it doesn't make it new; lup's first, each rule's reason and steer with its first finding and a line after;
- **counted in a line,** what stands elsewhere in those files that the conversation wasn't told, with how to list it;
- **at the next call that writes nothing,** what a half-finished edit left, if it still stands: a name used before its import is written, an import before its use, and pyright's unknown types following them, counted under them. In the second lup's records, none of 2,400 such was still there at a turn's end;
- **at the next call,** the type errors the write caused in the files importing what it wrote, which the engine re-checks a step at a time between checks, so no write waits on them;
- **never,** what the gate's `--fix` fixes, a spelling rule's findings and a heuristic's, which the gate lists.

**Quiet.** During a refactor an agent knows leaves the code broken for a while, `lup code-rules quiet` holds back what's told after their writes, as DESIGN.md's *Quiet* has it; `--lift` tells once, beside their next call, what still stands in the files they wrote meanwhile, and nothing of the states in between. It's kept as a file in the room's temporary directory, by lup's id for the agent, which the room's part reads at each call.

A report past 2,000 characters says how many findings each file has and how to list them, rather than going out at a length Claude Code puts behind a preview. Each finding told is recorded, and whether a later check found it gone or kept by an `ignore`, in the repository's git directory; `lup code-rules outcomes` sums it up rule by rule, what a review of the rules reads.

## `# lup:` comments

How code speaks to its next reader, read into models (`directives.py`) with Python's own tokenizer and parser (`reading.py`), so a check, a landing and a review read them alike, with no engine or project loaded. A TypeScript file's `// lup:` comments are found with TypeScript's own parser, through the engine, so a `//` inside a string or a regular expression is never one, and what each says is read with the same grammar. A comment starting `# lup:` is a call:
- **`ignore("<rule>", why="…", issue=…)`** keeps one finding of that rule, on its own line, or, standing alone, on the next line holding code. One keeping nothing is itself a finding, `unused-ignore`, which `fix` removes. `issue` names what it waits on, a fix to the rule say;
- **`defer(issue=…, when=…, why=…)`** marks work knowingly left undone, with an issue tracking it, here by its number or elsewhere as `owner/repo#7`, or a condition a module declares, by its name;
- **anything else is a note**, `note("…")` or free text alike, which can't be wrong.

An `ignore` or a `defer` written wrong, or a call of another name passing `issue` or `when`, is `malformed-directive`, never read as a note, so a mistyped one can't sit there doing nothing.

`changed_deferrals` says which deferrals a change of a Python file adds, removes and rewords, from its text before and after (`deferrals_changed` from any file's directives, a TypeScript file's among them): what a landing lists. A deferral moved to another line is neither added nor removed, and one whose issue and condition stay while its reason changes is reworded.

## The engine

pyright has no plugin API, so the rules live in a TypeScript program compiled against pyright's own source (`engine/`): pyright's program, loaded as its command line loads it, the rules reading its tree and asking its type evaluator, in a table of a file per section (`engine/src/rules/`), each rule with its examples, code it flags rewritten the steer's way and near misses it leaves alone.

The package carries the sources, never a build: a check builds the engine where it first runs, in the repository's git directory, which every worktree and room of it shares, named by what its sources and pyright's release make it, so a worktree just made finds it built. The release is the environment's `pyright` package's, so the engine answers as the pyright an editor runs there does. Building fetches pyright's source at that release once (about 440 MB, with its dependencies), type-checks the engine and bundles it with esbuild: about 15 seconds where nothing is there yet. A check runs it once through `node`, reading the worktree's environment as files: 7 seconds for this repository's 125 files.

It runs where it's typed, in the agent's room, on the room's own files, so nothing it reads crosses a wall, and it needs no guard against a link leading it elsewhere.
