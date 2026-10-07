# The after-call diff: judging every write by its result

**One sentence:** whenever no tool call is running, lup compares the agent's worktree with the last state it accepted, and applies the code rules and type checks to whatever changed, whichever tool changed it. The operator is asked before a new file or a suppression lands.

This is the second item of `DESIGN.md`'s first build step, built alongside the library. It's the review workflow, and every call goes through it. This slice covers:
- the checkpoint and the snapshot store;
- asking the operator in Claude Code before a new file or a suppression lands;
- refusals, which put the file back, save the agent's version, and report every finding at once;
- the rule engine and the first rules: parsers over regex, `tuple-shape`, `set-shape`;
- pyright's type errors at each checkpoint;
- the `# lup:` directives, of which only `ignore` is implemented here;
- the hooks for Claude Code and Codex;
- installing it in this repository's own sessions.

Later:
- asking on a new public name or a changed signature;
- protected paths;
- answering in the dashboard;
- keeping the store out of the agent's reach, which comes with launch and containers.

## What changes from `DESIGN.md`

Agreed in conversation, to be written into `DESIGN.md` in its own pull request.

1. **Judge the worktree's state, not each call.** lup keeps one accepted state per worktree and compares the worktree with it at each checkpoint. Whatever changed since then is judged, whichever call or process made it. The effects probe's before-and-after-each-call windows left three things unsolved, and this settles them:
   - parallel calls;
   - writes that land after their call;
   - someone else's edit charged to the agent.
2. **lup asks, refuses, or stays silent. It never says "allow", and "defer" goes.**
   - Staying silent sends the call through the runtime's own permission mode (Claude Code's hooks docs: "staying silent doesn't approve it").
   - So whether auto mode's classifier judges commands is the launch piece's choice of mode. lup's hook works the same under either.
   - The line count goes with "defer". Claude Code's own `defer` decision means something else: pausing a headless run so it can resume later.
3. **Type errors arrive at each checkpoint**, a few seconds after the write. `DESIGN.md` said "once a burst of edits settles". They're information, not a refusal; the turn still can't end with errors left in files it touched.

## The checkpoint

The judging core never sees a runtime. Each runtime's adapter turns its hooks into four events:

| Event | Claude Code | Codex |
|---|---|---|
| session started | `SessionStart` | `SessionStart` |
| call started (id) | `PreToolUse` | `PreToolUse` |
| call finished (id) | `PostToolUse` | `PostToolUse` |
| turn ended | `Stop` | `Stop` |

**A checkpoint runs whenever a call finishes and no other call is running,** and again when the turn ends.
- **Parallel calls** are judged together once the last one finishes.
- **Serial calls** are judged one by one.
- **A late background write** is judged at the next checkpoint.

The checkpoint is after the batch and before the agent's next model request, so a refusal or a type error reaches the agent before it writes its next line.

This needs nothing beyond the four events, so it works the same on both runtimes. Claude Code's `PostToolBatch` would give the same moment on Claude alone, and isn't needed.

**It degrades gracefully:**
- A "finished" with no matching "started" is ignored. Codex's `write_stdin` can deliver the original command's `PostToolUse` without a `PreToolUse` of its own.
- A call that never reports finishing (interrupted, crashed) is cleared when the turn ends. The turn-end checkpoint judges everything anyway.
- The bookkeeping is a set of call ids under a file lock, since hooks for parallel calls run concurrently.

## How a checkpoint goes

1. **Snapshot.** The worktree is written into lup's own store as a git tree: a private index, `git add -A` and `write-tree`. Ignored files are left out, as `.gitignore` says. The store is a bare repository outside the worktree, and git runs with `core.fsmonitor` and hooks turned off. The probe showed a planted `core.fsmonitor` running inside a call.
2. **Compare** it with the accepted tree (`git diff-tree`). If nothing changed, the checkpoint is done. That's the common case after a read.
3. **Set aside what's already committed.** A changed file whose new content equals its version at the checkout's `HEAD` isn't judged. This is what a checkout, a merge, a pull, a stash or a `git restore` produce, and that content was judged or reviewed when it was committed. A file with conflict markers isn't `HEAD`'s content, so it's judged.
4. **Check** every changed Python file: the rules (not on tests), pyright's type errors, and the `# lup:` directives.
5. **Refuse:**
   - a file with rule findings on lines this change touched;
   - a new file the operator wasn't asked about;
   - a suppression the operator wasn't asked about.

   Shell-made files and suppressions are refused with a pointer to `Write` or `Edit`, so they come back through the prompt. That enforces `AGENTS.md`'s "create files with your file tool".
6. **Act:** a refused file goes back to its accepted content, or is removed if it was new, and the agent's version is saved. What's left becomes the new accepted tree.
7. **Report** to the agent, once: everything refused, then the type errors as information.

The accepted tree starts as a snapshot when a session starts. If a stored accepted tree already exists for the worktree, the difference happened while no session was running. That's the operator's work or a pull, so it's accepted without judging.

**Cost:**
- One snapshot per checkpoint, about 50 ms at lup's size according to the probe. The existing projects have 161 to 3,721 tracked files.
- Plus the checker's incremental run on the changed files (see *The engine*), measured in the implementation's pull request.
- Target: under 300 ms per checkpoint on this repository, type check included.

## Asking the operator

The operator wants to see a new file before it lands: it's the change that shows design best (`DESIGN.md`, *Policy*). They also want to approve each suppression when it's added, not in a list at the pull request.

**On Claude Code, through its own prompt.**
- **When it asks:** before a `Write` creates a file, or before a `Write` or `Edit` adds a `# lup: ignore`, the `PreToolUse` hook answers "ask". The prompt's reason names the new path, or the rule and the reason given for it.
- **Edits:** to know what an `Edit` adds, lup applies the edit to the current file. If the old text isn't there exactly once, lup stays silent and the tool fails on its own.
- **Auto mode:** a hook's "ask" "forces a permission prompt in auto mode" (hooks docs). Tested in this session, the bare `Write` ask rule also prompts in auto mode.
- **Overwrites stop asking.** The blanket `permissions.ask` on `Write` in `.claude/settings.json` goes. Overwriting an existing file isn't a design signal.
- **An approval covers the path.** If the new file is then refused by a rule and fixed in its saved copy, moving the copy into place isn't asked again.

**On Codex, through a hold.** Codex's `PreToolUse` can't answer "ask" yet. So a new file or a new suppression is held at the checkpoint instead. The agent waits inside the hook, and the operator answers with `lup-dev holds approve <id>` or `lup-dev holds decline <id> --comment …`.
- `lup-dev holds` lists what's waiting, with the diff.
- A decline puts the change back and saves it, with the comment beside it. An approval with a comment passes the comment on.
- The hook waits up to 24 hours; the first lup held calls for 4 hours without trouble. Unanswered by then, the change is put back and saved, and the hold stays open.
- This is a declared gap: on Codex the operator answers from a terminal until the dashboard exists.

## Refusals

The refused file goes back to its accepted content. The agent's version is saved under `.lup/saved/<n>/<path>` in the worktree (`.lup/` is ignored, so saved copies are never judged). The agent fixes the listed lines there and moves the file into place; the move is judged like any write. Nothing is resent whole.

The report, in pyright's shape:

```
lup refused 1 file. It is back as it was; your version is saved.

src/lup/claude.py (saved at .lup/saved/3/src/lup/claude.py)
  src/lup/claude.py:41:12 - tuple-shape: a fixed-length tuple[str, int] hides what each position means
      steer: name the fields with a pydantic model
  src/lup/claude.py:88:5 - regex: `import re` parses with a regular expression
      steer: use the format's own parser (lup docs rules regex)

Fix these lines in the saved copy, then move it into place:
  mv .lup/saved/3/src/lup/claude.py src/lup/claude.py
To keep a finding, add on its line or the line above (the operator is asked):
  # lup: ignore("<rule>", why="<reason>")

Type errors in changed files (information; the turn can't end with these):
  src/lup/codex.py:12:9 - error: "thread" is possibly unbound
```

