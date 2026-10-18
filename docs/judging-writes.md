# Judging every write: allow or ask, findings told

lup judges every write in the worktrees of an agent's repository, and answers allow or ask the operator, telling the agent lup's findings in it. A file tool's write (`Edit`, `Write`) is judged before it lands, on the content it would produce. Anything else (a command, a script, a background process, Codex's `apply_patch`) is judged at the next checkpoint, by comparing each worktree with the last state lup accepted for it. The code is `packages/lup-dev/src/lup_dev/policy/` (judging) and `codescan/` (reading code), with the typed engine in `packages/lup-dev/checker/`.

The rules themselves are elsewhere: `docs/conventions.md` says what each convention is and why, and `docs/rules.md`, generated from the engine's table, gives each rule with its examples. This doc is how a write gets judged.

## What we have

### The outcomes

- **allow:** the call goes through with no prompt. On Claude Code the hook answers `allow`: silence would leave the call to the runtime's own permission mode, a prompt per edit in Manual mode. On Codex nothing needs answering, since it doesn't ask before an `apply_patch` inside the workspace.
- **ask:** the change is held for the operator's answer, the agent waiting inside the hook, on every runtime: a file tool's write before it lands, anything else at the checkpoint; the hold is an item in the operator's inbox, answered in the dashboard's review or with `lup-dev inbox answer` (*Asking the operator*).
- **flagged:** the change lands as an allow would, the agent told nothing of it, and the verdict log records it under the names of what it asks (`Judgement.flags`).
- **refused:** what the operator had to see first and didn't is put back, with the agent's version saved (*Refusals*): a change made through the shell that asks, on a runtime that asks before a call; a hold declined, or left unanswered.

lup's findings never decide the outcome: those on the lines a change touches are told right after it (*Findings*).

### What each change gets

| Change | What it asks | By default |
|---|---|---|
| A test, scratch (`tmp/`), docs or data file, at any size | nothing | allow |
| An operator's document (`DESIGN.md`, `AGENTS.md`) | `operator`, every time | held |
| A protected path | `protected`, every time; a protected Python module gets lup's rules too, its findings told | held |
| A path the declaration excludes | nothing, and nothing reported; one that's also protected still asks `protected` | allow |
| A new production file | `new-file` | flagged |
| A write over the whole of an existing production file | `whole-file` | flagged |
| A change to the public API (*The public-API ask*) | `public-api` | flagged |
| An added `# lup: ignore` | `ignore`, every time | held |
| A finding of lup's rules on a line the change touches | the rule's name | told; held or flagged only where the declaration names the rule |
| Removing a `# lup:` note present when the session started | nothing, and it's reported | allow |
| A deleted file | `protected` or `operator` where it's one; otherwise nothing | held, or allow |
| Any other production change | nothing | allow, its findings told |

`policy/judge.py` holds this (`Judge`, `Judgement`), shared by the judgement before a write lands and by the checkpoint, so a change gets the same outcome however it was made. There's no line count: a size limit makes agents split their edits to fit it.

- **Approvals.** An approval covers the path's design asks (a new file, a whole write, a public-API change) for the rest of the session, in that worktree alone, so a file approved isn't asked again as it's worked on (`Ask.covered`).
- **Held and flagged, by name.** The declaration names what's held and what's flagged, in one vocabulary: the two roles that ask (`protected`, `operator`), the kinds of change (`new-file`, `whole-file`, `public-api`, `ignore`), and lup's rules by their ids (`Project.held`, `Project.flagged`; `docs/declaration.md`). An ask named in neither is let through. By default `protected`, `operator` and `ignore` are held, and `new-file`, `whole-file` and `public-api` flagged: a protected change takes effect outside the agent's reach before anything lands, and an `ignore` takes a check away, while a change of design can be seen once it has landed. A name both lists hold, or neither vocabulary knows, fails the declaration's load; a rule's name is checked against the engine's table at the first judgement (`Judge.named_rules`).
- **The operator's switch, per conversation.** "Hold each flagged write" holds what the declaration flags for one conversation, a session's own or a subagent's: `h` on its row of the dashboard's tree turns it, and the row says "holding" (`docs/dashboard.md`). The host service keeps it with the launch's conversations (`SetHolding`, `Conversation.holding`), through restarts, and the judge asks it for the conversation writing, before a file tool's write and at each checkpoint (`ShowHolding`, `Announcing.holding`, `Judge.holding`). A move of `HEAD` isn't any conversation's, so it never holds for the switch; with no host service running, nothing does.

**Path roles.** Each path has one role, the first that matches (`Roles.role`, `policy/roles.py`):
1. **protected:** the project's declaration, and what its modules protect: by default manifests and lockfiles; the tools' own configuration files, each read before its table in `pyproject.toml`, so one written unasked would override what the gate checks; what runs outside the agent's reach (`.github/`, `.git/`, git hooks, editor, container and runtime settings); what widens a later launch (`sync.json`); secrets (`.env*.local`); `.gitignore`, since what it ignores the checkpoint never sees; and the person's own files git ignores (`AGENTS.local.md`, `lup_project.local.py`), which nothing else would show the operator;
2. **operator:** `DESIGN.md` and `AGENTS.md`;
3. **excluded:** what the declaration holds to nothing: no rules, no findings, writes allowed. Protection is matched first, so exclusion takes the checks away, never the operator's review;
4. **test:** a module pytest collects as a test, or a `conftest.py` under a test root (`docs/conventions.md`, *Tests*);
5. **scratch:** `tmp/` at any depth, and `.lup/`, where saved versions wait;
6. **docs:** Markdown files, and `docs/` at the root alone, so Python under a package's `docs/` isn't waved through;
7. **data:** JSON, CSV, YAML, TOML and other data formats outside a source tree (under `src/`, or in a package), where a data file ships with the code;
8. **production:** everything else, so a file nobody classified is gated.

