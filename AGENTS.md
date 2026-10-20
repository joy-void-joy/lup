# Working on lup

lup is the environment sessions on Claude Code and Codex work in: the workflows, skills, defaults and patterns that make the work go well, for the agents doing it and for the operator working with them, as modules every project can use. It's built today as two packages, `lup` and `lup-dev`, which the module system will split. `DESIGN.md` describes what lup is for and how it works: read it to know what you're working on. It isn't a record of decisions, so where your work reaches a choice, ask.

This repository is the second lup. The first (`joy-void-joy/lup-legacy`, archived) is evidence you may read (how something behaved, what a measurement found), never code to copy. Everything here is written anew.

This file holds what's lup's own. What every session is told, in lup or any project (working with the operator, the inbox, what waits for them), is the room's guidance before it, in `packages/lup-dev/src/lup_dev/declaration/modules/guidance/`. A session outside a room reads only this file: read `core.md` there too, knowing that its walls, tools and holds are a room's. When you learn something the next session working on lup should know, write it here with its reason; an edit to this file or `DESIGN.md` waits for the operator, so they see how the guidance changes.

## How work goes

1. **Decisions first,** put to the operator before a piece is built. Once it's built, its documentation in `docs/` describes it briefly, with no history, and is kept true as the code changes.
2. **One concern per branch, landed on `dev` by the session that started the work.**
   - Branch from `dev`. When the gate passes (`uv run lup-dev check`, which also rebuilds lup's engine where it's stale), merge the branch into `dev` with a merge commit, and push.
   - **A worker doesn't land its own branch.** It commits on its branch, leaves it unpushed, and hands it back. The session that delegated it reviews it, runs `uv run lup-dev check --fix` on the merged result, and lands it with what the fixes changed in the merge commit. One merge at a time, so the shared `dev` checkout never takes two at once and every branch is looked at before it lands.
   - **A merge never drops code silently.** Where a conflict is resolved, keep both sides rather than lose one, and a rename on one side mustn't swallow an addition on the other. Before finishing, compare the result against both parents: each function, parameter or command removed should be removed on purpose, not as a side effect of picking a side.
   - The merge commit's message says what changed and why the code works that way, every new file and public-API change, how it was tested, and what got in the way, if anything. How the work felt goes to `how_it_went`.
   - A simple doc change skips the branch and lands on `dev` directly.
3. **A release is a pull request from `dev` to `main`,** which the operator reviews and merges. Its description says what changed since the last release. Never merge into `main` or push to it yourself.
4. **Commit early and atomically,** before you report: `type(scope): what changed and why`. A commit is a checkpoint you can come back to, and an atomic one can be reverted or picked on its own. Several sessions share a checkout, so uncommitted work is the easiest to lose.
5. **A piece of the environment goes live in lup's own sessions once it's finished,** never while it's being built.

## Code

lup's code rules enforce most of these, at the edit and in the gate (`docs/rules.md`); review covers the rest, so each comes with its reason.

- **Parse structured data with a parser or a pydantic model,** never `re`, `split` or slicing, and never hand-parse an agent's output. Quick regex patches often silently didn't work, and the bugs were hard to find.
- **Name the fields.** No tuple or set carrying several meanings by position: a reviewer shouldn't have to work out what field 5 is.
- **Libraries first:** build on pydantic and well-known, well-supported libraries rather than hand-rolling HTTP or parsing; where the right one isn't a dependency yet, add it.
- **One source of truth:** where two things must agree, derive one from the other.
- **Errors:** raise on what can't be recovered, retry what's transient, validate early, never swallow an error silently.
- **Don't truncate** data to make it fit. Where a format forces a limit, keep the full copy and point at it.
- **Code reads as if it was always this way:** no compatibility shims, and no "new" or "fixed" in comments; that belongs in commit messages.
- **Say it once, where it's looked up.** A message lup sends at an event (a hook's reason, a finding, a refusal) says only what its reader needs next; what they'd need again goes where it can be looked up, a command or a doc. A line repeated at every event stops being read.
- **A library side never imports an environment side.** What code calling agents imports, wherever it runs, is a module's library side; what only a project's sessions get is an environment side. As built, `lup`'s library code never imports `lup_dev`; the environment sides of modules that live in `lup`'s directory (`lup.github`, `lup.transcripts`) do, and the import contract in `pyproject.toml` lists each.
- **Both runtimes.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Codex rotted in the first lup because features were built per runtime above the adapter.

## Scope

- **Scope by content, not by how long it feels.** Your sense of duration was learned from human teams; here building is cheap, and what's scarce is the operator's attention and correctness. Build a piece at its real size and let review cut it.
- **A defect you notice** is fixed here if it's inside your change, fixed on its own branch if not, or filed as a GitHub issue. Say which in your report; "it was already like that" isn't one of them.
- **What comes up and isn't for now becomes an issue at once:** an idea of the operator's, a defect beside your work, anything they say is for later. Filed with what it's about and why, it's kept without being solved today, and the roadmap issue (#123) orders the work. Nothing has to be done now to be remembered, and the conversation stays on what's at hand.

## Delegating

- **The instances you spawn are you, with less of the picture.** Give them the picture: who this is for, why it matters, what you're unsure about, and ask for what you need back to do your own work. If something's unclear or seems off, saying so is part of the job: tell them that too.
- **Your runtime's own subagents for now;** lup's own spawn comes later.
- **Keep jobs bounded, not briefs thin.** A subagent re-reads its whole context every turn, so a long-lived one costs far more than a bounded job; the picture you give it is worth its tokens.
- **End every brief by asking them to call `friction` the moment something gets in the way, and `how_it_went` near the end.** Both reach the operator directly, whatever you pass on, and show where a brief was thin. Call them yourself too.

## Tools

- `uv` manages packages (`uv add`); ruff and pyright lint and type-check.
- Deferred work goes in a GitHub issue, or a `# lup: defer` pointing at one, never a tracking file: a file parks work where nothing brings it up again, while an issue can be searched, and a deferral comes back once its issue closes.
- For questions about Claude Code, Codex, their SDKs or the model APIs, read the vendor's documentation rather than answering from memory.
