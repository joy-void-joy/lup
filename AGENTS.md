# Working on lup

lup is the environment sessions on Claude Code and Codex work in: the workflows, skills, defaults and patterns that make the work go well, for the agents doing it and for the operator working with them, as modules every project can use. It's built today as two packages, `lup` and `lup-dev`, which the module system will split. `DESIGN.md` describes what lup is meant to be: read it to know what you're working on.

This repository is the second lup. The first (`joy-void-joy/lup-legacy`, archived) is evidence you may read (how something behaved, what a measurement found), never code to copy. Everything here is written anew.

This file is lup's own section of the guidance. Before it, every session in every project reads the sections lup's modules ship: `core.md`, `python.md` and `code_rules.md` in `packages/lup-dev/src/lup_dev/declaration/modules/guidance/`, and a `guidance.md` beside the module that ships it. A session outside a room reads only this file: read those too, knowing that their walls, tools and holds are a room's.

To change what sessions are told, propose an edit to the file it belongs in, with its reason. Before adding a line, check that every session needs it, not only your task, and that lup doesn't already say it at the moment it's due: lines added mid-task for one task are what make guidance hard to read. Edits to these files and to `DESIGN.md` wait for the operator, so they see how the guidance changes.

## Landing work

1. **Decisions first,** put to the operator before a piece is built.
2. **One concern per branch,** from `dev`, landed by the session that started the work. When the gate passes, merge the branch into `dev` with a merge commit, and push. The gate (`uv run lup-dev check`) builds lup's engine first where it's missing or stale, so run it before `pytest` in a fresh worktree. A simple doc change skips the branch and lands on `dev` directly.
3. **A worker doesn't land its own branch.** It commits on its branch, leaves it unpushed, and hands it back. The session that delegated it reviews it, runs `uv run lup-dev check --fix` on the merged result, and lands it with what the fixes changed in the merge commit. One merge at a time, so the shared `dev` checkout never takes two at once and every branch is looked at before it lands.
4. **A merge never drops code silently.** Where a conflict is resolved, keep both sides rather than lose one, and don't let a rename on one side swallow an addition on the other. Before finishing, compare the result against both parents: each function, parameter or command removed should be removed on purpose, not as a side effect of picking a side.
5. **Commit messages** are `type(scope): what changed and why`. A merge commit's message says what changed and why the code works that way, every new file and public-API change, how it was tested, and what got in the way, if anything. How the work felt goes to `how_it_went`.
6. **A release is a pull request from `dev` to `main`,** which the operator reviews and merges. Its description says what changed since the last release. Never merge into `main` or push to it yourself.
7. **lup's own sessions use a piece once it's finished.** Until then, don't select it in `lup_project.py` or point lup's guidance at it: the sessions building it would be working inside it.

The roadmap issue (#123) orders the work, so what you file can find its place there.

## lup's code

Beside the code rules every project gets (`docs/conventions.md` has the reasons behind each):
- **Say it once, where it's looked up.** A message lup sends at an event (a hook's reason, a finding, a refusal) says only what its reader needs next; what they'd need again goes where it can be looked up, a command or a doc. A line repeated at every event stops being read.
- **A library side never imports an environment side.** What code calling agents imports, wherever it runs, is a module's library side; what only a project's sessions get is an environment side. As built, `lup`'s library code never imports `lup_dev`; the environment sides of modules that live in `lup`'s directory (`lup.github`, `lup.transcripts`) do, and the import contract in `pyproject.toml` lists each.
- **Both runtimes.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Codex rotted in the first lup because features were built per runtime above the adapter.

## docs/

`docs/README.md` lists the docs, a line each. Each piece's doc describes it as built: what it's for, how to use it, and the reasons that aren't obvious, each beside the fact it explains, in a screen or two, kept true as the code changes. Details go in docstrings beside the code, future work in issues, and what was measured in `docs/field-notes.md`, with its version and date. No history: what was tried, when, and who decided stays out. A doc is one piece's, so it can move with that piece's module once the core is split into modules (#113); a citation names a doc and its section, and a test checks it names ones that exist.
