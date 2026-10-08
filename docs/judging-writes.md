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
- answering in the dashboard (until then, Claude Code's prompt, the terminal, and the interim review hook, which queues prompts in the first lup's dashboard);
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

- **allow:** the call goes through with no prompt. On Claude Code the hook answers `allow`. On Codex nothing needs answering: Codex doesn't ask before an `apply_patch` inside the workspace, and its `PermissionRequest` fires only for a patch that needs approval (one writing outside the writable roots, or retried after a sandbox denial), which lup leaves to Codex's own approval (*Checks owed*, settled).
- **ask:** the operator decides before the change lands. On Claude Code it's the runtime's own prompt. Where a runtime can't ask before a call, the change is held: the agent waits inside the hook until the operator answers.
- **refuse:** the change doesn't land, or is put back, with the agent's version saved and every finding reported at once.

Refuse wins over ask: a change with rule findings is refused before the operator is asked about it, so they never review a version that will be refused anyway.

lup never stays silent on a write it judges. Staying silent would send the call to the runtime's own permission mode, which in Manual mode means a prompt per edit.

## What each change gets

| Change | Outcome |
|---|---|
| A test, scratch (`tmp/`), docs or data file, at any size | allow |
| `DESIGN.md` or `AGENTS.md` | ask: they're the operator's |
| A protected path | ask; a protected Python module gets the rules too, so a finding on the lines the change touches refuses it |
| A path the project's declaration excludes | allow, nothing reported; a protected one still asks |
| Production code with a rule finding on the lines the change touches | refuse, every finding in the file listed, the agent's version saved |
| A new production file, or overwriting a whole existing one | ask |
| A change to the public API (see below) | ask |
| An added `# lup: ignore` | ask |
| Removing a `# lup:` note present when the session started | allow, and reported |
| Any other production edit | allow, once the rules pass it |

