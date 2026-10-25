# Working on lup

lup is the environment sessions on Claude Code and Codex work in: the workflows, skills, defaults and patterns that make the work go well, for the agents doing it and for the operator working with them, as modules every project can use. It's built today as two packages, `lup` and `lup-dev`, which the module system will split. `DESIGN.md` describes what lup is meant to be: read it to know what you're working on.

This repository is the second lup. The first (`joy-void-joy/lup-legacy`, archived) is evidence you may read (how something behaved, what a measurement found), never code to copy. Everything here is written anew.

This file is lup's own section of the guidance. Before it, every session in every project reads the sections lup's modules ship: `core.md`, `python.md` and `code_rules.md` in `packages/lup-dev/src/lup_dev/declaration/modules/guidance/`, and a `guidance.md` beside the module that ships it. A session outside a room reads only this file: read those too, knowing that their walls, tools and holds are a room's.

To change what sessions are told, propose an edit to the file it belongs in, with its reason. Before adding a line, check that every session needs it, not only your task, and that lup doesn't already say it at the moment it's due: lines added mid-task for one task are what make guidance hard to read. Edits to these files and to `DESIGN.md` wait for the operator, so they see how the guidance changes.

## Landing work

1. **Decisions first,** put to the operator before a piece is built.
2. **One concern per branch,** from `dev`, landed by the session that started the work with lup's `land` tool, given the branch and the merge commit's message: it merges the branch onto `dev`, runs the gate on the merge with its fixes, waits for the operator's approval of what was flagged, pushes, and cleans up the branch and its worktree. The gate (`uv run lup-dev check`) builds lup's engine first where it's missing or stale, so run it before `pytest` in a fresh worktree. A simple doc change skips the branch: commit it on `dev` and call `land` without one.
3. **A worker doesn't land its own branch.** It commits on its branch, runs the gate there, leaves it unpushed, and hands it back without merging `dev` into it: a clean merge is `land`'s. The session that delegated it reviews it and lands it. Where `land` says the merge conflicts, whoever works on the branch merges `dev` into it in its worktree, resolves, runs the gate there, and the branch is landed again.
4. **A merge never drops code silently.** Where a conflict is resolved, keep both sides rather than lose one, and don't let a rename on one side swallow an addition on the other. Before finishing, compare the result against both parents: each function, parameter or command removed should be removed on purpose, not as a side effect of picking a side.
5. **After landing,** close each issue the merge settles once nothing is dropped: what's left filed as its own issue, a lesson carried where it'll be looked up, and the closing comment saying where each went.
6. **Commit messages** are `type(scope): what changed and why`. A merge commit's message says what changed and why the code works that way, every new file and public-API change, how it was tested, and what got in the way, if anything. How the work felt goes to `how_it_went`.
7. **A release is a pull request from `dev` to `main`,** which the operator reviews and merges. Its description says what changed since the last release. Never merge into `main` or push to it yourself.
8. **lup's own sessions use a piece once it's finished.** Until then, don't select it in `lup_project.py` or point lup's guidance at it: the sessions building it would be working inside it.

**Issues stay few and current.** Before filing, search, and add to the issue that's there rather than file one beside it. When a newer issue covers an older one, close the older the same day, saying where each part went: close readily, and reopen or file anew for a part that remains. The roadmap issue (#123) orders the work: filing or closing an issue it lists means editing its list, not adding a comment. Each issue carries its type as a label (`bug`, `feature`, `task`, or `tracking` for one that only lists others) and its priority (`priority: high` for what's next and for a security hole, `priority: medium` for the rest of the roadmap's first phase, `priority: low` for everything else), with `design first` where its design is settled with the operator before it's built and `security` for a hole in the walls or in what's published, so the list can be filtered rather than read whole.

## lup's code

Beside the code rules every project gets (`docs/conventions.md` has the reasons behind each):
- **Say it once, where it's looked up.** A message lup sends at an event (a hook's reason, a finding, a refusal) says only what its reader needs next; what they'd need again goes where it can be looked up, a command or a doc. A line repeated at every event stops being read.
- **A library side never imports an environment side.** What code calling agents imports, wherever it runs, is a module's library side; what only a project's sessions get is an environment side. As built, `lup`'s library code never imports `lup_dev`; the environment side of a module that lives in `lup`'s directory (`lup.github`) does, and the import contract in `pyproject.toml` lists it. A module in a distribution of its own keeps its environment side in a subpackage, held apart by contracts of its own (`packages/lup-transcripts/README.md`, *Layout*).
- **Both runtimes.** A shared construct is done when it works on Claude Code and on Codex, shown by their tests, or when the runtime that can't do it declares the gap with evidence. Codex rotted in the first lup because features were built per runtime above the adapter.

## docs/

`docs/README.md` lists the docs, a line each. Each piece's doc describes it as built: what it's for, how to use it, and the reasons that aren't obvious, each beside the fact it explains, in a screen or two, kept true as the code changes. Details go in docstrings beside the code, future work in issues, and what was measured in `docs/field-notes.md`, with its version and date. No history: what was tried, when, and who decided stays out. A doc is one piece's, so it can move with that piece's module once the core is split into modules (#113); a citation names a doc and its section, and a test checks it names ones that exist.
