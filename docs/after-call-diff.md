# The after-call diff: judging every write by its result

**One sentence:** after the agent's tool calls, lup compares its worktree with the last state it accepted, and applies the code rules and holds to whatever changed, whichever tool changed it.

This is the second item of `DESIGN.md`'s first build step, built alongside the library. It's the review workflow: every call goes through it, and it replaces the bridge's prompt on `Write` once installed. This slice covers:
- the snapshot store and the comparison;
- the code-rule engine, with the first rules: parsers over regex, `tuple-shape`, `set-shape`;
- refusals, which put the file back, save the agent's version, and report every finding at once;
- holds on new files, answered by the operator from a terminal command for now;
- the hooks for Claude Code and Codex;
- a command for the pull-request check, which lists every suppression;
- installing it in this repository's own sessions.

Later slices of this piece:
- holds on a new public name or a changed signature, which need a diff of the public surface;
- protected paths;
- type errors delivered as information;
- the turn-end gate;
- answering holds in the dashboard.

Containers and keeping the store out of the agent's reach come with launch.

## What changes from `DESIGN.md`

Three proposals here change `DESIGN.md`, so they're the operator's to accept. They're listed first, and the rest of the note assumes them.

1. **Judge the worktree's state, not each call.** `DESIGN.md` says "after every call … the files it changed are diffed". The effects probe judged that way: a snapshot before and after each call. It left these unsolved:
   - parallel calls, whose windows overlap;
   - writes landing after their call, charged to the wrong one;
   - a person's edit during a call, charged to the agent.

   Here lup keeps one accepted state per worktree and compares the worktree with it at each judging point. Whatever changed since then is judged, whichever call or process made it. On Claude Code, the judging point is the end of each batch of tool calls (`PostToolBatch`), so parallel calls are judged together after all of them have finished. A late write is judged at the next point. With a worktree per agent (launch), the agent is the only writer, so "whatever changed" is the agent's work.
2. **Three outcomes: allow, refuse, hold. No "defer".**
   - "Defer" hands a large edit to the runtime's own permission prompt. That prompt runs *before* a call, but the diff only exists *after* it, so a `sed` or a script that already wrote the file has no prompt left to go to.
   - Line count is also the signal `DESIGN.md` itself calls weaker than the design signals, and the only one that rewards splitting a change.
   - "Refuse" is the code rules' outcome, which `DESIGN.md` describes under *Code rules* rather than among the three.
3. **`set-shape` fires only on sets of tuples.** In the first lup it fired on every declared set. nori turned it off ("would put a suppression on nearly every routine … trains one to add the marker without reading it"), and lup's own code carried 31 suppressions of it. Following `DESIGN.md`'s own rule for a noisy rule, it's rewritten to fire only where positional data is at stake (see *The rules*).

## How a judging point goes

1. **Snapshot.** The worktree is written into lup's own store as a git tree: a private index, `git add -A` and `write-tree`. Ignored files are left out, as `.gitignore` says. The store is a bare repository outside the worktree, and git runs with `core.fsmonitor` and hooks turned off. The probe showed a planted `core.fsmonitor` running inside the call.
2. **Compare** it with the accepted tree (`git diff-tree`). Nothing changed: done. That's the common case after a read.
3. **Set aside what's already committed.** A changed file whose new content equals its version at the checkout's `HEAD` isn't judged. This is what a checkout, a merge, a pull, a stash or a `git restore` produce, and that content was judged or reviewed when it was committed. Without this step, switching branches would replay old work as new writes. A file with conflict markers isn't `HEAD`'s content, so it's judged.
4. **Run the code rules** on every changed Python file that isn't a test (see *The rules*). A file with findings on the lines this change touched is refused.
5. **Hold every new file** the rules passed: a path absent from both the accepted tree and `HEAD`. A new file is the change the operator most wants to see (`DESIGN.md`, *Policy*). In Python, a new module is a new file.
6. **Act:**
   - a refused file goes back to its accepted content, or is removed if it was new, and the agent's version is saved;
   - holds wait for the operator (see *Holds*);
   - what's left becomes the new accepted tree.
