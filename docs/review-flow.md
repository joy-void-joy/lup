# Reviews: drafts, submissions, and the agent's own wait

**One sentence:** A write the operator must review goes into a draft instead of the file, so the call succeeds. The agent submits its drafts in bulk, each with what it changes and why, and the operator sees only what's submitted. An approval is carried out for the agent and accepted by the judge in the same step. The agent freezes itself on a review only when its next step needs that change.

This piece is about how a change the judge asks about reaches the operator and comes back. *What* is asked stays the judge's (`docs/judging-writes.md`, *What each change gets*). It closes #16: bundling, and approved changes carried out for the agent. For writes, it replaces the bridge's interim review (`.claude/hooks/interim_review.py`): refused at once, a background `wait`, then "repeat this exact call". `DESIGN.md`'s *A review queues; the agent carries on* is the design it builds on. This note proposes reshaping that section's first sentence, since a write needing review is no longer refused (decision 1).

## What went wrong, and what answers it

| What went wrong in practice | What answers it here |
|---|---|
| A write needing review came back as a tool error ("Queued for the operator's review… repeat this exact call") | The call succeeds: the write lands in a draft, and the agent is told so beside the result |
| The bookkeeping of background waits and exact repeats | Nothing is repeated. An approval is carried out for the agent, and an answer reaches it at its next call. `wait` exists only to freeze |
| Two edits to one file needed two approvals, the second recorded against the file before the first (#16) | One draft per file, so every edit to it is one change, submitted once |
| A worker's repeat wasn't exact, leaving stale records | There's no repeat to get wrong |
| Edits to a file while its review waited made the review stale | The file doesn't change while its review waits: edits go into the draft, and the approval applies the version the operator saw |
| Agents routed around a long wait: an hour testing a scratch copy, or switching from Write to Edit | Nothing is refused, so there's nothing to route around. An Edit of a drafted file goes into the same draft. What the agent needs to run, it submits and waits on |
| In the first lup, the operator didn't know what was theirs to review and what the agent was still writing | Drafts are never shown. The operator sees a change when the agent submits it, with its context |

## The spike: what a hook can do

### Claude Code (2.1.295)

The setup lives in a scratch directory, its own project, away from this repository. Its `.claude/settings.json` runs one Python script on `PreToolUse` and `PostToolUse` for `Write|Edit|Read`. The script redirects a call on `src/<path>` to `.drafts/src/<path>`, answering `permissionDecision: "allow"` with `updatedInput` and an `additionalContext` note:
- a first Edit's draft is made by copying the file;
- a Read of `src/APPROVE` moves every draft into place, standing in for an approval;
- one mode puts the real path back in the result through `PostToolUse`'s `updatedToolOutput`.

Each run reset the files and ran one fixed prompt, telling the model not to retry a failed call:

```
command claude -p "<prompt>" --model haiku --setting-sources project --no-session-persistence \
  --tools Read,Write,Edit --permission-mode manual --output-format stream-json --verbose
```

The results below are the tool results the model received, read from the stream, and the files on disk afterwards.

| Run | Calls | What happened |
|---|---|---|
| 1 | Write a new `src/new.py`, then Read it | The Write landed at the draft, with no error: `File created successfully at: …/.drafts/src/new.py`. `src/new.py` was never created. The Read was redirected and showed the draft. The note reached the model |
| 2 | Read `src/lib.py`, then Edit it (the hook copies it to a draft nobody Read) | The Edit landed in the draft: `The file …/.drafts/src/lib.py has been updated successfully.` The real file was unchanged |
| 3 | Write a new `src/new.py`, then Edit `src/new.py` | The Write went to the draft. The Edit was refused before any hook ran (the hook log has no entry for it): `<tool_use_error>File does not exist.…</tool_use_error>` |
| 4 | Read `src/old.py`; Edit `y = 1`→`y = 2` (redirected, real path put back); Edit `y = 2`→`y = 3` at the real path; the same Edit at the draft's path; "approve"; Edit `y = 3`→`y = 4` at the real path, without reading it again | The first Edit's result named the real path: `The file …/src/old.py has been updated successfully.` The second was refused before any hook: `String to replace not found in file. String: y = 2`. The Edit at the draft's path passed. After the draft was moved into place, the last Edit passed without a fresh Read |
| 5 | Run 4 without putting the real path back | The same outcomes, so the restored path wasn't what let the last Edit through |
| 6 | A draft of `src/lib.py` exists beforehand; Read `src/lib.py`; Edit the draft's path; Edit `src/lib.py` on a line both versions share | The Read showed the draft. Both Edits passed and landed in the draft |
| 7 | Write `src/.claude/x.json` and `src/.git/y.txt` (both redirected under `.drafts/`), and `.claude/z.json` (allowed as it is) | All three were refused: `Claude requested permissions to edit …/.drafts/src/.claude/x.json which is a sensitive file.` In `-p` with nobody to answer, a prompt is a refusal |

What it settles:
- **A redirected Write lands at the draft and reports success, naming the draft's path.** `updatedToolOutput` can put the real path back in what the model reads (run 4).
- **Claude Code checks an Edit against the path the agent gave, before any hook runs.** The file must exist, must have been read, and must hold `old_string`. Only the execution is redirected. The hooks reference says so: "Validation rejections are returned as `tool_use_error` results and happen before hooks run, so they fire neither `PreToolUse` nor `PostToolUseFailure`." An Edit addressed to the real file therefore fails in two cases, with Claude Code's own error, which no hook sees:
  - the file exists only as a draft (run 3);
  - its `old_string` is text only the draft holds (run 4).
- **Executing on the draft needs no Read of the draft** (run 2). After an approval moved the draft into place, the real file could be edited without reading it again (runs 4 and 5). That fits the read-first check reading the real path and the changed-since-read check reading the path written. I didn't confirm the mechanism in Claude Code's code.
- **A redirected Read shows the draft, and counts as reading both paths** (run 6).
- **A hook's `allow` doesn't approve a write into a directory Claude Code protects** (`.git`, `.claude`, `.vscode`, `.husky`, `.devcontainer` and a few more). The check reads the redirected path, at any depth (run 7). So a draft's path must never hold such a segment.
- **Not settled:**
  - whether a `PostToolBatch` hook can explain a refused Edit to the agent (documented to receive the batch's calls and results; not tried);
  - whether an escaped draft path (`%2Eclaude`) passes the protected-path check, as it should, since no segment is named `.claude`.
- **The run count:** seven runs, two more than the handful the brief allowed; runs 5 and 7 each settled something the earlier ones left open.

### Codex (0.156.1)

From its hooks docs (now at `learn.chatgpt.com/docs/hooks`) and its source at tag `rust-v0.156.1`, which matches the installed CLI. Nothing was run end to end.
- **`PreToolUse` can rewrite `apply_patch`, and the shell.** It answers `permissionDecision: "allow"` with `updatedInput: {"command": "<the new patch>"}`. The docs: "To rewrite a supported tool call without blocking, return permissionDecision: "allow" with updatedInput". In the source, `core/src/tools/handlers/apply_patch.rs:466-479` replaces the patch. Codex's own test, `pre_tool_use_rewrites_apply_patch_before_execution` (`core/tests/suite/hooks.rs:5143`), redirects an `*** Add File:` to another path.
- **The hook sees only the patch's text** (`tool_input.command`, `apply_patch.rs:459-463`), no file list. To redirect a patch, lup would have to read its target paths out of it, which means parsing the agent's patch: `DESIGN.md` drops `apply_patch` parsing (*Runtimes*).
- **An `*** Update File:` needs its redirected target to exist** (`apply-patch/src/file_update.rs:34-45`).
- **A patch sent through the shell** (`apply_patch <<EOF`) fires `PreToolUse` as `Bash`, not `apply_patch` (`unified_exec/exec_command.rs:378-405`).
- **`PermissionRequest` can't rewrite.** Its `updatedInput` "fail[s] closed today" (docs; `hooks/src/engine/output_parser.rs:401-414`): the decision is dropped and the normal approval follows.
- **`PostToolUse` can't undo a write** ("It can't undo side effects from a tool that already ran").

So on Codex, drafts are made at the checkpoint, after the patch lands, with no parsing (*The two runtimes*, decision 8).

## Drafts

### What gets a draft

- **What the judge asks about, unchanged:**
  - a new production file, or a whole-file overwrite;
  - a public-API change;
  - an added `# lup: ignore`;
  - a protected path;
  - one of the operator's documents.

  Where the judge answered `ask` (Claude Code) or held the call (Codex), the change becomes a draft.
- **Refuse still wins.** A write with lup's findings on the lines it touches is refused as now, every finding listed and the agent's version saved. A draft is never a way past the rules.
- **Once a file has a draft, every write to it goes into the draft,** whatever that write would get on its own. Each write is still judged by the rules as a write to the file, so a finding refuses it and the draft stays as it was.
- **An approval covers the path's design asks for the session,** as it does now (`docs/judging-writes.md`, decision 34). Once a new module is approved, later edits land in it directly. A protected path, an operator's document and each added `ignore` still ask every time, so each starts a draft again.

### Where drafts live

**At `<worktree>/.lup/drafts/<path>`:** one draft per file, per worktree.
- **The path is escaped.** Each segment of the file's path that starts with a dot has that dot written `%2E`, so `.claude/settings.json` has its draft at `.lup/drafts/%2Eclaude/settings.json`. Claude Code refuses a hook-approved write into any directory it protects, at any depth (run 7).
- **lup's record of each draft** is kept in the worktree's store, beside the accepted tree (`drafts.json`). It holds:
  - the file;
  - the draft's path;
  - its base: the file's accepted content when the draft began, kept as a blob in the store;
  - the conversation that began it (the session, and the subagent where there is one);
  - the submission it's in, if any.

Why there:
- **`.lup/` is ignored by git.** So the checkpoint's snapshot never sees a draft, git never commits one, and ruff passes over them.
- **pytest and pyright skip directories whose name starts with a dot** (pytest's default `norecursedirs` holds `.*`, pyright's default `exclude` holds `**/.*`). In this repository their settings reach only `packages/` anyway. No import path reaches `.lup/` either. A draft never runs.
- **The agent's file tools and its shell reach it,** which they must: the agent keeps editing its draft.

### How the file tools reach them, on Claude Code

| The call | The file has no draft | The file has a draft |
|---|---|---|
| Write the file | Judged as now. If it asks, it's answered `allow` with `updatedInput` pointing it at the draft's path, and the draft begins with the file's accepted content as its base | Judged as a write to the file; redirected into the draft |
| Edit the file | Judged as now. If it asks, the hook first copies the file as it stands to the draft's path, recording its accepted content as the base, then redirects the Edit there (run 2) | Redirected into the draft, once Claude Code's own check passes: the file must exist, have been read and hold `old_string`. Otherwise its own error (runs 3 and 4) |
| Write or Edit the draft's path | A write under `.lup/drafts/` with no record begins a draft of the file its path names, judged as a write to that file | Judged as a write to the file; it lands where it's addressed |
| Read the file | As now | Where the file exists: not redirected. It shows the file as the shell sees it, with a note naming the draft. Where the file exists only as a draft: redirected to it (run 1) |

- **The result names the draft's path.** The real path isn't put back (decision 6).
- **The note, at a draft's beginning:** "lup put this change in a draft at `<draft>`, since `<what's asked>`. `<file>` is unchanged: the shell, the tests and git see it as it was. Keep editing the draft; when it's ready, submit it with `lup-dev submit <file> "<what changes and why>"`, and run `lup-dev wait <file>` if your next step needs it." Later writes into the draft get one line.
- **When Claude Code refuses an Edit addressed to a drafted file:** this happens when the file exists only as a draft, or when the text is one only the draft holds. The agent gets Claude Code's own error. A `PostToolBatch` hook adds a line naming the draft (a check owed).
- **Grep and Glob don't see drafts,** since they're ignored; `lup-dev drafts` lists them (*Lifecycle*).
- **The judge must be the only `PreToolUse` hook that rewrites a call.** aib found that a later hook's answer discards an earlier `updatedInput` (`DESIGN.md`, *Field Notes*). In this repository it is the only one.

### What the shell and the tests see

The file as last accepted. A test importing a module that exists only as a draft fails to import. That's the signal to submit it and wait (*Waiting*). Copying a draft into `tmp/` to try it is scratch, and allowed; the operator sees none of it.

### The checkpoint and drafts

- **Drafts are ignored, so no snapshot holds them.** A shell write into a draft (`sed -i` on it) is judged at submit, when the draft is judged whole.
- **A shell write that asks is drafted, not refused or held.** This is decision 7; Codex's `apply_patch` is a shell write here. The file goes back to its accepted content, and the content written goes into its draft, which begins there. The agent is told "lup staged your change to `<file>` as a draft at `<draft>`". Until the checkpoint, the content stands in the file: for the rest of that call, and for calls running beside it.
- **A judged shell write to a file that has a draft is merged into the draft,** and the file goes back. The merge is three-way, with `git merge-file`: the draft's base, the draft, and the write. A conflict refuses the shell write as a refusal does now (put back, the version saved), and the draft is left as it was.
- **Content the checkpoint sets aside** (committed elsewhere, a merge, a move of `HEAD`) isn't the session's write, so it's never drafted. When it changes a drafted file, the draft is behind (below).
- **A move's asks stay as now.** A commit made through the shell is judged once, never put back, and its asks are kept as a hold no agent waits on (`docs/judging-writes.md`, step 4).
- **An applied approval is judged content.** Applying one (below) records each file's new content in the session's record, as a file tool's finished write is recorded. The checkpoint accepts it without judging it again.
- **A deletion that asks** (a protected file or an operator's document removed through the shell) is drafted as a deletion: the file comes back, and the draft records that it's deleted.

### When the file moves under a draft

A pull, a merge or another session's edit can change a drafted file. The draft's base then no longer matches the file. At the next checkpoint, lup rebases the draft with `git merge-file`: the old base, the file's new content, and the draft.
- **Clean:** the draft takes the merge, and its base becomes the file's new content. The agent is told.
- **Conflicts:** the markers are left in the draft, and the agent is told. `lup-dev submit` refuses the draft until they're gone.

Either way, a submission waiting with the file in it is withdrawn, since the version it shows was made against the old file.

## Submitting

```
lup-dev submit [--why "<what the change is for>"] <file> "<what changes in it, and why>" [<file> "<…>"]...
```

- **Each file is named by its own path;** its draft's path is accepted too.
- **Its context is required:** one or two plain sentences, as the first lup asked. What changes, then why, naming the function or command, and whether behaviour changes. The operator decides from these words.
- **`--why` speaks for the whole.** It's optional with one file, whose context then heads the review.

What it does:
1. **Judges each draft whole, as a write to its file against the accepted content.**
   - Lup's rules: a finding refuses the whole submission, every file's findings listed, as a refusal lists them. Nothing is parked.
   - The asks, which the review lists for each file.
   - A draft that no longer asks anything (the agent took the new class back out, say) is applied at once and shown in the review as context.
2. **Shows a landed file named in it as context:** its diff since the session started there, with nothing to apply (decision 10). That's how a new module comes with its tests.
3. **Records the submission:** a number, then each file with its context, its base, and the version submitted. The submitted versions are kept under `.lup/review/<n>/`.
4. **Parks one review** in the dashboard, holding every file (*What the operator sees*).
5. **Prints** the review's id, its files, and the wait command.

- **A file submitted again while its review waits supersedes the review.** The waiting review is withdrawn, and a new one is parked holding all its files: those named again at their draft as it stands, the rest at the version submitted before. Both contexts are kept.
- **It refuses:**
  - a path that's neither a draft nor a landed change;
  - a draft that still holds conflict markers;
  - an empty context.

## What the operator sees

Only submissions; drafts never appear. In the bridge they're shown in the first lup's dashboard, as one `Propose` per submission, through `lup_dev/legacy_dashboard.py`. That's how the installer already parks the judge's review (`docs/judging-writes.md`, *The judge's review, in the dashboard*):
- **The review's heading** is the `--why`.
- **Each file is a fold.** Its header says whether the file is created, overwritten or deleted, then gives its context and its asks: why it needs review, or "context, already landed". Inside is the whole diff, highlighted, as the installer's review shows it.
- **The before side is exported to `.lup/review/<n>/`,** and the page shows each path under it, as the installer's export does. Removing the export is how a review is withdrawn: the dashboard retires a review whose recorded files don't stand on disk as recorded, and the host offers no other way.
- **A desktop notice** is raised when a review is parked, as the interim hook does now.
- **The first lup expires a review an hour after it's parked** when its requester isn't on its roster, which no bridge session is. Something must park it again, or a submission from an agent that's gone idle vanishes from the page (decision 13).

## Answers

### Approval

The approval is carried out by whichever comes first:
- the agent's `lup-dev wait`;
- the session's next checkpoint, where no call is running, so no call sees files change under it.

Both run in the agent's environment; the dashboard runs nothing. In one step, under the store's lock:
1. **Check** that each file still holds the base it was submitted against. If one doesn't, nothing is applied: the review is stale, and the agent is told why.
2. **Write** every file's submitted version, or delete it where the change deletes it: all of them or none.
3. **Record** each file's new content in the session's record as judged and approved. The checkpoint then accepts it, and the approval covers the path's design asks for the session.
4. **Log** the operator's answer in the verdict log, against the drafts' verdicts.
5. **Spend** the approval in the first lup's host (`docs/judging-writes.md`, decision 110), so the dashboard shows the review carried out.
6. **Settle each draft:**
   - one that still equals its submitted version is removed;
   - one edited since stays, its base now the submitted version, so it holds only the later edits.
7. **Remove** `.lup/review/<n>/`.

The agent hears: "The operator approved submission `<n>`; lup applied it: `<files>`", with the note and the line comments.

### Decline

Nothing on disk changes. The file was never touched, and the draft is the agent's version, still where it was, so nothing needs saving, unlike a refusal. `DESIGN.md`'s "a declined change is restored, never lost" holds as it stands.
- **The note and the line comments reach the agent:** `wait` prints them, and the next checkpoint tells them once.
- **They stay with the submission's record,** and `lup-dev drafts` shows them beside the draft until it's submitted again.
- **The agent revises the draft and submits it again.**

### Line comments

Each comment is anchored to lines of one file, on its before or after side (the first lup's `LineComment`). Paths come back from the export to the file's own path, printed `path:first-last (side): note`, as the installer prints them.
- **An after-side comment counts lines in the version submitted,** which `.lup/review/<n>/` keeps until the answer is read. Where the draft changed since, the message says so and names the submitted copy.
- **A remark** (comments sent before deciding) is passed on when it's read, as the installer does.

## Waiting: the agent freezes itself

```
lup-dev wait [<file or review>...]
```

- **Blocks until every review named is answered,** with no cap. With no argument it waits on every review open in the worktree.
- **Applies each approval** (above), and prints each answer:
  - approved and applied, with the files;
  - declined, with the note, the comments and the draft's path;
  - stale or withdrawn, with why and what to do.
- **Exits** 0 when everything named is approved and applied; 1 when anything was declined; 2 when anything couldn't be applied, or there was nothing to wait on.
- **Parks a review again** when the first lup expires it, as the installer does.

**When to run it:** when the next step needs the change: importing it, running tests on it, building on the operator's answer. Otherwise the agent carries on, with no cap on how many reviews are open. It needn't run `wait` to hear an answer: answers reach it at its next checkpoint, already applied when approved.

**How it holds, on Claude Code:** a `wait` run in the foreground is a hold inside the call, released by the answer.
- Claude Code's Bash ceiling is 10 minutes unless `BASH_MAX_TIMEOUT_MS` raises it (its environment-variable reference). So `.claude/settings.json`'s `env` sets it to a day, 86,400,000 ms, a Codex hold's day, and the agent passes that `timeout`.
- If the runtime still moves the command to the background, it wakes the agent when the command exits. A local session has no time limit on background commands (its tools reference).
- A hold past the hour costs a cache rebuild, which `DESIGN.md` accepts.
- lup's own wait tool, when it comes, holds inside its call (`DESIGN.md`, *Sessions*) and replaces this command.

## The race: edits after submitting

The operator flagged this race: the agent keeps editing a file whose review waits.
- **The approval pins the version submitted:** that's what's applied, whatever the draft holds by then.
- **Edits made after submitting go into the draft as before,** and the review doesn't change.
- **Once approved,** a draft equal to the submitted version is removed. One edited since stays as a draft whose base is the version just applied, so its diff is only the later edits, to be submitted in turn.
- **Once declined,** the draft stays, later edits and all.
- **To show the operator the newer version before they answer,** the agent submits the file again, which supersedes the review.

**The first lup's guard stays:** apply only where every file still stands as recorded (step 1 of *Approval*). With drafts the agent's own edits can't move the file, so the guard trips only for a change from elsewhere, and the draft is rebased first (*When the file moves under a draft*).

## Lifecycle

- **Drafts last across turns and sessions,** per worktree, and never expire. A session that ends leaves its drafts for the next one in the worktree.
- **Listed:**
  - `lup-dev drafts` shows each drafted file, its draft's path, who began it, and its state: a draft, in review `<n>`, declined (with the note), or behind its file. It also lists the open reviews.
  - A session's start (new, resumed, cleared or compacted) tells the agent the worktree's drafts and open reviews, where there are any.
- **A session's own turn's end doesn't hold on drafts.** It tells the operator, in `systemMessage`, which drafts are left unsubmitted and which reviews wait: the channel `docs/judging-writes.md` uses for what doesn't hold a turn (decision 126). Anything a turn's end tells the agent continues the turn.
- **A subagent's end with drafts it began and didn't submit blocks once,** listing them: "submit them, or drop them". After a block it ends, telling the operator, as #32's turn's end does.
- **A worker's submissions still waiting when it hands back are its session's.** They apply at the session's next checkpoint, and whoever lands the branch commits them. A draft isn't in the worktree's files, so a worker can't commit one.
- **Cleared:**
  - by its approval, once the draft equals its submitted version;
  - by `lup-dev drafts drop <file>`, the agent's own choice;
  - when its worktree is removed.

## Commands and the other prompts

- **Protected files and the operator's documents draft like every ask.** A file in a directory Claude Code protects gets an escaped draft path. The approval is applied by lup rather than by a file tool, so Claude Code's own prompt for that directory never fires: the operator reviews the submission instead. So edits to `DESIGN.md` or to `.claude/settings.json` reach the operator in a submission, with context, however many edits made them (decision 20).
- **A command has nothing to stage.** This covers a push, any command outside the narrow allow rules, and a WebFetch. It stays with the interim hook, which parks it at once as its own review, through `PermissionRequest`. The lean (decision 21):
  - the hook's `wait` runs the approved command where the agent would have, in its recorded working directory and the agent's environment, and prints what it printed;
  - nothing is repeated, as `DESIGN.md` wants;
  - the refusal's text says the command is parked, rather than reading as a failure.

  A push needing review goes this way, until pushes go through the host's services in containers (`DESIGN.md`, *Policy*).

## The two runtimes

| | Claude Code | Codex |
|---|---|---|
| A file tool's write that asks | Redirected into its draft before it lands (`updatedInput`) | `apply_patch` lands; the checkpoint puts the file back and stages the content in its draft |
| A shell write that asks | Staged at the checkpoint | Staged at the checkpoint |
| A write to a drafted file | A file tool's is redirected; a shell write is merged at the checkpoint | Merged at the checkpoint; or the agent patches the draft's path, judged as the file |
| How long asked content stands in the file | Never, for a file tool; until the checkpoint, for a shell write | Until the call's checkpoint, as a refused patch does now |
| Submit, wait, list drafts | `lup-dev submit`, `wait`, `drafts` | The same commands |
| A long `wait` | A foreground hold, ceiling raised by `BASH_MAX_TIMEOUT_MS` | A long-running command the agent polls in its exec session (a check owed) |
| Hearing an answer | At the next checkpoint, beside the call's result | The same |
| Holds an agent waits on | None | None: drafts replace them. A move's holds stay on both |

**The declared difference:** on Codex an asked change stands in the file for the rest of its call. Codex could redirect before the patch lands, through `PreToolUse`'s `updatedInput`, if lup read the patch's target paths with a parser of its format. That isn't proposed (decision 8).

## What it replaces in the bridge

- **Goes, for writes:**
  - the path from the judge's `ask`, through Claude Code's prompt, the interim hook's `PermissionRequest`, a refusal and a background `wait`, to the exact repeat;
  - the holds an agent waits on, on Codex;
  - the interim hook's queue entries for writes.

  The hook's own `PreToolUse` write review, already unregistered, goes once no session started with the old settings runs (`docs/judging-writes.md`, decision 66).
- **Stays until the bridge ends:**
  - the interim hook on `PermissionRequest`, for every prompt that isn't a file tool's write;
  - its `PostToolBatch` notes;
  - its `wait`, which also runs approved commands if decision 21 is taken;
  - `legacy_dashboard.py`, which grows a queue for submissions and the keeper (decision 13).
- **When lup's own dashboard and tools land** (`DESIGN.md`'s build order, 4 and 5):
  - submissions park in lup's own dashboard, with no expiry, no export and no keeper;
  - `wait` becomes lup's tool, holding inside its call.

## Modules and public API

All in `packages/lup-dev/src/lup_dev/`.

**New:**

| Module | What it's for | Public API |
|---|---|---|
| `policy/drafts.py` | The drafts of a worktree: where each lives, its base, beginning one, merging a write into one, rebasing, dropping | `Draft` (file, draft path, base, began by, submission); `Drafts` (one worktree's: `of(path)` for a file or its draft's path, `begin`, `merge`, `rebase`, `drop`, `all`); `draft_path(worktree, file)` |
| `policy/submissions.py` | Submitting drafts: judging each whole, recording the submission, parking it; carrying out an answer | `Submission`, `SubmittedFile` (file, context, base, version submitted, whether it's context only); `submit`, `apply`, `wait` |
| `review.py` | What reviews share: the operator's answer, and the seam to wherever reviews are parked | `Answer` and `LineComment`, moved from `install.py`; `Queue`, an ABC: `park(submission) -> str`, `look(review) -> Answer \| None`, `spend(review)`, `withdraw(review)` |

**Changed:**
- **`legacy_dashboard.py`:** `LegacyQueue`, a `Queue`, beside `LegacyDashboard`, both through `Host`; and the keeper, a hidden `lup-dev review keep <worktree>` like `importers`.
- **`install.py`:** `Answer` and `LineComment` imported from `review.py`.
- **`policy/before.py`:**
  - `Decision.outcome` gains `"draft"`, with the draft's path;
  - a Read of a drafted file gets its note, or its redirect.
- **`policy/runtime.py`:** `asks_before()` becomes `redirects()`, saying whether the runtime can point a file tool's call at another path before it runs.
- **`policy/checkpoint.py`:**
  - staging asked shell writes;
  - merging writes into drafts, and rebasing drafts;
  - carrying out answers at a checkpoint;
  - what a session's start, a turn's end and a subagent's end say about drafts.
- **`policy/holds.py`:** holds an agent waits on go; a move's holds stay.
- **`policy/verdicts.py`:** a `draft` outcome; a submission's answer logged against its drafts' verdicts.
- **`policy/report.py`:** the new messages.
- **`adapters/claude.py`:**
  - `PreToolUse` answers `allow` with `updatedInput` and its note, and handles `Read`;
  - a `PostToolBatch` handler for the hint.
- **`adapters/codex.py`:** no holds for asks.
- **`layout.py`:** `CheckoutLayout.drafts` and `CheckoutLayout.review(n)`.
- **`cli.py`:**
  - `lup-dev submit`, `lup-dev wait`, `lup-dev drafts` and `lup-dev drafts drop`;
  - `lup-dev holds` keeps a move's holds.

**Outside the package:**
- **`.claude/settings.json`:** `env.BASH_MAX_TIMEOUT_MS`; the judge on `PostToolBatch`; narrow allow rules for the three commands (decision 22).
- **`.claude/hooks/interim_review.py`:** its `wait` runs approved commands (decision 21).
- **`docs/judging-writes.md`:** where it says the judge asks, it points here.

## Checks owed

- **`PostToolBatch` explaining a refused Edit:** whether its hook reads the batch's refused Edit and adds a line the agent sees before its next request.
- **An escaped draft path, `%2Eclaude`,** passing Claude Code's protected-path check.
- **A foreground Bash call held for hours** under a raised `BASH_MAX_TIMEOUT_MS`, as a `PreToolUse` hold of 4 hours ran cleanly (`DESIGN.md`, *Field Notes*). Also whether a subagent's call moved to the background wakes that subagent.
- **Codex:**
  - a staged `apply_patch`, end to end;
  - how `lup-dev wait` holds there: its exec session's limits, and whether polling it costs requests.
- **Claude Code's read state:** why an Edit after the approval needed no fresh Read (runs 4 and 5). Nothing here depends on it, since the agent reads before it edits anyway.

## Decisions

Each is numbered so it can be answered "leaning", "undecided" or "leave open", with its alternatives and my lean. All are the operator's until answered.

1. **A write that asks goes into a draft, and the call succeeds.** On Claude Code, the judge answers `allow` with `updatedInput` pointing at the draft. *Alternatives:* the interim hook's refusal, queue and exact repeat, as now; a refusal telling the agent to write the draft itself (the first lup's `tmp/cdx/<path>`), which keeps the error framing; Claude Code's prompt held until answered, which the operator found slow. *Lean:* the draft. *Where:* `policy/before.py`, `adapters/claude.py`. It reshapes `DESIGN.md`'s "the call is refused at once, saying so" for writes.
2. **Drafts live at `<worktree>/.lup/drafts/<path>`,** each dot-segment escaped (`%2E`). *Alternatives:* lup's state directory outside the worktree, out of an agent's reach once in a container but then not reachable by its file tools without a mount; `tmp/drafts/`, which mixes drafts into the agent's own scratch; unescaped paths, which Claude Code refuses under `.claude/` or `.git/` (run 7); a flat numbered name per draft, safe but unreadable. *Lean:* `.lup/drafts/`, escaped. *Where:* `policy/drafts.py`, `layout.py`.
3. **One draft per file per worktree,** shared by the session and its subagents, each recording who began it. *Alternative:* per session, which loses drafts when a resumed or forked session gets a new id, and hides a worker's drafts from the session landing its branch. *Lean:* per worktree. *Where:* `policy/drafts.py`.
4. **A Read of a drafted file shows the file as the shell sees it, with a note naming the draft;** a file that exists only as a draft is redirected. *Alternative:* redirect every Read to the draft, which works (run 6) and keeps the agent's view on what it wrote. But Claude Code checks an Edit against the real file, so an agent editing what it read in the draft gets "String to replace not found" (run 4), and its view would disagree with the shell and the tests. *Lean:* the note. *Where:* `policy/before.py`, `adapters/claude.py`.
5. **Every write to a drafted file goes into its draft:** redirected where the runtime can, merged three-way at the checkpoint otherwise. *Alternatives:* refuse writes to the file with a pointer to the draft, an error again; let them land on the file, which moves the draft's base under it. *Lean:* into the draft. *Where:* `policy/before.py`, `policy/checkpoint.py`, `policy/drafts.py`.
6. **A redirected call's result names the draft's path.** *Alternative:* put the real path back with `updatedToolOutput` (works, run 4), which hides the draft from an agent that must address it when Claude Code's check refuses an Edit of the real file (runs 3 and 4). *Lean:* name the draft. *Where:* `adapters/claude.py`.
7. **A shell write that asks is staged at the checkpoint on both runtimes:** the file put back, the content into its draft. *Alternatives:* refused with a pointer to the file tools on Claude Code, and held on Codex, as now; the reason for refusing was to bring the change to the prompt, and drafts have no prompt to bypass. *Lean:* staged. *Where:* `policy/checkpoint.py`.
8. **Codex's `apply_patch` is staged at the checkpoint, not redirected before it lands.** *Alternative:* `PreToolUse`'s `updatedInput` rewriting the patch, which Codex supports and tests, but which needs the patch's target paths read with a parser of its format, which `DESIGN.md` drops; it also misses a patch sent through the shell. *Lean:* the checkpoint, declaring that the content stands in the file for the rest of the call. *Where:* `policy/checkpoint.py`, `adapters/codex.py`.
9. **`lup-dev submit [--why …] <file> "<context>" [<file> "<context>"]...`,** with a context required for each file. *Alternatives:* repeated options (`--file X --about "…"`), wordier but with no pairs read by position; the first lup's directory with a `.proposal.json` manifest; `--why` required. *Lean:* the operator's pairs, `--why` optional. *Where:* `cli.py`, `policy/submissions.py`.
10. **A landed file named in a submission is shown as context:** its diff since the session started, nothing applied. *Alternative:* drafts only, so a new module reaches the operator without its tests beside it. *Lean:* yes, lightly. *Where:* `policy/submissions.py`.
11. **A submission is judged whole at submit.**
    - A finding refuses the whole submission.
    - A draft that no longer asks is applied at once and shown as context.

    *Alternatives:* park it and let the files with findings go stale, as nothing judges a draft's shell edits until then; send a draft that no longer asks to the operator anyway. *Lean:* judged whole. *Where:* `policy/submissions.py`.
12. **The review is parked in the first lup's dashboard as one `Propose`,** with its before side exported to `.lup/review/<n>/`. *Alternative:* record the before side at the file's own path, so the page shows the real path and the dashboard itself retires the review if the file moves, but nothing can then withdraw it, which superseding needs. *Lean:* the export, as the installer's review does. *Where:* `legacy_dashboard.py`.
13. **A keeper keeps each submission in the first lup's dashboard past its hour.** `lup-dev submit` starts it if none runs: one per worktree under a lock, like the importers pass. It parks expired reviews again and exits once nothing waits. *Alternatives:* park again only when the agent's hook or `wait` looks, so the review of an agent that's gone idle vanishes after an hour; put sessions on the first lup's roster, which couples the bridge to its coordination. *Lean:* the keeper. *Where:* `legacy_dashboard.py`, `cli.py`.
14. **An approval is carried out by the agent's `wait` or the session's next checkpoint, whichever comes first.**
    - All of a submission's files or none.
    - Only where each file still holds its base.
    - Recorded as judged content, so the judge accepts it in the same step.

    *Alternatives:* `wait` alone, so an agent that never waits never gets its change; the dashboard, which runs on the host outside the wall (`DESIGN.md` rules it out). *Lean:* either. *Where:* `policy/submissions.py`, `policy/checkpoint.py`.
15. **A decline leaves the draft where it is.** The note and comments are told once and kept with the submission. *Alternative:* move the draft to `.lup/saved/`, as a refusal saves a version, where nothing was put back. *Lean:* leave it. *Where:* `policy/submissions.py`.
16. **Edits after submitting stay in the draft.** The approval applies the version submitted; the draft, if edited since, stays with only the later edits. *Alternatives:* refuse writes to a draft while its review waits, which stops the agent; apply the newest draft, which the operator never saw. *Lean:* stay. *Where:* `policy/submissions.py`, `policy/drafts.py`.
17. **Submitting a file again while its review waits supersedes the whole review.** *Alternatives:* refuse until it's answered; withdraw only the files named again, splitting what was submitted together. *Lean:* supersede. *Where:* `policy/submissions.py`.
18. **The freeze is `lup-dev wait` in the foreground,** a hold inside the call with a day's ceiling (`BASH_MAX_TIMEOUT_MS`). *Alternatives:* in the background, woken when it exits, which is today's bookkeeping; no wait at all, relying on the next checkpoint, which needs another call to come. *Lean:* the foreground hold now, lup's own wait tool later. *Where:* `cli.py`, `policy/submissions.py`, `.claude/settings.json`.
19. **Lifecycle:**
    - drafts last until approved, dropped, or their worktree goes;
    - a session's turn's end tells the operator, without holding;
    - a subagent's end blocks once on drafts it didn't submit;
    - a session's start lists them.

    *Alternatives:* every turn's end holds on unsubmitted drafts, which keeps a main session from stopping to talk; nothing at all, which loses a worker's drafts at hand-back. *Lean:* as listed. *Where:* `policy/checkpoint.py`.
20. **A file in a directory Claude Code protects is reviewed through its submission,** not Claude Code's own prompt, since lup applies the approval. *Alternative:* keep those files out of drafts and on Claude Code's prompt, which goes through the interim hook's queue and repeat. *Lean:* through the submission. *Where:* `policy/drafts.py`.
21. **A command needing review stays with the interim hook,** parked at once. Its `wait` runs the approved command for the agent, so nothing is repeated, and the refusal says the command is parked. *Alternatives:* as now; a submission that names a command to run once its files are approved, which waits for the host's services. *Lean:* `wait` runs it. *Where:* `.claude/hooks/interim_review.py`.
22. **The agent runs the installed judge's commands, never a worktree's copy,** since `submit` judges and `wait` writes the judge's store (`docs/judging-writes.md`, decision 17). The bare name finds the worktree's copy first: in this session, `which -a lup-dev` lists `tree/dev/.venv/bin/lup-dev` before `~/.local/bin/lup-dev`, under the session's `VIRTUAL_ENV`.
    - *Alternatives:* the bare name, which runs whichever copy the `PATH` holds first; `"$(uv tool dir --bin)/lup-dev"`, as the hooks run it, which no narrow allow rule can match.
    - *Lean:* guidance spells `~/.local/bin/lup-dev`, with narrow allow rules for it, and each command refuses when it isn't the installed copy, naming that path.

    *Where:* `cli.py`, `.claude/settings.json`, `AGENTS.md`'s *Tools* (the operator's).
23. **The dashboard shows no drafts.** *Alternative:* list them on the agent's row as "being written", once lup's own dashboard exists. *Lean:* none now; revisit with lup's dashboard.
24. **`Answer` and `LineComment` move from `install.py` to a new `review.py`,** with the `Queue` seam. *Alternative:* `policy/submissions.py` imports them from `install.py`, tying submissions to the installer. *Lean:* the move. *Where:* `review.py`, `install.py`.
