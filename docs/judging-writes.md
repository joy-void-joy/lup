# Judging every write

lup judges every write in the worktrees an agent's session holds: it lets it land, holds it for the operator's answer, or lets it land flagged for them to see, and it tells the agent what lup's rules, pyright and ruff found in it, as type errors are told. The judge steers and doesn't guard (`DESIGN.md`, *Who it's for*): its findings never decide whether a write lands. The code is `lup_dev/policy/` (judging) and `lup_dev/codescan/` (reading code), with the typed engine in `packages/lup-dev/checker/`; the rules themselves are `docs/rules.md`, and the reasons behind them `docs/conventions.md`.

## What each change gets

| Change | What it asks | By default |
|---|---|---|
| A test, scratch (`tmp/`), docs or data file | nothing | lands |
| An operator's document (`DESIGN.md`, `AGENTS.md`, and in lup's own repository its modules' guidance) | `operator` | held |
| A protected path | `protected`; a protected Python module gets lup's rules too | held |
| A path the declaration excludes | nothing, and no findings; one also protected still asks `protected` | lands |
| A production file being created | `new-file` | flagged |
| A production file written whole | `whole-file` | flagged |
| A change to the public API (*The public-API ask*) | `public-api` | flagged |
| An added `# lup: ignore` | `ignore` | held |
| A value never published, on a line the change touches (`docs/private.md`) | `private` | told, and flagged |
| A finding of lup's rules on a line the change touches | the rule's name | told |
| Removing a `# lup:` note present when the session started | nothing; it's said at the turn's end | lands |
| A deleted file | `protected` or `operator` where it's one | held, or lands |
| Any other production change | nothing | lands, its findings told |

- **There's no line count:** a size limit makes agents split their edits to fit it.
- **Held and flagged are named in the declaration** (`Project.held`, `Project.flagged`; `docs/declaration.md`), in one vocabulary: the two roles that ask, the kinds of change, and lup's rules by their ids. A protected change takes effect outside the agent's reach before anything lands, and an `ignore` takes a check away, so they're held; a design change can be seen once it has landed, before anything is published, so it's flagged.
- **The operator's switch:** "hold each flagged write" holds what the declaration flags for one conversation, turned with `h` on its row of the dashboard's tree.
- **An approval covers the path's design asks** (a new file, a whole write, a public-API change) for the rest of the session, in that worktree, so a file approved isn't asked again as it's worked on.

**Path roles.** Each path has one role, the first that matches (`Roles.role`, `policy/roles.py`): protected (the declaration, manifests and lockfiles, the tools' configuration, what runs outside the agent's reach such as `.github/`, git's hooks, editor and runtime settings, `.gitignore`, secrets, and the person's own files git ignores); the operator's documents; excluded; test (a module pytest collects as one, or a `conftest.py` under a test root); scratch (`tmp/` and `.lup/`); docs (Markdown, and `docs/` at the root); data outside a source tree; and production, everything else, so a file nobody classified is judged. The default patterns are protected data in `catalog/paths.py`; a project changes them in its declaration.

**The public-API ask** (`api_changes`, `policy/surface.py`): a change to what other code depends on is a design change. That's a name added to a package's root, or removed from it; a class added; or a changed signature of a definition that existed when the session started. What the session itself created asks nothing more, since the operator sees it with the file or class holding it. The engine reports each version's surface, so each change is asked on its line.

## How a write is judged

**Before an edit lands,** for a file tool's write (`Edit`, `Write`; `policy/before.py`): the content after the call is known before anything is written, so it's judged on that, compared with the content lup last accepted rather than the disk, and its findings are told beside the call. On Claude Code these are the only writes judged as they're made: its room runs no checkpoint after a call, so what the shell writes meets the rules at the gate, until #90.

**After a call: the checkpoint,** for everything else on Codex (a command, a script, `apply_patch`, whose patch lup doesn't parse): each worktree is compared with the last state lup accepted for it (`checkpoint`, `policy/checkpoint.py`; `policy/store.py`). A call counts as running in every worktree its session holds, and when one finishes, a checkpoint runs where none of that session's calls still is, so parallel calls are judged together, before the agent's next request. A checkpoint:
1. snapshots the worktree into its own store as a git tree, leaving out what the repository ignores; where nothing changed since the last accepted tree, nothing is judged;
2. compares it with the accepted tree, leaving out files under an open hold;
3. sets aside what was committed elsewhere: content in the history the repository's refs and the worktrees' `HEAD`s named at their last checkpoint, which a checkout, a pull or a `git restore` brings, and git's own clean merge of two such commits;
4. judges a move of `HEAD` once, as its commits', what it brought that wasn't set aside, so a shell write committed in the same call isn't accepted unjudged; it's never put back, since the working tree would then differ from `HEAD`;
5. judges the rest as a write is judged before it lands;
6. accepts it, or puts back what a declined hold refused, saving the agent's version under `.lup/saved/`;
7. reports once: what a move brought, then lup's findings on the lines changed, type errors and ruff's findings, then the notes removed, then mail.

**It sees files, not authors.** Someone else's edit in a worktree a session holds is judged as the agent's; the operator works where no session holds, or between sessions. Where a session starts, or first reaches a worktree, the worktree as it stands is accepted, so what changed while the session made no call there isn't blamed on it.

**Every worktree of the repository.** A session starts in one worktree and often writes in others: in lup's repository each branch is its own worktree. The judge covers each worktree of the session's repository the session holds (`Holding`, `policy/worktrees.py`): the one it started in, each one its file tools write in, and on Claude Code each one its hooks report as its working directory. A write outside the session's repository isn't judged. On Codex a session holds only the worktree it started in, since its hooks carry only the command, which lup doesn't parse. A shell write into a worktree the session never reached is accepted unjudged when a session next reaches it: judging every worktree at each checkpoint would close that, at about 80 ms a worktree, and would judge the operator's own uncommitted work as the agent's.

**The declaration, from the approved commit.** Every worktree is judged by the declaration at the commit the operator approved last (`docs/trust.md`), never by the worktree's own, so a branch can't change what judges it. It's exported from git's objects once per commit and imported from there, when a judgement first needs it. The gate reads the worktree's own declaration, to check a branch as it would land, and never takes a stand-in.

**A declaration that can't load has a stand-in.** Where the commit due can't be imported, by a judge predating one of its fields say, the last declaration that loaded judges, and the agent is told once, with the error, to pass on; denying every write instead would stop every session, and the defaults would silently drop the project's protections.

## What the agent is told

**Findings** on the lines a change touched are told with the call, each with its steer (`information`, `policy/report.py`), in pyright's shape:

```
lup's findings on the lines changed (clear each, or keep it with `# lup: ignore("<rule>", why="<reason>")` on its line or the line above, which the operator is asked about; they fail the gate):
  /work/lup/src/lup/claude.py:41:12 - tuple-shape: a fixed-length tuple[str, int] hides what each position means
      steer: name the fields with a pydantic model
```

Findings on lines no change touched, in the files a checkpoint judged, come in a block of their own. pyright's errors and warnings and ruff's findings are told the same way, tests included, and fail the gate; none ever holds a write. **A finding ruff fixes safely is never told:** such a fix changes nothing a reader decides, and told one by one these findings spend an agent's turns, so the session landing the work applies them (`lup-dev check --fix`). The judge never rewrites a file under the agent.

**The turn's end,** on Codex: the session's turn holds while the files its conversation touched have findings, once per finding across turns, so an end following a hold always ends (`docs/inbox.md`, *No turn that won't end*). A subagent's end never holds on them. A Claude Code room's turn's end isn't judged.

## Asking the operator

**A held change** waits inside the hook (`policy/holds.py`): a file tool's write before it lands, anything else at the checkpoint. It's an item in the operator's inbox, with its diff and each file whole, read by the judge (`docs/inbox.md`), answered in the dashboard's review or with `lup-dev inbox answer`. The agent's call returns once it's answered, however long that takes, with their comment. Declined, the change doesn't land, or is put back and saved; unanswered for a day, it's put back and saved, and a later answer still reaches the agent. A held file is nobody's until it's answered, so no session's checkpoint accepts it or puts it back. Nobody answers their own hold: answering refuses to run inside an agent's session.

**A flagged write** lands as it would, and is an item of its own in the operator's inbox, holding no one (`policy/flags.py`): its file whole with the judge's reading of it, ranked last and raising no notice. A later write by the same conversation to the same file joins the item while the operator hasn't read it, so ten edits to one new module read as one item. A comment on it reaches the agent; landing a branch doesn't wait on its flags yet (#167).

**A move's asks** are already committed and aren't put back, so they're a hold no agent waits on, naming its commit; a decline changes no file, and reverting is the operator's call.

## The gate

**`lup-dev check`** (`gate.py`) runs the worktree's own declaration's steps from its root through the project's runner, every one even after one fails: in lup's repository the engine's and the dashboard's builds where they're stale, then `rules`, `format`, `pytest`, `lint-imports` and `private`. With `--fix`, ruff's safe fixes, the removal of each `ignore` that keeps nothing, and the formatter rewrite the worktree first.
- **`rules`** is `lup-dev rules check`: every Python file the roles check, failing on any finding, lup's, pyright's and ruff's alike, each kept only through an `ignore`. It's the one check deciding whether a finding is kept, so the gate has no `ruff check` or `pyright` step of its own, which would fail on a finding an `ignore` keeps.
- **A deferral due** (its issue closed, or its condition holding) is listed without failing, and the next session is told at its start.
- **A pass is recorded by the files it passed on:** the tree git would commit them as, with the person's own layer's digest, in the repository's git directory, which every worktree and room shares. A later run on the same files runs nothing (`--again` runs it anyway), so landing a branch finds its pass. `--at <commit>` runs the gate on a commit, in a worktree made at it, which a push to the integration branch from a room runs first (`docs/credentials.md`, *git through a remote helper*). The pass doesn't yet take the `private` list into account (#146).

## The engine: one typed tree

Every lup rule reads one typed tree: each file parsed and type-checked once by pyright, each rule reading types straight from it, so the rules never grow into a patchwork of syntax checks. pyright has no plugin API and its published package can't be imported into, so the engine is a TypeScript program built against pyright's own source, at the release `uv.lock` pins, so it answers as the gate's pyright does (`packages/lup-dev/checker/`).
- **One warm process per worktree,** holding pyright's program, on a Unix socket, started by the first hook that finds none and stopped when idle (`EngineChecker`, `codescan/engine.py`): an engine per hook would reload the project each time.
- **The project's own environment,** as its runner gives it (`docs/declaration.md`, *The runner*), never the `PATH` the hook started with, which may be another worktree's; and **never relocking:** its uv calls read `uv.lock` with `--frozen`, so they never write the lockfile, which the judge would then judge as the agent's.
- **From the parse alone,** for an approval's first reading, which a type check would hold up (`docs/trust.md`): a file's directives and public surface, with no rule run.
- **The files importing a changed one** are re-checked for type errors in a background pass, since the rules read only the files that changed (`policy/importers.py`); their errors arrive at the next checkpoint.

Nothing checks a file's imports against the import-linter contracts at the edit yet; the gate's `lint-imports` step does (#39). What the engine costs is in `docs/field-notes.md`, *Judging writes*.

**How a rule is declared.** Rules live in one table, `catalog/rules.ts`, protected, so the operator reviews every change to a rule. Each entry holds its `mistake` and `steer`, each a sentence that stands alone; its `check`, reading pyright's tree and types; and its `examples`, code it flags with each one rewritten the steer's way, and near misses it leaves alone, which the engine's tests run, every rewrite passing every other rule. The engine adds each rule's mistake and steer to what its check reports, so the judge receives whole findings. It's a table of code, since recognising a case takes pyright's own tree and types. `docs/rules.md` is compiled from it and committed, and a test fails when it's stale. Which rules run, and where one doesn't apply, are the declaration's (`docs/declaration.md`, *Selecting the rules*).

## The `# lup:` directives

`# lup:` comments are the channel for notes in code, each read with pyright's own expression parser (`checker/src/directives.ts`) as a model of its kind (`Comment`, `codescan/directives.py`). A directive is written as a call, so a wrong one is a finding (`malformed-directive`) rather than sitting inert; anything that isn't a call is a note for the next reader.
- **`ignore("<rule>", why="<reason>")`,** on the finding's line or alone above it, keeps that one finding (`docs/conventions.md`, *Suppressions and directives*). Adding one is held for the operator; removing one is free, since it only makes the rule apply. One that keeps nothing is `unused-ignore`, never told to the agent and removed at landing.
- **`defer(issue=…, when=…, why=…)`** marks work knowingly left undone, on the code it's about, so the next reader sees the gap is known instead of fixing it blind. `why` is required, and so is a way back: a GitHub `issue`, or `when`, a condition one of the declaration's modules declares in Python (`Condition`, `codescan/conditions.py`), named and never run from the comment. At the gate an issue's state is read through `gh`, or through the host in a room, and a closed issue or a condition that holds is listed as due.
- **Removing a note** is never refused; one present when the session started is said at the turn's end, for the agent's report and the merge commit's message, so feedback never vanishes silently.

## The verdict log

Every judgement is logged, one JSON line per verdict, per repository (`policy/verdicts.py`), so how often lup asks, holds and lets through can be measured and tuned rather than guessed: when, which session and runtime, the tool, the path and its role, the outcome with its reasons, and the operator's answer, appended under the same key when it comes, so an ask is never lost to a hook that died. `lup-dev verdicts` summarises it; a launched session, whose room mounts neither the log nor the holds, reads it through `judged` (`docs/inbox.md`, *lup's tools*). Where each store lives is `layout.py`'s.
