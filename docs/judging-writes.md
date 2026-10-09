# Judging every write: allow, ask or refuse

**One sentence:** lup judges every write in the worktrees of an agent's repository. An `Edit` or `Write` is judged before it lands, on the content it would produce. Anything else (a command, a script, a background process, Codex's `apply_patch`) is judged at the next checkpoint, by comparing each worktree with the last state lup accepted for it. Each change is allowed, asked of the operator, or refused.

This is the first piece of `DESIGN.md`'s build order, built alongside the library. It's the review workflow, and every call goes through it. It covers:
- the three outcomes, and what each kind of change gets;
- judging `Edit` and `Write` before they land;
- the checkpoint and its snapshot store, for everything else;
- which worktrees of the repository a session's writes are judged in, and a move of `HEAD` (a commit, a merge, a checkout) judged once, as a commit's;
- asking the operator: in Claude Code's own prompt, and through holds where a runtime can't ask;
- refusals, which report every finding at once and save the agent's version;
- the typed engine and the code rules (the conventions they enforce are in `docs/conventions.md`);
- type errors and ruff's findings as information at each checkpoint;
- the `# lup:` directives: `ignore`, `defer`, notes, and removing a note;
- tests written as a specification, expressed with protected paths and mounts;
- the verdict log;
- the hooks for Claude Code and Codex, and installing them in this repository.

