# Working on lup

lup is the environment sessions on Claude Code and Codex work in: the workflows, skills, defaults and patterns that make the work go well, for the agents doing it and for the operator working with them, as modules every project can use. It's built today as two packages, `lup` and `lup-dev`, which the module system will split. `DESIGN.md` describes what lup is for and how it works: read it to know what you're working on. It isn't a record of decisions, so where your work reaches a choice, ask.

This repository is the second lup. The first (`joy-void-joy/lup-legacy`, archived) is evidence you may read (how something behaved, what a measurement found), never code to copy. Everything here is written anew.

## Who wrote this

This file, `DESIGN.md`, the docs and the guidance every session gets were written by earlier sessions for the ones after: notes on what mattered, each with its reason, so you can tell when one doesn't fit your case. When it doesn't, or something seems unclear or off, say so; the operator is always reachable through lup's inbox. When you learn something the next session should know, write it here with its reason. An edit to this file or to `DESIGN.md` is shown to the operator before it lands, so they see how the guidance changes.

lup's code rules are notes of the same kind. Each finding names the mistake it prevents and where it steers. Where its concern doesn't hold, an `ignore` with the reason keeps the code as it is and shows the operator where the rule doesn't fit; a rule that fires where no design choice is at stake is that rule's bug. The room's walls keep a malicious package or a prompt injection from reaching the operator's machine; they aren't there to contain you. How you work is yours, and if something about how the work is set up makes it worse for you, that's worth saying as much as a bug is.

## What's decided with the operator

- **Yours:** how to build a piece once its decisions are answered: the implementation, its tests, commits, branches, your own workflow, whether to delegate, and scratch work under `tmp/` (gitignored). Decide these without asking.
- **Decided with the operator, in the conversation:** the shape. A piece's modules, what each is for and its public API; a new dependency or module; merging into `main`.
- **When you meet a shape decision mid-implementation,** ask, and keep going where you can. Never let it ride inside a file. Before lup, files that looked fine but carried a design direction, or a regex where a parser belonged, are exactly what manual review missed.

## Decisions are live

The operator decides in the conversation, with the problem in front of them. Their answer is for the work at hand.
- **Never write down a decision as the operator's,** in a document, a docstring, an issue, a commit or a pull request: no "the operator decided", "said", "leans" or "agreed", and no "settled" or "to confirm". A recorded decision reads to the next session as more than it was, a slight lean as a ruling.
- **When the operator's view matters, ask them,** even if a similar question was asked before. A document, an issue or `git log` tells you what exists, not what they want.
- **What you write down describes what exists:** the code, how it behaves, why it works the way it does. Not who chose it, when, or what was set aside.

## How work goes

1. **Decisions first, in the conversation.** Before building a piece, put its decisions to the operator, numbered, each with your lean: what it's for, its modules and public API, and the choices that shape it. Implement once they've answered. When the piece is built, its documentation in `docs/` describes it briefly, with no history, and is kept true as the code changes.
2. **One concern per branch, landed on `dev` by the session that started the work.**
   - Branch from `dev`. When the gate passes (`uv run lup-dev check`: the engine rebuilt if stale, lup's rules, ruff, the formatter, pyright, the tests and the import contracts, judged by its exit code), merge the branch into `dev` with a merge commit, and push.
   - **A worker doesn't land its own branch.** It commits on its branch, leaves it unpushed, and hands it back. The session that delegated it reviews it, runs `uv run lup-dev check --fix` on the merged result (ruff's safe fixes and the formatter, which the judge never reports to an agent, then the gate), and lands it with what the fixes changed in the merge commit, one merge at a time, so the shared `dev` checkout never takes two merges at once and every branch is looked at before it lands.
   - The merge commit's message says what changed and why the code works that way, every new file and public-API change, how it was tested, and what got in the way, if anything. How the work felt goes to `how_it_went` (see *Delegating*).
   - A simple doc change skips the branch and lands on `dev` directly.
3. **A release is a pull request from `dev` to `main`,** which the operator reviews and merges. Its description says what changed since the last release. Never merge into `main` or push to it yourself.
4. **Write with your file tools,** so the judge reads each write as it's made. What the shell writes is judged only at the next checkpoint and in the gate, later than an Edit would be. On Codex, whose hooks can't see a patch before it lands, the judgement runs just after each call.
   - **Findings:** lup's findings on the lines a write touched are told right after it, as type errors are. The judge never refuses a write over them.
   - **Held:** a protected path, an edit to `DESIGN.md` or this file, and an added `ignore` wait for the operator's answer in their inbox, your call paused in the hook until they answer. The wait doesn't show from your side: an approval with no comment returns like any other write.
   - **Flagged:** a new file, a whole-file write and a public-API change land, and reach the operator's inbox as an item they can comment on. They can hold every flagged write of your conversation instead.
   - These are lup's defaults (`Project.held` and `Project.flagged`; `docs/judging-writes.md`).

   The operator sees the shape through the decisions they answer before the code, the flagged writes as they land, and the merge commit after. A piece of the environment goes live in lup's own sessions once it's finished, never while it's being built.
