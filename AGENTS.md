# Working on lup

lup is the environment sessions on Claude Code and Codex work in: the workflows, skills, defaults and patterns that make the work go well, for the agents doing it and for the operator working with them, as modules every project can use. `DESIGN.md` says what it's meant to be. Read it before anything else, and judge your piece against it rather than against a checklist: it's short, and edits to it wait for the operator, so it says what they mean lup to be.

To change what sessions are told, propose an edit to the file it belongs in, with its reason. Before adding a line, check that every session needs it, not only your task, and that lup doesn't already say it at the moment it's due: lines added mid-task for one task are what make guidance hard to read. Edits to this file and to `DESIGN.md` wait for the operator, so they see how the guidance changes.

## Where this repository stands

This is the third lup, and it starts from `DESIGN.md`. Milestone 1's tracking issue (#1) lists the pieces in order, and each piece's issue says what it is, what carries over and when it's done.

Until this lup runs its own sessions (#13), you run on the second lup: its rooms, its tools and its guidance. Where that guidance speaks of lup's own repository (its docs, its commands, `lup-dev`), it means the second lup's, not this one.

## The earlier lups

- **The second lup** (`joy-void-joy/lup-legacy-2`; where the operator relates it, a room mounts it read-only beside this one) has working code for most pieces. For a piece, read its doc there first (`docs/`, a screen or two each), then its code and its tests, which show how it behaves. Carry over what fits this repository's shape (a module in its own directory, nothing outside the contract, a page that knows no module), and rewrite what doesn't. Its files of thousands of lines are the shape to leave behind, not to copy.
- **Its docs, issues and design texts were written by sessions.** They say what was built and how it was reasoned, not what the operator decided, its roadmap and its design issues included. Where one bears on the shape of your piece, put it to the operator rather than taking it as settled.
- **`docs/field-notes.md` came over whole:** what was measured of each runtime and of git, with its version. Where a note names a path, a command or an issue, it's the second lup's.
- **The first lup** (`joy-void-joy/lup-legacy`) is evidence only: how something behaved, what a measurement found.

## How the work goes

- **Decisions first,** put to the operator before a piece is built.
- **Hand building on with the conversation, not a brief.** When part of the work goes to another agent, fork it (Claude Code's `fork` agent, Codex's `fork_context`) rather than summarise for it: a fork has what was discussed, so what it asks the operator is about the work rather than about your brief. A brief is for a side job, a search or a measurement, whose report comes back to you.
- **Build the piece whole, on both runtimes, and run it.** A piece is done when it does what its issue says on Claude Code and on Codex, driven end to end with real logins. A test against a stub of a runtime proves the stub. Where you can't run something from your room, say so and ask, rather than build past it.
- **Finish what you took up.** What you couldn't finish stays in its issue, saying what's left and why, rather than going to a new issue nobody holds.

## Landing work

1. **One concern per branch,** from `dev`, landed with `land` by whoever wrote it, never by the session that handed them the work: what waits on the operator at landing, and each comment on it, reaches the one who wrote the code. A simple doc change skips the branch: commit it on `dev` and call `land` without one.
2. **A merge never drops code silently.** Where a conflict is resolved, keep both sides rather than lose one, and don't let a rename on one side swallow an addition on the other. Before finishing, compare the result against both parents: each function, parameter or command removed should be removed on purpose, not as a side effect of picking a side.
3. **Commit messages** are `type(scope): what changed and why`. A merge commit's message says what changed and why the code works that way, every new file and public-API change, how it was tested, and what got in the way, if anything.
4. **A release is a pull request from `dev` to `main`,** which the operator reviews and merges. Its description says what changed since the last release. Never merge into `main` or push to it yourself.

**Issues stay few and current.** Before filing, search, and add to the issue that's there rather than file one beside it. The tracking issue orders the work: filing or closing an issue it lists means editing its list. An issue is written for someone reading it outside lup, saying what and why; a session's raw detail stays in the session.

## lup's code

Beside the code rules every project gets:
- **Modules from the first commit.** Every piece is a module in its own directory, the core's included, and nothing sits outside the contract. A module whose doc no longer fits a screen or two is two modules.
- **The page knows no module.** A view a module can't say in blocks is a reason to grow the blocks, for every module, never to draw that view in the page.
- **Say it once, where it's looked up.** A message lup sends at an event (a hook's reason, a finding, a refusal) says only what its reader needs next; what they'd need again goes where it can be looked up, a command or a doc. A line repeated at every event stops being read.
- **A library side never imports an environment side,** held apart by import contracts.
- **Nothing above the runtimes' adapter names a runtime.** Codex rotted in the first lup because features were built per runtime above the adapter.

## docs/

`docs/README.md` lists the docs, a line each. Each module's doc describes it as built: what it's for, how to use it, and the reasons that aren't obvious, each beside the fact it explains, in a screen or two, kept true as the code changes. Details go in docstrings beside the code, future work in issues, and what was measured in `docs/field-notes.md`, with its version and date. No history: what was tried, when, and who decided stays out.
