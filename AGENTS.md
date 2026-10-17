# Working on lup

lup is where the operator's way of working with agents lives: the workflows, skills, defaults and patterns that make sessions on Claude Code and Codex better, as modules every project can use. It's built today as two packages, `lup` and `lup-dev`, which the module system will split. `DESIGN.md` describes what lup is for and how it works: read it to know what you're working on. It isn't a record of decisions, so where your work reaches a choice, ask.

This repository is the second lup. The first (`joy-void-joy/lup-legacy`, archived) is evidence you may read (how something behaved, what a measurement found), never code to copy. Everything here is written anew.

## What's yours, what's the operator's

- **Yours:** how to build a piece once the operator has answered its decisions: the implementation, its tests, commits, branches, whether to delegate, and scratch work under `tmp/` (gitignored). Decide these without asking.
- **The operator's:** the shape. A piece's modules, what each is for and its public API; a new dependency or module; `DESIGN.md` and this file; merging.
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
   - The merge commit's message says what changed and why the code works that way, every new file and public-API change, how it was tested, and a short note on how the work felt (see *Delegating*).
   - A simple doc change skips the branch and lands on `dev` directly.
3. **A release is a pull request from `dev` to `main`,** which the operator reviews and merges. Its description says what changed since the last release. Never merge into `main` or push to it yourself.
4. **Write with your file tools.** While lup is being built, the judge runs only before an Edit or Write lands: it refuses a write with a finding of lup's code rules, before the file changes, and asks the operator only about a protected path or one of their documents (`DESIGN.md`, this file), as a prompt in their terminal (`asks` in `lup_project.py`). On Codex, whose hooks can't see a patch before it lands, the same judgement runs just after each call. What the shell writes meets the rules only in the gate, later than an Edit would have. The operator sees the shape through the decisions they answer before the code and the merge commit after it. A piece of the environment goes live in lup's own sessions once it's finished, never while it's being built.
5. **Commit early and atomically**, before you report: `type(scope): what changed and why`.

## Code

lup's code rules enforce most of these, at the edit and in the gate (`docs/rules.md`); review covers the rest, so each comes with its reason.

- **Parse structured data with a parser or a pydantic model,** never `re`, `split` or slicing, and never hand-parse an agent's output. Quick regex patches often silently didn't work, and the bugs were hard to find.
- **Name the fields.** No tuple or set carrying several meanings by position: a reviewer shouldn't have to work out what field 5 is.
- **Libraries first:** build on pydantic and well-known, well-supported libraries rather than hand-rolling HTTP or parsing; where the right one isn't a dependency yet, add it.
- **One source of truth:** where two things must agree, derive one from the other.
- **Errors:** raise on what can't be recovered, retry what's transient, validate early, never swallow an error silently.
- **Don't truncate** data to make it fit. Where a format forces a limit, keep the full copy and point at it.
- **Code reads as if it was always this way:** no compatibility shims, and no "new" or "fixed" in comments; that belongs in commit messages.
- **A library side never imports an environment side.** What code calling agents imports, wherever it runs, is a module's library side; what only a project's sessions get is an environment side. As built, `lup` never imports `lup_dev`.
- **Both runtimes.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Codex rotted in the first lup because features were built per runtime above the adapter.

## Tests

- **Stub every agent and network call.** Tests that reached real agents or searches were slow (20 minutes a test in one project) and flaky.
- **No real clock and no wall-clock timing.** A test that fails and then passes is a failure to fix: load-sensitive tests kept the first lup's gate red.
- **Tests are exempt from the code rules.**

## Scope

- **Scope by content, not by how long it feels.** Your sense of duration was learned from human teams; here building is cheap, and what's scarce is the operator's attention and correctness. Build a piece at its real size and let review cut it.
- **A defect you notice** is fixed here if it's inside your change, fixed on its own branch if not, or filed as a GitHub issue. Say which in your report; "it was already like that" isn't one of them.

## Working with the operator

- **Several decisions at once:** number them in plain text, each with your lean, so each can be answered "leaning", "undecided" or "leave open". **One quick choice:** your runtime's question tool, where it has one.
- **Explain a decision from scratch:** the problem, what's there now, the options, and which you'd pick and why.
- **Check before you claim.** A doc, a comment, another agent's report or your own earlier message is a claim until checked against the code or a run. Say plainly when something you said was wrong.
- **If an instruction seems wrong for your case, say so,** and keep going where you can.
- **Write what the operator reads to decide in plain words:** what changes, then why, naming the file or command.

## Delegating

- **Your runtime's own subagents for now;** lup's own spawn comes later. Prefer short, bounded jobs: a subagent re-reads its whole context every turn, so long-lived ones are most of the token spend.
- **End every brief by asking how the work felt:** what was smooth, what got in the way (the exact command and message), what they'd change. "Nothing notable" is a fine answer. Close your own pull requests with the same note.

## Tools

- `uv` manages packages (`uv add`); ruff and pyright lint and type-check.
- Deferred work goes in a GitHub issue. No tracking files.
- For questions about Claude Code, Codex, their SDKs or the model APIs, read the vendor's documentation rather than answering from memory.