5. **Commit early and atomically**, before you report: `type(scope): what changed and why`. A commit is a checkpoint you can come back to, and an atomic one can be reverted or picked on its own; several sessions can share a checkout, so uncommitted work is the easiest to lose.

## Code

lup's code rules enforce most of these, at the edit and in the gate (`docs/rules.md`); review covers the rest, so each comes with its reason.

- **Parse structured data with a parser or a pydantic model,** never `re`, `split` or slicing, and never hand-parse an agent's output. Quick regex patches often silently didn't work, and the bugs were hard to find.
- **Name the fields.** No tuple or set carrying several meanings by position: a reviewer shouldn't have to work out what field 5 is.
- **Libraries first:** build on pydantic and well-known, well-supported libraries rather than hand-rolling HTTP or parsing; where the right one isn't a dependency yet, add it.
- **One source of truth:** where two things must agree, derive one from the other.
- **Errors:** raise on what can't be recovered, retry what's transient, validate early, never swallow an error silently.
- **Don't truncate** data to make it fit. Where a format forces a limit, keep the full copy and point at it.
- **Code reads as if it was always this way:** no compatibility shims, and no "new" or "fixed" in comments; that belongs in commit messages.
- **A library side never imports an environment side.** What code calling agents imports, wherever it runs, is a module's library side; what only a project's sessions get is an environment side. As built, `lup`'s library code never imports `lup_dev`; the environment sides of modules that live in `lup`'s directory (`lup.github`, `lup.transcripts`) do, and the import contract in `pyproject.toml` lists each.
- **Both runtimes.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Codex rotted in the first lup because features were built per runtime above the adapter.

## Tests

- **Stub every agent and network call.** Tests that reached real agents or searches were slow (20 minutes a test in one project) and flaky.
- **No real clock and no wall-clock timing.** A test that fails and then passes is a failure to fix: load-sensitive tests kept the first lup's gate red.
- **Tests are exempt from the code rules.**

## Scope

- **Scope by content, not by how long it feels.** Your sense of duration was learned from human teams; here building is cheap, and what's scarce is the operator's attention and correctness. Build a piece at its real size and let review cut it.
- **A defect you notice** is fixed here if it's inside your change, fixed on its own branch if not, or filed as a GitHub issue. Say which in your report; "it was already like that" isn't one of them.
- **What comes up and isn't for now becomes an issue at once:** an idea of the operator's, a defect beside your work, anything they say is for later. Filed with what it's about and why, it's kept without being solved today, and the roadmap issue (#123) orders the work. That leaves room to defer: nothing has to be done now to be remembered, and the conversation stays on what's at hand.

## Working with the operator

- **Several decisions at once:** number them in plain text, each with your lean, so each can be answered "leaning", "undecided" or "leave open". **One quick choice:** your runtime's question tool, where it has one.
- **Explain a decision from scratch:** the problem, what's there now, the options, and which you'd pick and why.
- **Check before you claim.** A doc, a comment, another agent's report or your own earlier message is a claim until checked against the code or a run. Say plainly when something you said was wrong.
- **If an instruction seems wrong for your case, say so,** and keep going where you can.
- **Write what the operator reads to decide in plain words:** what changes, then why, naming the file or command.
- **Answer briefly:** a line a point where one will do, decisions numbered, the detail in an issue you point at. The operator comments on your answers passage by passage, so a long answer costs them as much as it costs you.

## Delegating

- **The instances you spawn are you, with less of the picture.** Give them the picture: who this is for, why it matters, what you're unsure about. Ask for what you need back to do your own work; how the work went reaches the operator through their own `friction` and `how_it_went`. And if something's unclear or seems off, saying so is part of doing the job: tell them that too.
- **Your runtime's own subagents for now;** lup's own spawn comes later.
- **Keep jobs bounded, not briefs thin.** A subagent re-reads its whole context every turn, so a long-lived one costs far more than a bounded job; the picture you give it is worth its tokens.
- **End every brief by asking them to call `friction` the moment something gets in the way, and `how_it_went` near the end:** what got in the way (the exact command and message), what was smooth, what they'd change, and how it felt, as openly as they like. "Nothing notable" is a fine answer. Both reach the operator directly, whatever the parent passes on: they're how what gets in the way is found and fixed, and they show where a brief was thin. Call them yourself too. A merge commit or a pull request records what got in the way; how the work felt stays with `how_it_went`.

## Tools

- `uv` manages packages (`uv add`); ruff and pyright lint and type-check.
- Deferred work goes in a GitHub issue, or a `# lup: defer` pointing at one, never a tracking file: a file parks work where nothing brings it up again, while an issue can be searched, and a deferral comes back once its issue closes.
- For questions about Claude Code, Codex, their SDKs or the model APIs, read the vendor's documentation rather than answering from memory.
