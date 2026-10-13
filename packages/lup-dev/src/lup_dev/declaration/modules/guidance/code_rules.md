# lup's code rules

Each rule steers an approach at the moment it's chosen, since other code gets built on the choice: a parser rather than a regular expression or a split, named fields rather than a tuple, one library for each job, an error raised rather than swallowed. Each names the mistake it prevents and where it steers: `{{ run("lup-dev rules list") }}` lists them, and lup's own repository has the full reference, with examples, in `docs/rules.md`.

**A refusal.** A write to production code with a finding on the lines it touches is refused: the file stays as it was, or is put back, and your version is saved under `.lup/saved/`. The refusal lists every finding in the file at once, each with its place, its rule, why the rule exists and its steer, so one pass fixes them all; findings on lines the write didn't touch are listed too, and don't refuse. Fix the listed lines in the saved copy and move it into place with the command the refusal gives, or, for a file that didn't exist yet, write it again with your file tool. `{{ run("lup-dev rules check") }}`, given a file's path, checks it as the gate does.

**`# lup:` comments are one grammar.** A call is a directive; anything else is a note, a remark for the next reader.
- **`# lup: ignore("tuple-shape", why="…")`,** on the finding's line or alone on the line above, keeps that one finding. Every rule accepts it, ruff's and pyright's too, and it's the one suppression: `# noqa`, `# type: ignore` and `# pyright: ignore` are refused. The operator reviews each one added, so it's for where the rule's concern doesn't hold, with the reason; one that keeps no finding is a finding itself.
- **`# lup: defer(issue=12, why="…")`,** or `when=` naming a condition one of the project's modules declares, marks work knowingly left undone, on the code it's about. The gate fails once its issue is closed or its condition holds, so it doesn't outlive the work it points at.

Tests are exempt from these rules. A rule that fires where no design choice is at stake is that rule's bug: say so in your report, rather than bending the code around it.
