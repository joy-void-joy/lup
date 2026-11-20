# The code rules

Patterns that are rarely the right choice (a regex, a tuple as a record, `Any`, a second library for a job), caught where they're written, since other code gets built on the choice (`DESIGN.md`, *Keeping the operator in the loop*). Each rule says the mistake it prevents and where it steers instead, and reads pyright's own typed tree, so `tuple-shape` sees through an alias and `string-split` tells `str.split` from `shlex.split`. `CodeRules` is a module of its own, which a playground room leaves out. Its package is `lup_code_rules`.

```python
from lup import Modules, Project
from lup_code_rules import CodeRules, Rules

project = Project(
    modules=Modules.default().add(
        CodeRules(rules=Rules().drop("elif", why="this project's dispatch reads better as chains"))
    )
)
```

## The module

- **`rules`**: which rules run, a selection of the engine's table by name (`lup code-rules rules` lists them). Every rule but `runtime-mention` by default, so a rule a later release adds runs unless a project drops it: `runtime-mention` is lup's own architecture, a runtime named only in its adapter, and fires on every choice of a project choosing its runtime by a setting.
- **`exempt`**: where lup's rules don't read, as patterns from the worktree's root (`PurePath.full_match`): tests, whose shapes are a test's own. pyright and ruff still read them.
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

## `# lup:` comments

How code speaks to its next reader, read with pyright's own expression parser (`engine/src/directives.ts`) into models (`directives.py`). A comment starting `# lup:` is a call:
- **`ignore("<rule>", why="…", issue=…)`** keeps one finding of that rule, on its own line, or, standing alone, on the next line holding code. One keeping nothing is itself a finding, `unused-ignore`, which `fix` removes. `issue` names what it waits on, a fix to the rule say;
- **`defer(issue=…, when=…, why=…)`** marks work knowingly left undone, with an issue tracking it, here by its number or elsewhere as `owner/repo#7`, or a condition a module declares, by its name;
- **anything else is a note**, `note("…")` or free text alike, which can't be wrong.

An `ignore` or a `defer` written wrong, or a call of another name passing `issue` or `when`, is `malformed-directive`, never read as a note, so a mistyped one can't sit there doing nothing.

## The engine

pyright has no plugin API, so the rules live in a TypeScript program compiled against pyright's own source (`engine/`): pyright's program, loaded as its command line loads it, the rules reading its tree and asking its type evaluator, in a table of a file per section (`engine/src/rules/`), each rule with its examples, code it flags rewritten the steer's way and near misses it leaves alone.

The package carries the sources, never a build: a check builds the engine where it first runs, in the repository's git directory, which every worktree and room of it shares, named by what its sources and pyright's release make it, so a worktree just made finds it built. The release is the environment's `pyright` package's, so the engine answers as the pyright an editor runs there does. Building fetches pyright's source at that release once (about 440 MB, with its dependencies), type-checks the engine and bundles it with esbuild: about 15 seconds where nothing is there yet. A check runs it once through `node`, reading the worktree's environment as files: 7 seconds for this repository's 125 files.

It runs where it's typed, in the agent's room, on the room's own files, so nothing it reads crosses a wall, and it needs no guard against a link leading it elsewhere.