**Path roles.** Each path has one role, the first that matches:
1. **protected:** the project declaration; dependency manifests and lockfiles (`pyproject.toml`, `uv.lock`, `package.json`, `bun.lock`); what runs outside the agent's reach (`.github/`, git's own directory and hooks (`.git/`, `.githooks/`, `.husky/`), `.pre-commit-config.yaml`, `.vscode/`, `.devcontainer/`, `.claude/`, `.codex/`); what widens a later launch (`sync.json`, `sync.json.local`); secrets (`.env*.local`); `.gitignore`, since what it ignores the checkpoint never sees; and whatever the project adds;
2. **operator's documents:** `DESIGN.md`, `AGENTS.md`;
3. **excluded:** what the project's declaration holds to nothing (`Project.excluded`): no lup rules, no ruff or pyright findings reported, writes allowed. A path both protected and excluded stays protected: it still asks, without rules or findings, so exclusion takes the checks away, never the operator's review;
4. **test:** a module pytest collects as a test: under a root it reads (`testpaths` in the nearest `pyproject.toml` holding pytest's options, nested projects included; the root itself without any) and matching its `python_files` patterns, or a `conftest.py` under such a root. A source module pytest reads only for its doctests stays production (`docs/conventions.md`, *Tests*);
5. **scratch:** `tmp/` at any depth, and the saved versions under `.lup/`;
6. **docs:** Markdown files and the root's `docs/`;
7. **data:** JSON, CSV, YAML and other data formats outside a source tree, which is anything under a `src/` directory or in a directory holding an `__init__.py`;
8. **production:** everything else.

Production is the default, so a file nobody classified is gated rather than waved through.

**A protected Python module gets lup's rules as production code does** (#14): protection adds the operator's review, it doesn't take the rules away. A finding on the lines a change touches refuses it, since refuse wins over ask; a clean change asks, with any design ask beside the protected one, and no approval covers the protected ask. Its type errors and ruff's findings are information like any module's, and must be clean at the turn's end; `lup-dev rules check` reads it too. `policy/roles.py` says which modules the rules read (`ruled`: production and protected) and whose pyright and ruff findings are reported (`checked`: those, and tests). The default patterns are data in `lup_dev/catalog/paths.py`, which the operator reviews; `policy/roles.py` holds the matching.

A deleted file asks where it's protected or one of the operator's documents, and is otherwise allowed: the public-API ask covers what other code loses. A write outside the session's worktree isn't judged here; edits in another repository come with launch and spawn.

**Where a project declares its roles:** a minimal `Project` starts in this piece (`lup_dev/project.py`), with only the fields it reads: its test roots, its additions to the protected paths, the paths it excludes, the rules it lifts from some paths, and the module declaring its conditions, shaped as `DESIGN.md`'s example (`Project(tests=[Pytest(root=…)], protected=Protected.default().add(…), excluded=[…], exempt=[Exemption(rule=…, paths=[…], why=…)], conditions="pkg.conditions")`). An exemption lifts one rule from every file its patterns match, with the operator's reason, where an `ignore` keeps one finding out on its line; the judge and `lup-dev rules check` leave out an exempt rule's findings, and every other rule still holds there. `excluded` is the settled part of `DESIGN.md`'s open question 8; compiling the declaration into the tools' own settings (ruff's and pyright's exclusions among them) is the declaration piece's. It's loaded from `[tool.lup] project = "pkg.module:project"`, importing from the worktree's root, its `src/`, and each uv workspace member and its `src/`, since the judge runs from its own installed copy; without one, the defaults apply, and one that can't be loaded is an error rather than a silent fallback. The declaration piece grows it.

## The public-API ask

A change to what other code depends on is a design change, so it's asked like a new file:
- a name added to or removed from a package's root (`__init__.py`);
- a new class;
- a changed signature of a definition that existed when the session started: parameters, their types, the return type.

Names created during the session don't ask: the operator sees them when the file or class that holds them is asked.

**How it's computed:** the engine reports each file's public surface (root names, classes, signatures) for the would-be content and for the content the session started with; lup compares the two.

The operator worries this may ask too much, so it's measured from day one through the verdict log, and tuned from what the log shows.

## Before an edit lands

For `Edit` and `Write`, lup knows the file's content after the call before anything is written. The adapter reads each as one of two proposals in lup's own words (`policy/before.py`), so the core never names a runtime's tools:
- **a whole write (`Write`):** the content it carries.
- **a replacement (`Edit`):** the current file with `old_string` replaced by `new_string`, once, or everywhere with `replace_all`. If `old_string` isn't there exactly as the tool requires, lup allows the call, and the tool fails on its own.

The hook (`PreToolUse`) runs the judgement on that content: the path's role, the code rules through the engine, the public-API comparison, the directives added or removed. It answers allow, ask or refuse. A refused edit never touches the file. The engine checks content that isn't on disk the way pyright's language server checks an unsaved buffer (a check owed below).

**What it's compared with** is the accepted content, not the file on disk, so a command's write not yet judged is judged with the edit: an edit to a file a command just created asks as a new file. A write allowed or asked is remembered with its call; when the call finishes, the checkpoint accepts that content as judged, and an asked call that ran means the operator approved it.

**A refused new file** is sent again with `Write` once it's fixed; the prompt is where the operator sees it whole. **A refused edit to an existing file** is fixed in its saved copy and moved into place: the move is a shell write, judged at the checkpoint by its diff against the accepted content, not as a whole-file overwrite. An approval covers the path for the rest of the session, so a file approved and then refused for a finding isn't asked again once fixed. It covers the asks that show the file's design (a new file, a whole write, a public-API change); a protected path, an operator's document and each added `ignore` are asked every time.

## After a call: the checkpoint

Everything that isn't an `Edit` or a `Write` is judged after the fact: a `sed`, a script, `cp`, a background process, and Codex's `apply_patch` (whose format lup doesn't parse; `DESIGN.md`, *Runtimes*).

The judging core never sees a runtime. Each runtime's adapter turns its hooks into four events:

| Event | Claude Code | Codex |
|---|---|---|
| session started | `SessionStart` | `SessionStart` |
| call started (id) | `PreToolUse` | `PreToolUse` |
| call finished (id) | `PostToolUse`, `PostToolUseFailure` | `PostToolUse` |
| turn ended | `Stop` | `Stop` |
| a subagent's conversation ended | `SubagentStop` | `SubagentStop` |

The events live in `policy/checkpoint.py`; the adapters in `lup_dev/adapters/`, the only modules that name a runtime (an import contract keeps them behind `lup_dev.cli`, and `docs/conventions.md` has the rule).

**A checkpoint runs whenever a call finishes and no other call is running,** and again when the turn ends. Parallel calls are judged together once the last one finishes; a late background write is judged at the next checkpoint. The checkpoint is before the agent's next model request, so a refusal reaches the agent before it writes its next line.

**Subagents.** A call that runs a subagent (Claude Code's `Agent`, Codex's `spawn_agent`) isn't counted as running: its subagent's own calls are, so a subagent's writes are judged as it makes them, and the report goes to the subagent whose call finished. The checkpoint sees files, not authors, so its report also waits, as mail, for every other conversation whose calls finished since the last checkpoint, and reaches each at its next finished call or the end of its conversation. A subagent's end clears its own calls and runs a checkpoint if none is left running; the turn-end checks are the session's.

**It degrades gracefully:**
- a "finished" with no matching "started" leaves the running calls as they are (Codex's `write_stdin` can deliver the original command's `PostToolUse` without a `PreToolUse` of its own), and still runs a checkpoint if no call is running;
- a call that never reports finishing is cleared when its conversation's turn ends, and the turn-end checkpoint judges everything anyway. Claude Code reports no event for a call the operator declined at its prompt, so a declined call stays counted until the turn ends: harmless, but it holds back the checkpoints of that turn;
- the in-flight calls are a set of ids under a file lock, since hooks for parallel calls run concurrently.

**How a checkpoint goes:**
1. **Snapshot.** The worktree is written into lup's own store as a git tree (a private index, `git add -A`, `write-tree`). Ignored files are left out, as `.gitignore` says. The store is a bare repository outside the worktree, and git runs with `core.fsmonitor` and hooks turned off: the effects probe saw a planted `core.fsmonitor` run inside a call.
2. **Compare** with the accepted tree (`git diff-tree`). Nothing changed is the common case after a read.
3. **Set aside what was committed elsewhere.** A changed file whose new content equals its content in a commit that existed at the previous checkpoint, or that arrived from a remote since, isn't judged: that's what a checkout, a pull, a merge, a stash or a `git restore` produce, and that content was judged where it was written. A commit made locally since the previous checkpoint doesn't launder its own files: one shell call that writes a new file and commits it is judged like any write. A file with conflict markers matches no commit, so it's judged.
   - **How:** the commits are those the worktree's refs and `HEAD` named at the previous checkpoint, plus its remote-tracking refs now, and `git log --find-object=<blob> <those commits> -- <path>` says whether any of their history holds that content at that path. A deletion is set aside when `HEAD` lacks the path and was one of those commits (a branch switch).
   - **A gap:** a remote-tracking ref also moves when the agent pushes, so one call that writes a file, commits it and pushes it is set aside like a pull. Telling a fetch from a push needs the reflog's messages; the hole is narrow while pushes run on the host, and closes with containers, where pushes go through a host service.
4. **Judge** every remaining change exactly as an edit is judged before it lands: role, rules, public API, directives. Content judged before it landed (a file tool's write whose call finished, a hold the operator approved) is accepted as it is; changed since, it's judged from that content.
5. **Refuse** what the table refuses, and what bypassed an ask: on a runtime that asks before a call, a new production file, a public-API change, a suppression, a protected path or an operator's document changed through the shell is refused with a pointer to the file tools, so it comes back through the prompt. That enforces `AGENTS.md`'s "create files with your file tool". On a runtime that can't ask before a call, it's held instead (*Asking the operator*).
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
- In the bridge, the interim review hook (`.claude/hooks/interim_review.py`) carries these asks to the first lup's review dashboard instead of the terminal prompt: it queues the call and refuses it at once, the agent hears the answer through the hook's `wait` subcommand run in the background, and repeats the exact call once it's approved. This piece decides what is asked; that hook carries it.

**On Codex, through a hold.** Codex's `PreToolUse` can't answer "ask", and `apply_patch` is judged at the checkpoint. So an ask on Codex is held at the checkpoint: the agent waits inside the hook, and the operator answers with `lup-dev holds approve <id>` or `lup-dev holds decline <id> --comment …`.
- `lup-dev holds` lists what's waiting, with the diff.
- A decline puts the change back and saves it, with the comment beside it. An approval with a comment passes the comment on.
- The hook waits up to 24 hours (the first lup held calls for 4 hours without trouble), polling the hold every 2 seconds. Unanswered by then, the change is put back and saved, and the hold stays open: an answer given later reaches the agent at its next checkpoint, and an approval then covers the path, so the saved version can go back into place. Codex's hook timeout has no maximum, so its `PostToolUse` and `Stop` hooks are configured with more than a day.
- While a hold waits, the store is released: other calls' checkpoints leave the held files alone.
- This is a declared gap: on Codex the operator answers from a terminal until the dashboard exists.

**Nobody answers their own hold.** `lup-dev holds approve` and `decline` refuse to run when their environment shows they run inside an agent's session: Claude Code's `CLAUDE_CODE_CHILD_SESSION`, Codex's `CODEX_THREAD_ID` (*Checks owed*, settled). Each adapter reads its own runtime's variable. That stops a mistake, not a determined agent: in the bridge the agent runs as the operator's user and could write the answer itself. The real separation comes with containers, where the hold store sits outside the container and answering runs only on the host.

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
- at each checkpoint, pyright's type errors and warnings and ruff's findings in the files changed, test files included, as plain context beside the call's result; with them, lup's findings on lines no change touched, and the type errors the background pass found in the files importing what changed;
- when the turn ends, the `Stop` hook refuses to end it while files touched this session, or files importing them where the pass found errors, have type errors, warnings or ruff findings, saying which;
- the formatter runs at commit.

ruff runs with `--ignore-noqa`, and pyright with `enableTypeIgnoreComments = false`; lup filters both through its own `# lup: ignore`, so there's one suppression syntax (`docs/conventions.md`). ruff is the project's own (`.venv/bin/ruff`) where it has one, run on the would-be content through stdin under the file's name, so the project's configuration applies (`codescan/ruff.py`).

**At the gate, `lup-dev rules check`** checks every Python file as the turn's end does, and fails on any finding: lup's (production only; tests are exempt), pyright's, ruff's, each through `# lup: ignore`, and each deferral whose issue is closed or whose condition holds. Since ruff and pyright alone don't read lup's `ignore`, this is the check that decides whether a finding is kept.

## Shell commands

- **On the host (now, in the bridge):** narrow allow rules in Claude Code's own settings, such as `Bash(uv run pytest:*)`, `Bash(uv run pyright:*)`, `Bash(git status:*)`, `Bash(git diff:*)`. Claude Code matches them, so lup parses no commands; auto mode keeps narrow rules and drops broad ones. Here they're written by hand in `.claude/settings.json`; the launch piece generates them from the declaration. Everything else goes to the runtime's own mode, and what a command writes is judged at the checkpoint either way.
- **The prompts the runtime's mode shows** reach the operator in the review dashboard as soon as possible: in the bridge, the interim review hook answers Claude Code's `PermissionRequest`, which fires whenever a prompt would be shown, by parking it as a review.
- **In a container (the launch piece):** every command runs; the container is the wall.
- **A probe owed:** whether a `PreToolUse` hook's `allow` skips auto mode's classifier. No vendor doc says so and the first lup never measured it. If it does, the hook can allow commands itself where the classifier only adds latency.

## The engine: one typed tree

Every lup rule reads one typed tree: each file parsed once and type-checked once, every rule reading types straight from that tree. That rules out the first lup's approach (a syntax tree, plus a pyright language server asked about one position at a time) and a syntax-only first stage: the rules are typed from the first one, so they never grow as a patchwork of syntax checks.

**Pyright's own tree, built against its source at a pinned release.**
- **What it is:** a small TypeScript program built against `packages/pyright-internal` from pyright's repository, shipped prebuilt inside `lup-dev`.
- **How it runs:** one long-lived process per worktree with a session, loading the project the way pyright does and keeping it warm, on a Unix socket under `$XDG_RUNTIME_DIR/lup/`. A hook that finds none starts it, under a lock so hooks running at once start one. It stops when nothing has asked it for `LUP_ENGINE_IDLE` (15 minutes by default), and at once for a client that expects another build, so a rebuilt engine replaces the old one at the next request.
- **Keeping in step without a file watcher:** a file checked with would-be content holds it until the next request, which puts the disk's back unless the edit landed, so a landed edit costs no second check. A file read from disk is checked by its `stat`, with pyright's own fingerprint deciding; a changed directory re-enumerates the project's files; a changed import search path or configuration reloads.
- **For each judgement:** it checks the given files, on disk or as would-be content. Each rule's check (*How a rule is declared*, below) reads pyright's parse tree, asking pyright's type evaluator for any expression's type. It also reports each file's public surface, the `# lup:` directives, and each file's own imports against the import-linter contracts.
- **What comes back:** one list, pyright's errors and warnings and lup's findings in the same shape, as JSON lines the Python side reads into pydantic models. Spans count lines and columns from 1, columns in characters as Python counts them, and leave out the parentheses around an expression.

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
5. **Files that import a changed one:** the rules read only the changed files, so their findings come at the edit. The changed files' importers are re-checked for type errors in the background, and their errors arrive at the next checkpoint. One background pass at a time per worktree: a change while one runs marks it to run once more afterwards, over everything changed, never a second process. The turn-end check waits for the pass, so no type error surfaces after the session. Built (`policy/importers.py`, `ImportersPass`) as a lock the pass holds for its whole life, which the system frees however the process ends: a request adds its files to what's pending and starts a process only when the lock is free; the pass takes everything pending, batch after batch, and releases its lock only once nothing is, under the state's own lock, so no request finds it gone with work left. Two requests racing can start a second process, which finds the lock held and exits without running a pass. Work left pending with no pass running is done by the turn's end while it waits.
6. **Type stubs:** the pinned standard-library stubs ship beside the bundle.

## How a rule is declared

**One table:** `lup_dev/catalog/rules.ts`, a plain object literal with one entry per rule, keyed by the rule's id. Each entry holds the rule whole:
- **`mistake`:** the mistake it prevents, as a sentence that stands alone;
- **`steer`:** where it steers instead, as a sentence that stands alone;
- **`check(file)`:** how it recognises its case, reading pyright's tree and asking pyright's type evaluator, through the engine's helpers;
- **`examples`:** its specification, as code (below).

```ts
'string-split': {
    mistake: 'Splitting structured text by hand matches the inputs it was tried on, and fails quietly on the rest.',
    steer: "Read the text with its format's parser: `shlex.split` for a command line, `urllib.parse` for a URL, `csv` for rows.",
    check(file) {
        for (const call of file.methodCalls(['split', 'rsplit'])) {
            const separator = call.argument('sep', 0);
            if (separator && !file.isNone(separator) && file.isText(call.receiver)) {
                file.report(call.node, `\`.${call.method}(…)\` splits a \`${file.printType(call.receiver)}\``);
            }
        }
        for (const call of file.methodCalls(['partition', 'rpartition'])) {
            if (file.isText(call.receiver)) {
                file.report(call.node, `\`.${call.method}(…)\` splits a \`${file.printType(call.receiver)}\``);
            }
        }
    },
    examples: {
        flags: [{ code: python`…url.split("/")[2]…`, rewritten: python`…urlsplit(url).hostname…` }],
        passes: [python`…shlex.split(line), line.split()…`],
    },
},
```

- **Where it lives:** in `lup_dev/catalog/`, with lup's other policy data, which `lup_project.py` protects: the operator reviews every change to a rule before it lands. It's TypeScript in a Python package's directory. The engine's build (`packages/lup-dev/checker/`) compiles the table into its bundle, and the table imports the engine's helpers through a path alias (`checker/…`) rather than relative paths across the tree. The build hands its `tsconfig.json` to the bundler explicitly: the bundler otherwise looks for the one nearest each file, and finds none above the table (checked with esbuild and tsc).
- **Each check stays short,** reading like the rule's sentence. What checks share is a helper in the engine (`checker/src/`), outside the table: finding the calls of a method, whether pyright finds an expression to be text, what a written type denotes with its aliases. A check that grows long is a helper waiting to be written.
- **The engine makes each finding whole.** A check reports where and what it saw ("`tuple[str, int]` is a tuple type"); the engine adds the rule's mistake to the message, and its steer. The judge receives complete findings, so `codescan/contract.py` doesn't change.
- **Python learns about rules only from the engine.** The engine lists its rules (id, mistake, steer, examples) straight from its table, without loading a project (`Checker.rules()`, `lup-dev rules list`). A check names the project's selection, or none for every rule, and the engine refuses one naming a rule it doesn't have. An `ignore` naming no rule never keeps a finding, so the judge reports it as `unused-ignore`. Python never declares a rule.

**Why a table of code:** recognising a case takes pyright's own tree and types. A vocabulary of declared matchers kept recognition reviewable, but spread a rule over the vocabulary and the engine. A spike (`tmp/spikes/rule-shape/`) then compared this table with Python rules over `ast` asking the warm engine by position. Both gave the same findings on 739 files. The Python version needed two trees to agree, though, and silently missed types pyright reads in strings outside annotations (`cast("tuple[int, str]", value)`) until the engine listed them; its checks also cost 10 to 20 times more. The table reads the one typed tree directly.

**Examples are the specification,** held in the entry as code (`examples`), short enough to read with the rule:
- **`flags`:** code the rule flags, each with its `rewritten`, the same code done the steer's way. A rule needs several kinds of case, which a pair of files couldn't hold.
- **`passes`:** near misses the rule must not flag: `.split()` with no separator, `shlex.split(…)`.
- **What the engine's tests check,** placing each snippet as a module of a small package: each of `flags` gets a finding from its rule and no other, so each example shows one rule; each `rewritten` passes every rule, ruff and pyright, so a rule's steer never trips another (`docs/conventions.md`, *Keeping the rules cohesive*), but for pyright's missing-source warning where a steer names a library lup doesn't install and pyright has its stubs (`tqdm`); each of `passes` gets no finding from its rule; and every rule has at least one of `flags`.
- **Kept short:** a rule needing a long example has a check or a steer that's too broad.
- Being strings in the table, they're no Python file of the tree, so no tool needs telling to leave them out.

**`docs/rules.md` is compiled from the table** (`lup-dev rules docs`, which asks the engine) and committed: the one generated file. It opens by saying it's generated from `lup_dev/catalog/rules.ts`, and that the table is what to edit. A gate test compiles it again and fails when the committed copy is stale. Once every rule is in the table, `docs/conventions.md`'s table of rules becomes a pointer to it, with a test that every rule id it names under *Enforced by:* is one the engine has. The engine's bundle is built, never committed.

**Every module under `catalog/` is protected,** the table included: changing one asks the operator, and a Python module there gets lup's rules as well, at the edit, at the turn's end and at `lup-dev rules check` (#14).

**Selection and exemptions are the project's declaration's:** which rules run (`DESIGN.md`: `rules=Rules.all() - {"tuple-shape"}`), and where a rule doesn't apply (`lup.types` derives lup's own bases from pydantic's `BaseModel`, which `model-mutability` refuses elsewhere). The table describes rules and holds no project's exemptions. Until the declaration piece brings selection, every rule runs on every file the judge sends the engine, which is production code only.

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
  - At the edit, the conditions module is read without running it (`ast`): every name it binds at its top level counts as declared. At the gate it's imported, and only `Condition` instances count.
  - `PythonAvailable(version="3.15")` holds once uv lists a final release of that version (`uv python list`); `PackageReleased(name=…, version=…)` once the package index has that version or a later final release, yanked ones left out. Both take what they read as a field, so a test hands them a fake.
  - A closed issue (`gh issue view --json state`) or a condition that holds fails `lup-dev rules check`, so the comment is updated or removed before the gate passes.

**What the judge reports about directives**, as lup findings on the directive's line (each directive answers for itself in `codescan/directives.py`): `unused-ignore` (an `ignore` whose rule doesn't fire on the line it covers, from any owner), `malformed-directive` (what the engine reports as malformed: an unknown call, or one missing what it needs), `defer-issue` (an `issue` that's neither a number nor `owner/repo#7`), `defer-condition` (a `when` naming no declared condition), and at the gate `defer-closed` and `defer-due`. They live beside the directives until the rule catalog (`lup_dev/catalog/`) holds them.

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
- the outcome (allow, ask, refuse, hold) and its reasons (the rules that refused, the kinds of ask, or the role that allowed: `rules-pass` for production);
- the operator's answer, when there is one.

