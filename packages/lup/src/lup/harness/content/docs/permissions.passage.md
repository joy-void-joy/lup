# Permission Policy

How the generated hooks decide allow, ask, defer, or deny, and the two
markers that change a decision. The guidance carries the rule; this page
carries the mechanism a denial sends you to.

## Sources of truth

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `harness/catalog.py`. Harness
generation compiles one hermetic dispatcher and runtime for each native
plugin. Never edit generated dispatcher or runtime files — change the
canonical source and regenerate.

## Shell classification

The policy classifies each shell command against
`lup.policy.vocabulary.default_vocabulary` as
`harness/content/shell_vocabulary.py` selects it, every URL scope,
and each edit in a batch. `lup.policy.shell_rules` owns the shape that table
takes and its erasure into the rows the kernel reads, never the words; the
project states only where it differs from what the library offers — a
downstream toolchain to add, a command it judges differently, one it drops —
so declaring `lake` costs one entry rather than a copy of every command the
library already judged. The shell
lattice reserves ask for judged risk; unjudged work denies, hinting the
escalation recipe. Under a launcher-verified OS sandbox
(`LUP_SANDBOX_ACTIVE`), unjudged work defers to that boundary, and a
`dangerouslyDisableSandbox` escape re-enters the deny lattice; the sandbox
block derives from the same `HookSet` declaration. A command the sandbox's
`excluded_commands` takes out of isolation re-enters it too, without the
escape: the boundary was told to leave that command alone, so there is
nothing for unjudged work to defer to.

Segments join deny > ask > defer > allow — unjudged rides into a judged
prompt, a judged deny wins the batch. Malformed input fails conservatively.

### What a rule states, and what it earns

**A rule says what an operation does. It never says what that earns.** The
lattice was once keyed on how a command was *spelled*: a rule named an
executable and stated a verdict beside it, so two commands with one effect
reached different answers whenever two people wrote the two rules. `effects`
is the declaration now — a list from the closed table in
`policy/kernel/effects.py`, each member deciding its own verdict from the
scope it was given, what the host measured, and where the session sits — and
`declared_verdict` derives the answer wherever it is used. Two spellings of
one effect cannot diverge, because there is one row for the effect and every
spelling reaches it.

`ShellCommandRule.effects` and `RunnerTargetRule.effects` are **required**. A
declaration stating none derives an allow, so an omission would be a grant
nobody wrote down rather than a gap a reader sees; a command that genuinely
does nothing this table guards says `changes_nothing`, which exists to be
sayable.

Two things a rule states that are not effects:

- `refuses` — where the agent goes instead, when this project declines the
  *spelling*. Set, the row denies whatever its effects would have earned, and
  the text is the whole of what the agent is told, so it names the route
  rather than the objection: `uv add` for `pip install`, writing the command
  out for `eval`. A refusal is about the route, and the route is not what an
  operation does — which is why it sits outside the effects instead of being
  spelled as one.
- `sandbox` — where an invocation has to run, whatever it earns. The axis
  below.

And the columns that say what a *word* adds or removes, each answering one
question the row alone cannot:

| column | what it states |
|---|---|
| `ask_flags` | the spellings that escalate this row |
| `flag_effects` | what the escalation is *about* — `git reset --hard` discards working-tree content, which the bare verb never did |
| `write_flags` | options whose value is a path this command writes, so the path is resolved and judged by the write row every other spelling reaches |
| `allow_flags`, `read_verbs`, `frozen_flags`, `write_markers`, `bare_reads`, `guarded_keys` | the de-escalations: a pure read-only form, a verb that pins the query action, a flag that pins a dependency restore to what its lockfile already declares (`bun install --frozen-lockfile`, and `uv sync --frozen` or `--locked` by the same judgement), a marker whose absence means it only reads, the argument-less form, a setting that redirects neither execution nor the repository this checkout talks to |
| `setting_flags`, `guarded_settings` | the same absence test about a global that carries a setting — `git -c color.ui=false` turns off colour, `git -c core.pager=x` runs a program and `git -c remote.origin.url=x` aims the next push somewhere else, and only the last two are worth interrupting about |
| `ask_refspecs` | the effects an operand's *grammar* carries, for a push that spells force and delete twice |
| `ask_destinations` | the forms of repository named inline that the first non-flag operand may carry — a URL or a path reaches one the remote table never heard of, where a bare remote name is one somebody approved putting there |

A rule declaring `reviewed` on a write says the route it takes has gates that
read what it wrote. It is declared rather than measured: which gates a
spelling passes through is fixed by the spelling, so it is known where the
rule is written and not at the path. That axis is what keeps the write row's
refusal aimed at *bypassing the content gates* rather than at editing a file.

What the classified verdict then becomes is a second, ordered pass, declared
as an order rather than written as a branch. `policy/kernel/settlement.py`
holds one row per rule, read the way `.gitignore` reads patterns: every row is
offered the running verdict, a row that rewrites hands its result to the next,
and the first row that settles ends the pass. So a statement about precedence
— *a stated reason never leaves a refusal standing*, *a judged deny is not
rescued by a boundary*, *a question nobody can answer is no judgment* — is one
row that says it, and changing the policy is moving, adding, or dropping one.
The rows, in order, each stating its own claim:

