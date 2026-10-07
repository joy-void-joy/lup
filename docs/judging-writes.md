# Judging every write: allow, ask or refuse

**One sentence:** lup judges every write in an agent's worktree. An `Edit` or `Write` is judged before it lands, on the content it would produce. Anything else (a command, a script, a background process, Codex's `apply_patch`) is judged at the next checkpoint, by comparing the worktree with the last state lup accepted. Each change is allowed, asked of the operator, or refused.

This is the first piece of `DESIGN.md`'s build order, built alongside the library. It's the review workflow, and every call goes through it. It covers:
- the three outcomes, and what each kind of change gets;
- judging `Edit` and `Write` before they land;
- the checkpoint and its snapshot store, for everything else;
- asking the operator: in Claude Code's own prompt, and through holds where a runtime can't ask;
- refusals, which report every finding at once and save the agent's version;
- the typed engine and the code rules (the conventions they enforce are in `docs/conventions.md`);
- type errors and ruff's findings as information at each checkpoint;
- the `# lup:` directives: `ignore`, `defer`, notes, and removing a note;
- tests written as a specification, expressed with protected paths and mounts;
- the verdict log;
- the hooks for Claude Code and Codex, and installing them in this repository.

Later:
- answering in the dashboard (until then, Claude Code's prompt, the terminal, and the interim review hook built on its own branch);
- keeping the store out of the agent's reach, and refusing reads of secrets, which come with launch and containers;
- edits a session makes in another repository, which come with launch and spawn.

## What the first lup did

The first lup's edit policy (`policy/kernel/edit.py` in `lup-legacy`, documented in its 132 KB `docs/permissions.md`) is the evidence. What the operator relied on was a small core; most of the size was machinery.

| Area | The first lup | Here | Why |
|---|---|---|---|
| Which files are gated | Only production code. Tests, scratch, data and docs passed at any size (the gates checked the `production` role) | **Kept** | The "auto-allowed files" the operator relies on |
| Code rules before any allow | The anti-pattern audit ran before every relaxation, so an allow meant "allowed and clean" | **Kept** | The same guarantee |
| New file or whole-file write | Asked (`full-write`): the largest single source of edit asks (21 of 34 parked `Write`s in its last week) | **Kept** | The change that shows design best |
| Protected and human-owned paths | Asked, whoever edited | **Kept** | Manifests, settings and CI run outside the agent's reach |
| Suppressions | Adding one asked | **Kept** | The operator approves each as it's added |
| Removing a review note | Refused (`feedback-removed`); an agent that added a `defer` couldn't take it back | **Reshaped:** free for a note added this session, reported for a committed one | Feedback mustn't vanish silently, but an agent must be able to undo its own note |
| Size | 3 or fewer "real" added lines allowed; more deferred to the runtime's own mode | **Dropped** | In auto mode, edits inside the working directory skip the classifier anyway (Claude Code's permission docs), so the limit only mattered in Manual mode. Its recorded effect was agents splitting edits to fit it. Auto mode is 214 of the 239 permission-mode records in the operator's host transcripts |
| When edits were judged | Before they landed, at `PreToolUse` | **Kept** for `Edit` and `Write`; the checkpoint for everything else | A refused edit never touches the file. Shell writes can't be judged before without parsing commands |
| Shell commands | A 160-command vocabulary over a shell-spelling analyzer; inside a container, unknown commands ran | **Reshaped:** narrow allow rules in Claude Code's settings on the host; every command runs in a container | `DESIGN.md` drops the analyzer. Its one gap: `cp README.md src/new.py` created a production file without asking, which the checkpoint catches |
| Machinery | Launch records and policy snapshots, nested and foreign repositories, git pointer guards, leases and autonomous identities | **Left for launch and rooms** | None of it decides what's allowed. The judge runs from an installed copy; git's config and hooks become read-only mounts in the container; autonomy becomes a field on `Room` |

## The three outcomes

- **allow:** the call goes through with no prompt. On Claude Code the hook answers `allow`; on Codex lup answers Codex's own `PermissionRequest` with `allow`.
- **ask:** the operator decides before the change lands. On Claude Code it's the runtime's own prompt. Where a runtime can't ask before a call, the change is held: the agent waits inside the hook until the operator answers.
- **refuse:** the change doesn't land, or is put back, with the agent's version saved and every finding reported at once.

Refuse wins over ask: a change with rule findings is refused before the operator is asked about it, so they never review a version that will be refused anyway.

lup never stays silent on a write it judges. Staying silent would send the call to the runtime's own permission mode, which in Manual mode means a prompt per edit.

## What each change gets

| Change | Outcome |
|---|---|
| A test, scratch (`tmp/`), docs or data file, at any size | allow |
| `DESIGN.md` or `AGENTS.md` | ask: they're the operator's |
| A protected path | ask |
| Production code with a rule finding on the lines the change touches | refuse, every finding in the file listed, the agent's version saved |
| A new production file, or overwriting a whole existing one | ask |
| A change to the public API (see below) | ask |
| An added `# lup: ignore` | ask |
| Removing a `# lup:` note present when the session started | allow, and reported |
| Any other production edit | allow, once the rules pass it |

**Path roles.** Each path has one role, the first that matches:
1. **protected:** the project declaration; dependency manifests and lockfiles (`pyproject.toml`, `uv.lock`, `package.json`, `bun.lock`); what runs outside the agent's reach (`.github/`, git hooks and `.git/config`, `.pre-commit-config.yaml`, `.vscode/`, `.devcontainer/`, `.claude/`, `.codex/`); what widens a later launch (`sync.json`, `sync.json.local`); secrets (`.env*.local`); and whatever the project adds;
2. **operator's documents:** `DESIGN.md`, `AGENTS.md`;
3. **test:** a module pytest collects as a test: under a root it reads (`testpaths` in the nearest `pyproject.toml`, nested projects included) and matching its `python_files` patterns. A source module pytest reads only for its doctests stays production (`docs/conventions.md`, *Tests*);
4. **scratch:** `tmp/` at any depth, and the saved versions under `.lup/`;
5. **docs:** Markdown files and `docs/`;
6. **data:** JSON, CSV, YAML and other data formats outside a source tree;
7. **production:** everything else.

Production is the default, so a file nobody classified is gated rather than waved through.

**Where a project declares its roles:** a minimal `Project` starts in this piece, with only the fields it reads: its test roots and its additions to the protected paths, shaped as `DESIGN.md`'s example (`Project(tests=[…], protected=Protected.default().add(…))`). The declaration piece grows it.

## The public-API ask

A change to what other code depends on is a design change, so it's asked like a new file:
- a name added to or removed from a package's root (`__init__.py`);
- a new class;
- a changed signature of a definition that existed when the session started: parameters, their types, the return type.

Names created during the session don't ask: the operator sees them when the file or class that holds them is asked.

**How it's computed:** the engine reports each file's public surface (root names, classes, signatures) for the would-be content and for the content the session started with; lup compares the two.

The operator worries this may ask too much, so it's measured from day one through the verdict log, and tuned from what the log shows.

## Before an edit lands

For `Edit` and `Write`, lup knows the file's content after the call before anything is written:
- **`Write`:** the content it carries.
- **`Edit`:** the current file with `old_string` replaced by `new_string`, once, or everywhere with `replace_all`. If `old_string` isn't there exactly as the tool requires, lup allows the call, and the tool fails on its own.

The hook (`PreToolUse`) runs the judgement on that content: the path's role, the code rules through the engine, the public-API comparison, the directives added or removed. It answers allow, ask or refuse. A refused edit never touches the file. The engine checks content that isn't on disk the way pyright's language server checks an unsaved buffer (a check owed below).

**A refused new file** is sent again with `Write` once it's fixed; the prompt is where the operator sees it whole. **A refused edit to an existing file** is fixed in its saved copy and moved into place: the move is a shell write, judged at the checkpoint by its diff against the accepted content, not as a whole-file overwrite. An approval covers the path for the rest of the session, so a file approved and then refused for a finding isn't asked again once fixed.

## After a call: the checkpoint