It's kept per repository, beside the store. An answer comes after its verdict (when the asked call finishes, or a hold is answered), so it's appended as the same verdict again under the same key, and a reader takes the last line for each key. `lup-dev verdicts --days 7` summarizes it by outcome and reason, with how asks and holds were answered. The first lup had no such log, and measuring its verdicts meant reconstructing them from transcripts.

## The two runtimes

| | Claude Code | Codex |
|---|---|---|
| `Edit`/`Write` judged | before they land (`PreToolUse`) | no such tools: `apply_patch` judged at the checkpoint |
| Checkpoint events | `PreToolUse`, `PostToolUse` (and `PostToolUseFailure`), `Stop`, `SubagentStop` | `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop` |
| allow | `PreToolUse` answers `allow` | nothing to answer: Codex doesn't ask for `apply_patch` inside the workspace |
| ask | `PreToolUse` answers `ask` | held at the checkpoint, answered from the terminal |
| refuse | `PreToolUse` answers `deny`, or put back at the checkpoint | put back at the checkpoint |
| How the agent hears | `additionalContext` beside the result | the same: `additionalContext` beside the result, which reaches the agent untouched |
| When judging itself fails | a file tool's write is denied, naming the failure; other calls go on, told | the agent is told beside the call's result; a turn ends after one block |
| Its sessions' commands carry | `CLAUDE_CODE_CHILD_SESSION=1` | `CODEX_THREAD_ID` |
| Configured in | `.claude/settings.json` | `.codex/hooks.json`, run only once its hash is trusted, so the operator trusts it after each change (in Codex's `/hooks`; there's no command for it) |