## The rules

Each rule names the mistake it prevents and where it steers: one line in the refusal, the full reason in `lup docs rules`. No rule reads source text with a regex. Every rule reads the typed tree from the engine below.

| Rule | Fires on | Why it exists | Steers to |
|---|---|---|---|
| `regex` | `import re`, `from re import …`, `import regex`. One finding at the import: using regular expressions in a module is one decision | Quick regex patches often silently didn't work: they matched the cases tried and failed quietly on the rest, and the bugs were hard to find | The format's own parser (`json`, `tomllib`, `csv`, `urllib.parse`, `pathlib`, `email`, `shlex`, `ast`, `datetime.fromisoformat`, `packaging.version`), or a pydantic model. A grammar of your own gets a parser library |
| `string-split` | `.split(sep)`, `.rsplit(sep)`, `.partition(…)`, `.rpartition(…)` where the receiver's type is `str` or `bytes`. `.split()` with no separator and `.splitlines()` are fine | The same silent failures as regex: quoting, escaping and the cases nobody tried | The same parsers |
| `tuple-shape` | A fixed-length tuple type anywhere: `tuple[…]`, `typing.Tuple[…]`, and aliases of them. `tuple[X, ...]` is a sequence and is fine | A reviewer has to work out what each position means ("what is field 5?") | A pydantic model naming each field |
| `set-shape` | A declared set: `set`, `set[…]`, `frozenset[…]`, aliases of them, and calls to `set()` and `frozenset()` | A dict keeps what a set throws away: a set of names is usually a record that lost its other fields | A dict keyed by the members, or a list of models. A set with truly nothing to record (things already seen) takes a suppression with its reason |

**Slicing** gets a rule once the engine is in. A slice on a `str` parsed as structured data is the third thing `AGENTS.md` names.

**Tests are exempt.** A file is a test if it sits under a `testpaths` entry of the nearest `pyproject.toml`'s pytest configuration, nested projects included. The declaration (`Project(tests=…)`) becomes the source when it exists. The art studio's exemption never applied because test roles came from something other than the suites the gate runs, and this reads the configuration pytest itself reads.

**Which findings refuse.** A refusal comes from findings on the lines the change touched; for a new file, that's every line. The refusal lists every finding in the file, so one pass fixes them all. The art studio's agent resent a 550-line file four times, once per rule. Findings on lines the change didn't touch are listed under their own heading and don't refuse. They exist only where a rule is newer than the code, and the update that brings a rule shows its findings to the project.

## The engine: one typed tree (open)

The operator wants one unified typed tree: each file parsed once and type-checked once, with every rule reading types straight from that tree. That rules out the first lup's approach: a syntax tree, plus a pyright language server asked about one position at a time, whose hover text then had to be read (`codescan/oracle.py`).

Pyright has no plugin API, and its published package is one bundled file (`dist/pyright-internal.js`, 3 MB), so its internals can't be imported from it. Two ways to get a typed tree:

**A. Pyright's own tree, from its source.**
- **What it is:** a small TypeScript program built against `packages/pyright-internal` from pyright's repository at a pinned release, shipped prebuilt inside `lup-dev` like the dashboard.
- **How it runs:** one long-lived process per session. It loads the project the way pyright does and keeps it warm.
- **At each checkpoint:** it re-checks the changed files incrementally. Each rule is a visitor over pyright's parse tree, asking pyright's type evaluator for any expression's type.
- **What comes back:** one list, pyright's type errors and lup's rule findings in the same shape, as JSON lines the Python side reads into pydantic models.
- *For:* the rules see exactly the types pyright reports in the editor and the gate, and one process does both jobs.
- *Against:*
  - rules are written in TypeScript;
  - pyright's internals aren't a public API, so a pyright upgrade is a deliberate step that the rules' tests check;
  - it needs a Node build, which the dashboard brings anyway.