7. **Report** to the agent, once, everything this point refused or held.

The accepted tree starts as a snapshot when a session starts. If a stored accepted tree already exists for the worktree, the difference happened while no session was running. That's the operator's work or a pull, so it's accepted without judging.

**Cost.** One snapshot per judging point. The probe measured about 50 ms at lup's size. The projects that exist are 161 to 3,721 tracked files, close to that. The 1.4–2.8 s figure in `DESIGN.md` was a synthetic 300k-file tree. The interpreter start and imports come on top. The target is under 300 ms per judging point on this repository, measured in the implementation's pull request.

## The rules

All rules parse with Python's `ast`; comments are read with `tokenize`. A file that doesn't parse has no findings: pyright reports the syntax error. Each rule names the mistake it prevents and where it steers, in the refusal (one line) and in `lup docs rules` (in full).

| Rule | Fires on | Why it exists | Steers to |
|---|---|---|---|
| `regex` | `import re`, `from re import …`, `import regex`. One finding at the import: using regular expressions in a module is one decision | Quick regex patches often silently didn't work: they matched the cases tried and failed quietly on the rest, and the bugs were hard to find | The format's own parser (`json`, `tomllib`, `csv`, `urllib.parse`, `pathlib`, `email`, `shlex`, `ast`, `datetime.fromisoformat`, `packaging.version`), or a pydantic model. A grammar of your own gets a parser library |
| `string-split` | `.split(sep)`, `.rsplit(sep)`, `.partition(…)`, `.rpartition(…)` on a value that isn't an imported module (`shlex.split` and `os.path.split` are fine). `.split()` with no separator and `.splitlines()` are fine | The same silent failures as regex: quoting, escaping and the cases nobody tried | The same parsers |
| `tuple-shape` | A fixed-length `tuple[…]` or `typing.Tuple[…]` anywhere: annotations, aliases, casts. `tuple[X, ...]` is a sequence and is fine | A reviewer has to work out what each position means ("what is field 5?") | A pydantic model naming each field |
| `set-shape` | A set whose members are tuples: a set display or comprehension of tuple displays, `set(…)`/`frozenset(…)` of a generator yielding them, and `.add((…))`. A `set[tuple[…]]` annotation is already `tuple-shape`'s, so it isn't reported twice | A set of tuples is a table of positional records; looking one up means knowing what each position holds | A frozen pydantic model as the member, or a dict keyed by what's looked up |

**Slicing isn't covered yet.** `AGENTS.md` names slicing alongside `re` and `split`, but telling a string slice from a list slice needs types. It comes with the type questions, through pyright, in a later slice.

**Tests are exempt.** A file is a test if it sits under a `testpaths` entry of the nearest `pyproject.toml`'s pytest configuration, nested projects included. When the declaration exists (`Project(tests=…)`), it becomes the source. The art studio's exemption never applied because test roles came from something other than the suites the gate runs, and this reads the same configuration pytest does.

### Suppressions

Every rule can be suppressed, and every suppression must give a reason. A suppression goes on the finding's line, or alone on the line directly above it:

```python
# lup: allow = { rule = "tuple-shape", why = "sh takes its redirections as positional tuples" }
```

- The text after `lup:` is TOML, read with `tomllib` into a pydantic model. `rule` must name a rule that exists, and `why` must not be empty.
- A suppression on a line where its rule doesn't fire is a finding of its own, so stale suppressions don't pile up.
- The pull-request check lists every suppression in the change.

The first lup had rules that refused any suppression. That left code calling a library that takes tuples (`sh`) impossible to type. Its own regex rule was suppressed 38 times with markers that didn't require a reason; 18 `string-split` markers had none.

### Which findings refuse