The default patterns are data in `catalog/paths.py`, protected with the rest of the catalog; a project changes them in its declaration (`docs/declaration.md`). lup's rules read production and protected Python modules (`Roles.ruled`); pyright's and ruff's findings are reported for those and for tests (`Roles.checked`). An exemption the declaration makes (`CodeRules.exempt`) lifts one rule from the paths it names (`Roles.exempt`), where an `ignore` keeps one finding on its line. Tests a session mustn't rewrite to fit its code, written beforehand as a specification, are made protected paths.

### The public-API ask

A change to what other code depends on is a design change, so it asks like a new file (`api_changes`, `policy/surface.py`):
- a name added to a package's root (`__init__.py`), or one removed that was there when the session started;
- a class added that wasn't in the accepted version or at the session's start;
- a changed signature (parameters, their kinds, annotations and defaults, the return type) of a definition that existed when the session started.

What the session itself created asks nothing more: the operator sees it when the file or class holding it is asked. The engine reports each version's surface (`Surface`; `checker/src/surface.ts`): a root's `__all__`, or every name it binds; every class, nested ones included; every function's and method's signature, private names counted. It's read for the content after the change, the accepted content before it, and the content the session started with.

### Before an edit lands

For `Edit` and `Write` the content after the call is known before anything is written, so they're judged before they land (`before`, `policy/before.py`): allowed, or asked in the runtime's prompt. The adapter reads each call as one of two proposals in lup's own words, so the core never names a runtime's tools:
- **a whole write** (`Overwrite`): the content it carries;
- **a replacement** (`Replacement`): the current file with `old_string` replaced by `new_string`, once, or everywhere with `replace_all`; an empty `old_string` on a missing file creates it. Where `old_string` isn't there as the tool requires, lup allows the call and the tool fails on its own.

The judgement compares with the accepted content, not the disk, so a command's write not yet judged is judged with the edit: an edit to a file a command just created asks as a new file. A write allowed or asked is remembered with its call (`Pending`); when the call finishes, the checkpoint accepts that content as judged, and an asked call that ran was approved (`confirm`, `policy/checkpoint.py`). The engine checks content that isn't on disk yet as pyright's language server checks an unsaved buffer.

**After a refusal,** the change comes back through the file tools, where the operator is asked: a file written whole again with `Write`, where the prompt shows it whole.

### After a call: the checkpoint

Everything else is judged after the fact: a `sed`, a script, `cp`, a background process, and Codex's `apply_patch`, whose patch lup doesn't parse. lup parses no command: whether one runs is the runtime's permission mode's call, or in a room, it runs (`docs/launch.md`, *The settings compiled for each runtime*). A checkpoint compares each worktree with the last state lup accepted for it (`checkpoint`, `policy/checkpoint.py`; `policy/store.py`).

The core never sees a runtime: each adapter (`lup_dev/adapters/`) turns its hooks into lup's events and implements `Runtime` (`policy/runtime.py`): its name, whether it asks before a call, and whether this process runs inside one of its sessions. Only `cli.py` lists the adapters; an import contract and the `runtime-mention` rule keep runtime names out of the rest.

| Event | Claude Code | Codex |
|---|---|---|
| `SessionStarted` | `SessionStart` | `SessionStart` |
| `CallStarted` | `PreToolUse` | `PreToolUse` |
| `CallFinished` | `PostToolUse`, `PostToolUseFailure` | `PostToolUse` |
| `TurnEnded`, the session's own conversation | `Stop` | `Stop` |
| `ConversationEnded`, a subagent's | `SubagentStop` | `SubagentStop` |

