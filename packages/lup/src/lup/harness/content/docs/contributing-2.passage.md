
A `data` commit of generated outputs may go straight to `dev`; code never
does. Session data under `notes/` is gitignored here, so such commits arise
only in a repository that opted into the commit-loop pattern at init.

Two branches: `dev` is the integration branch feature work merges into, and
`main` is stable and receives only reviewed pull requests from `dev`. Never
commit code directly to `dev`.

{{ rebase_skill }} pushes, opens the pull request, and rebuilds history
with `git reset --soft main` and a force-push; re-run it after each round of
review fixes. {{ close_skill }} merges the approved one and cleans up. {{ merge_skill }} guides conflict
resolution — and during a merge the bias is toward inclusion: audit the result
against both parents and confirm every removed function, parameter, or command
was removed deliberately rather than lost to a conflict side.

Generated artifacts are regenerated, never hand-merged. Every file in a
generated tree conflicts on parallel branches because every line is derived,
so `.gitattributes` declares those trees under a driver that keeps one side,
and `lup-devtools git merge-driver` registers that driver in a clone that has
not run `worktree create`. Reconciling such a file hunk by hunk produces an
artifact matching neither tree: take either side, run
`lup-devtools harness generate all`, and let `harness check all` confirm it
settled.

That declaration is a lockout guard as much as a convenience. One file in
those trees is executed rather than read — the compiled hook dispatcher — so
conflict markers in it leave a script that will not parse, and the permission
boundary answers every shell command and every edit by refusing, `git merge
--abort` included. Reaching that state, the refusal says which build product
broke and what rebuilds it, and the rebuild has to be run from outside the
session. The driver is per-clone git config, so it covers a merge performed in
a clone that registered it and nothing else: a merge run on the forge's own
server reads no config and lands the conflict anyway.

## What has to be green

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
uv run lup-devtools dev check              # markers, anti-patterns, boundaries
uv run lup-devtools harness check all      # generated-tree drift
uv run lup-devtools dev rules --check      # the generated rule reference
```

The gate type-checks against the environment `uv` runs it in: the
configuration it hands Pyright names the environment `UV_PROJECT_ENVIRONMENT`
redirects to, resolved against the project the way `uv` resolves it, so a
session keeping its environment elsewhere is not checked against a stale
`.venv` beside it; with the variable unset, the root configuration's `.venv`
stands.

The generated trees include the frontend bundles under `lup.web`'s package
data, built from `packages/lup/web/` by Vite, so the gate needs `bun`. The
workspace's dependencies it restores itself, the way `uv run` syncs the
environment before running: where `packages/lup/web/node_modules` is missing
or older than `bun.lock`, the bundle build and the `bun test` row run
`bun install --frozen-lockfile` first, and `git worktree create` runs it
beside `uv sync` (both skipped by `--no-sync`), so a fresh worktree is ready.
A restore that fails is the row's verdict, carrying bun's own output. The
policy allows that frozen restore, and `uv sync --frozen` and `uv sync
--locked` on the same reasoning — a frozen lockfile pins every package by
integrity hash, which is what `uv run` already fetches unasked — while
`bun install` without the flag, `bun add`, `uv sync` without a freeze flag and
`uv add` ask, since each can rewrite the lockfile. The workspace's own tests
are a third suite beside the two pytest roots, run by `bun test` from the
workspace, so a green gate ran the frontend's tests too. They sit beside
their source as `*.test.ts` and `*.test.tsx`, and carry the `test` role a
file under `tests/` carries — a whole one is written without a question —
because the policy derives that role from the suites the gate declares
rather than from a second table naming the same files.

[quality-pipeline.md](quality-pipeline.md) explains which of the three
automated layers catches what. The short version: `git hooks install`
refuses a commit whose generated artifacts are behind their source and a
push whose branch fails the gate, the per-push CI workflow runs those same
commands and binds whether or not anyone armed the hooks, and the nightly
lane owns everything that needs a real native CLI.

Two conventions catch most first-time review comments:

- **Every function specifies input and output types**, and `Any`,
  `dict[str, Any]`, and `dict[str, object]` are not among them. Use a
  `TypedDict`, a Pydantic model, or `JsonValue`/`JsonObject` from `lup.types`
  for data whose schema lives elsewhere. `# type: ignore` is forbidden; the
  audited `# lup: ignore[rule-id]` escape hatch exists for genuine boundaries.
- **Errors are never silently swallowed.** No `except: pass`, no
  `contextlib.suppress`. Log with `logger.exception()`, handle it, or re-raise.

[rules.md](rules.md) indexes every executable rule with its matching shape and
the module that enforces it. A denial names its rule id, so you rarely need to
read it first.

### The `# lup: ignore` escape hatch

When `Any` or another anti-pattern is genuinely needed — an untyped library
boundary, MCP — an inline ignore requests user approval rather than silencing
the check on its own authority.

Prefer the typed, pyright-style `# lup: ignore[rule-id]`, comma-separating a
list (`# lup: ignore[dict-get, tuple-shape]`), so a site silences exactly the
rule it needs and still trips the others. The bare `# lup: ignore` stays
valid, but the auditor flags it as untyped to nudge migration. The marker sits
on the line that trips the rule, or stands alone directly above it — one
policy for every rule alike, and nowhere else reaches. Inline is the canonical
placement; the line above is where a reason too long for the column budget
goes, since a comment is the one thing the formatter cannot wrap.

