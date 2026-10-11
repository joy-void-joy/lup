# Reviews: drafts, submissions, and the agent's own wait

**One sentence:** A write the operator must review goes into a draft instead of the file, so the call succeeds. The agent submits its drafts through lup's own tools, in bulk, each with what it changes and why, and the operator sees only what's submitted. Each answer reaches the agent once. An approved change is carried out when the agent waits for it, or at its turn's end, never mid-task, and the judge accepts it in the same step.

This piece is about how a change the judge asks about reaches the operator and comes back. *What* is asked stays the judge's (`docs/judging-writes.md`, *What each change gets*). It closes #16: bundling, and approved changes carried out for the agent. It replaces the bridge's interim review (`.claude/hooks/interim_review.py`): refused at once, a background `wait`, then "repeat this exact call". `DESIGN.md`'s *A review queues; the agent carries on* is the design it builds on. This note proposes reshaping that section's first sentence, since a write needing review is no longer refused (decision 1).

## What went wrong, and what answers it

| What went wrong in practice | What answers it here |
|---|---|
| A write needing review came back as a tool error ("Queued for the operator's review… repeat this exact call") | The call succeeds: the write lands in a draft, and one line beside the result says so |
| The bookkeeping of background waits and exact repeats | Nothing is repeated, and the default is no wait at all: each answer arrives with the agent's next call. The agent waits only to freeze |
| Two edits to one file needed two approvals, the second recorded against the file before the first (#16) | One draft per file, so every edit to it is one change, submitted once |
| A worker's repeat wasn't exact, leaving stale records | There's no repeat to get wrong |
| Edits to a file while its review waited made the review stale | The file doesn't change while its review waits: edits go into the draft, and the approval applies the version the operator saw |
| Agents routed around a long wait: an hour testing a scratch copy, or switching from Write to Edit | Nothing is refused, so there's nothing to route around. An Edit of a drafted file goes into the same draft. What the agent needs to run, it submits and waits on |
| In the first lup, the operator didn't know what was theirs to review and what the agent was still writing | Drafts are never shown. The operator sees a change when the agent submits it, with its context |
| In the first lup, agents complained of being pinged again and again about the same thing | Each answer is told once, never again (*Told once, never re-told*) |

## Two rules

### Told once, never re-told

Each answer the operator gives (an approval, a decline, a remark) is told to the agent exactly once:
- by `wait`, when the agent is waiting on that review;
- otherwise, with the agent's next call after the answer arrives, beside that call's result.

It's never told again. Afterwards, the agent finds it only when it asks, through `reviews`.

**The reason:** the first lup's agents complained of exactly this. A reminder about something already told is noise that spends the agent's attention and turns, and nothing new is learned from it.

Any reminder is the operator's, never the agent's. An approved command the agent hasn't run stays in its `reviews` list, and shows in the operator's dashboard as "approved, not yet run". Whether to nudge the agent is then the operator's call.

The same holds for drafts. Their one line is said once per file, when the file is first drafted (decision 1).

**The same holds for the operator: parking a review again is silent.** The first lup's dashboard expires a review an hour after it's parked, and the keeper parks it again (decision 20). That re-park raises no desktop notice and sends no message to anyone, and a frozen mark carries over to the new id without one either. The operator was told when the change was first submitted, and when an agent first froze on it. A notice at each re-park would repeat every hour for as long as the review waits; the interim hook did exactly that, and is being fixed.

### Nothing approved happens behind the agent's back

- **An approved command runs only when the agent waits for it:** at a moment it chooses, with the command's output in the wait's result.
- **An approved edit applies when the agent waits for it, or at its turn's end on its own,** never mid-task. An approved edit can't be forgotten: if the agent never waits, its turn's end applies it.
- **Neither happens at an ordinary call.** The files an agent is working with don't change under it between two of its calls, except by its own hand.

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
- **`PreToolUse` can rewrite `apply_patch`, the shell, and MCP tools.** It answers `permissionDecision: "allow"` with `updatedInput`. The docs: "To rewrite a supported tool call without blocking, return permissionDecision: "allow" with updatedInput". For `Bash` and `apply_patch`, `updatedInput` must carry the `command`; "For MCP and other local function tools, updatedInput is the replacement arguments object." In the source, `core/src/tools/handlers/apply_patch.rs:466-479` replaces the patch. Codex's own test, `pre_tool_use_rewrites_apply_patch_before_execution` (`core/tests/suite/hooks.rs:5143`), redirects an `*** Add File:` to another path.
- **The hook sees only the patch's text** (`tool_input.command`, `apply_patch.rs:459-463`), no file list. To redirect a patch, lup would have to read its target paths out of it, which means parsing the agent's patch: `DESIGN.md` drops `apply_patch` parsing (*Runtimes*).
- **An `*** Update File:` needs its redirected target to exist** (`apply-patch/src/file_update.rs:34-45`).
- **A patch sent through the shell** (`apply_patch <<EOF`) fires `PreToolUse` as `Bash`, not `apply_patch` (`unified_exec/exec_command.rs:378-405`).
- **`PermissionRequest` can't rewrite.** Its `updatedInput` "fail[s] closed today" (docs; `hooks/src/engine/output_parser.rs:401-414`): the decision is dropped and the normal approval follows.
- **`PostToolUse` can't undo a write** ("It can't undo side effects from a tool that already ran").

So on Codex, drafts are made at the checkpoint, after the patch lands, with no parsing (*The two runtimes*, decision 8).

### MCP tools, on both runtimes

lup's own tools are served over MCP (*lup's own tools*). From each runtime's MCP docs, and Codex's source:

| | Claude Code | Codex |
|---|---|---|
| Where a project declares a server | `.mcp.json` at the project's root ("project scope"), committed; each worktree has its copy | `.codex/config.toml`, `[mcp_servers.<name>]`, "trusted projects only" |
| How a session gets it | Read when the session starts. A project's server needs approval: `enabledMcpjsonServers` in `.claude/settings.json`, honoured in a trusted folder | Read when the session starts, in a trusted project |
| A call's time limit | The server's `timeout` in `.mcp.json`, in ms; unset, `MCP_TOOL_TIMEOUT`, or "about 28 hours" | The server's `tool_timeout_sec`. The docs say it defaults to 60 s; the source says 300 s (`codex-mcp/src/rmcp_client.rs:104`) |
| An idle limit | A stdio server's call with no response and no progress notification for 30 minutes aborts. A per-server `timeout` of at least 1000 ms floors that window (2.1.203 and later) | None documented (a check owed) |
| Backgrounding | "An MCP tool call in the main conversation that is still running after two minutes moves to a background task", unless `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` is `0`. A subagent's calls never move | None documented |
| Prompting | Allowed by a `permissions.allow` rule (`mcp__lup`) | A per-server and per-tool `approval_mode` (`auto`, `prompt`, `writes`, `approve`) |
| What the server learns of its caller | `CLAUDE_PROJECT_DIR` in its environment; no session or subagent | Not documented |
| Hooks | `PreToolUse` and `PostToolUse` fire for MCP tools, named `mcp__<server>__<tool>`, and `updatedInput` replaces their arguments | `PreToolUse` fires for them, and `updatedInput` replaces their arguments |

## Drafts

### What gets a draft

- **What the judge asks about, unchanged:**
  - a new production file, or a whole-file overwrite;
  - a public-API change;
  - an added `# lup: ignore`;
  - a protected path;
  - one of the operator's documents.

  Where the judge answered `ask` (Claude Code) or held the call (Codex), the change becomes a draft.
- **Anything the agent wants the operator's opinion on, on purpose** (*Asking anyway*, below).
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
  - a rename's old path, where it's one;
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
| Read the file | As now | Where the file exists: as now, showing the file as the shell sees it. Where it exists only as a draft: redirected to the draft (run 1) |

- **The result names the draft's path.** The real path isn't put back (decision 6).
- **The first time a file is drafted, one line goes beside the call's result,** in `additionalContext`, which the model read with the result in every spike run:
  > Drafted for review, not landed: `<file>` (the draft is `<draft>`). Keep editing the draft; submit it when it's ready.

  It's said once per file, never again for later writes into the draft or for reads of the file (*Told once, never re-told*).
- **When Claude Code refuses an Edit addressed to a drafted file:** this happens when the file exists only as a draft, or when the text is one only the draft holds. The agent gets Claude Code's own error. That error is new information, not a re-telling, so a `PostToolBatch` hook may add a line naming the draft (a check owed).
- **Grep and Glob don't see drafts,** since they're ignored; `reviews` lists them.
- **The judge must be the only `PreToolUse` hook that rewrites a call.** aib found that a later hook's answer discards an earlier `updatedInput` (`DESIGN.md`, *Field Notes*). In this repository it is the only one.

### Asking anyway

The first lup's `review propose` let a session put a change the gates would let through before the operator: "the session asked anyway". Here, a change becomes a draft on purpose by being written at its draft's path rather than at the file:
- **A new file, or a whole rewrite:** the agent writes it at `.lup/drafts/<path>`.
- **An edit to an existing file:** the agent copies the file there first (`cp`), then edits the copy.

The first file-tool write there begins the draft's record, its base the file's accepted content. A draft with no record by then gets one at submit. The submit tool's description says how, with the escaping rule.

The review shows such a file with "nothing here asks for review; the agent asked for your view" (decision 17).

### Renames

Today a rename is a deletion and a creation, and the creation of a production file asks. So the old file's deletion would land (a deletion is allowed unless the file is protected) while the new file waits in a draft, leaving half a rename in the worktree. Instead:
- **A rename made with the file tools:** the agent writes the new file (it drafts) and names the old path in the file's `renamed_from` when it submits. It leaves the old file in place; the approval removes it.
- **A rename made through the shell** (`git mv`, `mv`) is read at the checkpoint with git's own rename detection (`git diff-tree -M` against the accepted tree), not by comparing content by hand. Where the new path asks, the rename is drafted whole: the old file comes back, and the draft records its old path.

Either way, the review shows the old file deleted and the new one created, with the context naming the move; the first lup's `Propose` has no move of its own. The approval applies both at once.

### What the shell and the tests see

The file as last accepted. A test importing a module that exists only as a draft fails to import. That's the signal to submit it and wait (*`wait`*). Copying a draft into `tmp/` to try it is scratch, and allowed; the operator sees none of it.

### The checkpoint and drafts

- **Drafts are ignored, so no snapshot holds them.** A shell write into a draft (`sed -i` on it) is judged at submit, when the draft is judged whole.
- **A shell write that asks is drafted, not refused or held.** This is decision 7; Codex's `apply_patch` is a shell write here. The file goes back to its accepted content, and the content written goes into its draft, which begins there. The first such draft of a file gets the one line. Until the checkpoint, the content stands in the file: for the rest of that call, and for calls running beside it.
- **A judged shell write to a file that has a draft is merged into the draft,** and the file goes back. The merge is three-way, with `git merge-file`: the draft's base, the draft, and the write. A conflict refuses the shell write as a refusal does now (put back, the version saved), and the draft is left as it was.
- **Content the checkpoint sets aside** (committed elsewhere, a merge, a move of `HEAD`) isn't the session's write, so it's never drafted. When it changes a drafted file, the draft is behind (below).
- **A move's asks stay as now.** A commit made through the shell is judged once, never put back, and its asks are kept as a hold no agent waits on (`docs/judging-writes.md`, step 4).
- **An applied approval is judged content.** Applying one (*Approval*) records each file's new content in the session's record, as a file tool's finished write is recorded. The checkpoint accepts it without judging it again.
- **A deletion that asks** (a protected file or an operator's document removed through the shell) is drafted as a deletion: the file comes back, and the draft records that it's deleted.

### When the file moves under a draft

A pull, a merge or another session's edit can change a drafted file. The draft's base then no longer matches the file. At the next checkpoint, lup rebases the draft with `git merge-file`: the old base, the file's new content, and the draft.
- **Clean:** the draft takes the merge, and its base becomes the file's new content.
- **Conflicts:** the markers are left in the draft, and `submit` refuses it until they're gone.

The agent is told once either way. A submission waiting with the file in it is withdrawn, since the version it shows was made against the old file.

## lup's own tools

The agent submits, waits, lists and replies through four tools: `submit`, `wait`, `reviews` and `reply`. They're served over MCP by the installed judge, the copy the operator reviewed (`docs/judging-writes.md`, decision 17); they aren't shell commands. Why:
- **No `PATH` to get wrong.** An activated worktree environment shadows the installed `lup-dev`: in the first round's session, `which -a lup-dev` listed `tree/dev/.venv/bin/lup-dev` before `~/.local/bin/lup-dev`.
- **Typed parameters.** Each file's context is a field, not a shell-quoted string.
- **The hooks see a named tool** (`mcp__lup__wait`), with its arguments, so nothing parses a command line.

The shell keeps a command line for the operator, from the same code: `lup-dev submit`, `wait`, `reviews` and `reply`.

**The first of `DESIGN.md`'s lup's tools.** Build order 4 lists lup's own tools: spawn, message, wait, ask, handoff. These are the first of that set, and the server is where the rest join. `wait` is meant to grow into the one wait for whatever the agent waits on: reviews now, workers and messages later.

**The minimum to build now:**
- one stdio server, `lup-dev mcp serve`, on the MCP Python SDK (`mcp`), with these four tools over `policy/submissions.py`;
- the judge's hook telling the server who calls (below);
- the two runtimes' configuration.

Spawn, message, ask and handoff come with build order 4; the dashboard's own review page with build order 5.

### The server, and who calls it

- **Configured for Claude Code in `.mcp.json`** at the repository's root, committed:
  - `"lup": {"command": "sh", "args": ["-c", "exec \"$(uv tool dir --bin)/lup-dev\" mcp serve"], "timeout": 86400000, "alwaysLoad": true}`.
  - The command runs the installed copy as the hooks do (`docs/judging-writes.md`, decision 65).
  - `timeout` is a day: it sets each call's wall-clock limit and floors the idle limit.
  - `alwaysLoad` puts the four tools in context from the start, rather than behind tool search. aib found deferred schemas made the agent guess search terms (`DESIGN.md`, *Field Notes*).
- **Configured for Codex in `.codex/config.toml`:** `[mcp_servers.lup]`, the same command, `tool_timeout_sec = 86400`, and an approval mode that lets lup's tools run unprompted.
- **Both files are protected.** `.codex/` is already protected; `.mcp.json` joins the protected defaults in `lup_dev/catalog/paths.py`, since it names what runs. Launch compiles both from the declaration later, as it does every runtime tree (`DESIGN.md`, *How lup reaches a project*).
- **How a session gets it:**
  - Claude Code reads `.mcp.json` when a session starts, and runs the server once `.claude/settings.json` approves it (`enabledMcpjsonServers: ["lup"]`).
  - A `permissions.allow` rule, `mcp__lup`, keeps its tools from prompting.
  - Codex reads its server in a trusted project.
  - A session started before this lands restarts to get it, as for hooks.
- **Who calls:** an MCP server isn't told which session or subagent calls it. Claude Code gives it only `CLAUDE_PROJECT_DIR`. So the judge's `PreToolUse` hook fills a `caller` argument on each call to lup's tools, through `updatedInput`, which both runtimes allow for MCP tools. The argument holds the session, the subagent, the call's id and its working directory. The tools' schema marks `caller` "filled by lup; leave it out", the hook overwrites whatever is there, and a call without it is refused, naming the missing hook (decision 11).
- **What's lost: backgrounding.**
  - An agent can't send a tool call to the background by choice, as it can a Bash command.
  - Claude Code moves a main conversation's MCP call to the background after two minutes on its own. `.claude/settings.json`'s `env` sets `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` to `0`, so a `wait` stays a freeze (decision 13). A subagent's calls never move.
  - With answers arriving at the next call by default, a background wait has nothing left to do.

### `submit`

| Parameter | What it is |
|---|---|
| `files` | A list, each with `path` (the file, or its draft's path), `context` (required: what changes in it, and why), and `renamed_from` (the old path, for a rename) |
| `why` | A short paragraph on the whole change; optional with one file, whose context then heads the review |
| `wait` | Wait for the answer in the same call, as `wait` on this review would |
| `timeout` | With `wait`: return "still waiting" after at most this long |

What it does:
1. **Judges each draft whole, as a write to its file against the accepted content.**
   - Lup's rules: a finding refuses the whole submission, every file's findings listed, as a refusal lists them. Nothing is parked.
   - The asks, which the review lists for each file. A draft that no longer asks anything, or never did (*Asking anyway*), is shown as asked for anyway; it's still the operator's to answer (decision 16).
2. **Shows a landed file named in it as context:** its diff since the session started there, with nothing to apply (decision 15). That's how a new module comes with its tests.
3. **Records the submission:** a number, the calling conversation, then each file with its context, its base, and the version submitted. The submitted versions are kept under `.lup/review/<n>/`.
4. **Parks one review** in the dashboard, holding every file (*What the operator sees*).
5. **Returns** the review's id and its files; with `wait`, the answer.

- **A file submitted again while its review waits supersedes the review.** The waiting review is withdrawn, and a new one is parked holding all its files: those named again at their draft as it stands, the rest at the version submitted before. Both contexts are kept.
- **It refuses:**
  - a path that's neither a draft nor a landed change;
  - a draft that still holds conflict markers;
  - an empty context.

**Its description carries the plain-words guidance,** as the first lup's `review propose --help` did. Proposed text:

> Submit drafts for the operator's review, as one review. The operator decides from your words, so write each file's context the way you'd tell a colleague at their desk. Lead with what changes, in ordinary words, then why. Name the file, function or command. Say what behaves differently, or say "no behaviour change".
>
> One of each kind:
> - A new file, `policy/drafts.py`: "New module: where each draft lives and the file content it started from. `Drafts.begin` copies a file into its draft the first time a write to it needs review. New behaviour."
> - A change, `policy/judge.py`: "`Ask.covered` now also covers a public-API ask on a file approved earlier in the session, so a second signature change in the same class isn't asked again. Fewer asks; nothing else changes."
> - A deletion, `docs/after-call-diff.md`: "Deleted: `docs/judging-writes.md` replaced it. No behaviour change."
> - A rename, `policy/turns.py` with `renamed_from` `policy/checkpoint.py`: "The turn's-end code moved out of `checkpoint.py`, unchanged, since that file had grown past 1,500 lines. No behaviour change."
> - Asking anyway, `policy/report.py`: "The refusal's first line now says how many files were refused. The judge wouldn't ask about this; I'd like your view on the wording before it lands."
> - Context, `tests/test_drafts.py`: "The tests for `drafts.py`, already landed, so you can see what's covered."
>
> Not this: "drafts carry base blobs per the store's record shape". That's terse house style, with the code doing the talking and abstract words standing in for the thing meant.
>
> To ask about a change the judge would allow, write it at its draft's path, `.lup/drafts/<path>`, with a dot that starts a path segment written `%2E`; for an edit, copy the file there first. To rename, write the new file and give the old path as `renamed_from`; leave the old file in place.

### `wait`

| Parameter | What it waits for |
|---|---|
| `review` | One review's answer |
| `any` | The first answer among several reviews |
| `all` | Every answer to the calling conversation's submissions |
| `file` | That file's change being applied: through its review's approval, or a later one if it's declined and submitted again |
| `timeout` | Optional, with any of the above: return "still waiting" after at most this long |

- **It returns each answer it waited for, told once:**
  - approved, then applied, with the files, or with an approved command's output;
  - declined, with the note, the comments and the draft's path;
  - stale or withdrawn, with why and what to do;
  - or "still waiting", at its `timeout`, or a little before the runtime's day.
- **It applies each approval it returns** (*Approval*). Waiting is the agent's moment.
- **When to call it:** only when the next step needs the change: importing it, running tests on it, building on the operator's answer. The default is no wait: the agent carries on, with no cap on how many reviews are open, and each answer reaches it with its next call.
- **How it holds:** inside the call, released by the answer.
  - On Claude Code, the server's `timeout` of a day bounds the call. A progress notification every minute shows the wait's state in `/tasks`.
  - On Codex, `tool_timeout_sec` bounds it.
  - A hold past the hour costs a cache rebuild, which `DESIGN.md` accepts.
- **The dashboard marks a review an agent is frozen on,** so the operator answers those first. The server knows while it waits. In the bridge, the first lup's dashboard has no such mark, so it's carried by:
  - a reply in the review's thread, "an agent is waiting on this review";
  - a desktop notice naming the review.

  lup's own dashboard shows the mark itself, and sorts by it (decision 27).

### `reviews`

Returns the calling conversation's drafts and submissions with their state, read only when the agent asks. The states:
- a draft, not submitted;
- waiting;
- approved, not yet applied, which applies at its next `wait` or its turn's end;
- applied;
- declined, with the note;
- stale or withdrawn;
- for a command, approved, not yet run.

The operator's `lup-dev reviews` lists the whole worktree's. A draft is dropped by deleting its file under `.lup/drafts/`; the next checkpoint forgets its record.

### `reply`

`reply(review, text)` answers the operator on one of the caller's own reviews, in its thread. It settles nothing: the review waits as it did. The first lup's `review reply` did this; its thread keeps the requester's replies in the relay beside the operator's remarks. In the bridge it's written through the first lup's host half (`append_review_record`), in the first lup's own reply record, which `legacy_dashboard.py` models (decision 28). Its description asks for plain words: name the file, function or command, and say what you changed or will change, and why.

## What the operator sees

Only submissions, plus commands parked for review; drafts never appear. In the bridge they're shown in the first lup's dashboard, as one `Propose` per submission, through `lup_dev/legacy_dashboard.py`. That's how the installer already parks the judge's review (`docs/judging-writes.md`, *The judge's review, in the dashboard*):
- **The review's heading** is the `why`.
- **Each file is a fold.** Its header says whether the file is created, overwritten or deleted, then gives its context and its asks: why it needs review, "the agent asked for your view", or "context, already landed". Inside is the whole diff, highlighted, as the installer's review shows it.
- **The before side is exported to `.lup/review/<n>/`,** and the page shows each path under it, as the installer's export does. Removing the export is how a review is withdrawn: the dashboard retires a review whose recorded files don't stand on disk as recorded, and the host offers no other way.
- **A desktop notice** is raised when a review is first parked, and when an agent first freezes on one. Parking it again after an expiry is silent.
- **An approved command not yet run** shows as approved and not carried out: the first lup's dashboard shows an approval nobody has spent that way.
- **The first lup expires a review an hour after it's parked** when its requester isn't on its roster, which no bridge session is. Something must park it again, or a submission from an agent that's gone idle vanishes from the page (decision 20).

## Answers

Each one is told once (*Told once, never re-told*): by `wait` when the agent waits on it, otherwise beside the result of the next call of the conversation that submitted. Where that conversation has ended (a subagent's), it goes to the session's own conversation. It travels as the judge's mail already does, taken when it's read (`docs/judging-writes.md`, decision 128).

### Approval

The agent hears it once: "The operator approved submission `<n>`; it applies when you wait on it, or at your turn's end", with the note and the line comments. When `wait` returns it, it's applied there and then, and said so.

It's carried out by whichever comes first:
- the agent's `wait` on it;
- the end of the turn of the conversation that submitted it: `Stop` for the session's own, `SubagentStop` for a subagent's. Only when no other conversation of the session has a call running in that worktree; otherwise at the next such end.

Never at an ordinary call, and never by the dashboard, which runs on the host outside the wall. In one step, under the store's lock:
1. **Check** that each file still holds the base it was submitted against. If one doesn't, nothing is applied: the review is stale, and the agent is told once why.
2. **Write** every file's submitted version, delete what the change deletes, and remove a rename's old path: all of it or none.
3. **Record** each file's new content in the session's record as judged and approved. The checkpoint then accepts it, and the approval covers the path's design asks for the session.
4. **Log** the operator's answer in the verdict log, against the drafts' verdicts.
5. **Spend** the approval in the first lup's host (`docs/judging-writes.md`, decision 110), so the dashboard shows the review carried out.
6. **Settle each draft:**
   - one that still equals its submitted version is removed;
   - one edited since stays, its base now the submitted version, so it holds only the later edits.
7. **Remove** `.lup/review/<n>/`.

Applied at a turn's end, it isn't told again: the agent heard when it would apply. The turn's end then checks the files it touched as it checks any, so type errors the applied files bring are reported there.

### Decline

Nothing on disk changes. The file was never touched, and the draft is the agent's version, still where it was, so nothing needs saving, unlike a refusal. `DESIGN.md`'s "a declined change is restored, never lost" holds as it stands.
- **The note and the line comments are told once,** and kept with the submission, where `reviews` shows them.
- **The agent revises the draft and submits it again,** or answers with `reply`.

### Remarks and line comments

- **A remark** (the operator's note and comments sent before deciding) is told once, like an answer. The agent may `reply`.
- **Each comment is anchored to lines of one file,** on its before or after side (the first lup's `LineComment`). Paths come back from the export to the file's own path, printed `path:first-last (side): note`, as the installer prints them.
- **An after-side comment counts lines in the version submitted,** which `.lup/review/<n>/` keeps until the answer is read. Where the draft changed since, the message says so and names the submitted copy.

### Commands

A command has nothing to stage: a push, any command outside the narrow allow rules, a WebFetch. When Claude Code would prompt for one, it's parked at once as its own review.
- **The lean, decision 31:** the judge's adapter answers `PermissionRequest` in place of the interim hook. The call is refused with the review's id, worded as parked, not failed: "Parked for the operator's review as `<id>`: `<command>`. Once approved, it runs when you `wait` on it."
- **Approved, it runs only when the agent waits for it:**
  - where it would have run: the call's recorded working directory, with the session's environment (not variables the agent exported in its own shell);
  - its output comes back in the wait's result;
  - its writes are judged at that call's checkpoint, as any write is.
- **Never waited for,** it stays approved and not yet run, in the agent's `reviews` and in the dashboard. Any reminder is the operator's.
- **A push needing review goes this way,** until pushes go through the host's services in containers (`DESIGN.md`, *Policy*).

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
- **Listed when asked:** through `reviews` for the agent, `lup-dev reviews` for the operator.
- **Told once when the agent can't know:** a session's start in a worktree with drafts or open reviews says so once, where the agent's context doesn't hold them: a new session, or one cleared or compacted. A resumed session isn't told; it still remembers.
- **A session's own turn's end doesn't hold on drafts.** It applies what's approved (*Approval*). It tells the operator once, in `systemMessage`, of a draft first left unsubmitted at a turn's end: the channel `docs/judging-writes.md` uses for what doesn't hold a turn (its decision 126). Anything a turn's end tells the agent continues the turn.
- **A subagent's end with drafts it began and didn't submit blocks once,** listing them: "submit them, or delete them". After that block it ends, and the operator is told, as #32's turn's end does.
- **A worker's submissions still waiting when it hands back are its session's.** Their answers go to the session's own conversation, and they apply at its wait or turn's end; whoever lands the branch commits them. A draft isn't in the worktree's files, so a worker can't commit one.
- **Cleared:**
  - by its approval, once the draft equals its submitted version;
  - by the agent deleting the draft's file;
  - when its worktree is removed.

## Protected files, and directories Claude Code protects

Protected files and the operator's documents draft like every ask. A file in a directory Claude Code protects (`.claude/`, `.git/`, `.vscode/` and the others) gets an escaped draft path. The approval is applied by lup rather than by a file tool, so Claude Code's own prompt for that directory never fires: the operator reviews the submission instead. So edits to `DESIGN.md` or to `.claude/settings.json` reach the operator in a submission, with context, however many edits made them (decision 30).

## The two runtimes

| | Claude Code | Codex |
|---|---|---|
| A file tool's write that asks | Redirected into its draft before it lands (`updatedInput`) | `apply_patch` lands; the checkpoint puts the file back and stages the content in its draft |
| A shell write that asks | Staged at the checkpoint | Staged at the checkpoint |
| A write to a drafted file | A file tool's is redirected; a shell write is merged at the checkpoint | Merged at the checkpoint; or the agent patches the draft's path, judged as the file |
| How long asked content stands in the file | Never, for a file tool; until the checkpoint, for a shell write | Until the call's checkpoint, as a refused patch does now |
| `submit`, `wait`, `reviews`, `reply` | lup's MCP server, from `.mcp.json` | The same server, from `.codex/config.toml` |
| The caller | Filled by the judge's `PreToolUse` hook | The same |
| A long `wait` | A day's `timeout`, with progress notifications; not moved to the background, since `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` is `0` | `tool_timeout_sec` of a day |
| An answer told once | Beside the next call's result (`additionalContext`) | The same |
| Commands needing review | Parked through `PermissionRequest`, run by `wait` | Codex's own approval, until host services: its `PermissionRequest` fires only for what its sandbox escalates |
| Holds an agent waits on | None | None: drafts replace them. A move's holds stay on both |

**The declared difference:** on Codex an asked change stands in the file for the rest of its call. Codex could redirect before the patch lands, through `PreToolUse`'s `updatedInput`, if lup read the patch's target paths with a parser of its format. That isn't proposed (decision 8).

## What it replaces in the bridge

- **Goes:**
  - for writes, the path from the judge's `ask`, through Claude Code's prompt and the interim hook, to a background `wait` and an exact repeat;
  - the holds an agent waits on, on Codex;
  - with decision 31, the interim hook whole: `PermissionRequest` and the delivery of what the operator wrote (its `PostToolBatch` notes) move to the judge's adapter, and `.claude/hooks/interim_review.py` is deleted once no session started with the old settings runs (`docs/judging-writes.md`, decision 66).
- **Stays until the bridge ends:** `legacy_dashboard.py`, which grows a queue for submissions and commands, replies, the frozen mark and the keeper.
- **When lup's own dashboard lands** (`DESIGN.md`'s build order, 5):
  - reviews park there, with no expiry, no export and no keeper;
  - the frozen mark is the page's own.

## Modules and public API

All in `packages/lup-dev/src/lup_dev/` unless named otherwise.

**New:**

| Module | What it's for | Public API |
|---|---|---|
| `policy/drafts.py` | The drafts of a worktree: where each lives, its base, beginning one, merging a write into one, rebasing, a rename's old path | `Draft` (file, draft path, base, began by, renamed from, submission); `Drafts` (one worktree's: `of(path)` for a file or its draft's path, `begin`, `merge`, `rebase`, `forget`, `all`); `draft_path(worktree, file)` |
| `policy/submissions.py` | Submitting drafts, waiting, listing and replying: the four tools' behaviour, which the server and the command line share; carrying out an answer | `Submission`, `SubmittedFile` (path, context, renamed from, base, version submitted, whether it's context only), `CommandReview`, `Caller` (session, subagent, call, working directory); `submit`, `wait` (with `Waiting`: one, any, all, or a file, and a timeout), `reviews`, `reply`, `apply` |
| `review.py` | What reviews share: the operator's answers, and the seam to wherever reviews are parked | `Answer`, `Remark` and `LineComment`, the last two moved from `install.py`; `Queue`, an ABC: `park`, `look`, `spend`, `withdraw`, `reply`, `frozen` |
| `server.py` | lup's own tools over MCP: `submit`, `wait`, `reviews`, `reply`, each a typed function over `policy/submissions.py`, with its description | `serve()`; the four tools' parameter models |

**Changed:**
- **`legacy_dashboard.py`:** `LegacyQueue`, a `Queue`, beside `LegacyDashboard`, both through `Host`. It adds replies and the frozen mark. The keeper is a hidden `lup-dev review keep <worktree>`, like `importers`.
- **`install.py`:** `Answer` and `LineComment` imported from `review.py`.
- **`policy/before.py`:**
  - `Decision.outcome` gains `"draft"`, with the draft's path and whether it's the file's first;
  - a Read of a file that exists only as a draft is redirected.
- **`policy/runtime.py`:** `asks_before()` becomes `redirects()`, saying whether the runtime can point a file tool's call at another path before it runs.
- **`policy/checkpoint.py`:**
  - staging asked shell writes, and drafting shell renames whole;
  - merging writes into drafts, and rebasing drafts;
  - applying approvals at a conversation's end;
  - answers as mail, told once;
  - what a session's start and a subagent's end say about drafts.
- **`policy/holds.py`:** holds an agent waits on go; a move's holds stay.
- **`policy/store.py`:** rename detection when comparing with the accepted tree.
- **`policy/verdicts.py`:** a `draft` outcome; a submission's answer logged against its drafts' verdicts.
- **`policy/report.py`:** the new messages.
- **`adapters/claude.py`:**
  - `PreToolUse` answers a draft with `allow`, `updatedInput` and its one line, and fills `caller` on lup's tools;
  - `PermissionRequest` parks commands (decision 31);
  - `PostToolBatch` for the hint.
- **`adapters/codex.py`:** no holds for asks; `caller` on lup's tools.
- **`catalog/paths.py`:** `.mcp.json` protected.
- **`layout.py`:** `CheckoutLayout.drafts` and `CheckoutLayout.review(n)`.
- **`cli.py`:**
  - `lup-dev mcp serve`;
  - the operator's `lup-dev submit`, `wait`, `reviews` and `reply`;
  - `lup-dev holds` keeps a move's holds.
- **`packages/lup-dev/pyproject.toml`:** the `mcp` dependency (decision 10).

**Outside the package:**
- **`.mcp.json`:** new, protected.
- **`.codex/config.toml`:** `[mcp_servers.lup]`.
- **`.claude/settings.json`:**
  - `enabledMcpjsonServers`;
  - `permissions.allow` for `mcp__lup`;
  - `env.CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS = "0"`;
  - with decision 31, the judge on `PermissionRequest` and `PostToolBatch`, and the interim hook's entries removed.
- **`docs/judging-writes.md`:** where it says the judge asks, it points here.

## Checks owed

- **`PostToolBatch` explaining a refused Edit:** whether its hook reads the batch's refused Edit and adds a line the agent sees before its next request.
- **An escaped draft path, `%2Eclaude`,** passing Claude Code's protected-path check.
- **Claude Code and MCP:**
  - a `wait` held for hours under the server's `timeout`, with progress notifications;
  - that `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` in `.claude/settings.json`'s `env` keeps a main conversation's call in the foreground;
  - that `updatedInput` on an MCP tool reaches the server with the `caller` filled.
- **Codex:**
  - a staged `apply_patch`, end to end;
  - the name its hooks give an MCP tool;
  - the `approval_mode` value that runs lup's tools unprompted;
  - whether an MCP call has an idle limit or is ever moved to the background;
  - `tool_timeout_sec`'s real default, which the docs give as 60 s and the source as 300 s.
- **Claude Code's read state:** why an Edit after the approval needed no fresh Read (runs 4 and 5). Nothing here depends on it.

## Decisions

Each is numbered so it can be answered "leaning", "undecided" or "leave open", with its alternatives and my lean. **(agreed)** marks what the operator settled in the first round on #37; the rest are the operator's until answered.

1. **(agreed)** **A write that asks goes into a draft, and the call succeeds.** The first time a file is drafted, one line beside the result says so: "Drafted for review, not landed: `<file>`… Keep editing the draft; submit it when it's ready." It comes once per file, not with every edit. *Alternatives:* the interim hook's refusal, queue and exact repeat; a refusal telling the agent to write the draft itself (the first lup's `tmp/cdx/<path>`), which keeps the error framing; Claude Code's prompt held until answered, which the operator found slow; the line with every write into the draft, which re-tells. *Where:* `policy/before.py`, `adapters/claude.py`. It reshapes `DESIGN.md`'s "the call is refused at once, saying so" for writes.
2. **Drafts live at `<worktree>/.lup/drafts/<path>`,** each dot-segment escaped (`%2E`). *Alternatives:* lup's state directory outside the worktree, out of an agent's reach once in a container but then not reachable by its file tools without a mount; `tmp/drafts/`, which mixes drafts into the agent's own scratch; unescaped paths, which Claude Code refuses under `.claude/` or `.git/` (run 7); a flat numbered name per draft, safe but unreadable. *Lean:* `.lup/drafts/`, escaped. *Where:* `policy/drafts.py`, `layout.py`.
3. **One draft per file per worktree,** shared by the session and its subagents, each recording who began it. *Alternative:* per session, which loses drafts when a resumed or forked session gets a new id, and hides a worker's drafts from the session landing its branch. *Lean:* per worktree. *Where:* `policy/drafts.py`.
4. **A Read of a drafted file shows the file as the shell sees it, with nothing added;** a file that exists only as a draft is redirected to it. *Alternatives:* redirect every Read to the draft, which works (run 6), but Claude Code checks an Edit against the real file, so an agent editing what it read in the draft gets "String to replace not found" (run 4); a note on each Read naming the draft, which re-tells. *Lean:* nothing added. *Where:* `policy/before.py`, `adapters/claude.py`.
5. **Every write to a drafted file goes into its draft:** redirected where the runtime can, merged three-way at the checkpoint otherwise. *Alternatives:* refuse writes to the file with a pointer to the draft, an error again; let them land on the file, which moves the draft's base under it. *Lean:* into the draft. *Where:* `policy/before.py`, `policy/checkpoint.py`, `policy/drafts.py`.
6. **A redirected call's result names the draft's path.** *Alternative:* put the real path back with `updatedToolOutput` (works, run 4), which hides the draft from an agent that must address it when Claude Code's check refuses an Edit of the real file (runs 3 and 4). *Lean:* name the draft. *Where:* `adapters/claude.py`.
7. **A shell write that asks is staged at the checkpoint on both runtimes:** the file put back, the content into its draft. *Alternatives:* refused with a pointer to the file tools on Claude Code, and held on Codex, as now. The reason for refusing was to bring the change to the prompt, and drafts have no prompt to bypass. *Lean:* staged. *Where:* `policy/checkpoint.py`.
8. **Codex's `apply_patch` is staged at the checkpoint, not redirected before it lands.** *Alternative:* `PreToolUse`'s `updatedInput` rewriting the patch, which Codex supports and tests, but which needs the patch's target paths read with a parser of its format, which `DESIGN.md` drops; it also misses a patch sent through the shell. *Lean:* the checkpoint, declaring that the content stands in the file for the rest of the call. *Where:* `policy/checkpoint.py`, `adapters/codex.py`.
9. **(agreed)** **`submit`, `wait`, `reviews` and `reply` are lup's own tools, served over MCP by the installed judge,** with the command line kept for the operator from the same code. These are the first of `DESIGN.md`'s lup's tools. *Alternatives:* shell commands, which an activated worktree environment can shadow with an unreviewed copy, and which carry each context as a shell-quoted string; Bash allow rules naming the installed copy's path. *Where:* `server.py`, `policy/submissions.py`, `cli.py`.
10. **The server is built on the MCP Python SDK (`mcp`), a new dependency of `lup-dev`.** `claude-agent-sdk`, which the library's `lup[claude]` extra uses, already requires `mcp>=1.23,<3`. *Alternatives:* wait for the library's `lup_tool` construct (`DESIGN.md`, *Two packages*) and serve through it, which delays this piece behind the library; `fastmcp`, a separate package; JSON-RPC by hand, which `AGENTS.md`'s libraries-first rules out. *Lean:* `mcp` now, moving to `lup_tool` once it serves MCP. *Where:* `packages/lup-dev/pyproject.toml` (the operator's), `server.py`.
11. **The judge's `PreToolUse` hook tells the server who calls,** filling a `caller` argument through `updatedInput`: the session, the subagent, the call and its working directory. The server refuses a call without it. *Alternatives:* none from the runtimes, since an MCP server isn't told its caller (Claude Code gives only `CLAUDE_PROJECT_DIR`); a server per session reading its parent process, which says nothing of subagents; the agent passing its own ids, which it doesn't know and could get wrong. *Lean:* the hook fills it. *Where:* `adapters/`, `server.py`.
12. **`.mcp.json` and `.codex/config.toml` configure the server, both protected,** with `.mcp.json` added to the protected defaults. Claude Code approves the server through `enabledMcpjsonServers`, and loads its tools up front (`alwaysLoad`). *Alternatives:* each person's own configuration (`~/.claude.json`, `~/.codex/config.toml`), which a project can't review or ship; a plugin, which `DESIGN.md` defers to launch. *Lean:* the project's files. *Where:* `.mcp.json`, `.codex/config.toml`, `catalog/paths.py`, `.claude/settings.json`.
13. **A `wait` holds inside its call for up to a day.** The server's `timeout` sets it, progress notifications report its state, and Claude Code's automatic backgrounding is off (`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0`), so a main conversation's `wait` stays a freeze. *Alternatives:* leave backgrounding on, so a main conversation's `wait` past two minutes becomes a background task and the agent works on: no longer a freeze, and the frozen mark would be wrong; the 28-hour default, a limit no one chose. *Lean:* as stated. *Where:* `.mcp.json`, `.claude/settings.json`, `server.py`.
14. **`submit`'s parameters:** `files` (each a `path`, a required `context`, and an optional `renamed_from`), `why`, `wait` and `timeout`. *Alternatives:* the first lup's directory with a `.proposal.json` manifest; `why` required. *Lean:* as listed. *Where:* `server.py`, `policy/submissions.py`.
15. **A landed file named in a submission is shown as context:** its diff since the session started, nothing applied. *Alternative:* drafts only, so a new module reaches the operator without its tests beside it. *Lean:* yes, lightly. *Where:* `policy/submissions.py`.
16. **Every submitted draft goes to the operator,** with its asks or "asked for your view"; lup's rules refuse the whole submission on a finding. *Alternatives:* apply at once a draft that no longer asks, as the first round proposed, which would land an asked-anyway change unreviewed; let files with findings go stale in the dashboard. *Lean:* everything submitted is reviewed. *Where:* `policy/submissions.py`.
17. **Asking anyway: a change becomes a draft on purpose by being written at its draft's path,** or copied there first for an edit. *Alternatives:* a fifth tool, `draft(file)`, which copies the file into its draft and returns the path, sparing the agent the escaping rule; a `submit` option naming files to draft as they stand. *Lean:* the draft's path, no new tool, with the rule in `submit`'s description; lightly, since `draft(file)` is cheap if agents stumble on the escaping. *Where:* `policy/before.py`, `server.py`.
18. **Renames:** a file names its `renamed_from`, and a shell rename that git's rename detection finds, where the new path asks, is drafted whole, the old file kept until approval. *Alternatives:* a deletion and a creation, as today, where the deletion lands and the creation waits, half a rename; a `rename` tool; content compared by hand, which `AGENTS.md`'s parser rule rules out when git already detects renames. *Lean:* as stated. *Where:* `policy/drafts.py`, `policy/store.py`, `policy/submissions.py`.
19. **The review is parked in the first lup's dashboard as one `Propose`,** with its before side exported to `.lup/review/<n>/`. *Alternative:* record the before side at the file's own path, so the page shows the real path and the dashboard itself retires the review if the file moves, but nothing can then withdraw it, which superseding needs. *Lean:* the export, as the installer's review does. *Where:* `legacy_dashboard.py`.
20. **A keeper keeps each submission in the first lup's dashboard past its hour.** `submit` starts it if none runs: one per worktree under a lock, like the importers pass. It parks expired reviews again, silently (*Told once, never re-told*), and exits once nothing waits. *Alternatives:* park again only when a `wait` or a hook looks, so the review of an agent that's gone idle vanishes after an hour; put sessions on the first lup's roster, which couples the bridge to its coordination. *Lean:* the keeper. *Where:* `legacy_dashboard.py`, `cli.py`.
21. **(agreed)** **Told once, never re-told.** Each answer is told once, by `wait` or with the conversation's next call; never again. An approved command not yet run stays in `reviews` and shows in the dashboard as "approved, not yet run"; any reminder is the operator's. *Reason:* the first lup's agents complained of being pinged about the same thing. *Alternative:* listing what's approved and not yet applied at every call, the first round's wording, withdrawn. *Where:* `policy/checkpoint.py` (mail), `policy/submissions.py`.
22. **(agreed)** **An approved edit applies when the agent waits on it, or at the end of the turn of the conversation that submitted it,** never mid-task; an approved command runs only when the agent waits on it. The turn's end applies only when no other conversation of the session has a call running in that worktree. *Alternatives:* at any checkpoint, the first round's lean, which changed files under the agent mid-task; only when it waits, so an agent that never waits never gets its change. *Where:* `policy/submissions.py`, `policy/checkpoint.py`.
23. **A decline leaves the draft where it is,** its note and comments told once and kept with the submission. *Alternative:* move the draft to `.lup/saved/`, as a refusal saves a version, where nothing was put back. *Lean:* leave it. *Where:* `policy/submissions.py`.
24. **Edits after submitting stay in the draft.** The approval applies the version submitted; the draft, if edited since, stays with only the later edits. *Alternatives:* refuse writes to a draft while its review waits, which stops the agent; apply the newest draft, which the operator never saw. *Lean:* stay. *Where:* `policy/submissions.py`, `policy/drafts.py`.
25. **Submitting a file again while its review waits supersedes the whole review.** *Alternatives:* refuse until it's answered; withdraw only the files named again, splitting what was submitted together. *Lean:* supersede. *Where:* `policy/submissions.py`.
26. **(agreed)** **`wait`'s forms:** one review; `any` of several; `all` of the conversation's submissions; a `file`, until its change is applied; each with an optional `timeout` returning "still waiting". `submit` can wait in the same call, and `reviews` lists state. The default is no wait. *Open detail, my lean:* `file` keeps waiting across a decline until a resubmission of that file is approved. The alternative returns at the decline, which tells the agent at once; leaning to return at the decline, lightly, so the agent isn't frozen on work only it can do. *Where:* `server.py`, `policy/submissions.py`.
27. **The frozen mark, in the bridge:** a reply in the review's thread and a desktop notice. *Alternative:* park the review again with its heading marked, which puts it at the top of the list but gives it a new id, and loses comments the operator was drafting on the page. *Lean:* the reply and the notice; lup's own dashboard sorts by it. *Where:* `legacy_dashboard.py`.
28. **`reply` is written through the first lup's host half** (`append_review_record`), in the first lup's reply record, modelled in `legacy_dashboard.py`. *Alternatives:* no replies until lup's own dashboard, which loses what the first lup had; the first lup's own `review reply` command, which runs its whole package. *Lean:* through the host half. Like `docs/judging-writes.md`'s decision 99 (d), it writes a record shape the first lup also defines, but only an appended line, which the host half offers. *Where:* `legacy_dashboard.py`.
29. **Lifecycle:**
    - drafts last until approved, deleted, or their worktree goes;
    - a session's turn's end applies what's approved and tells the operator once of a draft left unsubmitted;
    - a subagent's end blocks once on drafts it didn't submit;
    - a new, cleared or compacted session is told once of the worktree's drafts and open reviews.

    *Alternatives:* every turn's end holds on unsubmitted drafts, which keeps a main session from stopping to talk; telling a resumed session too, which re-tells; nothing at a subagent's end, which loses a worker's drafts at hand-back. *Lean:* as listed. *Where:* `policy/checkpoint.py`.
30. **A file in a directory Claude Code protects is reviewed through its submission,** not Claude Code's own prompt, since lup applies the approval. *Alternative:* keep those files out of drafts and on Claude Code's prompt, through the interim hook's queue. *Lean:* through the submission. *Where:* `policy/drafts.py`.
31. **Commands needing review move to the judge:**
    - its adapter answers `PermissionRequest` and parks the command as a review in the same queue;
    - `wait` runs it once approved, with its output;
    - `reviews` and the dashboard show "approved, not yet run";
    - the interim hook goes whole.

    *Alternatives:* keep the interim hook for commands, its own Bash `wait` running them, which leaves two waits and two lists; a submission naming a command to run once its files are approved, which waits for the host's services. *Lean:* move them. *Where:* `adapters/claude.py`, `policy/submissions.py`, `.claude/settings.json`.
32. **The dashboard shows no drafts.** *Alternative:* list them on the agent's row as "being written", once lup's own dashboard exists. *Lean:* none now; revisit with lup's dashboard.
33. **`Answer` and `LineComment` move from `install.py` to a new `review.py`,** with `Remark` and the `Queue` seam. *Alternative:* `policy/submissions.py` imports them from `install.py`, tying submissions to the installer. *Lean:* the move. *Where:* `review.py`, `install.py`.
34. **A draft is dropped by deleting its file,** and the next checkpoint forgets its record. *Alternatives:* a `drop` tool or command, one more name for an `rm`; keeping a dropped draft's record until submit notices. *Lean:* deleting the file. *Where:* `policy/drafts.py`, `policy/checkpoint.py`.