Everything that isn't an `Edit` or a `Write` is judged after the fact: a `sed`, a script, `cp`, a background process, and Codex's `apply_patch` (whose format lup doesn't parse; `DESIGN.md`, *Runtimes*).

The judging core never sees a runtime. Each runtime's adapter turns its hooks into four events:

| Event | Claude Code | Codex |
|---|---|---|
| session started | `SessionStart` | `SessionStart` |
| call started (id) | `PreToolUse` | `PreToolUse` |
| call finished (id) | `PostToolUse` | `PostToolUse` |
| turn ended | `Stop` | `Stop` |

**A checkpoint runs whenever a call finishes and no other call is running,** and again when the turn ends. Parallel calls are judged together once the last one finishes; a late background write is judged at the next checkpoint. The checkpoint is before the agent's next model request, so a refusal reaches the agent before it writes its next line.

**It degrades gracefully:**
- a "finished" with no matching "started" is ignored (Codex's `write_stdin` can deliver the original command's `PostToolUse` without a `PreToolUse` of its own);
- a call that never reports finishing is cleared when the turn ends, and the turn-end checkpoint judges everything anyway;
- the in-flight calls are a set of ids under a file lock, since hooks for parallel calls run concurrently.

**How a checkpoint goes:**
1. **Snapshot.** The worktree is written into lup's own store as a git tree (a private index, `git add -A`, `write-tree`). Ignored files are left out, as `.gitignore` says. The store is a bare repository outside the worktree, and git runs with `core.fsmonitor` and hooks turned off: the effects probe saw a planted `core.fsmonitor` run inside a call.
2. **Compare** with the accepted tree (`git diff-tree`). Nothing changed is the common case after a read.
3. **Set aside what was committed elsewhere.** A changed file whose new content equals its content in a commit that existed at the previous checkpoint, or that arrived from a remote since, isn't judged: that's what a checkout, a pull, a merge, a stash or a `git restore` produce, and that content was judged where it was written. A commit made locally since the previous checkpoint doesn't launder its own files: one shell call that writes a new file and commits it is judged like any write. A file with conflict markers matches no commit, so it's judged.
4. **Judge** every remaining change exactly as an edit is judged before it lands: role, rules, public API, directives.
5. **Refuse** what the table refuses, and what bypassed an ask: a new production file, a public-API change or a suppression made through the shell is refused with a pointer to `Write` or `Edit`, so it comes back through the prompt. That enforces `AGENTS.md`'s "create files with your file tool".
6. **Act:** a refused file goes back to its accepted content, or is removed if it was new, and the agent's version is saved. What's left becomes the new accepted tree.
7. **Report** to the agent, once: everything refused, then type errors and ruff's findings as information.

The accepted tree starts as a snapshot when a session starts. If a stored accepted tree already exists for the worktree, the difference happened while no session ran there: the operator's work or a pull. It's accepted without judging.

**Someone else's edit during a session** can't be told apart from the agent's: the checkpoint sees files, not authors. An edit the operator makes in a worktree while an agent's session runs there is judged as the agent's, and if refused it's put back with the version saved, so nothing is lost. The operator works in their own worktree, or between sessions.

**Cost:**
- one snapshot per checkpoint, about 50 ms at lup's size (the effects probe); the existing projects have 161 to 3,721 tracked files;
- plus the engine's incremental re-check of the changed files;
- target: under 300 ms per checkpoint on this repository, type check included.

## Asking the operator

**On Claude Code, through its own prompt.** The `PreToolUse` hook answers `ask`, with a reason naming what's asked: the new path, the protected path, the public name or signature, or the rule and the reason given for an `ignore`.
- A hook's `ask` forces a prompt in auto mode too (hooks docs; tested on this repository for the bare `Write` rule).
- Settings' `ask` and `deny` rules are evaluated whatever the hook answers, so the blanket `permissions.ask` on `Write` in `.claude/settings.json` goes when this lands; otherwise every `Write` still prompts.
- In the bridge, the interim review hook (built on its own branch) can carry these asks to the first lup's review dashboard instead of the terminal prompt. This piece decides what is asked; that hook or the prompt carries it.

**On Codex, through a hold.** Codex's `PreToolUse` can't answer "ask", and `apply_patch` is judged at the checkpoint. So an ask on Codex is held at the checkpoint: the agent waits inside the hook, and the operator answers with `lup-dev holds approve <id>` or `lup-dev holds decline <id> --comment …`.
- `lup-dev holds` lists what's waiting, with the diff.
- A decline puts the change back and saves it, with the comment beside it. An approval with a comment passes the comment on.
- The hook waits up to 24 hours (the first lup held calls for 4 hours without trouble). Unanswered by then, the change is put back and saved, and the hold stays open.
- This is a declared gap: on Codex the operator answers from a terminal until the dashboard exists.

**Nobody answers their own hold.** `lup-dev holds approve` and `decline` refuse to run when their environment shows they run inside an agent's session (the variables each runtime sets in the commands it runs; a check owed). That stops a mistake, not a determined agent: in the bridge the agent runs as the operator's user and could write the answer itself. The real separation comes with containers, where the hold store sits outside the container and answering runs only on the host.

## Refusals

The refused file goes back to its accepted content, or never changes if it was refused before landing. The agent's version is saved under `.lup/saved/<n>/<path>` in the worktree (`.lup/` is ignored, so saved copies are never judged). The agent fixes the listed lines there and moves the file into place; nothing is resent whole, except a new file, which goes back through `Write` and its prompt.

The report, in pyright's shape:

```
lup refused 1 file. It is unchanged; your version is saved.

src/lup/claude.py (saved at .lup/saved/3/src/lup/claude.py)
  src/lup/claude.py:41:12 - tuple-shape: a fixed-length tuple[str, int] hides what each position means
      steer: name the fields with a pydantic model
  src/lup/claude.py:88:5 - regex: `import re` parses with a regular expression
      steer: use the format's own parser (lup docs rules regex)

Fix these lines in the saved copy, then move it into place:
  mv .lup/saved/3/src/lup/claude.py src/lup/claude.py
To keep a finding, add on its line or the line above (the operator is asked):
  # lup: ignore("<rule>", why="<reason>")
```

**Which findings refuse.** Findings on the lines the change touched; for a new file, every line. The refusal lists every finding in the file, so one pass fixes them all: the art studio's agent resent a 550-line file four times, once per rule. Findings on untouched lines are listed under their own heading and don't refuse; they exist only where a rule is newer than the code.

## Type errors and ruff's findings

They're information, not refusals (`DESIGN.md`: "information never travels on a blocking channel"):
- at each checkpoint, pyright's type errors and ruff's findings in the files changed, as plain context beside the call's result;
- when the turn ends, the `Stop` hook refuses to end it while files touched this session have type errors or ruff findings, saying which;
- the formatter runs at commit.

ruff runs with `--ignore-noqa`, and pyright with `enableTypeIgnoreComments = false`; lup filters both through its own `# lup: ignore`, so there's one suppression syntax (`docs/conventions.md`).

## Shell commands

- **On the host (now, in the bridge):** narrow allow rules in Claude Code's own settings, such as `Bash(uv run pytest:*)`, `Bash(uv run pyright:*)`, `Bash(git status:*)`, `Bash(git diff:*)`. Claude Code matches them, so lup parses no commands; auto mode keeps narrow rules and drops broad ones. Here they're written by hand in `.claude/settings.json`; the launch piece generates them from the declaration. Everything else goes to the runtime's own mode, and what a command writes is judged at the checkpoint either way.
- **The prompts the runtime's mode shows** reach the operator in the review dashboard as soon as possible: in the bridge, the interim review hook answers Claude Code's `PermissionRequest`, which fires whenever a prompt would be shown, by parking it as a review.
- **In a container (the launch piece):** every command runs; the container is the wall.
- **A probe owed:** whether a `PreToolUse` hook's `allow` skips auto mode's classifier. No vendor doc says so and the first lup never measured it. If it does, the hook can allow commands itself where the classifier only adds latency.

## The engine: one typed tree

Every lup rule reads one typed tree: each file parsed once and type-checked once, every rule reading types straight from that tree. That rules out the first lup's approach (a syntax tree, plus a pyright language server asked about one position at a time) and a syntax-only first stage: the rules are typed from the first one, so they never grow as a patchwork of syntax checks.

**Pyright's own tree, built against its source at a pinned release.**
- **What it is:** a small TypeScript program built against `packages/pyright-internal` from pyright's repository, shipped prebuilt inside `lup-dev`.
- **How it runs:** one long-lived process per worktree with a session, loading the project the way pyright does and keeping it warm. It stops when no session has used it for a while (an overridable default).
- **For each judgement:** it checks the given files, on disk or as would-be content. Each rule is a visitor over pyright's parse tree, asking pyright's type evaluator for any expression's type. It also reports each file's public surface, the `# lup:` directives, and each file's own imports against the import-linter contracts.
- **What comes back:** one list, pyright's type errors and lup's findings in the same shape, as JSON lines the Python side reads into pydantic models.

Pyright has no plugin API, and its published package is one bundled file whose internals can't be imported. Nothing existing does this: Zzzen/pyright-lint has been dead since February 2023; basedpyright, ty, Pyrefly and Zuban offer no extension API; pyright's type server answers one query per expression, which is the oracle approach. mypy's tree in Python stays the fallback if building on pyright's internals turns out too costly to keep up; it would be a second type checker that can disagree with pyright at the edges.

**A spike measured it** (pyright 1.1.414, about 970 lines of TypeScript, evidence under `tmp/spikes/pyright-rules/`):
- **Same answers as pyright:** on the first lup's library, 32 of 32 type errors matched the CLI's exactly.
- **The rules cost under 1% of the check,** at most 8 ms per file.
- **Warm re-checks:** one changed file 65–270 ms median (10–620 range); ten files 0.5–2.7 s, over the target. Nearly all of it is pyright's own re-check, which the type errors need anyway. The machine was heavily loaded, so these are pessimistic.
- **Accuracy:** the typed `string-split` leaves out `shlex.split` and `re.split`, which a syntax-only rule flags. `tuple-shape` caught every alias form tried.
- **Directives** parse in place with pyright's own expression parser.
- **Upgrades:** the rule code compiled unchanged against pyright releases 17 months apart; about 40 lines of project setup broke.
- **Cost:** a 3.5 MB bundle plus 28 MB of standard-library stubs, and 1.5–2.7 GB of memory on a 700-file project. With many sessions, that's per worktree, which is why idle processes stop.

**The spike's questions, as decided:**
1. **Aliases:** a tuple alias is flagged where it's defined, and its uses only when it's defined outside the project.
2. **`Any`:** `string-split` fires on a receiver declared `Any`, but not on one pyright can't infer, so findings don't depend on the environment being installed.
3. **Unions:** `str | X` is flagged when any member is `str` or `bytes`.
4. **Tuples:** `list[X]` is the one spelling of a sequence (`docs/conventions.md`), so `tuple-shape` flags every tuple type; the spike's edge tuples need no special case.
5. **Files that import a changed one:** the rules read only the changed files, so their findings come at the edit. The changed files' importers are re-checked for type errors in the background, and their errors arrive at the next checkpoint. One background pass at a time per worktree: a change while one runs marks it to run once more afterwards, over everything changed, never a second process. The turn-end check waits for the pass, so no type error surfaces after the session.
6. **Type stubs:** the pinned standard-library stubs ship beside the bundle.

## The `# lup:` directives

`# lup:` comments are the channel for notes in code. The grammar:
- **A directive is written as a call**, read with the engine's Python parser; each directive is a small model with its fields.
- **Anything that isn't a call is a note:** `# lup: the retry count matches the provider's documented limit`. Notes are collected for the resolver when it exists.
- **A call to an unknown directive is a finding,** so a wrong directive never sits there silently. In the first lup, a file-wide ignore placed after the docstring did nothing (#213).

**`ignore`:** `# lup: ignore("tuple-shape", why="sh takes its redirections as positional tuples")`, on the finding's line or alone on the line above. Every rule accepts it. Adding one asks the operator. An `ignore` without its reason, or whose rule doesn't fire there, is a finding. Removing one is free: it only makes the rule apply.

**`defer`:** work knowingly left undone, written on the code it's about, so the next reader sees the gap is known and tracked instead of fixing it blind or calling it pre-existing:
```python
# lup: defer(issue=12, why="retries ignore Codex's reset time until its SDK reports it")
# lup: defer(when=sdk_reports_cache_ttl, why="read the TTL from the SDK instead of assuming an hour")
```
- **`why` is required:** what's left undone here, in one line.
- **It needs a way to come back: an `issue`, a `when`, or both.** Without either it's a note nothing would ever close, which is how the first lup's notes piled up.
- **`issue`** is an issue number in this repository, or `"owner/repo#7"` elsewhere. The ledger's to-do items point at GitHub issues too, so a `defer` stays valid when the ledger arrives. A `defer` whose issue is closed is reported, so the comment never outlives the work it points at.
- **`when`** names a condition written in Python, which wakes the deferral when it holds. A condition is an instance of lup's `Condition` ABC (one method, `holds() -> bool`), declared in the module the project's declaration names for its conditions. lup ships stock ones (`PythonAvailable(version="3.15")`, `PackageReleased(name=…, version=…)`); a project subclasses its own. The comment holds only the name, so nothing in a comment is ever run, and the condition is typed and tested like any code.
- **Work that isn't about one spot in the code** isn't a `defer`: it's only an issue (as `frozendict`, issue #7).
- **Checked:** its syntax and fields at the edit, and that `when` names a declared condition; at the gate, the issue's state and the condition, which may reach GitHub and the package index (tests stub both).

**Removing a note:**
- a note or directive added during this session can be removed freely, so an agent can take back its own `defer`;
- one present when the session started can be removed too, and the removal is reported: the turn-end check lists the committed notes removed this session, for the agent's report and the merge commit's message, so feedback never vanishes silently;
- once the ledger exists, a note pointing at a record is removed when its record is closed.

## Tests written as a specification

Some work is built against tests written beforehand: the operator, or an agent they asked, writes the tests a feature must pass, and another session implements until they pass. The failure to guard against is the implementing agent changing the tests to match its implementation, which makes them pass and the feature still wrong.

The first lup had an "acceptance guard" for it, an opt-in path role it never turned on for itself. Here it needs no construct of its own:
- **asked:** a project adds those tests to its protected paths, so editing one asks the operator;
- **refused outright:** a room implementing against them mounts them read-only, so the wall refuses the write, once rooms exist.

## The verdict log

Every judgement is logged from day one, so how often lup asks, refuses and allows can be measured and tuned instead of guessed. One JSON line per verdict, a pydantic `Verdict`:
- time, session, runtime;
- the tool, or `checkpoint`;
- the path and its role;
- the outcome (allow, ask, refuse, hold) and its reason (the rule, or the kind of ask);
- the operator's answer, when there is one.

It's kept per repository, beside the store. `lup-dev verdicts` summarizes it by outcome and reason over a period. The first lup had no such log, and measuring its verdicts meant reconstructing them from transcripts.

## The two runtimes

| | Claude Code | Codex |
|---|---|---|
| `Edit`/`Write` judged | before they land (`PreToolUse`) | no such tools: `apply_patch` judged at the checkpoint |
| Checkpoint events | `PreToolUse`, `PostToolUse`, `Stop` | the same |
| allow | `PreToolUse` answers `allow` | `PermissionRequest` answered `allow` |
| ask | `PreToolUse` answers `ask` | held at the checkpoint, answered from the terminal |
| refuse | `PreToolUse` answers `deny`, or put back at the checkpoint | put back at the checkpoint |
| How the agent hears | `additionalContext` beside the result | `decision: block` replaces the result, so lup puts the original output first, in full, then the report |
| Configured in | `.claude/settings.json` | `.codex/hooks.json`, run only once its hash is trusted, so the operator trusts it after each change |

On Codex a refused `apply_patch` lands for the moment between the call and the checkpoint; on Claude Code a refused `Edit` never lands. That's the declared difference.

## Where things live

| What | Where | Why there |
|---|---|---|
| The store: snapshots, the accepted tree, in-flight calls, holds, refusals | `$XDG_STATE_HOME/lup/worktrees/<id>/`, outside the worktree | The restore source must be out of the agent's reach. In the bridge it isn't, since the agent runs as the operator's user; launch puts it out of the container |
| The verdict log | `$XDG_STATE_HOME/lup/repositories/<id>/verdicts.jsonl` | One place to measure a repository's verdicts across its worktrees |
| Saved versions | `<worktree>/.lup/saved/` | The agent has to edit and move them |
| The judge itself | A local copy installed from `dev` (`uv tool install` from the `dev` checkout), refreshed when `dev` moves | An agent editing the rules in its worktree isn't judged by its own edit, and a broken judge in a worktree can't refuse every write including its own fix (in the first lup, conflict markers in the compiled hook refused every command). A branch changing the rules runs them in its own tests until it lands |

In lup itself, the judge's own source isn't asked about at each edit: the judge that runs is the installed copy, so an edit in a worktree can't change what judges it. It's protected after the edit and before it runs, the way the art studio's trust on launch worked. Refreshing the installed judge from `dev` shows the operator the diff of its source since the copy they last approved, and the approved copy keeps judging until they approve the new one. The operator sees exactly what will run before it runs. `DESIGN.md`'s protection of lup's policy and launch code is this same review, applied to every launch once trust on launch is ported.

## Modules

In `packages/lup-dev/src/lup_dev/`:

| Module | What it's for |
|---|---|
| `roles.py` | Path roles: which role a path has |
| `before.py` | `Edit` and `Write` before they land: the would-be content, then the judgement |
| `checkpoint.py` | The four runtime-neutral events, the in-flight set, deciding when to judge |
| `changes.py` | The store: snapshot, compare, set aside what was committed elsewhere, restore, save, move the accepted tree forward |
| `judge.py` | One judgement over a set of changed files, shared by `before.py` and the checkpoint: role, rules, public API, directives, outcome |
| `surface.py` | Comparing a file's public surface before and after |
| `checker.py` | The client for the engine: findings, type errors, surfaces, directives for a set of files |
| `directives.py` | The `# lup:` directive models, and checking them |
| `holds.py` | Holds (Codex): waiting for an answer, and answering |
| `verdicts.py` | The verdict log and its summary |
| `report.py` | The reports, in pyright's shape |
| `hooks/claude.py`, `hooks/codex.py` | Each runtime's payloads in, its outputs out |
| `cli.py` | `lup-dev hook`, `lup-dev rules check`, `lup-dev holds`, `lup-dev verdicts` |

The rules live in `packages/lup-dev/checker/`, a TypeScript project built into one file.

The `lup-dev` command is this piece's stand-in until the declaration and CLI piece builds the real `lup` command tree. The commands keep their meaning there; their final names are that piece's call.

## Installing it here

- `.claude/settings.json` gets the four hooks and the narrow `Bash` allow rules, and loses the `permissions.ask` on `Write` and the interim checker hook (`.claude/hooks/interim_rules.py`, removed).
- `.codex/hooks.json` gets the same four hooks.
- `.gitignore` gets `.lup/`.

## Checks owed

- **Auto mode:** whether a `PreToolUse` hook's `allow` skips the classifier.
- **The engine:** that it checks content not yet on disk, as pyright's language server does an open buffer.
- **Holds:** which environment variables Claude Code and Codex set in the commands they run, so `lup-dev holds approve` can tell it's inside a session.
- **Codex:** what its `PermissionRequest` carries for `apply_patch`, so lup can answer it without parsing the patch; its hook timeout limit, which isn't documented.
- **Claude Code:** whether hooks run in the order that keeps the in-flight set right when calls run in parallel. A "finished" before its "started" would be ignored and leave the call open until the turn ends: harmless, but it delays the checkpoint.
- **Not used:** Claude Code's own record of a command's edits (`bashEditDiff`), which missed files in the probe, a protected one among them.

## Decisions

Each with its alternative and where it lives. **(yours, agreed)** marks what the operator decided; **(yours)** what still waits on them.

1. **(yours, agreed)** Judge state against the last accepted state, at checkpoints. *Alternative:* a snapshot before and after each call. *Where:* `changes.py`, `judge.py`.
2. **(yours, agreed)** The checkpoint is "no call running", built from four runtime-neutral events. *Alternative:* `PostToolBatch` on Claude, a lock on Codex. *Where:* `checkpoint.py`.
3. **(yours, agreed)** lup allows, asks or refuses; it never stays silent on a write it judges. *Alternative:* ask, refuse or stay silent, which the operator first agreed and then reversed: the allow is what keeps routine work from interrupting. *Where:* `judge.py`, `hooks/`.
4. **(yours, agreed)** No line count: any production edit the rules pass is allowed unless something asks. *Alternative:* the first lup's 3-line threshold. *Where:* `judge.py`.
5. **(yours, agreed)** `Edit` and `Write` are judged before they land; the checkpoint judges everything else. *Alternative:* the checkpoint for every write, which restores refused edits after the fact. *Where:* `before.py`.
6. **(yours, agreed)** The allow table: tests, scratch, docs and data at any size; production gated by the rules; asks on new or whole-file production writes, protected paths and suppressions. *Where:* `roles.py`, `judge.py`.
7. **(yours, agreed)** `DESIGN.md` and `AGENTS.md` ask. *Alternative:* allowed like other docs and reviewed after. *Where:* `roles.py`.
8. **(yours, agreed)** Where path roles are declared before the declaration piece: a minimal `Project` now, with test roots and protected-path additions. *Alternative:* defaults and pytest's `testpaths` only. *Where:* `roles.py`, `lup_project.py`.
9. **(yours, agreed to try)** Ask on a public-API change: a package root's names, a new class, a changed signature of a definition that existed when the session started. *Alternative:* no public-API ask. *Where:* `surface.py`, the engine.
10. **(yours, agreed)** Every verdict logged from day one, summarized by `lup-dev verdicts`. *Alternative:* reconstruct from transcripts, as the first lup's study had to. *Where:* `verdicts.py`.
11. **(yours, agreed)** You're asked in Claude Code's prompt (or through the interim review hook); Codex holds at the checkpoint. *Alternative:* holds on both runtimes. *Where:* `before.py`, `holds.py`.
12. **(yours, agreed)** The typed engine on pyright's own tree from the first rule, with no syntax-only stage. *Alternatives:* mypy's tree; ruff's `banned-api` plus a syntax checker first. *Where:* `checker/`.
13. **(yours, agreed)** The spike's six questions, as decided above: no tuple types at all, and importers re-checked in one background pass per worktree, waited on at turn end. *Alternative:* importers left to the gate, which could surface a type error after the session. *Where:* `checker/`, `checkpoint.py`.
14. **(yours, agreed)** `# lup:` directives as calls, everything else a note, a wrong directive a finding. *Where:* `directives.py`.
15. **(yours, agreed)** `defer` carries a required `why`, an `issue`, a `when` naming a `Condition` declared in Python, or both; a closed issue is reported; the ledger's to-do items point at GitHub issues. *Alternatives:* a condition written as a requirement string in the comment; `defer` pointing only at ledger records. *Where:* `directives.py`, the gate.
16. **(yours, agreed)** Removing a note: free if added this session; reported if committed; through its record once the ledger exists. *Alternative:* the first lup's refusal. *Where:* `judge.py`, `directives.py`.
17. **(yours, agreed)** The judge runs from a local copy installed from `dev`. *Alternative:* the worktree's own copy. *Where:* the hook commands.
18. **(yours, agreed)** No acceptance guard of its own: tests written as a specification are protected paths a project adds, and read-only mounts in a room. *Alternative:* the first lup's opt-in `acceptance` path role. *Where:* `roles.py` (protected-path additions).
19. **(yours, agreed for now)** Shell commands on the host through narrow allow rules in Claude Code's settings; the prompts the rest causes reach the review dashboard as soon as possible (in the bridge, through the interim hook's `PermissionRequest`). *Alternative:* a lup vocabulary, which needs the shell parser `DESIGN.md` drops. *Where:* `.claude/settings.json`.
20. Content committed elsewhere isn't judged; commits made locally since the previous checkpoint are. *Alternatives:* judge it all, which replays history as new writes; set aside anything equal to `HEAD`, which let a write-and-commit through. *Where:* `changes.py`.
21. Findings on touched lines refuse; the refusal lists every finding in the file. *Alternative:* any finding in a touched file refuses. *Where:* `judge.py`, `report.py`.
22. Type errors and ruff's findings are information at each checkpoint and refuse only at turn end. *Alternative:* refuse at the checkpoint, which `DESIGN.md` rules out. *Where:* `judge.py`.
23. A refused new file comes back through `Write`; a refused edit through its saved copy. *Alternative:* hold the moved copy at the checkpoint for the operator, which Claude Code can't prompt for there. *Where:* `before.py`, `report.py`.
24. `lup-dev holds` refuses to answer from inside a session; the real separation waits for containers. *Where:* `holds.py`.
25. **(yours, agreed)** The note is `docs/judging-writes.md`: it judges edits before they land, not only after the call. *Alternative:* keep `docs/after-call-diff.md`.
26. **(yours, agreed)** The judge's own source is reviewed before an installed copy runs, not asked at each edit: refreshing from `dev` shows its diff since the last approved copy, which keeps running until the operator approves. *Alternative:* a protected path asked at every edit, which reviews each step rather than what will run. *Where:* the judge's installer.