On Codex a refused `apply_patch` lands for the moment between the call and the checkpoint; on Claude Code a refused `Edit` never lands. That's the declared difference.

Both runtimes hear a report the same way. Codex's docs say a `PostToolUse` hook's `additionalContext` "is added as extra developer context". Past the handler's `additionalContextLimit` (2,500 tokens by default), Codex keeps the whole text in a file and shows a preview pointing at it, so the hook configuration raises the limit for reports to arrive whole.

## Where things live

| What | Where | Why there |
|---|---|---|
| The store: snapshots, the accepted tree, in-flight calls, holds, refusals | `$XDG_STATE_HOME/lup/worktrees/<id>/`, outside the worktree | The restore source must be out of the agent's reach. In the bridge it isn't, since the agent runs as the operator's user; launch puts it out of the container |
| The verdict log | `$XDG_STATE_HOME/lup/repositories/<id>/verdicts.jsonl` | One place to measure a repository's verdicts across its worktrees |
| Which worktree each session started in | `$XDG_STATE_HOME/lup/sessions/<session>.json` | A session's later events find their worktree even after a `cd` elsewhere |
| Saved versions | `<worktree>/.lup/saved/` | The agent has to edit and move them |
| A worktree's engine: its socket, and its lock and log | `$XDG_RUNTIME_DIR/lup/<id>.sock` (or `lup-<user>` in the system's temporary directory); the lock and log in the store | A socket's path holds about a hundred bytes, which the store's path can exceed |
| The built engine and its stubs | `lup_dev/codescan/bundle/`, built by `packages/lup-dev/checker/build.py`, ignored by git | The installed package carries it, so the judge finds its engine beside it |
| The judge itself | A local copy installed from `dev` by `lup-dev install` (`uv tool install` from the `dev` checkout), refreshed when `dev` moves; the hooks run it as `"$(uv tool dir --bin)/lup-dev"` | An agent editing the rules in its worktree isn't judged by its own edit, and a broken judge in a worktree can't refuse every write including its own fix (in the first lup, conflict markers in the compiled hook refused every command). A branch changing the rules runs them in its own tests until it lands |
| The commit the operator approved last | `$XDG_STATE_HOME/lup/judge/approved.json` | The next refresh shows the judge's source since it |

In lup itself, the judge's own source isn't asked about at each edit: the judge that runs is the installed copy, so an edit in a worktree can't change what judges it. It's protected after the edit and before it runs, the way the art studio's trust on launch worked. Refreshing the installed judge from `dev` shows the operator the diff of its source since the copy they last approved, and the approved copy keeps judging until they approve the new one. The operator sees exactly what will run before it runs. `DESIGN.md`'s protection of lup's policy and launch code is this same review, applied to every launch once trust on launch is ported.

