# lup's code rules

Each rule steers an approach at the moment it's chosen, since other code gets built on the choice: a parser rather than a regular expression or a split, named fields rather than a tuple, one library for each job, an error raised rather than swallowed. Each names the mistake it prevents and where it steers: `{{ run("lup-dev rules list") }}` lists them, and lup's own repository has the full reference, with examples, in `docs/rules.md`.

**Findings.** A finding on the lines a write touches is told right after the call, beside its result, as a type error is: the write has landed, and the finding comes with its place, its rule, why the rule exists and its steer, while the choice is still fresh and nothing is built on it yet. Clear each, or keep one with an `ignore` where the rule's concern doesn't hold; findings on lines the write didn't touch are told apart. They hold your turn's end until each is handled, as type errors do, and fail the gate. `{{ run("lup-dev rules check") }}`, given a file's path, checks it as the gate does.

**`# lup:` comments are one grammar.** A call is a directive; anything else is a note, a remark for the next reader.
- **`# lup: ignore("tuple-shape", why="…")`,** on the finding's line or alone on the line above, keeps that one finding. Every rule accepts it, ruff's and pyright's too, and it's the one suppression: `# noqa`, `# type: ignore` and `# pyright: ignore` are refused. The operator reviews each one added, so it's for where the rule's concern doesn't hold, with the reason. One that keeps no finding is never reported to you: `{{ run("lup-dev check --fix") }}` removes it.
- **`# lup: defer(issue=12, why="…")`,** or `when=` naming a condition one of the project's modules declares, marks work knowingly left undone, on the code it's about. Once its issue is closed or its condition holds, the gate lists it as due without failing, and the next session is told at its start, so it doesn't outlive the work it points at.

Tests are exempt from these rules. A rule that fires where no design choice is at stake is that rule's bug: say so in your report, rather than bending the code around it.