**When it runs.** A call counts as running in every worktree its session holds (`running.json`, under a file lock, since parallel calls' hooks run at once). When one finishes, a checkpoint runs in each of them where none of that session's calls is still running, so parallel calls are judged together; each turn's end runs one too. Another session's calls hold none of its checkpoints back (`Running.idle`): a call no hook ever finishes (a configuration hooking only `PreToolUse`, a crashed session) would otherwise stop judging there for everyone, and lup runs one agent per worktree. The checkpoint comes before the agent's next model request, so a finding reaches it before it writes its next line.

**Subagents.** A call that runs a subagent (`Agent` or `Task`, `spawn_agent`) isn't counted; the subagent's own calls are, so its writes are judged as it makes them and told to it. The checkpoint sees files, not authors, so its report also waits as mail for each other conversation whose calls finished since the last one.

**It degrades gracefully.** A finish with no start (Codex's `write_stdin` can bring a command's `PostToolUse` on a later call) leaves the running calls as they are. A call that never reports finishing (one the operator declined at Claude Code's prompt, one that failed on Codex) is cleared at its conversation's turn's end, whose checkpoint judges everything anyway; until then it holds back only its own session's checkpoints. A refused call never runs, so it isn't counted.

**How a checkpoint goes,** in each worktree:
1. **Snapshot** the worktree into its store as a git tree (the store's own index, `git add --all`, `write-tree`), leaving out what the repository ignores and `.lup/`. git runs with `core.fsmonitor` and hooks turned off (`lup_dev/git.py`), since a planted `core.fsmonitor` runs inside a call. Where the snapshot is the accepted tree, the common case after a read, nothing is judged and no declaration is loaded.
2. **Compare** with the accepted tree, leaving out files under an open hold.
3. **Set aside what was committed elsewhere** (`Elsewhere`, `policy/store.py`): content in the history of the commits the repository's refs and the worktree's `HEAD` named at its last checkpoint, the other worktrees' `HEAD`s at theirs (`heads.json`), and the remote-tracking refs (`git log --find-object`). That's what a checkout, a pull, a stash or a `git restore` produce, judged where it was written. git's clean merge of two such commits, remade with `git merge-tree --write-tree`, is set aside too, or merging a branch that adds a class to a file both sides changed would be refused as a public-API change; conflicts and resolutions written by hand are judged.
4. **Judge a move of `HEAD` once, as its commits'.** Where `HEAD` moved (a commit, a merge, a pull, a reset), what it brought that step 3 didn't set aside was first written in a commit since the last checkpoint, such as a shell write committed in the same call; accepted unjudged, a commit through the shell would skip the judge. It's judged once (`brought`), against the accepted content, with no session's approvals, and never put back: that would leave the working tree different from `HEAD`, and the next `git restore` would bring it back. Its verdicts carry no session; it's told naming the commit, its lup findings failing the gate before the branch lands; its asks become a hold no agent waits on (*Asking the operator*). Changes on top of the move are judged against `HEAD`'s content.
5. **Judge** the rest as a write is judged before it lands; content judged before it landed (a file tool's write, an approved hold) is accepted as it is.
6. **Refuse** what bypassed an ask (`fates`): on a runtime that asks before a call, an ask made through the shell is refused, pointing at the file tools, so it comes back through the prompt (`AGENTS.md`, *How work goes*); on one that can't, it's held.
7. **Act** (`act`): a refused file goes back to its accepted content, or is removed if new, its version saved; the rest becomes the accepted tree.
8. **Report** once: refusals, what a move brought, notices, then lup's findings on the lines changed, type errors and ruff's findings, then the notes removed, then mail (`Checked.text`). The Python files that landed go to the importers pass (*The engine: one typed tree*).

**Where a session's judging starts.** When a session starts, or first reaches a worktree, the worktree as it stands becomes the accepted tree and the session's starting tree there (`begin`), which the public-API ask and removed notes compare with. What changed since a stored accepted tree was made while the session made no call there (the operator's work, a pull, another session's), so it's accepted unjudged rather than blamed on the agent; a file under an open hold keeps its accepted content, and while a call of the session itself is running there (one left running as it resumes), that call's checkpoint judges it. A session that starts again begins again in every worktree it holds.

**Someone else's edit** in a worktree a session holds is judged as the agent's, since the checkpoint sees files, not authors; refused, it's put back with its version saved. The operator works where no session holds, or between sessions. What a checkpoint costs is in `docs/field-notes.md`, *Judging writes*.

### Every worktree of the repository

A session starts in one worktree and often works in others: in lup's repository each branch is its own worktree (`tree/<branch>`), so a session started in `tree/dev` writes in `tree/feat-…`, and its workers in theirs. The judge covers the worktrees of the session's repository that the session holds (`policy/worktrees.py`), each by its own store and roles under the declaration the operator approved (*The declaration, from the approved commit*).

- **The session's repository** is git's common directory for its working directory, so a session started in a bare repository's own directory is judged too, holding no worktree until it reaches one; one started outside any repository isn't judged until a later hook's working directory is in one.
- **A write's worktree** is the one git names from the file's nearest existing directory (`place`). A write outside the session's repository, in a nested repository included, isn't judged: the runtime decides. In the repository's own git directory outside every worktree (`lup.git/config`, `lup.git/hooks/`), a file tool's write asks, as `.git/` does, since those files run outside the agent's reach; no snapshot covers it.
- **The worktrees a session holds** (`Holding`, in the session index): the one it started in, each one its file tools write in, and each one a hook reports as its working directory, which on Claude Code follows a `cd` in the session's own conversation. A worker's hooks carry its session's id, so its worktree is its session's. A worktree whose root is gone (landing a branch removes it) isn't held. Reaching a worktree begins the session there.
- **On Codex** a session holds only the worktree it started in: its hooks' `cwd` is the session's working directory, and its `Bash` and `apply_patch` carry only the command, which lup doesn't parse. Under its `workspace-write` sandbox a write elsewhere is outside the writable roots, and Codex's own approval decides it.
- **The gap:** a shell write into a worktree the session never reached isn't judged, and is accepted when a session next reaches it; `AGENTS.md`'s *Write with your file tools* makes a session's first write in a worktree a file tool's. Judging every worktree at each checkpoint would close it, at about 80 ms a worktree, and would judge the operator's own uncommitted work as the agent's.

**One checkpoint per worktree.** A call's finish runs one in each worktree the session holds where none of its calls is still running, and the agent hears their reports together; a turn's end runs over every one. Reports and asks name each file by its absolute path, as pyright's command line does, since the agent's working directory may be any of them; the verdict log keeps paths relative to the worktree it names.

### The declaration, from the approved commit

Every worktree of a repository is judged by the declaration at the commit the operator approved last through trust on launch (`docs/launch.md`, *Trust on launch*), never by the worktree's own (`Worktree.loaded`, `policy/checkpoint.py`): what runs on the host is what they approved, and a branch can't change what judges it.
- **The approval** is read from `repositories/<id>/approved.json` in lup's state (`lup_dev/approval.py`), with the person's own layer approved beside it (`lup_project.local.py`), which is put beside the commit's export.
- **Before any approval,** the integration branch's tip judges: `dev`, or what `LUP_INTEGRATION_BRANCH` names where the judge runs. Without that branch, each worktree's `HEAD` commit judges it, and the defaults before its first commit.
- **Read once per commit.** Its Python modules and `pyproject.toml` files are exported into lup's state (`declarations/<commit>/`) from git's objects (`Git.export`), not through `git archive`, whose `.gitattributes` handling could change what's imported, and the declaration is imported from there (`declaration/load.py`), the conditions modules it names with it, so all of it comes from one commit. It's loaded when a judgement first needs it, so a call's start loads none.
- **The gate reads the worktree's own** (`Worktree.at`), to check a branch as it would land. pytest's configuration, which gives the test roots where the declaration names none, is the worktree's own too.

Judging reads the declaration resolved (`Declaration`, `declaration/resolve.py`): each role's patterns, the test roots, the exemptions, the conditions modules, each module's rule selection, the runner and `asks`.

**A declaration that can't load has a stand-in.** The approved commit can hold a declaration the installed judge can't import (a field it predates), or be gone from the repository. Each declaration that loads is kept, resolved (`last-declaration.json`, `LastDeclaration`), and where the one due can't load, the last that loaded judges, and the agent is told once, with the error, to pass on to the operator; approving the tip with `lup-dev trust` is usually the fix. Denying every write instead would stop every session until the next approval, and the defaults would silently drop the project's protections. The runner is kept as the commands it puts before a tool (`Prefixed`, `docs/declaration.md`, *The runner*), since a project's own runner can't come back from JSON. The gate never takes a stand-in.

**When judging fails** at a turn's end, the turn ends anyway, since the agent can't fix the judge, and the operator is warned once for each failure in a session, in `systemMessage` (`first_warning`). Elsewhere a failure denies a file tool's write, naming it, and other calls go on: a crash would read as no decision, letting a write meant for review through.

### The turn's end

The session's own turn's end (`TurnEnded`; `end_turn`, `policy/checkpoint.py`) runs a checkpoint in each worktree the session holds, waits for the importers pass, and holds the turn while the files its own conversation touched, or files importing them where the pass found errors, have lup's findings, type errors, pyright warnings or ruff findings, re-checked as they stand (`unclean`). A subagent's end (`ConversationEnded`) runs its checkpoint but never holds on those: every worker passes the gate before it hands back, and one waiting on a review has files importing what hasn't landed, errors it can't fix.

- **Whose files.** The files touched and watched are kept per conversation (`Session.touched`, `watched`). A file tool's write is the conversation's that made it; a shell write is every conversation's whose calls finished since the last checkpoint (`writers`), since holding an end on a file it didn't write is the safe side, which the once-per-finding rule lets end. The importers pass carries the conversations that wrote what it re-checks, and what it finds is watched for them.
- **While a subagent works,** from its first call to the end of its conversation (`Conversations.working`), the session's end doesn't hold on what's left in a file they both touched, which may be the subagent's in progress, and tells the operator instead. A worktree where a subagent's call is running gets no checkpoint at the session's end, so the subagent's write in progress isn't judged as the session's; that call's finish runs it. A session that starts again forgets its subagents at work, until their next call; one whose end the runtime never reports stays at work until then.
- **Once per finding, across turns** (`holding`, `inbox/ends.py`; `docs/host-tools.md`, *No turn that won't end*). An end that follows a block (`stop_hook_active`, on both runtimes) ends, whatever's left, and the operator is told. What a turn ended past is kept per conversation, and a later end holds only on findings not among them, the same file, place, rule and message; one fixed that comes back holds again.
- **What a turn's end must tell still blocks,** each thing once: a refusal, a move, an answer to a hold, the notes removed (at the session's end) and mail. Anything else is told to the operator in `systemMessage`, since on both runtimes whatever a turn's end tells the agent continues the turn.

### Asking the operator

- **Through a hold, on every runtime** (`policy/holds.py`). A change that asks is held, the agent waiting inside the hook: a file tool's write before it lands (`held_write`, `policy/before.py`), its call let through or denied with the answer; anything else at the checkpoint, put back or kept. The hold is put in the operator's inbox as a held change (`HeldChange`, `Announcing`): what's held, what each file asks, its diff, and each file held whole, what it holds and what the change makes it (`held_files`, beside the diff), which the dashboard's review shows highlighted, its changes marked and its unchanged runs folded (`docs/dashboard.md`, *The review*). It's answered there, in the review (Space `a` or `x`, the comments written under it, on its files' lines among them, going with the answer, each under the lines it quotes), or with `lup-dev inbox answer <n>`, which writes the answer to the hold. A decline puts the change back, or never lets it land, and saves the agent's version, the comment in the agent's report; an approval covers the path for the rest of the session. The hook polls every 2 seconds for up to 24 hours; unanswered by then, the change is put back and saved, and the hold stays open: a later answer reaches the agent at its next checkpoint, an approval covering the path so the saved version can go back. A launched room's hooks wait 25 hours for the host service. Claude Code's own prompt isn't used: answered in the inbox, a hold is answered the same way on both runtimes, wherever the operator is.
- **A held file is nobody's** until the operator answers: it keeps its accepted content (`WorktreeState.holding`), and no session's start, checkpoint or turn's end accepts it, judges it or puts it back, so a decline always has something to put back.
- **A move's asks, after the fact.** What a move of `HEAD` asks is already committed and isn't put back, so on both runtimes it's a hold no agent waits on, naming its commit (`Hold.commit`), its inbox item asking whether to keep what the commit brought: a hook waiting on it would block a session that may not have made the commit. Its answer is logged when given, and told to the session that found the move at its next checkpoint (`late_answers`); a decline changes no file, and reverting is the operator's call.
- **Nobody answers their own hold.** Answering refuses to run inside an agent's session, which each adapter recognises by the variable its runtime sets in the commands it runs (`CLAUDE_CODE_CHILD_SESSION`, `CODEX_THREAD_ID`; `Runtime.inside`). That stops a mistake, not a determined agent: on the host, as the operator's user, an agent could write the answer itself. A room doesn't mount the stores the holds are in.

### Findings

lup's findings on the lines a change touched (`touched_lines`; every line of a new file), and what's wrong with its directives, are told right after the call, beside its result, each with its steer, as a type error is: the change has landed, and the agent clears each finding or keeps it with an `ignore`, which asks the operator. Those on lines no change touched are told apart. They hold the session's turn's end, as type errors do (*The turn's end*), and fail the gate.

The report, in pyright's shape:

```
lup's findings on the lines changed (clear each, or keep it with `# lup: ignore("<rule>", why="<reason>")` on its line or the line above, which the operator is asked about; they fail the gate):
  /work/lup/src/lup/claude.py:41:12 - tuple-shape: a fixed-length tuple[str, int] hides what each position means
      steer: name the fields with a pydantic model
  /work/lup/src/lup/claude.py:88:5 - regex: `import re` parses with a regular expression
      steer: use the format's own parser (lup docs rules regex)
```

`information` in `policy/report.py` writes it, and `tests/test_report.py` checks that this block is what it writes for these two findings, whose messages are illustrative.

### Refusals

A change the operator had to see first, and didn't, goes back to its accepted content, and the agent's version is saved under `.lup/saved/<n>/<path>` in the worktree: one made through the shell that asks, on a runtime that asks before a call, which comes back through the file tools; a hold declined, with the operator's comment, or left unanswered (*Asking the operator*). `refusal` in `policy/report.py` writes the report: each file, where its version is saved, and why.

### Type errors and ruff's findings

They're told, never refused: at each checkpoint, pyright's errors and warnings and ruff's findings in the files changed, tests included, beside the call's result, with lup's findings on untouched lines and the type errors the importers pass found; at the session's turn's end, they hold it (*The turn's end*); at the gate, they fail it (*The gate*). pyright's warnings count as its errors do (`checker/src/report.ts`).

ruff runs with `--ignore-noqa` and pyright with `enableTypeIgnoreComments = false`, so `# lup: ignore` is the one suppression (`docs/conventions.md`, *Suppressions and directives*). ruff runs through the project's runner with its command for the judge (`runner.judging(…)`: for `Uv()`, `env -u VIRTUAL_ENV uv run --frozen --quiet ruff check …`), from the worktree's root, so it's the project's own ruff where its environment has one, never relocking (*The engine: one typed tree*); would-be content goes through stdin under the file's name, so the project's configuration applies (`codescan/ruff.py`). It runs with `--exit-zero`, since uv's failures exit 1 as ruff's findings would, and a failure raises `RuffError` with the runner's or ruff's message.

**A finding ruff fixes safely is never told to the agent.** `ruff check --fix` applies only a fix ruff marks `safe`, so those findings are `fixable` (`Finding.fixable`) and left out wherever the agent hears findings, though they still count for the `ignore` naming one. Such a fix changes nothing a reader decides, and told one by one, these findings spend an agent's turns. The session landing the work applies them (`lup-dev check --fix`); the gate without `--fix`, as in CI, fails on them. The judge never rewrites a file under the agent.

### The gate

**`lup-dev rules check`** is the gate's `rules` step (`rules_check`, `scanned` in `cli.py`): every Python file the roles check, checked as the turn's end does, failing on any finding (lup's in production and protected modules, pyright's, ruff's, fixable ones and unused `ignore`s included), each through `# lup: ignore`. It's the one check deciding whether a finding is kept, so the gate has no `ruff check` or `pyright` step, which would fail on a finding an `ignore` keeps, and lup's rules hold wherever the gate runs, the judge running or not. With no paths it lists the worktree's files from git (tracked, and untracked but not ignored), so the roles decide what's checked. A deferral whose issue closed or whose condition holds is a reminder, listed without failing, and kept in the repository's git directory (`lup/due.json`, `Due`) for a session's main conversation to be told at its start.

**`lup-dev check`** (`gate.py`, whose docstring says the rest) runs the worktree's own declaration's steps from its root through the project's runner, every one even after one fails: in lup's repository `engine` (built when the bundle is older than its sources), `rules`, `format`, `pytest`, `lint-imports`. With `--fix`, ruff's safe fixes, `lup-dev rules fix` (removing each `ignore` that keeps nothing) and the formatter rewrite the worktree first (`Fixes`).

**A pass is recorded by the files it passed on** (`Standing`, `Passes`): the tree git would commit the worktree's files as, with the digest of the person's own layer of the declaration where there's one, in the repository's git directory (`lup/passes/`), which every worktree and room shares. A later run on the same files runs nothing (`--again` runs it anyway), so the merge commit landing a branch finds its pass. `--at <commit>` runs the gate on a commit, in a worktree made at it (`at_commit`); a push to the integration branch from a room runs it first (`docs/host-tools.md`, *git through a remote helper*).

### The engine: one typed tree

Every lup rule reads one typed tree: each file parsed and type-checked once by pyright, and each rule reading types straight from that tree. There's no syntax-only first stage and no language server asked about one position at a time, so the rules don't grow into a patchwork of syntax checks. Pyright has no plugin API, and its published package is one bundle whose internals can't be imported, so the engine is built against pyright's source.

- **What it is:** a TypeScript program (`packages/lup-dev/checker/src/`) built against pyright's `packages/pyright-internal` at the release `uv.lock` pins, so it answers as the gate's pyright does. `checker/build.py` fetches that source once into `$XDG_CACHE_HOME/lup/pyright/`, type-checks the engine and the rule table, and bundles them with esbuild into `lup_dev/codescan/bundle/`, the standard-library stubs beside it; git ignores the bundle, and the installed package carries it.
- **How it runs:** one long-lived Node process per worktree, holding pyright's program warm, on a Unix socket under `$XDG_RUNTIME_DIR/lup/` (`EngineChecker`, `codescan/engine.py`; `checker/src/server.ts`). A hook that finds none starts it, under a lock; an engine per hook would reload the project each time. It stops when unasked for `LUP_ENGINE_IDLE` (15 minutes by default), and at once for a client expecting another build or another environment, so the next request starts the right one.
- **In step without a file watcher:** a file checked with would-be content holds it until the next request, which puts the disk's back unless the edit landed; files on disk are checked by their `stat`; a changed configuration, or the interpreter replaced, builds a new program (`WarmProgram`, `checker/src/program.ts`).
- **Which environment:** the one the project's runner gives the worktree (`docs/declaration.md`, *The runner*). The engine runs the runner's command for Python (`runner.judging(["python"])`) from the worktree's root to name the interpreter, and stamps it with pyright's configuration and the files the runner says decide the environment (for `Uv()`, `pyproject.toml`, `uv.toml`, `uv.lock`, `.python-version`), so a lock arriving with a merge is synced before the next check. Never the `PATH` or `VIRTUAL_ENV` it inherited from the hook that started it, which may be another worktree's.
- **Never relocking:** the judge's uv calls, the engine's and ruff's, read `uv.lock` with `--frozen`: they make and sync the environment, but never write `uv.lock`, a protected path the checkpoint would judge as the agent's shell write, and never resolve over the network. A worktree with a `pyproject.toml` and no `uv.lock` gets no environment, and the engine and ruff fail with uv's message. A project not on uv declares its runner (`Plain()`, or its own).
- **For each check,** it reports per file pyright's errors and warnings and lup's findings in one list (`FileReport`, `codescan/contract.py`), with the file's `# lup:` directives, its public surface and its imports; columns count characters from 1, as Python does.
- **The files importing a changed one** are re-checked for type errors in a background pass, since the rules read only the changed files (`ImportersPass`, `policy/importers.py`). Their errors arrive at the next checkpoint, and the session's turn's end waits for the pass, so no type error surfaces after the session. One pass runs at a time per worktree, holding a lock the system frees however the process ends; a request adds its files to what's pending, and the pass takes batch after batch until nothing is. It re-checks a file at a time, so a check waiting behind it runs between two files (`ImportersJob`, `checker/src/engine.ts`).

Nothing checks a file's imports against the import-linter contracts at the edit; the gate's `lint-imports` step does. The spike this shape rests on is in `docs/field-notes.md`, *Judging writes*.

### How a rule is declared

Rules live in one table, `lup_dev/catalog/rules.ts`, keyed by each rule's id and protected with the rest of the catalog, so the operator reviews every change to a rule. Each entry holds the rule whole:
- `mistake` and `steer`: the mistake it prevents and where it steers instead, each a sentence that stands alone;
- `check(file)`: how it recognises its case, reading pyright's tree and asking pyright's type evaluator through the engine's helpers (`checker/src/file.ts`), where what checks share lives, so each check stays short;
- `examples`: its specification, as code: `flags`, each with its `rewritten` done the steer's way, and `passes`, near misses it mustn't flag. The engine's tests run every one (`tests/test_engine.py`; `docs/conventions.md`, *Keeping the rules cohesive*).

The engine's build compiles the table into its bundle. A check reports where and what it saw, and the engine adds the rule's mistake and steer, so the judge receives whole findings. Python learns of rules only from the engine (`Checker.rules`, `lup-dev rules list`), and each check request carries each module's rule selection, which the engine resolves against its table, refusing a name it doesn't hold. It's a table of code because recognising a case takes pyright's own tree and types: rules in Python over `ast`, asking the engine by position, would need two trees to agree and cost far more (`docs/field-notes.md`, *Judging writes*).

`docs/rules.md` is compiled from the table (`lup-dev rules docs`, `codescan/reference.py`) and committed, the one generated file lup commits; a test fails when it's stale. Which rules run, and where one doesn't apply, are the declaration's (`docs/declaration.md`, *Selecting the rules*): lup's default runs every rule but those `catalog/rules.py` leaves out, and the table holds no project's exemptions.

### The `# lup:` directives

`# lup:` comments are the channel for notes in code. The engine reads each with pyright's own expression parser (`checker/src/directives.ts`), and each kind is a model answering for itself (`Comment`, `codescan/directives.py`): which finding it keeps, what's wrong with it, what identifies it across edits.
- **A directive is written as a call;** an unknown one, or one missing what it needs, is `malformed-directive`, so a wrong one never sits there inert.
- **Anything that isn't a call is a note:** `# lup: the retry count matches the provider's documented limit`.

**`ignore`:** `# lup: ignore("<rule>", why="<reason>")`, on the finding's line or alone above it, where it covers the next line holding code (`docs/conventions.md`, *Suppressions and directives*). Adding one asks the operator; removing one is free, since it only makes the rule apply. One whose rule doesn't fire on the line it covers, or that names a rule the selection leaves out, is `unused-ignore`: fixable, so never told to an agent, and removed at landing by `lup-dev rules fix`.

**`defer`:** work knowingly left undone, written on the code it's about, so the next reader sees the gap is known and tracked instead of fixing it blind or calling it pre-existing:
```python
# lup: defer(issue=12, why="retries ignore Codex's reset time until its SDK reports it")
# lup: defer(when=sdk_reports_cache_ttl, why="read the TTL from the SDK instead of assuming an hour")
```
- **`why` is required,** and so is a way to come back, an `issue`, a `when` or both: a note nothing would close piles up. Work that isn't about one spot in the code is only an issue.
- **`issue`** is a GitHub issue: a number in this repository, or `"owner/repo#7"`; anything else is `defer-issue`.
- **`when`** names a `Condition` (`codescan/conditions.py`: one method, `holds()`) declared in a Python module one of the declaration's modules names for its conditions. The comment holds only the name, so nothing in a comment is ever run, and the condition is typed and tested like any code. lup ships `PythonAvailable(version=…)`, which holds once uv lists a final release of that version, and `PackageReleased(name=…, version=…)`, once the package index has that version or a later final one. A `when` naming no declared condition is `defer-condition`.
- **Checked** at the edit for its syntax and fields, the conditions modules read with `ast` rather than imported, so a hook doesn't run them (finding one imports its parent packages). At the gate the conditions are asked, and the issue's state read with `gh`, or in a room through the host service (`HostIssues`; `docs/host-tools.md`, *The gate in a room*). A closed issue (`defer-closed`) or a condition that holds (`defer-due`) is a reminder, listed without failing; issues that can't be asked (no `gh`, no login, offline) are left unchecked, said.

**Removing a note** is never refused. One added during the session goes freely, so an agent can take back its own `defer`; one present when the session started goes too, and the turn's end lists each such removal once, for the agent's report and the merge commit's message, so feedback never vanishes silently.

### The verdict log

Every judgement is logged, so how often lup asks, refuses and allows can be measured and tuned instead of guessed (`policy/verdicts.py`). One JSON line per verdict (`Verdict`): the time, the session (none for a move of `HEAD`), the runtime, the tool (or `checkpoint`, or `move`), the worktree, the path and its role, the outcome (allow, ask, refuse, hold) with its reasons (the names of what it holds; for an allow, the names of what it flags, else the rules of the findings told, else the role, `rules-pass` for production), and the operator's answer. An answer comes later, so it's appended as the same verdict again under the same key, and a reader takes the last line for each key; an ask logged only once answered would be lost when a hook dies. It's kept per repository, so one place measures a repository's worktrees. `lup-dev verdicts --days 7` summarises it by outcome and reason, with how asks and holds were answered.

### The two runtimes

| | Claude Code | Codex |
|---|---|---|
| A file tool's write | judged before it lands (`PreToolUse`) | no such tools: `apply_patch` is judged at the checkpoint |
| Worktrees a session holds | where it started, where its file tools write, where its hooks report its working directory | where it started |
| ask | held in `PreToolUse` for a file tool's write, at the checkpoint for the rest, answered in the inbox | held at the checkpoint, answered in the inbox |
| refused | an ask made through the shell: the checkpoint puts it back | a hold declined or unanswered: the checkpoint puts it back |
| How the agent hears | `additionalContext` beside the call's result | the same |
| Its sessions' commands carry | `CLAUDE_CODE_CHILD_SESSION=1` | `CODEX_THREAD_ID` |

What each adapter relies on from its runtime is in its module's docstring (`adapters/claude.py`, `adapters/codex.py`) and in `docs/field-notes.md`.

### Installing it here

The judge's whole set is its hooks on `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop` and `SubagentStop`, with `PostToolUseFailure` on Claude Code, every tool matched. lup's repository commits no `.claude/` and no `.codex/`, so lup's own sessions run only through `lup-dev launch` (`docs/launch.md`): each hook pipes its payload to the host service, which answers with the copy of `lup-dev` the operator approved for the repository (`docs/launch.md`, *The one hook and the host service*).
- **Claude Code** runs `SessionStart`, `PreToolUse` on every call, `Stop` and `SubagentStop`. The judge reads `SessionStart` and the file tools' writes (`WRITING`, `adapters/claude.py`), and runs no checkpoint: a write it lets through stays counted as running, which holds nothing back, and what the shell writes meets the rules at the gate.
- **Codex** runs the whole set, each hook read by the judge: the checkpoint after each call, the only place its hooks see a patch, and each turn's end.
- **`lup_project.py`** declares `asks="protected"`, the test roots `packages/*/tests`, `runtime-mention` added back, the library's front door exempt from it and the catalog from `constant-home`, and `LupDevelopment`, which builds the engine before the gate's first step and protects `lup_dev/catalog/**`.
- **The judge's own source** beyond the catalog isn't asked about at each edit: the judge that runs is the installed copy, so an edit in a worktree can't change what judges it, nor a broken judge in a worktree refuse its own fix. The operator reads what changed in it once, through trust on launch, before it runs (`docs/launch.md`, *Trust on launch*).

**Checking it live,** once the operator has approved `dev`'s tip (`uv run lup-dev trust` in the `dev` checkout, from their own terminal): in a launched session, ask the agent to add `import re` to an existing module (allowed, the `regex` finding told after it), to write a docs file (allowed without a prompt), and to edit `pyproject.toml` (held, the agent waiting, until the operator answers its item in the inbox). `lup-dev verdicts` shows them.

### Where things live

| What | Where | Why there |
|---|---|---|
| A worktree's store: snapshots, the accepted tree and each session's starting tree (as refs), its state, the calls running, holds, each session's record there, the importers pass, the engine's lock and log | `$XDG_STATE_HOME/lup/worktrees/<id>/` | Outside the worktree, so the restore source is out of the agent's reach in a room; on the host, as the operator's user, it isn't |
| The verdict log, each worktree's `HEAD` at its last checkpoint, the last declaration that loaded, the exported declarations, the approval | `$XDG_STATE_HOME/lup/repositories/<id>/`: `verdicts.jsonl`, `heads.json`, `last-declaration.json`, `declarations/<commit>/`, `approved.json` | One per repository, read from every worktree |
| A session's repository and the worktrees it holds; its subagents at work and what its turns ended past; the failures its operator was warned of | `$XDG_STATE_HOME/lup/session-index/<session>.json`, `.conversations.json`, `.warned.json` | A session's later hooks find its worktrees wherever its working directory is |
| Saved versions | `<worktree>/.lup/saved/<n>/` | The agent edits and moves them |
| The gate's passes, and the deferred work it last found due | `<git common dir>/lup/passes/`, `lup/due.json` | Every worktree and room of the repository shares them, and they outlast a room's session |
| A worktree's engine socket | `$XDG_RUNTIME_DIR/lup/<id>.sock`, or `lup-<user>` in the temporary directory | A socket's path holds about a hundred bytes, which a store's path can exceed |
| The built engine | `lup_dev/codescan/bundle/` | The installed package carries it beside the judge |

`layout.py` places all of it, with the rest of lup's state.

### Modules

In `packages/lup-dev/src/lup_dev/`, whose subsystems import downwards (`adapters` above `launch`, `policy`, `codescan`, `declaration` and `catalog`: an import contract in `pyproject.toml`; `docs/conventions.md`, *Package layout*). The rest of the package is in `docs/launch.md` and `docs/host-tools.md`.

| Module | What it holds |
|---|---|
| `policy/roles.py` | Path roles: which role a path has, which paths the rules read, whose findings are reported |
| `policy/judge.py` | One judgement over a set of changed files: role, rules, public API, directives, outcome |
| `policy/surface.py` | The public-API comparison |
| `policy/before.py` | A file tool's write before it lands: its proposal, its would-be content, the judgement |
| `policy/checkpoint.py` | The events, the calls running, the checkpoint in each worktree, a move of `HEAD`, the turn's end, the declaration a worktree is judged by and its stand-in |
| `policy/store.py` | The store: snapshot, compare, set aside what was committed elsewhere or merged from it, restore, save |
| `policy/worktrees.py` | The session's repository, a path's worktree, the worktrees a session holds |
| `policy/importers.py` | The background pass re-checking the files importing what changed |
| `policy/holds.py` | Holds: waiting for an answer, and answering |
| `policy/verdicts.py` | The verdict log and its summary |
| `policy/report.py` | What the agent and the operator are told, in pyright's shape |
| `policy/runtime.py` | `Runtime`: what the core needs to know of a runtime |
| `codescan/contract.py` | The engine's contract: findings, reports, surfaces, rules, and `Checker`, which tests fake |
| `codescan/engine.py` | `EngineChecker`, the engine's client |
| `codescan/ruff.py` | ruff's findings, run through the runner |
| `codescan/directives.py` | The `# lup:` directive models and what's wrong with them; the issue trackers a deferral is checked against |
| `codescan/conditions.py` | `Condition`, the stock conditions, and reading a project's |
| `codescan/reference.py` | `docs/rules.md`, compiled from the rules the engine lists |
| `catalog/paths.py`, `catalog/rules.ts`, `catalog/rules.py`, `catalog/gate.py` | The default path patterns, the rule table, the rules lup's default leaves out, the gate's steps |
| `adapters/claude.py`, `adapters/codex.py` | Each runtime's hooks read as lup's events, and its answers spelled |
| `gate.py` | `lup-dev check`: its steps, its fixes, its passes, the gate on a commit |
| `cli.py` | The `lup-dev` command, and the one place listing the adapters |
| `packages/lup-dev/checker/` | The engine's TypeScript, built with the rule table into one bundle |

The `lup-dev` command stands in for the `lup` command tree until that's built; the commands keep their meaning there.

## Where it's going

`DESIGN.md`, *Keeping the operator in the loop*, describes where judging heads:
- **Spelling rules at the gate.** Spelling rules (`elif` chains, loops that fill a list) aren't told while the agent works: fixed at the gate where a fixer exists, and reported once before landing (`docs/conventions.md`, *Who owns each concern*).
- **Flagged writes in the review.** What lands flagged gathers per branch in the operator's review as it lands, so a change of design is seen while it's fresh, and merging the branch waits on that review.
- **Batches.** What the operator should see (new modules, whole-file writes, public-API changes, added `ignore`s, protected paths) gathers into a batch the agent proposes when it's ready, one diff with its explanation, which pauses the agent until the operator answers unless it carries on.
- **The room as the wall.** Every agent runs in a container, with the store and the holds out of its reach, and a path a room mounts read-only (tests written as a specification, say) is refused by the wall itself.
- **Imports checked at the edit,** against the import-linter contracts, from the imports the engine already reports.
- **Notes with a home:** the notes the engine collects go to a resolver, and a note pointing at a ledger's record goes when the record closes.
- **The `lup` command tree** in place of `lup-dev`.