A directive naming a rule that nothing it guards trips is refused rather than
approved — it silences nothing, so the approval would buy an exemption the
auditor already calls spurious. The refusal names the rule that does not fire,
and what the line trips instead where it trips something. Rules another
scanner owns are not judged this way: the edit gate carries the anti-pattern
table alone, and a verdict it cannot reach is not one it refuses over. Nor is
the bare form, which names no rule and so silences every rule there is — the
auditor still reports one that guards nothing, so a bare marker the gate
admits can still be a marker `dev check` refuses.

A spurious finding is the one kind with no decision in it, so
`dev check --antipatterns --fix` deletes those directives instead of listing
them, then sweeps again and reports what is left. The reason prose above a
standalone directive goes with it, being a sentence explaining a rule that
does not fire; prose written above *that* is not its reason and stays. The
other two kinds are untouched, because both are asking for a judgement:
"missing" is whether the rule is right or the line is, and "untyped" is a
reason nobody has written yet.

In a file's opening comment block the marker goes file-wide — a standalone
`# lup: ignore` disables anti-pattern checks for the whole file, and
`# lup: ignore[rule-id]` disables only that rule, the way `# pyright: ignore`
works for files.

### A customization marker reads two ways

`# lup: template: <decision>` is the one marker whose meaning depends on which
repository it sits in, and `[tool.lup] template` in `pyproject.toml` says
which. While that flag stands the repository is the scaffold itself and its
customization markers are inventory: `dev check` counts them and says no
more, because a permanent wall of text would sit in front of the notes
somebody is actually owed. `dev init` clears the flag in the same rewrite that
renames the package, and from then on every marker still standing lists in
`dev check` as a decision this domain has not made.

`uv run lup-devtools dev todos` walks them either way — an alias for
`dev comments --kind template` — and initialization goes through them one by
one. Answering one means writing this domain's own code where the scaffold's
example stood, which leaves no original ask for a `solved:` claim to be
checked against, so the marker is deleted rather than converted, exactly as
`ignore` is. Advisory in both readings: a domain that means to leave one
standing writes `# lup: defer:` and says why, which is the sentence it should
have to write rather than a red branch it learns to ignore.

## Tests

One standard decides whether a test earns its place: **would it catch a
realistic regression?** A test that asserts a fixture back at itself, or that
pins language behavior rather than library behavior, is deleted rather than
maintained.

Two lanes. `tests/unit/` is deterministic, runs on every push, and pins
adopter-visible behavior: security decisions, byte determinism, wire formats,
state persistence. `tests/integration/` carries the `integration` marker, is
deselected by default, and runs against real installed native CLIs and Docker
on the nightly lane — that is where anything requiring a live boundary
belongs, and nothing in the unit lane may infer it.

The strongest fixtures in the repository are the shared policy cases in
`test_semantic_policy.py`: every case runs against both the canonical policy
objects and the assembled hermetic runtime under `python3 -I -S`, so the
dependency-free generated kernel cannot drift from the library. When you touch
`lup.policy`, that suite is the one to run first.

Behavior that must not regress silently is pinned rather than described:
`test_harness_compilation.py` holds byte-deterministic regeneration and the
live tree drift-clean, `test_rule_reference.py` fails when
[rules.md](rules.md) goes stale, and `test_capability_matrix_docs.py` does the
same for the capability matrix.

## Reviewing a change

A change to canonical harness source arrives with its regenerated artifacts,
and both halves are reviewed together. What to look for:

- A prompt change should be understandable from its content module alone.
- A policy-data change should trace to the `HookSet` or a canonical rule
  object — and `hooks/runtime/kernel.py` should be byte-identical to the
  canonical kernel, with configuration confined to `policy_data.py`.
- Both native trees change when a portable declaration does; only the owning
  tree changes for an adapter-private renderer change.
- `.lup-ownership.json` is generated proof, not hand-authored metadata.
- A conflict is never resolved by deleting an unknown file. Classify its
  ownership or leave the conflict explicit.
- No credentials, plugin trust, installed cache contents, active sessions, or
  local profile configuration are ever committed.

Unresolved `# lup:` review notes stay visible in a full local `dev check`.
They are feedback to act on, not lint to clear: a note comes out when the code
or structure it points at has actually changed. Resolving one is a rewrite,
not a removal: fix what the note points at — or, for a question, answer it
definitively in code, docs, or a recorded user decision — then restate the
marker as `# lup: solved: <the note's original words>`, text unchanged, so
the claim sits beside what it claims to fix and can be checked against what
was asked. A `solved:` claim is retired only by the verify-solved review
pass, through `dev comments --retire`; the edit gate refuses a hand-deletion
or rewording for everyone, agent and human alike. `defer:` notes park work
at the site until deliberately resumed, and `ignore[<rule-id>]` hatches are
not feedback at all — they come out with the violation they cover. {{ resolve_skill }} runs that pass;
[resolver.md](resolver.md) describes what it does.

## Native evidence and the release gate

Deterministic fixtures run on every change. A scheduled workflow additionally
runs the full integration marker against installed Claude and Codex binaries,
covering the session-id, pager, dynamic-tool-schema, and blocked-edit
boundaries that only a real CLI can prove. `harness doctor` compares installed
versions against the typed evidence ledger; a newer component warns locally
and fails the nightly strict check, while the live job still runs so drift
cannot suppress the evidence needed to review it.

Beyond the ordinary pull-request checks, cutting a release requires two
consecutive scheduled nightly runs in which:

- the credentials-gated native job **completed successfully** — a skipped job
  is not a green run, and a completed failure stays release-blocking;
- the strict evidence job reported no drift between the installed native
  versions and [native-capabilities.md](native-capabilities.md).

Review the probe output together with the evidence ledger rather than updating
the ledger mechanically.
