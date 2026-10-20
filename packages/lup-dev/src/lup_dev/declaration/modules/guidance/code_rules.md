# lup's code rules

lup's code rules are notes like this guidance. Each steers an approach at the moment it's chosen, since other code gets built on the choice: a parser rather than a regular expression or a split, named fields rather than a tuple, one library for each job, an error raised rather than swallowed. Each finding names the mistake it prevents and where it steers. `{{ run("lup-dev rules list") }}` lists them; lup's own repository has the full reference, with examples, in `docs/rules.md`.

**Findings** on the lines a write touches are told right after the call, beside its result, as type errors are: the write has landed, and the choice is still fresh. Findings on lines the write didn't touch are told apart. Clear each, or keep one with an `ignore` where the rule's concern doesn't hold. They hold your turn's end until each is handled, and fail the gate. `{{ run("lup-dev rules check") }}`, given a file's path, checks it as the gate does.

**`# lup:` comments are one grammar.** A call is a directive; anything else is a note for the next reader.
- **`# lup: ignore("tuple-shape", why="…")`,** on the finding's line or alone on the line above, keeps that one finding. It's the one suppression, for every rule, ruff's and pyright's too: `# noqa`, `# type: ignore` and `# pyright: ignore` are refused. An added one waits for the operator, and shows them where a rule doesn't fit. One that keeps no finding is never reported to you: `{{ run("lup-dev check --fix") }}` removes it.
- **`# lup: defer(issue=12, why="…")`,** or `when=` naming a condition one of the project's modules declares, marks work knowingly left undone, on the code it's about. Once its issue closes or its condition holds, the gate lists it as due without failing, and the next session is told at its start, so it doesn't outlive the work it points at.

Tests are exempt from these rules, though not from ruff and pyright. A rule that fires where no design choice is at stake is that rule's bug: say so (`friction`), rather than bending the code around it.
