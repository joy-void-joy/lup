# lup's code rules

lup's code rules are notes like this guidance: each catches a pattern that's rarely the right choice, at the moment it's chosen, since other code gets built on the choice. You're not expected to hold them in memory. Each finding is written to be read cold: what it caught, why that's a mistake, and where it steers.

**Worth knowing before you write,** since hearing them after a long file means restructuring it rather than fixing a line:
- **Nothing is private:** no leading underscore, and a helper with one caller nests inside it. A name is public or nested, so a reviewer never wonders whether `_x` is really private.
- **A shape is a model** deriving from `lup.types.Model`, which is frozen (`MutableModel` where values must change): no dataclass, `NamedTuple` or `TypedDict`, and no tuple or set carrying several meanings. A dict read by literal keys is a model waiting to be validated. One way to declare a shape, validated where it's declared, and no reviewer working out what field 5 is.
- **Structured text is read with its parser** (`json`, `tomllib`, `shlex`, `urllib.parse`, `ast`, `packaging.version`): no `re`, and no `split`, slicing, `strip(chars)` or `replace` to take a string apart. A quick pattern matches the cases tried and fails quietly on the rest; a parser fails loudly.
- **A constant has a home:** a number or a duration is a parameter's or a field's default, so a caller can change it; a path is in the package's `layout.py` and an environment variable a field of its `settings.py`, so each can be found.
- **One library per job:** `lup.programs` to run a program, `typer` for a command line, `pathlib` for files, `pydantic-settings` for the environment, `tenacity` for retries. Two libraries for a job are two ways of doing it, which sessions split between.
- **`match` or guard clauses rather than `elif`,** and a comprehension rather than a loop filling a list: a `match` names what decides once, where a chain hides it.

`{{ run("lup-dev rules list") }}` gives every rule the project runs in a line or two; lup's own repository has the full reference, with examples, in `docs/rules.md`.

**Beyond what a rule can check:** where two things must agree, derive one from the other. Raise on what can't be recovered, retry what's transient, and never swallow an error. Don't truncate data to make it fit; where a format forces a limit, keep the full copy and point at it. An agent's answer comes typed, through lup's `submit`, never parsed by hand. Code reads as if it was always this way, with history in commit messages.

**Findings** on the lines you changed come right after the write, beside its result, as type errors do: the write has landed, and the choice is still fresh. Findings elsewhere in the files you touched come in a block of their own. Fix each, or keep one with an `ignore` where the rule's concern doesn't hold. The gate fails on any left. `{{ run("lup-dev rules check") }}`, given a file's path, checks it as the gate does.

**`# lup:` comments are one grammar.** A call is a directive; anything else is a note for the next reader.
- **`# lup: ignore("tuple-shape", why="…")`,** on the finding's line or alone on the line above, keeps that one finding, whichever tool reported it, ruff and pyright included. It's the only suppression: `# noqa`, `# type: ignore` and `# pyright: ignore` don't count here. Adding one is held for the operator, which shows them where a rule doesn't fit: that's what it's for, so don't bend the code to avoid one. One that no longer keeps a finding is removed by `{{ run("lup-dev check --fix") }}`.
- **`# lup: defer(issue=12, why="…")`** marks work knowingly left undone, on the code it's about; `when=` names a condition one of the project's modules declares instead of an issue. Once the issue closes or the condition holds, the gate lists it as due without failing, and the next session is told at its start.

Tests are exempt from lup's rules, though not from ruff and pyright. A rule that fires where no design choice is at stake is that rule's bug: say so with `friction`, rather than bending the code around it.