**B. mypy's tree, in Python.**
- **What it is:** mypy's build API with `export_types` returns each file's tree and the type of every expression.
- **How rules work:** each rule is a Python visitor.
- *For:* rules in Python.
- *Against:*
  - mypy is a second type checker beside pyright, and its inferred types can differ at the edges (narrowing, overloads), so a rule could disagree with what pyright shows;
  - staying warm between checkpoints means driving mypy's internal incremental machinery, or paying a cached build each time;
  - pyright would still run separately for the type errors.

**Lean: A, after a spike.** On its own branch:
1. build `pyright-internal` at a pinned tag;
2. load this repository;
3. write `tuple-shape` and `string-split` as visitors;
4. measure a checkpoint.

If the internals turn out too unstable to build against, B is the fallback.

Whichever engine is chosen also reads everything else lup reads in Python source, the `# lup:` directives included, so there's one parser.

## The `# lup:` directives

`# lup:` comments are the channel for notes in code. Their grammar:
- **A directive** is written as a call: `# lup: ignore("tuple-shape", why="sh takes its redirections as positional tuples")`. The text after `lup:` is read with the engine's Python parser, and each directive is a small model with its fields.
- **Anything that isn't a call is a note:** `# lup: the retry count matches the provider's documented limit`. Notes are collected for the resolver when it exists.
- **A call to an unknown directive is a finding,** so a directive that's wrong never sits there silently. In the first lup, a file-wide ignore placed after the docstring did nothing (#213). So are an `ignore` without its reason and an `ignore` whose rule doesn't fire there.

This slice implements `ignore`, on the finding's line or alone on the line directly above it. Every rule accepts it; the first lup had rules that refused any suppression, which left code calling `sh` (it takes tuples) impossible to write. Adding one asks the operator (see *Asking the operator*).

Later directives point at records. `# lup: defer("L-12")` points at a ledger entry, and the check requires that entry to be committed, so a pointer never dangles.

## The two runtimes

| | Claude Code | Codex |
|---|---|---|
| Checkpoint events | `PreToolUse`, `PostToolUse`, `Stop` | The same |
| Asking before a new file or suppression | `PreToolUse` answers "ask" | Not supported yet: held at the checkpoint, answered from the terminal |
| How the agent hears | `additionalContext` beside the result | `decision: block` replaces the result, so lup puts the original output first, in full, then the report |
| Configured in | `.claude/settings.json` | `.codex/hooks.json`, run only once its hash is trusted, so the operator trusts it after each change |

Checks owed:
- **Codex:** its hook timeout limit, which isn't documented.
- **Claude Code:** whether hooks run in the order that keeps the in-flight set right when calls run in parallel. A "finished" that lands before its "started" would be ignored and leave the call open until the turn ends. That's harmless but delays the checkpoint.
- **Not used:** Claude's own record of a command's edits (`bashEditDiff`), which missed files in the probe, a protected one among them.

## Where things live

| What | Where | Why there |
|---|---|---|
| The store: snapshots, the accepted tree, the in-flight calls, holds, refusals | `$XDG_STATE_HOME/lup/worktrees/<id>/`, outside the worktree | The restore source must be out of the agent's reach. In the bridge it isn't, since the agent runs as the operator's user. Launch puts it out of the container |
| Saved versions | `<worktree>/.lup/saved/` | The agent has to edit and move them |
| The judge itself | Installed from `main`, not run from the worktree being judged | A session that edits the judge shouldn't be judged by its edit. Trust on launch does this properly later |

## Modules

In `packages/lup-dev/src/lup_dev/`:

| Module | What it's for |
|---|---|
| `checkpoint.py` | The four runtime-neutral events, the in-flight set, deciding when to judge |
| `changes.py` | The store: snapshot, compare, set aside `HEAD`'s content, restore, save, move the accepted tree forward |
| `judge.py` | One checkpoint: changed files in, verdicts out (refuse, hold, accept) |
| `asking.py` | Before a `Write` or `Edit`: would it create a file or add a suppression? |
| `checker.py` | The client for the engine: findings, type errors and directives for a set of files |
| `directives.py` | The `# lup:` directive models, and checking them |
| `holds.py` | Holds (Codex): waiting for an answer, and answering |
| `report.py` | The reports, in pyright's shape |
| `hooks/claude.py`, `hooks/codex.py` | Each runtime's payloads in, its outputs out |
| `cli.py` | `lup-dev hook`, `lup-dev rules check`, `lup-dev holds` |

With engine A, the rules live in `packages/lup-dev/checker/` as a TypeScript project built into one file. With B, they're in `lup_dev/rules/`.

The `lup-dev` command is this slice's stand-in until the declaration and CLI piece builds the real `lup` command tree. The commands keep their meaning there; their final names are that piece's call.

## Installing it here

- `.claude/settings.json` gets the four hooks, and loses the `permissions.ask` on `Write`.
- `.codex/hooks.json` gets the same four.
- `.gitignore` gets `.lup/`.

No CI workflow for now: suppressions are approved as they're added.

## Decisions

Each with its alternative and where it lives. The ones marked **(yours)** are the operator's.

1. **(yours, agreed)** Judge state against the last accepted state. *Alternative:* a snapshot before and after each call. *Where:* `changes.py`, `judge.py`.
2. **(yours, agreed)** The checkpoint is "no call running", built from four runtime-neutral events. *Alternative:* `PostToolBatch` on Claude, with `PostToolUse` under a lock on Codex, which is two mechanisms. *Where:* `checkpoint.py`.
3. **(yours, agreed)** lup asks, refuses or stays silent, and never says "allow". "Defer" and the line count go. *Alternative:* keep "allow" for small edits, which would skip the runtime's own mode. *Where:* `asking.py`, `hooks/`.
4. **(yours, agreed)** You're asked in Claude Code before a new file or a suppression lands. Shell-made ones are refused, and the blanket `Write` prompt goes. Codex gets a hold. *Alternative:* a hold on both runtimes, answered from the terminal. *Where:* `asking.py`, `holds.py`.
5. **(yours, agreed)** The four rules, with `set-shape` as broad as before. *Where:* the engine.
6. **(yours, open)** The engine: pyright's tree built from source (A, lean, after a spike) or mypy's (B). *Where:* `checker/` or `rules/`.
7. **(yours, agreed)** `# lup:` directives as calls, everything else a note, a wrong directive a finding. `ignore` only for now. *Alternatives:* `ignore[rule] why` read by a grammar library; TOML in the comment (`# lup: ignore = { rule = "tuple-shape", why = "…" }`). *Where:* `directives.py`.
8. Content equal to `HEAD` isn't judged. *Alternatives:* judge it, which makes every checkout replay history as new writes; recognize git commands, which is the command-spelling parsing `DESIGN.md` removed. *Where:* `changes.py`.
9. Findings on touched lines refuse; the refusal lists every finding in the file. *Alternative:* any finding in a touched file refuses. *Where:* `judge.py`, `report.py`.
10. Type errors are information at each checkpoint and refuse only at turn end. *Alternative:* refuse at the checkpoint, which `DESIGN.md` rules out ("information never travels on a blocking channel"). *Where:* `judge.py`.
11. The judge runs from `main`'s copy. *Alternative:* from the worktree's own environment. *Where:* the hook commands.
12. Test roles come from pytest's `testpaths`. *Alternative:* wait for the declaration. *Where:* `judge.py`.
13. **(yours, agreed)** The package is `packages/lup-dev` (`lup-dev`, `lup_dev`), with a stand-in `lup-dev` command. *Where:* `packages/lup-dev/`.