**The installer** (`lup_dev/install.py`, `lup-dev install`), run by the operator from the `dev` checkout:
1. It refuses inside an agent's session (by the variables each runtime sets, as for holds), so an agent never approves the judge that judges it; and it refuses when the judge's source has changes not committed, which the copy would carry unreviewed.
2. It builds the engine (`packages/lup-dev/checker/build.py`).
3. It shows, in a pager, the diff of everything the installed judge carries since the commit approved last, or whole the first time: both packages' `pyproject.toml` and `src/`, the engine's source (`packages/lup-dev/checker/`), and `uv.lock`. Tests and docs aren't carried, so they aren't shown. An approved commit no longer in the repository shows everything.
4. Approved, it installs `packages/lup-dev` with `uv tool install --force`, and records the commit. Declined, nothing changes.
- **How uv installs it.** `uv tool install` from the workspace member's directory honours `lup`'s workspace source, installing it from the checkout as a path dependency; both packages are copies, not editable, and `lup_dev` carries the built bundle (checked with a scratch `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, where the copy listed its rules and answered hooks). But it resolves the tool's other dependencies afresh, ignoring `uv.lock`: the first trial got `filelock` 4.0.12, `tenacity` 9.2.1 and `typer` 0.27.3 where the lock pins 4.0.10, 9.1.4 and 0.27.2. So the installer exports the lock's versions (`uv export --package lup-dev --no-dev --no-emit-workspace`) and passes them as `--constraints`, and the copy runs what the gate ran.

## Modules

In `packages/lup-dev/src/lup_dev/`, by subsystem (`docs/conventions.md`, *Package layout*), highest layer first:

| Module | What it's for |
|---|---|
| **`adapters/`** | **Each runtime's hooks: the only modules naming a runtime** |
| `adapters/claude.py`, `adapters/codex.py` | Each runtime's payloads in, its outputs out, and the variables it sets in its commands |
| **`policy/`** | **Judging every write** |
| `policy/roles.py` | Path roles: which role a path has |
| `policy/judge.py` | One judgement over a set of changed files, shared by `policy/before.py` and the checkpoint: role, rules, public API, directives, outcome |
| `policy/surface.py` | Comparing a file's public surface before and after |
| `policy/before.py` | A file tool's replacement or whole write before it lands: the would-be content, then the judgement |
| `policy/checkpoint.py` | The runtime-neutral events, the in-flight set, deciding when to judge, the checkpoint, holds at the checkpoint |
| `policy/importers.py` | The background pass re-checking the files that import what changed |
| `policy/store.py` | The store: snapshot, compare, set aside what was committed elsewhere, restore, save, move the accepted tree forward |
| `policy/holds.py` | Holds: waiting for an answer, and answering |
| `policy/verdicts.py` | The verdict log and its summary |
| `policy/report.py` | The reports, in pyright's shape |
| `policy/runtime.py` | The `Runtime` ABC: what the core needs to know about a runtime, which each adapter implements |
| **`codescan/`** | **Reading code** |
| `codescan/contract.py` | The engine's contract: findings, type errors, surfaces, directives for a set of files, and the rules the engine lists |
| `codescan/engine.py` | `EngineChecker`, the engine's client: finds or starts a worktree's engine on its socket, asks it, and replaces one from another build |
| `codescan/reference.py` | `docs/rules.md`, compiled from the rules the engine lists |
| `codescan/directives.py` | The `# lup:` directive models, and checking them |
| `codescan/conditions.py` | The `Condition` ABC, the stock `PythonAvailable` and `PackageReleased`, and reading a project's conditions |
| `codescan/ruff.py` | ruff's findings on the changed files, in the engine's `Finding` shape |
| **`catalog/`** | **The data that sets lup's policy, protected** |
| `catalog/paths.py` | The default path patterns each role starts from |
| `catalog/rules.ts` | lup's rules, one entry each: its mistake, its steer, its check and its examples, compiled into the engine |
| **root** | **Package-wide** |
| `project.py` | The minimal `Project` declaration (`Protected`, `Pytest`, `excluded`, `Exemption`), and loading it from `[tool.lup]` |
| `install.py` | Installing the judge: the operator reviews its source since the commit approved last before a new copy runs |
| `settings.py`, `layout.py` | The environment variables `lup_dev` reads; where it keeps what it stores |
| `clock.py` | The clock judging reads and waits on, which tests drive |
| `errors.py` | `LupDevError`, the root of what `lup_dev` raises |
| `cli.py` | `lup-dev hook claude\|codex`, `lup-dev rules check`, `lup-dev holds`, `lup-dev verdicts`, `lup-dev install`; the one place listing the adapters |

The rules live in `catalog/rules.ts`. The engine that runs them lives in `packages/lup-dev/checker/`, a TypeScript project built with the table into one file, which is never committed.

The `lup-dev` command is this piece's stand-in until the declaration and CLI piece builds the real `lup` command tree. The commands keep their meaning there; their final names are that piece's call.

## Installing it here

- **`.claude/settings.json`:**
  - the installed judge's hooks, `"$(uv tool dir --bin)/lup-dev" hook claude`, on `SessionStart`, `PreToolUse`, `PostToolUse` and `PostToolUseFailure` (matching every tool), `Stop` and `SubagentStop`; `Stop` and `SubagentStop` get 1,200 seconds, since the turn's end waits for the importers pass;
  - the interim review hook (`.claude/hooks/interim_review.py`) kept only as the carrier of prompts to the review dashboard, on `PermissionRequest` and `PostToolBatch`: the judge decides what's asked, and its `ask` reaches the dashboard through the prompt it causes (*Checks owed*). The hook's own `PreToolUse` write review is no longer registered; its code stays until no session started with the old settings runs, since such a session would still send it `PreToolUse` and a hook that stopped answering it would block every write there;
  - the old checker's hook removed, and `.claude/hooks/interim_rules.py` with it;
  - the narrow `Bash` allow rules: the gate's commands (`uv run pytest`, `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`, `uv run lint-imports`) and read-only git (`git status`, `git diff`, `git log`).
- **`.codex/hooks.json`:** the same hooks with `hook codex`, every tool matched by leaving the matcher out; no `PostToolUseFailure` and no `PermissionRequest`, which Codex's adapter doesn't answer. `PostToolUse`, `Stop` and `SubagentStop` get a `timeout` of 90,000 seconds, above a hold's day, and `PostToolUse` an `additionalContextLimit` of 20,000 tokens, so a report arrives whole; past it, Codex keeps the whole text in a file and shows a preview pointing there. Codex runs a project's hooks only once trusted, in its `/hooks`.
- **`lup_project.py`** excludes `.claude/hooks/**`: the interim hooks are uv scripts with their own dependencies, outside the conventions, and go with the bridge. They stay protected.
- **Why the hooks name the tool's bin directory** rather than `lup-dev` on the `PATH`: a shell with a worktree's environment activated finds that worktree's own `lup-dev` first, which is exactly the copy the installed judge exists not to run. `uvx lup-dev` was the other way to reach an installed tool, but where none is installed it fetches a package of that name from the index. Until the operator's first install, the command isn't there, and every runtime treats a hook that fails that way as no decision.
- `.gitignore` gets `.lup/` (already there).
- The typed engine is wired in one place, `cli.engine()`, and built by the installer before the copy is made; the installed package carries the bundle.

**The first install, and checking it live** (the operator's, from the `dev` checkout):
1. `git -C <dev checkout> pull --ff-only origin dev`, then `uv run lup-dev install` from the checkout, in their own terminal: read the review, and approve.
2. `"$(uv tool dir --bin)/lup-dev" --help` lists the commands; `"$(uv tool dir --bin)/lup-dev" rules list` lists the engine's rules.
3. Restart the Claude Code sessions in the repository: a session reads its hooks when it starts. In Codex, trust the project's hooks in `/hooks`.
4. Live checks in a fresh session: ask the agent to create a new module under `packages/lup-dev/src/` with the `Write` tool, which should reach the review dashboard as an ask, settling the check owed on `PermissionRequest`; ask it to add `import re` to an existing module with `Edit`, which should be refused with the report, the file unchanged and the version saved under `.lup/saved/`; ask it to write a docs file, which should pass without a prompt.
5. `lup-dev verdicts` (installed or from the checkout) shows those verdicts.

## Checks owed

- **Auto mode:** whether a `PreToolUse` hook's `allow` skips the classifier. Still open: Claude Code's permission docs say a mod's approval skips it, and nothing about a hook's.
- **A judge's `ask` reaching the dashboard:** whether Claude Code's `PermissionRequest` hook runs for the prompt a `PreToolUse` hook's `ask` causes. Its hooks reference says each half: a hook's `"ask"` "prompts the user to confirm", and "also forces a permission prompt in auto mode"; `PermissionRequest` "runs when Claude Code is about to ask you for permission to use a tool", and its hooks "run only when Claude Code is about to ask you for permission, or when it would otherwise auto-deny a call that can't prompt". It never says the two meet in so many words, so it's inferred from those, and checked live by the operator's first ask after installing (*Installing it here*).
- **The engine:** that it checks content not yet on disk, as pyright's language server does an open buffer. Settled: it opens the file with that content, as an editor's buffer, and puts the disk's back at the next request unless the edit landed (`tests/test_engine.py`, *would-be content*).
- **Holds, settled:** which variables each runtime sets in the commands it runs.
  - Claude Code's environment-variable reference: `CLAUDE_CODE_CHILD_SESSION` is "set to `1` in subprocesses Claude Code spawns via the Bash, PowerShell, and Monitor tools, hook commands, and status line commands", and, unlike `CLAUDECODE`, "only set by Claude Code itself when it launches a subprocess and not by IDE extensions", whose terminals the operator may answer from. Observed in this session's commands.
  - Codex sets `CODEX_THREAD_ID` in every command its agent runs (`codex-rs/core/src/unified_exec/process_manager.rs` at `rust-v0.156.1`, inserted after the shell environment policy, so a profile can't strip it), with `CODEX_CI=1`. Its hooks run with Codex's own environment, without them.
- **Codex, settled:**
  - Its `PermissionRequest` for `apply_patch` carries `tool_input: {"command": <the patch>}` and no file list (`core/src/tools/approvals.rs`). It fires only when the patch needs approval: under `on-request`, a patch writing outside the writable roots, or retried after a sandbox denial; under `never`, never. Inside the workspace Codex doesn't ask, so lup answers nothing and judges at the checkpoint; a patch reaching outside is left to Codex's approval, since lup doesn't judge writes outside the worktree yet. The design's "answered `allow`" would have let those through unjudged.
  - Its hook `timeout` defaults to 600 seconds with no maximum: `timeout_sec.unwrap_or(600).max(1)` (`hooks/src/engine/discovery.rs`); its docs: "If timeout is omitted, Codex uses 600 seconds for most hooks". A timed-out hook fails open.
  - Its payloads (`hooks/schema/generated/*.input.schema.json`): every hook has `session_id`, `cwd`, `hook_event_name`; `PreToolUse` and `PostToolUse` add `tool_name`, `tool_input`, `tool_use_id` and, for a subagent, `agent_id`; `PostToolUse` adds `tool_response`; `Stop` adds `stop_hook_active`. Its shell tool is reported as `Bash`, `apply_patch` as `apply_patch`, a subagent's start as `spawn_agent`.
  - Its `PreToolUse` can't ask: "`permissionDecision: "ask"` … [is] parsed but not supported yet" (its hooks docs), and a plain `allow` fails open (`hooks/src/engine/output_parser.rs`). lup never answers it.
- **Claude Code, settled:** its hooks reference says `PreToolUse` "runs before a tool call executes" and `PostToolUse` "after a tool call succeeds" (`PostToolUseFailure` "after a tool call fails"), each with the call's `tool_use_id`, and that matching hooks "run in parallel". A call's finish never comes before its start, so the in-flight set stays right; parallel calls' hooks overlap, which the file lock covers.
- **Not used:** Claude Code's own record of a command's edits (`bashEditDiff`), which missed files in the probe, a protected one among them.

## Decisions

Each with its alternative and where it lives. **(yours, agreed)** marks what the operator decided; **(yours)** what still waits on them.

1. **(yours, agreed)** Judge state against the last accepted state, at checkpoints. *Alternative:* a snapshot before and after each call. *Where:* `policy/store.py`, `policy/judge.py`.
2. **(yours, agreed)** The checkpoint is "no call running", built from four runtime-neutral events. *Alternative:* `PostToolBatch` on Claude, a lock on Codex. *Where:* `policy/checkpoint.py`.
3. **(yours, agreed)** lup allows, asks or refuses; it never stays silent on a write it judges. *Alternative:* ask, refuse or stay silent, which the operator first agreed and then reversed: the allow is what keeps routine work from interrupting. *Where:* `policy/judge.py`, `adapters/`.
4. **(yours, agreed)** No line count: any production edit the rules pass is allowed unless something asks. *Alternative:* the first lup's 3-line threshold. *Where:* `policy/judge.py`.
5. **(yours, agreed)** `Edit` and `Write` are judged before they land; the checkpoint judges everything else. *Alternative:* the checkpoint for every write, which restores refused edits after the fact. *Where:* `policy/before.py`.
6. **(yours, agreed)** The allow table: tests, scratch, docs and data at any size; production gated by the rules; asks on new or whole-file production writes, protected paths and suppressions. *Where:* `policy/roles.py`, `policy/judge.py`.
7. **(yours, agreed)** `DESIGN.md` and `AGENTS.md` ask. *Alternative:* allowed like other docs and reviewed after. *Where:* `policy/roles.py`.
8. **(yours, agreed)** Where path roles are declared before the declaration piece: a minimal `Project` now, with test roots and protected-path additions. *Alternative:* defaults and pytest's `testpaths` only. *Where:* `policy/roles.py`, `lup_project.py`.
9. **(yours, agreed to try)** Ask on a public-API change: a package root's names, a new class, a changed signature of a definition that existed when the session started. *Alternative:* no public-API ask. *Where:* `policy/surface.py`, the engine.
10. **(yours, agreed)** Every verdict logged from day one, summarized by `lup-dev verdicts`. *Alternative:* reconstruct from transcripts, as the first lup's study had to. *Where:* `policy/verdicts.py`.
11. **(yours, agreed)** You're asked in Claude Code's prompt (or through the interim review hook); Codex holds at the checkpoint. *Alternative:* holds on both runtimes. *Where:* `policy/before.py`, `policy/holds.py`.
12. **(yours, agreed)** The typed engine on pyright's own tree from the first rule, with no syntax-only stage. *Alternatives:* mypy's tree; ruff's `banned-api` plus a syntax checker first. *Where:* `checker/`.
13. **(yours, agreed)** The spike's six questions, as decided above: no tuple types at all, and importers re-checked in one background pass per worktree, waited on at turn end. *Alternative:* importers left to the gate, which could surface a type error after the session. *Where:* `checker/`, `policy/importers.py`.
14. **(yours, agreed)** `# lup:` directives as calls, everything else a note, a wrong directive a finding. *Where:* `codescan/directives.py`.
15. **(yours, agreed)** `defer` carries a required `why`, an `issue`, a `when` naming a `Condition` declared in Python, or both; a closed issue is reported; the ledger's to-do items point at GitHub issues. *Alternatives:* a condition written as a requirement string in the comment; `defer` pointing only at ledger records. *Where:* `codescan/directives.py`, the gate.
16. **(yours, agreed)** Removing a note: free if added this session; reported if committed; through its record once the ledger exists. *Alternative:* the first lup's refusal. *Where:* `policy/judge.py`, `codescan/directives.py`.
17. **(yours, agreed)** The judge runs from a local copy installed from `dev`. *Alternative:* the worktree's own copy. *Where:* the hook commands.
18. **(yours, agreed)** No acceptance guard of its own: tests written as a specification are protected paths a project adds, and read-only mounts in a room. *Alternative:* the first lup's opt-in `acceptance` path role. *Where:* `policy/roles.py` (protected-path additions).
19. **(yours, agreed for now)** Shell commands on the host through narrow allow rules in Claude Code's settings; the prompts the rest causes reach the review dashboard as soon as possible (in the bridge, through the interim hook's `PermissionRequest`). *Alternative:* a lup vocabulary, which needs the shell parser `DESIGN.md` drops. *Where:* `.claude/settings.json`.
20. Content committed elsewhere isn't judged; commits made locally since the previous checkpoint are. *Alternatives:* judge it all, which replays history as new writes; set aside anything equal to `HEAD`, which let a write-and-commit through. *Where:* `policy/store.py`.
21. Findings on touched lines refuse; the refusal lists every finding in the file. *Alternative:* any finding in a touched file refuses. *Where:* `policy/judge.py`, `policy/report.py`.
22. Type errors and ruff's findings are information at each checkpoint and refuse only at turn end. *Alternative:* refuse at the checkpoint, which `DESIGN.md` rules out. *Where:* `policy/judge.py`.
23. A refused new file comes back through `Write`; a refused edit through its saved copy. *Alternative:* hold the moved copy at the checkpoint for the operator, which Claude Code can't prompt for there. *Where:* `policy/before.py`, `policy/report.py`.
24. `lup-dev holds` refuses to answer from inside a session; the real separation waits for containers. *Where:* `policy/holds.py`.
25. **(yours, agreed)** The note is `docs/judging-writes.md`: it judges edits before they land, not only after the call. *Alternative:* keep `docs/after-call-diff.md`.
26. **(yours, agreed)** The judge's own source is reviewed before an installed copy runs, not asked at each edit: refreshing from `dev` shows its diff since the last approved copy, which keeps running until the operator approves. *Alternative:* a protected path asked at every edit, which reviews each step rather than what will run. *Where:* the judge's installer.

Taken while building it:

27. **(yours, agreed)** A runtime is named only in its adapter (`lup_dev/adapters/`): its payloads, tool names, how it hears a report, and the variables it sets in its commands. The core sees a runtime through `Runtime` (its name, whether it asks before a call, whether this process runs inside one of its sessions), and only `cli.py` lists the adapters, which an import contract keeps. A `runtime-mention` rule, for the engine, refuses a runtime's name elsewhere (`docs/conventions.md`). *Alternative:* `hooks/claude.py` and `hooks/codex.py` beside a core that names them. *Where:* `adapters/`, `policy/runtime.py`, `pyproject.toml`.
28. **(yours, agreed)** The default path patterns are data in `lup_dev/catalog/paths.py`, which the operator reviews; `policy/roles.py` holds the matching. *Alternative:* defaults in `policy/roles.py`. *Where:* `catalog/paths.py`.
29. An adapter's variables (`CLAUDE_CODE_CHILD_SESSION`, `CODEX_THREAD_ID`) are its runtime's wire spellings, read by a small settings model in the adapter. *Alternative:* fields of `settings.py`, which would name the runtimes in the core. *Where:* `adapters/`.
30. `.gitignore` is protected. *Alternative:* left unprotected, which lets one shell write hide every later file from the checkpoint. *Where:* `catalog/paths.py`.
31. A `conftest.py` under a test root is a test. *Alternative:* production, since pytest doesn't collect it as a test module, which would gate a suite's fixtures. *Where:* `policy/roles.py`.
32. A source tree is anything under `src/` or in a directory holding an `__init__.py`, where data files are production; `docs/` is the root's. *Alternative:* `docs/` at any depth, which would wave through Python under a package's `docs/`. *Where:* `policy/roles.py`, `catalog/paths.py`.
33. Deleting a protected path or an operator's document asks; deleting anything else is allowed. *Alternative:* every production deletion asks. *Where:* `policy/judge.py`.
34. An approval covers the path's design asks (a new file, a whole write, a public-API change) for the session; a protected path, an operator's document and each `ignore` ask every time. *Alternative:* it covers every ask on the path. *Where:* `policy/judge.py` (`Ask.covered`).
35. Removing a definition or class that existed when the session started doesn't ask; removing a name from a package's root does, as written above. *Alternative:* any removal of a session-start definition asks. *Where:* `policy/surface.py`.
36. A write outside the session's worktree isn't judged; the runtime decides. *Alternative:* refuse it. *Where:* `policy/before.py`.
37. A file tool's write is judged against the accepted content, not the file on disk. *Alternative:* the disk, which would let a command's unjudged write ride in with an edit. *Where:* `policy/before.py`.
38. A call that runs a subagent isn't counted as running; a checkpoint's report waits as mail for every other conversation whose calls finished since the last one; a subagent's end clears its calls. *Alternative:* count the spawn, which would judge a subagent's writes only when it ends, and tell only its parent. *Where:* `policy/checkpoint.py`, `adapters/`.
39. Codex's `PermissionRequest` isn't answered: the design's "answered `allow`" was based on it firing for every patch, and it fires only for patches that need approval (*Checks owed*). *Alternative:* answer `allow`, which would let patches outside the worktree through unjudged. *Where:* `adapters/codex.py`.
40. What's wrong with a directive is reported by the judge as its own findings (`unused-ignore`, `malformed-directive`, `defer-issue`, `defer-condition`, `defer-closed`, `defer-due`), each directive answering for itself through a `Comment` base. *Alternative:* the engine reports them, and the judge dispatches on directive kinds. *Where:* `codescan/directives.py`.
41. At the edit, a conditions module is read without running it; at the gate it's imported. *Alternative:* import it at the edit, which runs a project's code in every hook. *Where:* `codescan/conditions.py`.
42. A closed issue or a condition that holds fails `lup-dev rules check`. *Alternative:* list them without failing, which lets them pile up. *Where:* `cli.py`, `codescan/directives.py`.
43. `PackageReleased` holds for that version or a later final one; `PythonAvailable` reads uv's list of interpreters. *Alternatives:* that exact version; the interpreter running the gate. *Where:* `codescan/conditions.py`.
44. One importers pass per worktree is a lock the pass holds for its life. *Alternative:* its process id checked with `os.kill(pid, 0)`, which kills the process on Windows and is fooled by a reused id. *Where:* `policy/importers.py`.
45. An answer to an ask or a hold is appended as the same verdict under the same key. *Alternative:* log an ask only once answered, which a hook that dies would lose. *Where:* `policy/verdicts.py`.
46. Two suppressions: git's `-z` output split on its NUL separators (`policy/store.py`), and the file tool's own replacement applied with `str.replace` (`policy/before.py`). *Alternatives:* a git library (dulwich, pygit2) for the store, a new dependency; slicing, which another rule refuses. *Where:* those two lines.
47. When judging itself fails, a file tool's write is denied and other calls go on, told; a turn's end is blocked once. *Alternative:* a crash, which a runtime treats as no decision, letting a write meant for review through. *Where:* `adapters/`.
48. **(yours, agreed)** Codex hears a report through `additionalContext`, as Claude Code does. *Alternative:* `decision: block`, which replaces the call's result, so lup repeated the original output before the report. *Where:* `adapters/codex.py`.
49. **(yours, agreed)** `lup_dev` is grouped by subsystem: `codescan/`, `policy/`, `adapters/`, `catalog/`, with package-wide modules at the root (`docs/conventions.md`, *Package layout*). An import contract keeps `adapters` > `policy` > `codescan` > `catalog`. *Alternative:* the flat package of 21 modules. *Where:* `packages/lup-dev/src/lup_dev/`, `pyproject.toml`.
50. **(yours, agreed)** A rule is one entry in one TypeScript table, holding its mistake, its steer and its check, which reads pyright's tree through the engine's helpers. *Alternatives:* a vocabulary of matchers declared in a Python catalog, which spread a rule across the vocabulary and the engine; Python rules over `ast` asking the engine by position, which a spike found needs two trees to agree and missed types pyright reads in strings. *Where:* `catalog/rules.ts`, `checker/src/`.
51. **(yours, agreed)** The table lives in `catalog/`, protected with lup's other policy data, and imports the engine's helpers through a path alias. *Alternative:* the table beside the engine in `checker/src/`, outside the protected catalog. *Where:* `catalog/rules.ts`, `checker/tsconfig.json`.
52. **(yours, agreed)** Python learns about rules only from the engine: complete findings, and the list of rules the engine reads from its table. *Alternative:* a `rules.json` compiled from the table for Python, dropped as one more generated file Python doesn't need. *Where:* the engine, `codescan/engine.py`.
53. **(yours, agreed)** `docs/rules.md` is the one generated, committed file, compiled from the table, with a gate test failing when it's stale; the engine's bundle is never committed. *Alternative:* a hand-kept table in `docs/conventions.md`. *Where:* `docs/rules.md`, `codescan/`.
54. **(yours, agreed)** A rule's examples are code in its entry: `flags`, each with its `rewritten`, and `passes`, its near misses. The engine's tests run them all: each of `flags` fires its rule and no other, each `rewritten` passes every rule, ruff and pyright, each of `passes` gets no finding from its rule, and every rule has one of `flags`. *Alternative:* example files by rule id (`catalog/examples/<id>/flagged.py`, `fixed.py`), which held one case per rule and needed ruff, pyright and pytest told to leave them out. *Where:* `catalog/rules.ts`, `tests/test_engine.py`.
55. **(yours, agreed)** Selection and exemptions are the project's declaration's; the table holds no project's exemptions. *Alternative:* exempt modules on each rule's entry. *Where:* the declaration piece; `lup_project.py` until then.
56. **(yours, agreed)** A protected Python module gets lup's rules as production code does, and still asks: a finding refuses it, a clean change asks (#14). Nothing is exempted, since the rules' examples are moving into the table as strings. *Alternative:* protected wins and the rules don't apply, which left `catalog/` checked by review and the gate's ruff and pyright alone. *Where:* `policy/roles.py` (`ruled`, `checked`), `policy/judge.py`, `policy/checkpoint.py`, `cli.py`.
57. The engine is built, never committed: `packages/lup-dev/checker/build.py` reads the pinned pyright from `uv.lock`, fetches its source once into `$XDG_CACHE_HOME/lup/pyright/`, type-checks and bundles the engine with esbuild (the engine's one npm dependency), and copies the stubs beside it into `lup_dev/codescan/bundle/`, which git ignores and the wheel carries. *Alternative:* commit the bundle and its 31 MB of stubs, so a fresh checkout needs no build, at the cost of every pyright upgrade landing as a large binary diff. *Where:* `checker/build.py`, `layout.py` (`Bundle`).
58. **(yours, agreed)** pyright's warnings are reported like its errors: information at each checkpoint, clean at the turn's end, and the gate runs `pyright --warnings`. *Alternative:* errors only, the pyright CLI's exit status. *Where:* the engine (`report.ts`).
59. One engine per worktree on a Unix socket, started by the hook that finds none under a lock, stopping after `LUP_ENGINE_IDLE` (15 minutes by default) or for a client expecting another build, which is told apart by the bundle's size and modification time. *Alternatives:* a TCP port, which any local user could reach; an engine per hook, which reloads the project each time (1.4 s on this repository). *Where:* `codescan/engine.py`, `checker/src/server.ts`, `settings.py`.
60. The importers pass runs a file at a time, and a check waiting behind it runs between two files; a check that changed the disk makes the pass look again. *Alternative:* the pass whole, which on the first lup's library held a check behind 27 seconds of re-checking. *Where:* `checker/src/engine.ts`, `checker/src/server.ts`.
61. **(yours, agreed)** `Project.excluded`: paths held to nothing, with their own role after the operator's documents. A path both protected and excluded stays protected and asks, without rules or findings. *Alternative:* exclusion before protection, which would let a write to an excluded hook land unasked. *Where:* `project.py`, `policy/roles.py`; `lup_project.py` excludes `.claude/hooks/**`.
62. **(yours, agreed)** The installer shows everything the installed judge carries since the commit approved last, asks, installs and records the commit; declined, the copy before keeps judging. *Alternative:* review at each edit of the judge's source (decision 26). *Where:* `install.py`, `lup-dev install`.
63. The installed copy's dependencies are held to `uv.lock` by constraints exported from it, since `uv tool install` resolves a tool afresh. *Alternatives:* let it resolve, which ran newer versions than the gate's on the first trial; `uv tool install --with-requirements`, which adds rather than constrains. *Where:* `install.py` (`Uv.install`).
64. The installer refuses inside an agent's session, and when the judge's source has changes not committed. *Alternative:* trusting whoever runs it, which would let an agent approve the judge that judges it, or install source the review didn't show. *Where:* `install.py`.
65. The hooks run `"$(uv tool dir --bin)/lup-dev"`. *Alternatives:* `lup-dev` on the `PATH`, which an activated worktree environment shadows with its own copy; `uvx lup-dev`, which fetches from the index where none is installed. *Where:* `.claude/settings.json`, `.codex/hooks.json`.
66. The interim review hook carries prompts to the dashboard, on `PermissionRequest` and `PostToolBatch`, and its own write review is no longer registered; its code for it stays while sessions started with the old settings run. *Alternative:* removing that code now, which would block every write in those sessions. *Where:* `.claude/settings.json`, `.claude/hooks/interim_review.py`.
67. The narrow `Bash` allow rules are the gate's commands and read-only git. *Alternative:* the note's four examples only. *Where:* `.claude/settings.json`.
68. `Project.exempt` lifts one rule from the paths its patterns match, each with its reason, applied where findings are kept: the judge's `kept` and `lup-dev rules check`. The turn's end reports only pyright's and ruff's findings, so it has nothing to lift. *Alternatives:* a selection sent to the engine per file, which would make the engine read the declaration; the declaration piece's full selection grammar, which is that piece's to design. *Where:* `project.py`, `policy/roles.py`, `policy/judge.py`, `cli.py`; `lup_project.py` exempts the library's front door from `runtime-mention`.