A refusal comes from findings on the lines the change touched. For a new file, that's every line. The refusal lists every finding in the file, so one pass fixes them all; the art studio's agent resent a 550-line file four times, once per rule. Findings on lines the change didn't touch are listed under their own heading and don't refuse. They exist only where a rule is newer than the code, and the update that brings a rule shows its findings to the project.

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
To keep a finding, put on its line or the line above:
  # lup: allow = { rule = "<rule>", why = "<reason>" }
```

## Holds

A held change stays in place, and the agent waits inside the hook until the operator answers. That's `DESIGN.md`'s "a wait is a hold inside the tool call": the agent pauses so the operator can catch up.

- **The operator answers** with `lup-env holds approve <id> [--comment …]` or `lup-env holds decline <id> --comment …`. `lup-env holds` lists what's waiting, with the diff.
- **On Claude Code**, the hook's spinner says what it waits on and names the command (`statusMessage`). A hook can't open the terminal or notify while it runs.
- **Approved:** the file joins the accepted tree.
- **Declined:** it's put back and saved like a refusal, with the operator's comment beside it.
- **Either way**, the agent's next context says it was held and carries the comment, so it knows it was seen and whether to change course.
- **The hook waits up to 24 hours** (the first lup held calls for 4 hours without trouble). If nobody answers by then, the file is put back and saved, and the hold stays open for a later answer.

The dashboard takes over answering when it exists; the stored hold is the same.

A hold past an hour costs the agent a cache rebuild. `DESIGN.md` accepts that rather than keeping the cache warm with a loop.

## The two runtimes

The judging is runtime-free. Each runtime gets an adapter that reads its hook payloads into pydantic models and writes its outputs. Both are tested with payloads recorded from the real CLIs.

| | Claude Code | Codex |
|---|---|---|
| Accepted tree starts at | `SessionStart` | `SessionStart` |
| Judging point | `PostToolBatch`, once per batch of calls, after all of them finish | `PostToolUse`, one at a time under a lock; Codex has no batch event |
| Turn end | `Stop`, judged again; a refusal or hold blocks the stop with the report | `Stop`, the same |
| How the agent hears | `additionalContext`, delivered before the next model call | `decision: block` replaces the tool result. lup puts the original output first, in full, then the report |
| Configured in | `.claude/settings.json` | `.codex/hooks.json`. Codex runs a project hook only once its hash is trusted, so the operator trusts it once after each change |

Gaps and checks owed:
- **Claude:** `PostToolBatch`'s docs don't say whether it fires for a batch of one call or under `-p`. If it doesn't, `PostToolUse` under a lock is the fallback, as on Codex.
- **Codex:**
  - If it runs a session's tool calls in parallel, a judging point under `PostToolUse` could catch a sibling call mid-write. Whether 0.160 does is to check.
  - Its hook timeout limit isn't documented.
  - `write_stdin` fires no `PreToolUse`, but can deliver the original command's `PostToolUse`. That's harmless here, since judging doesn't depend on which call ran.
- **Claude's own record of a command's edits** (`bashEditDiff` in the Bash result) missed files in the probe, a protected one among them, so it isn't used.

## Where things live

| What | Where | Why there |
|---|---|---|
| The store: snapshots, the accepted tree, holds, the record of refusals | `$XDG_STATE_HOME/lup/worktrees/<id>/`, outside the worktree | The restore source must be out of the agent's reach. In the bridge it isn't, since the agent runs as the operator's user; launch puts it out of the container |
| Saved versions | `<worktree>/.lup/saved/` | The agent has to edit and move them |
| The judge itself | Installed from `main`, not run from the worktree being judged | A session that edits the judge shouldn't be judged by its edit. Trust on launch does this properly later |

## Modules

The environment's first piece: `packages/lup-env/src/lup_env/`.

| Module | What it's for |
|---|---|
| `changes.py` | The store: snapshot, compare, set aside `HEAD`'s content, restore, save, move the accepted tree forward |
| `rules/engine.py` | Parse a file, run the rules, map findings to changed lines, read suppressions |
| `rules/parsing.py` | The `regex` and `string-split` rules |
| `rules/shapes.py` | `tuple-shape` and `set-shape` |
| `judge.py` | One judging point: a diff in, verdicts out (allow, refuse, hold), runtime-free |
| `holds.py` | The hold records, waiting for an answer, and answering |
| `report.py` | The reports, in pyright's shape |
| `hooks/claude.py`, `hooks/codex.py` | Each runtime's payloads and outputs |
| `cli.py` | `lup-env hook`, `lup-env rules check`, `lup-env holds` |

Public names: `Finding`, `Rule`, `Verdict`, `Hold`, and the commands. The rule set is the extension point later rules plug into.

The `lup-env` command is this slice's stand-in until the declaration and CLI piece (build step 2) builds the real `lup` command tree. The commands keep their meaning there; their final names are that piece's call.

## Installing it here

- `.claude/settings.json` gets the three hooks. The `permissions.ask` on `Write` goes, since the hold on new files covers every write path, `Write` included. Keeping both would prompt twice for each new file.
- `.codex/hooks.json` gets the same three.
- `.gitignore` gets `.lup/`.
- A GitHub Actions workflow runs `lup-env rules check` against the pull request's base and lists every suppression in the job summary.

## Decisions

Each with its alternative, and where it lives. The ones marked **(yours)** are the operator's.

1. **(yours)** Judge state against the last accepted state, at the end of each batch. *Alternative:* a snapshot before and after each call (`DESIGN.md`'s wording, the probe's kit). *Where:* `changes.py`, `judge.py`.
2. **(yours)** Allow, refuse, hold; no defer. *Alternative:* keep defer for `Edit`, `Write` and `apply_patch` only, decided before the call from the tool's input; shell writes would never defer. *Where:* `judge.py`.
3. Content equal to `HEAD` isn't judged. *Alternatives:* judge it, which makes every checkout replay history as new writes; recognize git commands, which is the command-spelling parsing `DESIGN.md` removed. *Where:* `changes.py`.
4. **(yours)** The four rules as in the table, with `set-shape` narrowed to sets of tuples. *Alternatives:* `set-shape` as before; dropping it. *Where:* `rules/`.
5. **(yours)** Every rule suppressible, with a required reason, and every suppression listed in the pull request. *Alternative:* unsuppressible rules, as the first lup had. *Where:* `rules/engine.py`.
6. Suppressions written as TOML in a comment, read with `tomllib`. *Alternatives:* a shorter form (`# lup: allow[tuple-shape] reason`) with a grammar library to parse it, a new dependency; or parsing it by hand, which the rule forbids. *Where:* `rules/engine.py`.
7. Findings on touched lines refuse; the refusal lists every finding in the file. *Alternatives:* any finding in a touched file refuses; or only touched lines are reported. *Where:* `rules/engine.py`, `report.py`.
8. A held call waits in the hook, answered by a terminal command for now. *Alternative:* put the file back and let the agent carry on, applying it when approved. That doesn't pause the agent, which `DESIGN.md` wants. *Where:* `holds.py`.
9. **(yours)** The hold replaces the bridge's `permissions.ask` on `Write`. *Alternative:* keep both until the dashboard. *Where:* `.claude/settings.json`.
10. The judge runs from `main`'s copy. *Alternative:* from the worktree's own environment. *Where:* the hook commands in `.claude/settings.json` and `.codex/hooks.json`.
11. Test roles from pytest's `testpaths`. *Alternative:* wait for the declaration. *Where:* `rules/engine.py`.
12. **(yours)** Package `packages/lup-env` (`lup-env`, `lup_env`), the modules above, and a stand-in `lup-env` command. *Alternative:* start the environment inside the library package and split it later, which is the boundary `AGENTS.md` asks to keep. *Where:* `packages/lup-env/`.
13. **(yours)** A CI workflow, which is a new file outside the container's walls. *Alternative:* run the check only in the hook. That misses Codex's gaps and anything committed without the hook. *Where:* `.github/workflows/`.