Later:
- answering in the dashboard (until then, Claude Code's prompt, the terminal, and the interim review hook, which queues prompts in the first lup's dashboard; the installer parks the judge's own review there too, *Where things live*);
- keeping the store out of the agent's reach, and refusing reads of secrets, which come with launch and containers;
- edits a session makes in another repository, which come with launch and spawn;
- a shell write into a worktree of the repository the session never reached, and on Codex every write outside the worktree the session started in, which close with rooms, whose mount is the worktree (*Every worktree of the repository*).

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

A deleted file asks where it's protected or one of the operator's documents, and is otherwise allowed: the public-API ask covers what other code loses. A write is judged in the worktree of the session's repository that holds it, by that worktree's roles under the declaration at the integration branch's tip (*Every worktree of the repository*); a write outside the session's repository isn't judged here, and edits in another repository come with launch and spawn.

**Where a project declares its roles:** a minimal `Project` starts in this piece (`lup_dev/project.py`), with only the fields it reads: its test roots, its additions to the protected paths, the paths it excludes, the rules it lifts from some paths, and the module declaring its conditions, shaped as `DESIGN.md`'s example (`Project(tests=[Pytest(root=…)], protected=Protected.default().add(…), excluded=[…], exempt=[Exemption(rule=…, paths=[…], why=…)], conditions="pkg.conditions")`). An exemption lifts one rule from every file its patterns match, with the operator's reason, where an `ignore` keeps one finding out on its line; the judge and `lup-dev rules check` leave out an exempt rule's findings, and every other rule still holds there. `excluded` is the settled part of `DESIGN.md`'s open question 8; compiling the declaration into the tools' own settings (ruff's and pyright's exclusions among them) is the declaration piece's. It's loaded from `[tool.lup] project = "pkg.module:project"`, importing from the root, its `src/`, and each uv workspace member and its `src/`, since the judge runs from its own installed copy; without one, the defaults apply, and one that can't be loaded is never silently replaced by the defaults (*The declaration, from the integration branch*). The judge reads it, and the `[tool.lup]` naming it, from the integration branch's tip, never from the worktree being judged; the gate reads the worktree's own. The declaration piece grows it.

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

The file's worktree is the one its path is in, which git names (*Every worktree of the repository*). The hook (`PreToolUse`) runs the judgement on that content: the path's role, the code rules through the engine, the public-API comparison, the directives added or removed. It answers allow, ask or refuse. A refused edit never touches the file. The engine checks content that isn't on disk the way pyright's language server checks an unsaved buffer (a check owed below).

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

**A checkpoint runs whenever a call finishes and no other call is running,** and again when the turn ends. It runs in each worktree the session holds, once no call counted there is running (*Every worktree of the repository*). Parallel calls are judged together once the last one finishes; a late background write is judged at the next checkpoint. The checkpoint is before the agent's next model request, so a refusal reaches the agent before it writes its next line.

**Subagents.** A call that runs a subagent (Claude Code's `Agent`, Codex's `spawn_agent`) isn't counted as running: its subagent's own calls are, so a subagent's writes are judged as it makes them, and the report goes to the subagent whose call finished. The checkpoint sees files, not authors, so its report also waits, as mail, for every other conversation whose calls finished since the last checkpoint, and reaches each at its next finished call or the end of its conversation. A subagent's end clears its own calls and runs a checkpoint if none is left running; the turn-end checks are the session's.

**It degrades gracefully:**
- a "finished" with no matching "started" leaves the running calls as they are (Codex's `write_stdin` can deliver the original command's `PostToolUse` without a `PreToolUse` of its own), and still runs a checkpoint if no call is running;
- a call that never reports finishing is cleared when its conversation's turn ends, and the turn-end checkpoint judges everything anyway. Claude Code reports no event for a call the operator declined at its prompt, so a declined call stays counted until the turn ends: harmless, but it holds back the checkpoints of that turn;
- the in-flight calls are kept per worktree under a file lock, since hooks for parallel calls run concurrently, each call with its session and its conversation, so a turn's end clears its own session's calls and no other's. (Before calls recorded their session, a turn's end cleared every session's own-conversation calls in the worktree.)

**How a checkpoint goes,** in each worktree it runs in:
1. **Snapshot.** The worktree is written into lup's own store as a git tree (a private index, `git add -A`, `write-tree`). Ignored files are left out, as `.gitignore` says. The store is a bare repository outside the worktree, and git runs with `core.fsmonitor` and hooks turned off: the effects probe saw a planted `core.fsmonitor` run inside a call.
2. **Compare** with the accepted tree (`git diff-tree`). Nothing changed is the common case after a read.
3. **Set aside what was committed elsewhere.** A changed file whose new content equals its content in a commit that existed at the previous checkpoint, or that arrived from a remote since, isn't judged: that's what a checkout, a pull, a merge, a stash or a `git restore` produce, and that content was judged where it was written. The content git's merge makes from such commits isn't judged either: a merge whose two sides both changed a file writes content no commit held, made from content judged on each side. A file with conflict markers matches no commit, so it's judged, and so is a resolution written by hand.
   - **How:** the commits are those the repository's refs and the worktree's `HEAD` named at its previous checkpoint, the `HEAD` each other worktree of the repository had at its own last checkpoint (kept per repository, beside the verdict log), and the remote-tracking refs now; `git log --find-object=<blob> <those commits> -- <path>` says whether any of their history holds that content at that path. For a merge (a `HEAD` reached since the last checkpoint with more than one parent, or a merge in progress), `git merge-tree --write-tree` of its parents remakes git's clean merge, and a file equal to its result is set aside when both parents are in the history of those commits; the paths it couldn't merge are judged, and a merge of more than two commits isn't remade (`policy/store.py`, `Elsewhere`). A deletion is set aside when `HEAD` lacks the path and was one of those commits (a branch switch), or when the remade merge lacks it.
   - **Why merges:** before they were remade, replayed against the judge with the tests' stub engine, a branch adding a class to a file both sides had changed was merged with `git merge`, and the checkpoint after it refused the merged file as a public-API change made through the shell, leaving the working tree different from `HEAD`. That's #22's harm with no checkpoint missed.
   - **A gap:** a remote-tracking ref also moves when the agent pushes, so one call that writes a file, commits it and pushes it is set aside like a pull. Telling a fetch from a push needs the reflog's messages; the hole is narrow while pushes run on the host, and closes with containers, where pushes go through a host service.
4. **Judge a move of `HEAD` once, as a commit's.** The worktree's `HEAD` is recorded at each checkpoint, and when a session begins there, in the repository's record of each worktree's `HEAD` (`heads.json`, beside the verdict log), which step 3 reads for the other worktrees. When it has moved (a commit, a merge, a pull, a checkout, a reset), the files the move changed whose content on disk is the new `HEAD`'s were put there by git, not typed: they're the move's, not the session's. What step 3 didn't set aside of them is content first written in a commit made since the last checkpoint: shell writes committed in the same call, a resolution committed through the shell, commits made while the judge couldn't run (#21). That is judged once, against the accepted content before the move, with no session's approvals, and it's:
   - **never put back:** putting it back leaves the working tree different from `HEAD` (#22), and protects nothing, since the next `git restore` brings the content back unjudged, the commit being among the tips by then. Replayed against the judge before this was built: a new module written and committed in one call was refused and removed, and the `git restore` that followed was accepted silently;
   - **attributed to no session:** its verdicts are logged without one, with `move` for their tool, since the checkpoint can't tell who committed;
   - **told as a commit's** to the conversations whose calls finished since the last checkpoint, naming the commit `HEAD` moved to, each file with lup's findings on the lines the commits touched, what it asks and the notes it removed. Its findings fail the gate before the branch lands; its asks are kept for the operator as one hold no agent waits on (*Asking the operator*).

   A file changed again after the move is judged in two steps, the move and then the rest against `HEAD`'s content, so the session isn't asked about what the commit brought; a refused rest goes back to `HEAD`'s content, since the move is accepted. Nothing is judged as a move where no `HEAD` was recorded for the worktree yet (a store kept by an earlier judge, until its first checkpoint), or where `HEAD` names no commit now.
5. **Judge** every remaining change exactly as an edit is judged before it lands: role, rules, public API, directives. Content judged before it landed (a file tool's write whose call finished, a hold the operator approved) is accepted as it is; changed since, it's judged from that content.
6. **Refuse** what the table refuses, and what bypassed an ask: on a runtime that asks before a call, a new production file, a public-API change, a suppression, a protected path or an operator's document changed through the shell and not committed (committed, it's the move's: step 4) is refused with a pointer to the file tools, so it comes back through the prompt. That enforces `AGENTS.md`'s "create files with your file tool". On a runtime that can't ask before a call, it's held instead (*Asking the operator*).
7. **Act:** a refused file goes back to its accepted content, or is removed if it was new, and the agent's version is saved. What's left becomes the new accepted tree.
8. **Report** to the agent, once: everything refused, then what a move brought, then type errors and ruff's findings as information.

The accepted tree starts as a snapshot when a session starts, or first reaches a worktree, and the worktree's `HEAD` is recorded with it. If a stored accepted tree already exists for the worktree, the difference happened while no session ran there: the operator's work or a pull. It's accepted without judging, unless a call is running there: then another session is at work in it, so the accepted tree stays, the session's starting tree there is that accepted tree, and that call's checkpoint judges what it writes. (Before this, a session's start accepted the worktree as it stood even while another session's call ran there.) A session that starts again (resumed, cleared or compacted) begins again in every worktree it holds.

**Someone else's edit during a session** can't be told apart from the agent's: the checkpoint sees files, not authors. An edit the operator makes in a worktree a session holds is judged as the agent's, and if refused it's put back with the version saved, so nothing is lost. The operator works in a worktree no session reaches, or between sessions.

**Cost**, for each worktree the session holds:
- one snapshot per checkpoint. Measured for #20 through the store's own code: 70 to 100 ms where nothing changed, about nine git processes, of which the snapshot is 5 ms at lup's size and 10 to 15 ms at nori's 4,000 files; a worktree's first snapshot takes 40 to 50 ms at lup's size and 2.5 to 3.6 s at nori's. The effects probe's figure was about 50 ms; the existing projects have 161 to 3,721 tracked files;
- where nothing changed, the checkpoint stops at the snapshot: no comparison when the snapshot is the accepted tree, no declaration loaded, nothing rewritten, `HEAD` and the refs read once each. Measured as built, a call's start and finish where nothing changed, with the tests' stub engine on a clone of this repository (97 files): 52 ms and 8 git processes with one worktree held (the judge before #20: 109 ms, 17), 148 ms and 20 with three, a checkpoint alone 37 to 43 ms;
- once for each commit of the integration branch, exporting its declaration: 77 ms for this repository's tip, then 1 ms to load it;
- plus the engine's incremental re-check of the changed files;
- target: under 300 ms per checkpoint on this repository, type check included, for a session holding one or two worktrees.

## Every worktree of the repository

Built for #20 (`policy/worktrees.py`). A session starts in one worktree and often works in others. In this repository each branch is its own worktree (`tree/<branch>`), so a session started in `tree/dev` writes in `tree/feat-…`, and its workers write in theirs. Before this, the judge looked only at the worktree a session started in, so most of that work went unjudged: a protected module, the whole rule table and a `.claude/` hook all reached `dev` without the operator's review. The store, the roles and the verdict log were already per worktree or per repository, so what changed is how the worktree is found, not how a write is judged.

**The session's repository.** When a session starts, lup reads its repository from its working directory: git's common directory (`git rev-parse --git-common-dir`). A worktree names it, and so does a bare repository's own directory (checked at `lup.git/` and `lup.git/tree/`), so a session started there is judged too, holding no worktree until it reaches one. A session started outside any repository isn't judged, until a later hook's working directory is in one. The session index keeps the repository and the worktrees the session holds, under a lock its parallel hooks share; a worktree is begun inside that lock, so a parallel hook never finds it half begun. A worktree whose root is gone (`git worktree remove`, as landing a branch does) isn't held: there's nothing in it to judge, and a checkpoint can't enter it.

**A write's worktree, from its path.** For an `Edit` or a `Write`, lup asks git from the file's nearest directory that exists: `--show-toplevel` names its worktree, `--git-common-dir` its repository.
- In a worktree of the session's repository, it's judged there, by that worktree's accepted content and roles, under the integration branch's declaration.
- In another repository, or in none, it isn't judged, and the runtime decides, as now. A repository nested inside a worktree is another repository: git says so, and the checkpoint's snapshot doesn't see inside it either.
- In the repository's own git directory, which in a layout like this one sits outside every worktree (`lup.git/config`, `lup.git/hooks/`, `lup.git/worktrees/`), it asks, as `.git/` does inside a worktree: those files run outside the agent's reach. No snapshot covers that directory, so only the file tools' writes there are judged. Its verdict names the git directory where a worktree would be, and no store keeps the write until its call finishes, so its answer isn't logged.

**The worktrees a session holds:**
- the worktree it started in;
- each worktree one of its file tools writes in;
- each worktree a hook reports as its working directory. Claude Code's hooks reference: "`cwd` follows Claude: the `cwd` field in the hook's input JSON is the worktree root after Claude enters a worktree, and the new directory after Claude runs `cd`." So after a `cd ../feat-x` in the session's own conversation, the next hook holds `feat-x`.

A subagent's hooks carry its session's id, so a worker's worktree is held by the session that started the worker. Reaching a worktree begins the session there as a start does: the accepted tree becomes the worktree as it stands (unless a call is running there), and the session's starting tree there is recorded, which the public-API ask and removed notes compare with.

**Which worktrees a checkpoint looks at.** Three options, costed with the figures above (*Cost*). This repository has 3 worktrees, nori 36 and the first lup 79.

| Option | Cost per checkpoint | What it judges |
|---|---|---|
| Every worktree of the repository | ~80 ms for each worktree: 0.25 s here, ~3.5 s on nori; and the first checkpoint that sees a worktree pays its first snapshot, 2.5 s each at nori's size | Everything, but also the operator's own worktree and other sessions' worktrees, as this session's writes. And the calls counted must span the repository, so one session's long call holds back every other session's checkpoints |
| The worktrees the session holds | ~80 ms for each held worktree, usually one to three: today's cost for a session in one worktree | Every file tool's write, and every shell write into a worktree the session reached; not a shell write into a worktree it never reached |
| Those changed since their record | The same as every worktree: knowing that a worktree changed takes the snapshot's pass over its files, and once that pass is done the snapshot costs almost nothing more | The same as every worktree |

**Lean: the worktrees the session holds.** It costs a session in one worktree what it costs now, never judges the operator's worktree or another session's, and covers what went unjudged in #20: file tools' writes in other worktrees, and shell writes where the session works.
- **The gap:** a shell write into a worktree the session never reached (no file tool there, never its working directory) isn't judged, and is accepted when a session next reaches that worktree. `AGENTS.md`'s "create files with your file tool" makes a session's first write in a worktree a file tool's. Rooms close the gap: a room's mount is its worktree.
- **On Codex** a session holds only the worktree it started in. Its hooks' `cwd` is the "Working directory for the session", and its `Bash` and `apply_patch` carry only `tool_input.command` (its hooks docs), which lup doesn't parse. Under its `workspace-write` sandbox a write elsewhere lies outside the writable roots, so Codex's own approval decides it, and lup doesn't judge it. That's the declared gap on Codex until rooms. A project that adds its other worktrees to the writable roots widens it, and so does running Codex without its sandbox (`danger-full-access`), where such a write lands unasked and unjudged.
- **The alternative worth weighing:** add a sweep of every worktree at the turn's end to the held ones. It catches shell-only writes on both runtimes, once per turn, where the turn's end already waits for the importers pass. Its price is the first one's: the operator's uncommitted work in any worktree is judged as the agent's.

**One checkpoint per worktree.** A call counts in every worktree its session holds when it starts. When a call finishes, a checkpoint runs in each worktree the session holds where no counted call is still running, one after another, and the agent hears their reports together. The turn's end runs over every worktree the session holds: the checkpoint, the importers pass, the type errors and ruff's findings left in what it touched, and the notes removed, each file named in full.

**What's kept where:**

| What | Kept | What it holds |
|---|---|---|
| The store: snapshots, the accepted tree, the state (commits seen, saved versions, files held) | per worktree | As before #20 |
| Each worktree's `HEAD` at its last checkpoint | per repository, beside the verdict log (`heads.json`) | Read by every worktree's checkpoint: its own, to see `HEAD` move (step 4), and the others', as commits judged (step 3) |
| A session's record: approvals, files touched, writes pending, content judged, notes removed, mail | per worktree, per session | A session has one in each worktree it holds; an approval covers the path in its worktree only |
| The calls running | per worktree (`running.json`) | Each call records its session; it counts in every worktree its session holds |
| Saved versions | `<worktree>/.lup/saved/` | As before |
| Holds | per worktree's store | A checkpoint over several worktrees can make a hold in each, waited on one after another; a move's hold names its commit, and keeps the verdicts its answer is logged against |
| The importers pass | per worktree | The turn's end waits for the pass of every worktree the session holds |
| The engine | per worktree | A session writing Python in several worktrees runs an engine in each, each 1.5 to 2.7 GB on a 700-file project (the spike), until it's idle |
| The declaration | the integration branch's tip, one for the repository | Below; loaded when a checkpoint or a write first needs it, not for a call's start or finish alone |
| The verdict log | per repository | Each verdict names its worktree |
| The session index | per session (`session-index/<session>.json`) | The repository and the worktrees held |

**State an earlier judge wrote.** The session index and the calls running changed shape, so they moved to new files (`session-index/`, `running.json`); the earlier ones (`sessions/<session>.json`, each store's `calls.json`) are left unread. A session running when the judge is reinstalled is picked up from its next hook's working directory, its starting tree and its record in each store kept; a call in flight then is forgotten, so its finish is a finish with no start. A store has no `HEAD` recorded until its first checkpoint, so a commit made before that isn't judged as a move. A verdict line without a worktree reads with none, and a hold without a commit as one an agent waits on, which is what each was.

**The declaration, from the integration branch.** Every worktree of a repository is judged by the declaration committed at the integration branch's tip (`dev`, the setting `LUP_INTEGRATION_BRANCH`), never by the worktree's own. The judge's code already comes only from the installed copy, so a branch can't change what judges it; the declaration now holds the same way. A branch's edits to `lup_project.py` take effect when they land on `dev`, as rules take effect when the operator installs them; a branch that needs a declaration change lands it first, as a hotfix on `dev`. An uncommitted edit in the `dev` worktree takes effect when it's committed. A repository without a branch of that name is judged, worktree by worktree, by the declaration each one's `HEAD` commit holds, and by the defaults before its first commit.
- **How a commit's declaration is imported:** the commit's Python modules and its `pyproject.toml` files (`git ls-tree`, then `git archive` of those paths) are exported once, into the repository's state (`declarations/<commit>/`), written whole before they're moved into place; earlier commits' exports are removed. The declaration and `[tool.lup]` are read from there, importing from the export's root, `src/` and workspace members as from a worktree's, and the conditions module it names is read there too: the declaration and what it names come from one commit. Python keeps a module once it's imported, and every declaration is the module `lup_project`, so loading one drops from `sys.modules`, once it's loaded, the modules it imported from where it was read (`project.py`, `importable`; before that, two worktrees' declarations loaded in one process both came back as the first's); finding a conditions module, which imports its parent packages, does the same. Neither writes bytecode: a `__pycache__/` the judge left in a worktree that doesn't ignore it would be judged at the next checkpoint as the session's new file.
- **The gate reads the worktree as it stands** (`lup-dev rules check`, and `Worktree.at`): it checks a branch as it would land, uncommitted edits to its declaration included, and takes no stand-in.
- **The roles' pytest configuration** (test roots read from each `pyproject.toml`) stays the worktree's own: it's pytest's configuration, a protected path, not lup's declaration.

**A declaration that can't load has a stand-in** (#21). After a branch that adds a field to the declaration lands, `dev`'s declaration uses the field before the installed judge knows it, until the operator reinstalls. So each declaration that loads is kept, per repository (`declaration.json`, beside the verdict log), and where the one due can't load, whatever its import raises, the last that loaded judges instead: the field takes effect at the next install, and nothing locks up meanwhile. The agent is told once for each failure, with the error, the commit that failed and the one standing in, to pass on to the operator; reinstalling the judge from `dev` is usually the fix. With nothing kept the failure stands, and the gate never takes a stand-in: there, a declaration that can't load fails.

**When judging fails at a turn's end** (#21), the turn ends anyway: the agent can't fix the judge. The operator is warned once for each failure in a session, in the runtime's warning to the user (`systemMessage` on both runtimes), which doesn't continue the turn; anything a `Stop` hook tells the agent continues it.

**Reports name each file in full.** A session hears about several worktrees, from any working directory, so reports name each file by its absolute path, as pyright's command line does, and the `mv` that puts a saved copy in place names both ends in full. So does each ask, in the runtime's prompt and in a hold. The verdict log keeps paths relative to the worktree it names.

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

**A move's asks, after the fact.** What a move of `HEAD` asks (step 4 of the checkpoint) is already committed, and it isn't put back, so on both runtimes it's kept as a hold that no agent waits on. `lup-dev holds` lists these apart from the holds an agent is waiting on, with the commit and the diff. An answer is logged when it's given, against the verdicts the hold keeps, and reaches the session that found the move at its next checkpoint, as a late answer does. A decline changes no file: reverting the commit is the operator's, or an agent's at their word. A late answer to a hold whose wait ran out is logged the same way, when it's given.

**Nobody answers their own hold.** `lup-dev holds approve` and `decline` refuse to run when their environment shows they run inside an agent's session: Claude Code's `CLAUDE_CODE_CHILD_SESSION`, Codex's `CODEX_THREAD_ID` (*Checks owed*, settled). Each adapter reads its own runtime's variable. That stops a mistake, not a determined agent: in the bridge the agent runs as the operator's user and could write the answer itself. The real separation comes with containers, where the hold store sits outside the container and answering runs only on the host.

## Refusals

The refused file goes back to its accepted content, or never changes if it was refused before landing. The agent's version is saved under `.lup/saved/<n>/<path>` in the worktree (`.lup/` is ignored, so saved copies are never judged). The agent fixes the listed lines there and moves the file into place; nothing is resent whole, except a new file, which goes back through `Write` and its prompt.

The report, in pyright's shape:

```
lup refused 1 file. It is unchanged; your version is saved.

/work/lup/src/lup/claude.py (saved at /work/lup/.lup/saved/3/src/lup/claude.py)
  /work/lup/src/lup/claude.py:41:12 - tuple-shape: a fixed-length tuple[str, int] hides what each position means
      steer: name the fields with a pydantic model
  /work/lup/src/lup/claude.py:88:5 - regex: `import re` parses with a regular expression
      steer: use the format's own parser (lup docs rules regex)

Fix these lines in the saved copy, then move it into place:
  mv /work/lup/.lup/saved/3/src/lup/claude.py /work/lup/src/lup/claude.py
To keep a finding, add on its line or the line above (the operator is asked):
  # lup: ignore("<rule>", why="<reason>")
```

Each path is absolute, the `mv` naming both ends in full, since a session's writes are judged in several worktrees and the agent's working directory may be any of them (*Every worktree of the repository*); so is each path an ask names. The example changes with the code: `tests/test_report.py` checks the two agree.

**Which findings refuse.** Findings on the lines the change touched; for a new file, every line. The refusal lists every finding in the file, so one pass fixes them all: the art studio's agent resent a 550-line file four times, once per rule. Findings on untouched lines are listed under their own heading and don't refuse; they exist only where a rule is newer than the code.

## Type errors and ruff's findings

They're information, not refusals (`DESIGN.md`: "information never travels on a blocking channel"):
- at each checkpoint, pyright's type errors and warnings and ruff's findings in the files changed, test files included, as plain context beside the call's result; with them, lup's findings on lines no change touched, and the type errors the background pass found in the files importing what changed;
- when the turn ends, the `Stop` hook refuses to end it while files touched this session, or files importing them where the pass found errors, have type errors, warnings or ruff findings, saying which;
- the formatter runs when work lands, with ruff's safe fixes (below).

ruff runs with `--ignore-noqa`, and pyright with `enableTypeIgnoreComments = false`; lup filters both through its own `# lup: ignore`, so there's one suppression syntax (`docs/conventions.md`). ruff is the project's own (`.venv/bin/ruff`) where it has one, run on the would-be content through stdin under the file's name, so the project's configuration applies (`codescan/ruff.py`).

**A finding ruff fixes safely is never reported to the agent:** not as information at a checkpoint, not at the turn's end. ruff's JSON output gives each finding's fix with its applicability, and `ruff check --fix` applies only a `safe` one, so those are the findings marked `fixable` (`codescan/ruff.py`); one whose fix is `unsafe` or display-only, or that the configuration makes unfixable (ruff gives no fix then), is reported as before. Fixing them is the landing session's job: `lup-dev check --fix` applies ruff's safe fixes and runs the formatter before the gate's steps, and the landing step in `AGENTS.md` runs it on the merged result. CI, and the gate run without `--fix`, only check, so a fixable finding still fails the gate until it's fixed. The judge never rewrites a file under the agent. A fixable finding still counts for the `ignore` naming it, which isn't reported unused; `--fix` applies the fix anyway, since ruff doesn't read lup's `ignore`.
- **Why:** a fix ruff makes safely is a mechanical rewrite that changes nothing a reader decides; told one by one, they spent an agent's turns (#33).

**At the gate, `lup-dev rules check`** checks every Python file as the turn's end does, and fails on any finding: lup's (production only; tests are exempt), pyright's, ruff's, each through `# lup: ignore`, and each deferral whose issue is closed or whose condition holds. Since ruff and pyright alone don't read lup's `ignore`, this is the check that decides whether a finding is kept. It reports fixable findings too, as the gate's `ruff check` does.

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
- time, session, runtime; a move of `HEAD` is logged with no session (checkpoint, step 4);
- the tool, `checkpoint`, or `move`;
- the worktree, and the path in it with its role; a write in the repository's git directory names that directory instead, and a line logged before verdicts named their worktree reads with none;
- the outcome (allow, ask, refuse, hold) and its reasons (the rules that refused, the kinds of ask, or the role that allowed: `rules-pass` for production);
- the operator's answer, when there is one.

It's kept per repository, beside the store. An answer comes after its verdict (when the asked call finishes, or a hold is answered), so it's appended as the same verdict again under the same key, and a reader takes the last line for each key. `lup-dev verdicts --days 7` summarizes it by outcome and reason, with how asks and holds were answered. The first lup had no such log, and measuring its verdicts meant reconstructing them from transcripts.

## The two runtimes

| | Claude Code | Codex |
|---|---|---|
| `Edit`/`Write` judged | before they land (`PreToolUse`) | no such tools: `apply_patch` judged at the checkpoint |
| Worktrees a session holds | where it started, where its file tools write, where its hooks report its working directory, which follows `cd` | where it started; under its `workspace-write` sandbox a write elsewhere is outside the writable roots, and Codex's own approval decides it |
| Checkpoint events | `PreToolUse`, `PostToolUse` (and `PostToolUseFailure`), `Stop`, `SubagentStop` | `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop` |
| allow | `PreToolUse` answers `allow` | nothing to answer: Codex doesn't ask for `apply_patch` inside the workspace |
| ask | `PreToolUse` answers `ask` | held at the checkpoint, answered from the terminal |
| refuse | `PreToolUse` answers `deny`, or put back at the checkpoint | put back at the checkpoint |
| How the agent hears | `additionalContext` beside the result | the same: `additionalContext` beside the result, which reaches the agent untouched |
| When judging itself fails | a file tool's write is denied, naming the failure; other calls go on, told; a turn ends, the operator warned once in `systemMessage` | the agent is told beside the call's result; a turn ends, the operator warned once in `systemMessage` |
| Its sessions' commands carry | `CLAUDE_CODE_CHILD_SESSION=1` | `CODEX_THREAD_ID` |
| Configured in | `.claude/settings.json` | `.codex/hooks.json`, run only once its hash is trusted, so the operator trusts it after each change (in Codex's `/hooks`; there's no command for it) |

On Codex a refused `apply_patch` lands for the moment between the call and the checkpoint; on Claude Code a refused `Edit` never lands. That's the declared difference.

Both runtimes hear a report the same way. Codex's docs say a `PostToolUse` hook's `additionalContext` "is added as extra developer context". Past the handler's `additionalContextLimit` (2,500 tokens by default), Codex keeps the whole text in a file and shows a preview pointing at it, so the hook configuration raises the limit for reports to arrive whole.

## Where things live

| What | Where | Why there |
|---|---|---|
| The store: snapshots, the accepted tree, in-flight calls, holds, refusals, each session's record there | `$XDG_STATE_HOME/lup/worktrees/<id>/`, one per worktree, outside it | The restore source must be out of the agent's reach. In the bridge it isn't, since the agent runs as the operator's user; launch puts it out of the container |
| The verdict log | `$XDG_STATE_HOME/lup/repositories/<id>/verdicts.jsonl` | One place to measure a repository's verdicts across its worktrees |
| Each worktree's `HEAD` at its last checkpoint | `$XDG_STATE_HOME/lup/repositories/<id>/heads.json` | Every worktree's checkpoint reads the others', so it's kept once per repository |
| The last of a repository's declarations that loaded | `$XDG_STATE_HOME/lup/repositories/<id>/declaration.json` | It stands in for a declaration that can't load (#21) |
| The integration branch's tip, exported to import its declaration | `$XDG_STATE_HOME/lup/repositories/<id>/declarations/<commit>/`: its Python modules and `pyproject.toml` files | Read once per commit; earlier exports are removed |
| The failures of the judge a session's operator was warned of | `$XDG_STATE_HOME/lup/session-index/<session>.warned.json` | Each is warned of once |
| Each session's repository and the worktrees it holds | `$XDG_STATE_HOME/lup/session-index/<session>.json` | A session's later events find its worktrees wherever its working directory is |
| Saved versions | `<worktree>/.lup/saved/` | The agent has to edit and move them |
| A worktree's engine: its socket, and its lock and log | `$XDG_RUNTIME_DIR/lup/<id>.sock` (or `lup-<user>` in the system's temporary directory); the lock and log in the store | A socket's path holds about a hundred bytes, which the store's path can exceed |
| The built engine and its stubs | `lup_dev/codescan/bundle/`, built by `packages/lup-dev/checker/build.py`, ignored by git | The installed package carries it, so the judge finds its engine beside it |
| The judge itself | A local copy installed from `dev` by `lup-dev install` (`uv tool install` from the `dev` checkout), refreshed when `dev` moves; the hooks run it as `"$(uv tool dir --bin)/lup-dev"` | An agent editing the rules in its worktree isn't judged by its own edit, and a broken judge in a worktree can't refuse every write including its own fix (in the first lup, conflict markers in the compiled hook refused every command). A branch changing the rules runs them in its own tests until it lands |
| The commit the operator approved last | `$XDG_STATE_HOME/lup/judge/approved.json` | The next refresh shows the judge's source since it |
| The approved commit's version of each changed file, while the judge's review waits | `<dev checkout>/.lup/install-review/<approved commit>/`, or `whole/` where no approved commit is known, removed once the review is answered or withdrawn | The first lup's dashboard retires a review whose recorded files don't stand on disk as recorded, so the review's before side has to stand somewhere (*The judge's review, in the dashboard*) |

In lup itself, the judge's own source isn't asked about at each edit: the judge that runs is the installed copy, so an edit in a worktree can't change what judges it. It's protected after the edit and before it runs, the way the art studio's trust on launch worked. Refreshing the installed judge from `dev` shows the operator the diff of its source since the copy they last approved, and the approved copy keeps judging until they approve the new one. The operator sees exactly what will run before it runs. `DESIGN.md`'s protection of lup's policy and launch code is this same review, applied to every launch once trust on launch is ported.

**The installer** (`lup_dev/install.py`, `lup-dev install`), run by the operator from the `dev` checkout in their own terminal, so the judge never installs itself:
1. It refuses inside an agent's session (by the variables each runtime sets, as for holds), so an agent never approves the judge that judges it; and it refuses when the judge's source has changes not committed, which the copy would carry unreviewed.
2. It lists the files the installed judge carries that changed since the commit approved last, or all of them the first time: both packages' `pyproject.toml` and `src/`, the engine's source (`packages/lup-dev/checker/`), and `uv.lock`. Tests and docs aren't carried, so they aren't shown. An approved commit no longer in the repository shows everything. Where none changed, it prints one line and stops: nothing is built, asked, installed or recorded.
3. It builds the engine (`packages/lup-dev/checker/build.py`), so a build that fails does so before the operator reads anything.
4. It parks the change as one review in the dashboard, each file whole on both sides, and waits for the answer (*The judge's review, in the dashboard*, below). `lup-dev install --in-terminal` shows it in the terminal instead, through a pager: each file under its own header, naming whether it's created, deleted or modified and the lines it adds and removes, then its hunks with three lines of context, removed lines red and added green; then it asks yes or no there.
5. Approved, it checks again that `HEAD` is the commit reviewed and that the judge's source has nothing uncommitted, installs `packages/lup-dev` with `uv tool install --force`, and records the commit. Declined, nothing changes. Either way it prints the operator's note and line comments.
- **How uv installs it.** `uv tool install` from the workspace member's directory honours `lup`'s workspace source, installing it from the checkout as a path dependency; both packages are copies, not editable, and `lup_dev` carries the built bundle (checked with a scratch `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, where the copy listed its rules and answered hooks). But it resolves the tool's other dependencies afresh, ignoring `uv.lock`: the first trial got `filelock` 4.0.12, `tenacity` 9.2.1 and `typer` 0.27.3 where the lock pins 4.0.10, 9.1.4 and 0.27.2. So the installer exports the lock's versions (`uv export --package lup-dev --no-dev --no-emit-workspace`) and passes them as `--constraints`, and the copy runs what the gate ran.

**The judge's review, in the dashboard** (#25). Step 4 was a pager: a file list, then the whole diff, with no colour and nothing marking where a file starts (1,804 lines for `35d590d..fb3f25a`). The first screen read as the whole review, so the operator read per-file counts, not the lines, and the rule table reached the installed judge without a real review (#20, #24). Until lup's own dashboard exists, the dashboard is the first lup's, reached through its host half (`packages/lup/src/lup/policy/assets/host.py` in its checkout, standard library only), as the interim review hook reaches it.

What that dashboard does with such a review, read in its code at `40c2d28` and checked by parking a review through the host half into a scratch repository, then reading it back with the dashboard's own `ReviewDocuments` and `moved`:
- **One review of many files** is its `Propose` call (`devtools/review/propose.py`): a payload holding each file's path and the document it becomes (none for a deletion), with the documents before recorded beside it as the review's preconditions. The page shows each file as a fold under a header naming its path, whether it's created, overwritten or deleted, and its added and removed lines; inside, the hunks with three lines of context, the unchanged lines between them folded, added and removed lines coloured, the source highlighted, with diff, before, after and raw views. Every file opens, since none carries a verdict of the first lup's policy: each header says "no verdict captured".
- **It takes documents, not a diff:** each file whole on both sides, and it works out the hunks itself (`difflib.SequenceMatcher`). The host keeps every string of a kibibyte or more in the relay's store, and nothing caps the files or lines shown; highlighting stops past 400,000 characters a document, well above anything the judge carries (its largest file, `catalog/rules.ts`, is 94 KB).
- **Line comments** anchor to one file's lines on either side (`LineComment`: the path, first and last line, `before` or `after`, the note). They're drafted on the page and sent with the answer, or before it as a remark; both are kept in the host's answers file. A draft not yet sent lives only in the open page, under its review.
- **A review binds the disk.** The dashboard retires a waiting review as stale when a file it recorded no longer stands on disk as recorded (`devtools/review/preimages.py`), and refuses to approve one. The installer's before side is the approved commit while the disk holds `HEAD`, so recorded at the checkout's own paths every changed file reads as moved: the scratch review's three files read as changed, deleted and created. Recorded at an export of the approved commit's files, none moved.
- **It expires a review an hour after it's parked when its requester isn't on the first lup's roster** (`expire_orphaned`, on every sweep), which no bridge session is, and the installer isn't either. The hook's `wait` parks such a review again under a new id.
- **Parking needs no running dashboard:** it appends to the checkout's relay (`.lup/questions.jsonl`), which a dashboard reads once it's served, with every sibling worktree of the roots it's served with. Nothing tells the installer whether one is served: the first lup gives its dashboard's address only to its own launches.

**Where the coupling to the first lup lives:**

| Option | Deleted when the bridge ends | What checks it | Costs |
|---|---|---|---|
| **(a)** A `Reviewer` in `lup_dev` that loads the host half, in a module of its own that only `cli.py` imports | That module, its tests, its setting and a line of `cli.py`; lup's own dashboard comes as another `Reviewer` | lup's rules, ruff, pyright and the gate's tests, with the host stubbed; and it's in the judge's own review, since `lup_dev/` is carried | Bridge code in the package and in the installed copy; another repository's module loaded by path into `lup-dev`, bound to its function signatures (frozen, since the first lup is archived); the host's replies modelled twice, here and in the hook, each read against the host |
| **(b)** The interim hook gains a subcommand that parks a review of given files and waits for the answer; `lup-dev install` runs it as a command named in its settings | The hook goes whole, as planned; `lup_dev` keeps a `Reviewer` that runs a command, with its protocol, to remove or repoint | Nothing: `.claude` is excluded from lup's rules, ruff and pyright, and no test reaches the hook | A new protocol (the files in, the answer out) defined on both sides, which nothing checks agree, since the hook can't import `lup_dev`. `runtime-mention` keeps `lup_dev` from naming `.claude/hooks/` as a default, so the operator sets the command in their shell (the installer runs in their terminal, outside `.claude/settings.json`'s `env`), and an unset one must refuse rather than fall back to the pager |
| **(c)** The first lup's own `review propose` command, run by `lup-dev install` | Its call in `lup_dev` | The first lup's tests | It maps a directory of files onto a checkout as it stands, so it needs (a)'s export as that checkout to show any diff; it judges each file by the first lup's edit gates, whose rules aren't lup's, and refuses the whole review over one file they refuse; it runs the first lup's whole package rather than its standard-library host half; approved, it expects its own waiter to write the files |
| **(d)** `lup_dev` writes the first lup's relay records itself | Like (a) | Like (a) | A second copy of the host's fingerprint and document store, which must agree with the host's |

**Lean: (a).** The code that decides whether the judge installs is checked by the gate and reviewed with the judge; the seam is the one `Reviewer` already is; it stays on the environment's side of the boundary (the library never sees it), and the bridge's end deletes one module. (b) keeps the coupling in the bridge's file, but puts the approval in code nothing checks, behind a protocol nothing holds both sides of.

**What changes in the code,** with (a) (decisions 99 to 109, and 110 to 116 taken while building it):
- **A new module, `lup_dev/legacy_dashboard.py`:** `LegacyDashboard`, a `Reviewer`. It loads the host half from the first lup's checkout, exports the approved commit's files, parks one `Propose` naming `lup-dev install` as its requester, waits, parks again after the first lup's hour, reads the answer and every remark, spends an approval through the host, and removes the export. Its models of the host's replies stay inside it (`Host`, the loaded module behind typed methods, and the records it reads), and so do the first lup's own paths and spellings: where its host half sits in its checkout, the relay's name, the answers' variable, `Propose`.
- **`install.py`:** `Reviewer.answer(review) -> Answer` in place of `approves(review) -> bool`; `Answer` (approved, note, comments) and `LineComment` (path, first and last line, side, note); `Review` holds `files: list[ChangedFile]` (a path in the checkout, its text at the approved commit and at `HEAD`, either none) and git's one-line count (`shortstat`), in place of the stat and the diff as text; `Installer.install()` returns an `Outcome`, one of `Unchanged`, `Declined` (with the answer) or `Installed` (with the approval and the answer), each saying itself in `report()`, which `cli.py` prints. `Terminal` shows each file under a header, coloured.
- **`settings.py`:** the first lup's checkout, read from the interim hook's own variable, `LUP_INTERIM_REVIEW_LEGACY_CHECKOUT`, with the hook's default (`lup-legacy.git/tree/dev` beside the directory holding the repository), so one setting points both at it.
- **`layout.py`:** `CheckoutLayout.install_review(since)`, the export's directory: `.lup/install-review/<since>/`, or `.lup/install-review/whole/` where no approved commit is known, since the created files' paths still have to lie under a directory where they don't stand.
- **`cli.py`:** `lup-dev install --in-terminal`.
- An import-linter contract keeping `legacy_dashboard` behind `cli.py`, as the adapters are, would go in `pyproject.toml`, which is the operator's to change.

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
| `policy/worktrees.py` | The session's repository, the worktree a path is in, and the worktrees a session holds: the session index |
| `policy/checkpoint.py` | The runtime-neutral events, the in-flight set, deciding when to judge, the checkpoint in each worktree the session holds, a move of `HEAD`, holds at the checkpoint |
| `policy/importers.py` | The background pass re-checking the files that import what changed |
| `policy/store.py` | The store: snapshot, compare, set aside what was committed elsewhere or merged from it, restore, save, move the accepted tree forward |
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
| `install.py` | Installing the judge: the operator reviews its source since the commit approved last before a new copy runs; the `Reviewer` seam, and the terminal's review |
| `legacy_dashboard.py` | The judge's review parked in the first lup's dashboard, through its host half: the bridge's `Reviewer`, which goes when lup's own dashboard lands |
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
1. `git -C <dev checkout> pull --ff-only origin dev`, then `uv run lup-dev install` from the checkout, in their own terminal: read the review in the first lup's dashboard (served with `uv run --directory <lup-legacy checkout> lup-devtools dashboard serve --root <dev checkout>`), and approve.
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
  - Its `PermissionRequest` for `apply_patch` carries `tool_input: {"command": <the patch>}` and no file list (`core/src/tools/approvals.rs`). It fires only when the patch needs approval: under `on-request`, a patch writing outside the writable roots, or retried after a sandbox denial; under `never`, never. Inside the workspace Codex doesn't ask, so lup answers nothing and judges at the checkpoint; a patch reaching outside is left to Codex's approval, since on Codex lup judges only the worktree a session started in (*Every worktree of the repository*). The design's "answered `allow`" would have let those through unjudged.
  - Its hooks' `cwd` is the "Working directory for the session", and "`Bash` and `apply_patch` use `tool_input.command`" (its hooks docs, read for #20): nothing in a payload says where a command or a patch writes, short of parsing them.
  - Its hook `timeout` defaults to 600 seconds with no maximum: `timeout_sec.unwrap_or(600).max(1)` (`hooks/src/engine/discovery.rs`); its docs: "If timeout is omitted, Codex uses 600 seconds for most hooks". A timed-out hook fails open.
  - Its payloads (`hooks/schema/generated/*.input.schema.json`): every hook has `session_id`, `cwd`, `hook_event_name`; `PreToolUse` and `PostToolUse` add `tool_name`, `tool_input`, `tool_use_id` and, for a subagent, `agent_id`; `PostToolUse` adds `tool_response`; `Stop` adds `stop_hook_active`. Its shell tool is reported as `Bash`, `apply_patch` as `apply_patch`, a subagent's start as `spawn_agent`.
  - Its `PreToolUse` can't ask: "`permissionDecision: "ask"` … [is] parsed but not supported yet" (its hooks docs), and a plain `allow` fails open (`hooks/src/engine/output_parser.rs`). lup never answers it.
- **Claude Code, settled:** its hooks reference says `PreToolUse` "runs before a tool call executes" and `PostToolUse` "after a tool call succeeds" (`PostToolUseFailure` "after a tool call fails"), each with the call's `tool_use_id`, and that matching hooks "run in parallel". A call's finish never comes before its start, so the in-flight set stays right; parallel calls' hooks overlap, which the file lock covers.
- **A subagent's working directory in its hooks:** whether Claude Code's `cwd` follows a `cd` in a subagent's calls as it does in the session's own conversation. Here a subagent's shell starts each call in the project's directory, so its hooks may never report another worktree; its file tools hold its worktree either way (*Every worktree of the repository*).
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
20. Content committed elsewhere isn't judged; commits made locally since the previous checkpoint are. *Alternatives:* judge it all, which replays history as new writes; set aside anything equal to `HEAD`, which let a write-and-commit through. *Where:* `policy/store.py`. Reshaped by 77 and 78 (#22): neither is what git merges from content committed elsewhere, and a commit made since the previous checkpoint is judged once, as a move of `HEAD`, rather than put back.
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
36. A write outside the session's worktree isn't judged; the runtime decides. *Alternative:* refuse it. *Where:* `policy/before.py`. Reshaped by 69 (#20): outside the session's repository.
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
47. When judging itself fails, a file tool's write is denied and other calls go on, told; a turn's end is blocked once. *Alternative:* a crash, which a runtime treats as no decision, letting a write meant for review through. *Where:* `adapters/`. Reshaped by 93 (#21): a turn's end isn't blocked; the operator is warned once.
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

Taken for #20 and #22:

69. **(yours)** The judge covers every worktree of the session's repository. The repository is read from the session's working directory as git's common directory, so a session started in a bare repository's own directory is judged too. *Alternatives:* pin a session to the worktree it starts in, and make one session per worktree the way of working (#20's option 2); leave it until rooms (#20's option 3). *Where:* `policy/worktrees.py`, `layout.py` (the session index).
70. **(yours)** A file tool's write is judged in the worktree its path is in, which git names from the file's nearest existing directory and which must belong to the session's repository. A repository nested in a worktree is another repository. *Alternative:* match the path by prefix against `git worktree list`, one call per session, which would judge a nested repository's files as the outer worktree's though no snapshot sees them. *Where:* `policy/worktrees.py`, `policy/before.py`.
71. **(yours)** A checkpoint looks at the worktrees the session holds: where it started, where its file tools wrote, where its hooks report its working directory. A shell write into a worktree it never reached is a declared gap, closed by rooms. *Alternatives:* every worktree of the repository, at about 80 ms each per checkpoint (0.25 s here, about 3.5 s on nori's 36) plus a first snapshot of seconds each at nori's size, judging the operator's and other sessions' worktrees as this session's; the worktrees changed since their record, which costs the same, since finding a change takes a snapshot; the held worktrees plus a sweep of every worktree at the turn's end, which catches shell-only writes on both runtimes once per turn and judges the operator's uncommitted work in any worktree as the agent's. *Where:* `policy/worktrees.py`, `policy/checkpoint.py`.
72. **(yours)** On Codex a session holds only the worktree it started in, a declared gap: its hooks' `cwd` stays the session's, its tools carry only a `command`, and under its `workspace-write` sandbox a write elsewhere is outside the writable roots, where Codex's own approval decides. *Alternative:* read the files an `apply_patch` names from its headers, which hand-parses an agent's output. *Where:* `adapters/codex.py`.
73. Reaching a worktree mid-session begins the session there as a start does, accepting the worktree as it stands unless a call is running there. That also fixed the start, which accepted a worktree while another session's call wrote in it. *Alternatives:* judge what changed since the worktree's stored accepted tree as this session's, which blames it for the operator's work between sessions; start a worktree without a store from its `HEAD`, which judges the operator's uncommitted work as the agent's. *Where:* `policy/checkpoint.py` (`begin`).
74. The calls running stay per worktree. A call records its session and counts in every worktree its session holds, and a turn's end clears only its own session's calls (before, it cleared every session's own-conversation calls in the worktree). *Alternatives:* one set per repository, where any session's long call holds back every other session's checkpoints; one set per session, where a checkpoint judges another session's write in progress in a shared worktree. *Where:* `policy/checkpoint.py` (`Call`, `Running`).
75. **(yours)** A file tool's write into the repository's own git directory asks, as `.git/` does inside a worktree. *Alternative:* leave it to the runtime as a path outside the repository, which in this repository's layout lets an edit to `lup.git/config` or `lup.git/hooks/` through unasked. *Where:* `policy/before.py`.
76. Loading a declaration drops, once it's loaded, the modules it imported from where it was read (a worktree, or a commit's export), so the next load imports its own; only modules imported during the load are dropped, so a worktree whose own `lup_dev` runs the check keeps it. Without it, a second worktree's `lup_project` came back as the first's. *Alternative:* an interpreter per declaration, a Python start per worktree per hook. *Where:* `project.py` (`load`).
77. **(yours)** Content git's merge makes from commits whose content was judged is set aside, as content committed elsewhere is; the commits judged include the `HEAD` each worktree of the repository had at its last checkpoint. *Alternatives:* as it was, which refused a clean merge's file when both sides changed it (replayed against the judge before this) and left the working tree different from `HEAD`; judge every merge result again, which asks the operator a second time about what they reviewed on the branch. *Where:* `policy/store.py` (`Elsewhere`, `Store.merges`).
78. **(yours)** A move of `HEAD` is judged once, as a commit's: what wasn't set aside is judged against the accepted content, never put back, logged with no session, and told as a commit's to the conversations whose calls finished. *Alternatives:* treat content committed on the branch as accepted (#22's option b), which lets anything committed through the shell skip the judge; as it was, putting it back, which leaves the working tree different from `HEAD` and is undone by the next `git restore`, since the commit is among the tips by then (replayed against the judge before this). *Where:* `policy/checkpoint.py` (`Move`, `brought`), `policy/store.py` (`Heads`); `HEAD` is kept per repository rather than in `WorktreeState` (decision 84).
79. **(yours)** A move's asks are kept for the operator as holds no agent waits on, answered after the fact, the answer reaching the session that found the move at its next checkpoint. *Alternatives:* told and logged only, which reaches the operator only through the agent's report; a hold the agent waits on, on both runtimes, which needs Claude Code's `PostToolUse` timeout raised to a day in `.claude/settings.json` and blocks a session that may not have made the commit. *Where:* `policy/holds.py` (`Hold`), `cli.py` (`lup-dev holds`).
80. Reports name each file by its absolute path, and the `mv` that puts a saved copy back names both ends in full. *Alternative:* paths relative to each worktree under a heading naming it, which an agent working elsewhere has to join by hand. *Where:* `policy/report.py`.
81. **(yours)** A verdict names its worktree; a move's verdicts carry no session and `move` for their tool. *Alternative:* a log per worktree, which loses the one place measuring a repository. *Where:* `policy/verdicts.py` (`Verdict`).
82. An approval covers a path in its worktree only. *Alternative:* a path across the repository's worktrees, which would let an approval on one branch cover different content on another. *Where:* `policy/checkpoint.py` (`Session`, one per worktree).
83. **(yours)** A new module, `policy/worktrees.py`: the session's repository, the worktree a path is in, and the worktrees a session holds. *Alternative:* in `policy/checkpoint.py`, where `locate` and `Worktree` lived, already 940 lines. *Where:* `policy/worktrees.py`; reaching a worktree, which begins the session there, stays in `policy/checkpoint.py` (`holding`), beside `begin`.

Taken while building #20 and #22:

84. Each worktree's `HEAD` at its last checkpoint is kept once per repository, beside the verdict log (`heads.json`), which every worktree's checkpoint reads: its own entry to see `HEAD` move, the others' as commits judged. *Alternative:* in each store's `WorktreeState`, as the design first had it, where reading the other worktrees' takes listing them with `git worktree list --porcelain`, whose `worktree <path>` lines would have to be split by hand, then opening each one's store. *Where:* `policy/store.py` (`Heads`), `policy/checkpoint.py` (`Worktree.heads`, `Worktree.record`), `layout.py`.
85. State whose shape changed goes in new files, the earlier ones left unread: the session index in `session-index/`, the calls running in `running.json`. A session running across a reinstall carries on from its next hook's working directory; a call in flight then is forgotten. *Alternatives:* read the earlier shapes too, a compatibility shim; refuse them with an error, which fails every hook of every running session until it's restarted. *Where:* `layout.py`.
86. A move is judged only where a `HEAD` was recorded for the worktree and where `HEAD` names a commit now; a merge of more than two commits isn't remade, and a merge's conflicted paths are judged. *Alternative:* a missing record read as no commit, which would judge everything the branch has as the move's on the first checkpoint after a reinstall. *Where:* `policy/checkpoint.py` (`moving`), `policy/store.py` (`Store.merges`).
87. What a move brought is judged with no session's approvals, against the content accepted before the move, which is also its baseline for the public-API ask and removed notes; a turn's or a subagent's end tells it as it tells a refusal, blocking once. *Alternative:* the approvals of the session whose checkpoint found it, which would let one session's approval cover a commit it may not have made. *Where:* `policy/checkpoint.py` (`brought`, `TurnEnded`, `ConversationEnded`).
88. An answer given while no agent waits (a move's hold, or one whose wait ran out) is logged when it's given, against the verdicts the hold keeps; one an agent waits on is logged by the waiting hook. Before, a late answer to a hold whose wait ran out wasn't logged at all. *Alternative:* log it when the session that found it hears it, which loses it if that session never runs again. *Where:* `policy/holds.py` (`Hold.verdicts`, `answer`).
89. A session that starts again (resumed, cleared or compacted) begins again in every worktree it holds, not only the one its working directory is in. *Alternative:* only that one, which leaves the operator's work between sessions in the others to be judged as the session's. *Where:* `policy/checkpoint.py` (`holding`, `SessionStarted`).
90. The declaration is loaded when a judgement first needs it, so a call's start and a finish that runs no checkpoint load none. *Alternative:* load it at every hook, an export and an import each, and a broken declaration failing calls that judge nothing. *Where:* `policy/checkpoint.py` (`Worktree.declared`, `Worktree.roles`).
91. Every ask names its file by its absolute path, in the runtime's prompt and in holds, as reports do. *Alternative:* asks relative to their worktree, which the operator can't place when a session works in several. *Where:* `policy/judge.py`.

Taken for #21:

92. **(yours, agreed)** Where the declaration due can't load, the repository's last declaration that loaded judges instead, kept per repository; the agent is told once for each failure, to tell the operator; with none kept, the failure stands; the gate never takes a stand-in. Whatever importing a declaration raises counts as its failing to load, conflict markers included. *Alternatives* (#21's): keep denying every file tool's write, which stops every session in the repository from the moment a declaration field lands until the next install; fall back to the defaults, which silently loses the project's protections (`lup_dev/catalog/**` here); ask on every write. *Where:* `policy/checkpoint.py` (`Worktree.loaded`, `LastDeclaration`, `Worktree.told`), `project.py` (`load`), `layout.py`.
93. **(yours, agreed)** When judging fails at a turn's end, the turn ends, and the operator is warned once for each failure in a session, in the runtime's `systemMessage`. *Alternatives:* block once at every turn's end, as before, which made the agent repeat a notice it can't act on; tell the agent in `additionalContext`, which on Claude Code continues the turn as a block does. *Where:* `adapters/` (`Stop.failed`, `OperatorWarning`), `policy/checkpoint.py` (`first_warning`), `policy/report.py` (`judge_failed`).

The declaration, from the integration branch:

94. **(yours, agreed)** The declaration is read from the integration branch's tip, never from the worktree being judged, as the judge's code comes only from the installed copy: a branch's declaration change takes effect when it lands on `dev`, and a branch needing one lands it first as a hotfix. *Alternative:* each worktree's own declaration, as built before, where a branch changes what judges it. *Where:* `policy/checkpoint.py` (`Worktree.of`, `Worktree.loaded`, `Judging`).
95. **(yours)** The integration branch is named by a `lup-dev` setting, `LUP_INTEGRATION_BRANCH`, defaulting to `dev`, set where the hooks run (the operator's environment, or `.claude/settings.json`'s `env`, both out of the agent's reach). *Alternatives:* a `[tool.lup]` key, which has to be read from some branch before the branch is known, and which a branch could repoint; a git config key (`lup.integration`), which an agent's shell can rewrite unjudged, since no snapshot covers the git directory; the remote's default branch (`origin/HEAD`), `main` here, which isn't where work lands. *Where:* `settings.py`, `cli.py` (`services`), `policy/checkpoint.py` (`Services.integration`).
96. **(yours)** A repository without a branch of that name is judged, worktree by worktree, by the declaration each one's `HEAD` commit holds, and by the defaults before its first commit: uncommitted edits never judge, but a branch's own commits do there. *Alternatives:* the worktree's own files, uncommitted edits included, as before; the defaults, which silently drop the project's protections; an error until the setting names a branch that exists, which stops judging in every such repository. *Where:* `policy/checkpoint.py` (`Worktree.loaded`).
97. **(yours)** A commit's declaration is imported from an export of the commit's Python modules and `pyproject.toml` files, written once per commit into the repository's state and moved into place whole, earlier exports removed; decision 76's isolation applies to the export's directory, and the conditions module the declaration names is read there too, so the declaration and what it names come from one commit. *Alternatives:* an import hook reading modules straight from git's objects, which writes nothing but is an importer to keep, and leaves modules without a file; an export into a temporary directory at every judgement, an archive each time; the whole tree, data and assets included; the conditions module read from the worktree being judged, which lets a branch add a condition and name it at once, but splits what the declaration names across two commits. *Where:* `policy/store.py` (`Store.tip`, `Store.export`), `policy/checkpoint.py` (`Worktree.exported`), `layout.py` (`Layout.exported`).
98. The gate (`lup-dev rules check`, through `Worktree.at`) reads the worktree's own declaration as it stands, and takes no stand-in. *Alternative:* the integration branch's, which would check a branch by a declaration it doesn't land with. *Where:* `policy/checkpoint.py` (`Worktree.at`), `cli.py`.

Taken for #25, the judge's review in the dashboard:

99. **(yours)** The installer parks the judge's review in the first lup's dashboard through a `Reviewer` in `lup_dev` that loads the first lup's host half from its checkout, as the interim review hook does: a new module, `lup_dev/legacy_dashboard.py` (`LegacyDashboard`), which only `cli.py` imports and which goes when lup's own dashboard lands. It finds the first lup's checkout as the hook does, through the hook's own variable, so one setting points both at it. *Alternatives* (*The judge's review, in the dashboard*): the interim hook gains a subcommand that `lup-dev install` runs through a command named in its settings, which keeps the coupling in the bridge's file but puts the approval in code nothing checks, behind a protocol defined on both sides; the first lup's `review propose`, which judges lup's code by the first lup's gates and refuses the whole review over one file they refuse; writing the first lup's relay records from `lup_dev`, a copy of its fingerprint to keep in step; a variable of its own for the first lup's checkout, a second setting to keep in step with the hook's. *Where:* `legacy_dashboard.py`, `install.py` (`Reviewer`), `settings.py`, `cli.py`; a contract keeping it behind `cli.py` would go in `pyproject.toml`.
100. **(yours)** One review, the first lup's `Propose`, with an entry for each changed file carrying its whole text at `HEAD`, the text at the approved commit recorded as its precondition; the dashboard works out the diff. The before side is exported to `.lup/install-review/<approved commit>/` in the checkout, and the review's paths are there, since the dashboard retires a review whose recorded files don't stand on disk; the page shows each path under that prefix, and the terminal maps comments back to the checkout's paths. The export is removed once the review is answered or withdrawn. *Alternatives:* the before side recorded at the checkout's own paths, which the dashboard retires as stale at once (checked: every file read as moved); a `git worktree` at the approved commit, which shows the paths without the prefix but adds a worktree to the operator's repository for as long as the review waits; the diff as one text, which the page can only print raw, with no files and no colour. *Where:* `legacy_dashboard.py`, `layout.py` (`CheckoutLayout.install_review`).
101. Git cuts the change into files: `git diff-tree -r -z --no-renames --name-only <approved> HEAD -- <what the judge carries>` lists them, read with the store's `nul_separated` (its suppression, decision 46), `git ls-tree` says which side holds each (decision 115), and `git cat-file blob` reads each side whole, from git's empty tree where no approved commit is known. A rename is a deletion and an addition. A carried file that isn't UTF-8 text refuses the install, naming it, since no review here can show it. *Alternatives:* split `git diff`'s output at its file headers, which hand-parses it, or read it with a parser such as `unidiff`, a new dependency, when the dashboard wants documents anyway; renames found, which a `Propose` can't show as a move; a file that isn't text listed by its object id and shown nowhere. *Where:* `install.py` (`Installer.review`, `ChangedFile`).
102. **(yours)** Once the review is answered, approved or declined, the installer prints the operator's note and line comments in the terminal, one `path:line (side): note` each, with paths in the checkout and the `before` side naming the approved commit. They stay where the first lup keeps them, its answers file, which the terminal names; lup keeps no copy. *Alternatives:* a copy in lup's state (`judge/declined/<commit>.json`) for an agent to read, a new file and its reader, when the operator who wrote them is at the terminal and briefs the agent; a GitHub issue, a network call in the installer. *Where:* `install.py` (`Answer`, `LineComment`), `cli.py`.
103. **(yours)** When no dashboard is served, the installer parks the review anyway and waits: parking appends to the checkout's relay, which a dashboard reads once it's served, and the waiting lines give the command that serves it. When the first lup's checkout or its host half is missing, it refuses, naming the setting, and nothing installs. The terminal's review stays for when the first lup can't be reached, only when asked for (`lup-dev install --in-terminal`), each file under its own header and coloured. *Alternatives:* fall back to the terminal unasked, which is how #25 happened; drop the terminal's review, which leaves no way to install a fix to the judge while the first lup's checkout is broken; look for a served dashboard, whose address the first lup gives only its own launches. *Where:* `install.py` (`Terminal`), `legacy_dashboard.py`, `cli.py`.
104. **(yours)** While it waits, the terminal shows which commit is reviewed since which, git's own one-line count (`git diff --shortstat`), the review's id, the command that serves the dashboard, that comments sent as remarks outlast the first lup's hour while drafts don't, and that Ctrl-C withdraws the review and installs nothing; then a line for each time the review is parked again, and the outcome with the comments. No file list, since the counts were what the operator read instead of the lines, and no spinner. It looks for the answer every 2 seconds through `Clock`, which tests drive. *Alternatives:* the per-file stat, as the pager's first screen had it; a spinner. *Where:* `legacy_dashboard.py`.
105. A review the first lup expires is parked again under a new id, as the hook's `wait` does, and the installer reads the remarks of every id it parked. *Alternatives:* put the installer on the first lup's roster, which couples it to the first lup's coordination too; stop and have the operator run it again, which loses the remarks sent so far from the answer the installer prints. *Where:* `legacy_dashboard.py`.
106. Ctrl-C withdraws the review by removing the export, so the dashboard retires it as stale at its next look and no approval can release it; the host half offers no cancel. *Alternative:* leave it waiting, where an approval given later releases nothing and reads as if it had. *Where:* `legacy_dashboard.py`.
107. Approved, the installer checks again that `HEAD` is the commit reviewed and that the judge's source has nothing uncommitted before it installs; if `dev` moved during the review, as when a branch lands in the `dev` checkout, it refuses, and the operator runs it again. *Alternatives:* no check, as with the pager, whose wait was seconds where a review's is the operator's reading time; install from an export of the reviewed commit, which needs the engine's toolchain set up there. *Where:* `install.py` (`Installer.install`).
108. **(yours, agreed in #25)** Where nothing the judge carries changed since the commit approved last, the installer prints one line and stops, before building: nothing is asked, installed or recorded, so the commit approved last stays one the operator reviewed. *Alternatives:* reinstall unasked, which would mend a removed copy but prints the build's and uv's output; record the new commit as approved, an approval nobody gave. *Where:* `install.py`.
109. **(yours)** The review runs with the checkout's own code (`uv run lup-dev install`), as before, so a change to the installer is reviewed by itself, the dashboard's reviewer included the first time it runs. *Alternative:* the installed copy reviews the checkout, so only approved code decides an approval; but the copy's list of what the judge carries is the old one, so a path newly carried would go unshown, and the engine's build runs the checkout's code before any review either way. In the bridge every agent's code runs on the host, so this guards against a mistake, not a determined change; containers make it a wall. *Where:* `cli.py`.

Taken while building #25:

110. **(yours)** An approval read from the dashboard is spent through the host half: the review is parked again, and the host claims the approval, as an agent's repeated call does. The dashboard then records the review as carried out, and one approval releases one install. *Alternative:* read the answer and leave it unspent, where the dashboard shows the review approved and never carried out, retires it as stale once the export is removed, and a later run of the same change would install on it unasked. *Where:* `legacy_dashboard.py` (`Host.spend`).
111. **(yours)** A change the dashboard answered already is answered at once by that answer, since the host recognizes a review by the fingerprint of everything it was parked with: running `lup-dev install` again on a declined change declines it again, with the same note; an approval given but never read (the installer stopped first) is spent, and installs. A declined change is reviewed again after a commit changes it, or with `--in-terminal`. *Alternative:* a fresh review at every run (a run's id in its reason), which leaves an earlier withdrawn review of the same files waiting beside it, live again once the export is rewritten. *Where:* `legacy_dashboard.py` (`Call`, `LegacyDashboard.waited`).
112. A review that leaves the dashboard's queue other than by expiring (retired as stale, cancelled) refuses the install, naming its state and the relay's reason. *Alternative:* park it again as after expiry, which loops every two seconds when a file under the export moved, since each review parked again records the same files. *Where:* `legacy_dashboard.py` (`LegacyDashboard.reviews`).
113. **(yours)** The first lup's own paths and spellings stay in `legacy_dashboard.py`: where its host half sits in its checkout, the relay's name, `LUP_REVIEW_ANSWERS`, `Propose`, and the review's rule (`lup-dev-install`), purpose (`quality_review`) and requirement (`human_only`). `docs/conventions.md` homes paths in `layout.py` and variables in `settings.py`, but these are the first lup's, which `lup_dev` neither stores nor reads itself, and the bridge's end deletes them with the module. *Alternative:* `layout.py` and `settings.py`, which leaves bridge entries in two package-wide modules. *Where:* `legacy_dashboard.py` (`LegacyDashboard.host`, `Host`).
114. The terminal's review asks yes or no, with no note: the operator answering there is at the terminal and briefs the agent themselves. Its pager lists no files first, and a file whose text is the same on both sides (its mode changed) says so under its header. *Alternative:* ask for a note after the answer. *Where:* `install.py` (`Terminal`).
115. Which side holds each changed file is read with `git ls-tree -r -z --name-only`, once a side, before `git cat-file blob` reads it. *Alternatives:* `cat-file` on every path with its failure read as absence, which can't tell a missing file from another failure; `diff-tree --name-status`, whose `-z` output alternates statuses and paths, read by position. *Where:* `install.py` (`Installer.review`).
116. The export of a first install, or of an approved commit gone from the repository, is `.lup/install-review/whole/`. *Alternative:* named for git's empty tree, which is what that before side is read from, but means nothing on the page. *Where:* `layout.py` (`CheckoutLayout.install_review`).

Taken for findings ruff fixes safely:

117. **(yours, agreed)** A finding ruff fixes safely isn't reported to the agent, at a checkpoint or at the turn's end. The landing session applies the fixes and the formatter with `lup-dev check --fix` on the merged result, folding what they change into the merge commit; CI and the gate without `--fix` only check. *Alternatives:* the judge applying them after a write, which rewrites a file under the agent; reporting them as before, one by one; leaving out findings with an unsafe fix too, whose rewrite can change what the code does, unreviewed. *Where:* `codescan/ruff.py`, `policy/judge.py` (`Judge.information`), `policy/checkpoint.py` (`unclean`), `gate.py`, `cli.py`, `AGENTS.md`.
118. A finding is fixable when ruff's JSON gives it a fix whose applicability is `safe`, the one kind `ruff check --fix` applies; ruff gives no fix where the configuration makes the rule unfixable. The applicability is read as ruff's three values (`safe`, `unsafe`, `display-only`), so an unknown one fails loudly. *Alternatives:* any fix at all, which would hide findings `--fix` leaves; the applicability read as free text. *Where:* `codescan/ruff.py`.
119. Fixability is a field of `Finding` (`fixable`), and fixable findings are left out where the agent hears them, not where ruff is read. *Alternative:* drop them in `Ruff.findings`, which would make the `ignore` naming one read as unused (`unused-ignore`, a refusal) and hide them from `lup-dev rules check`. *Where:* `codescan/contract.py`, `policy/judge.py`, `policy/checkpoint.py`.
120. `lup-dev rules check` still reports fixable findings, as the gate's `ruff check` does. *Alternative:* leave them out there too, which lets it pass where the gate fails. *Where:* `cli.py`.
121. The fixes are `ruff check --fix-only --ignore-noqa`, then `ruff format`, run as steps before the gate's and reported like them. `--fix-only` applies the fixes and reports nothing, leaving what's left to the gate's ruff step. *Alternatives:* `ruff check --fix`, which also reports what's left and fails, so each finding would be reported twice; a command of its own, which a landing session would have to remember to run first. *Where:* `gate.py` (`Fixes`, `Check.fixes`), `cli.py`.
122. **(yours)** The fix steps are data in `gate.py`, not beside the gate's steps in `catalog/gate.py`, which this change was to leave alone. *Alternative:* `catalog/gate.py`, protected with the rest of the gate's data, the better home; moving them is a small follow-up. *Where:* `gate.py` (`Fixes`).
