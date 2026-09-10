"""How to contribute to this repository, whichever component you land in."""

import lup.harness.content.conventions as conventions
import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def document(layout: ApplicationLayout) -> models.PromptDocument:
    """The contribution guide, naming this project's own half by its own name."""
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=rf"""# Contributing

This page is for a contributor arriving cold. It covers getting a working
checkout, deciding where a change belongs, and what has to be green before it
lands. The component guides — [library.md](library.md),
[template.md](template.md), [harness.md](harness.md) — cover *how* to make a
change once you know where it goes.

## Getting set up

```bash
uv sync                                    # both workspace packages
uv run lup-devtools setup                  # interactive: keys, integrations
uv run lup-devtools dev check --changed     # ruff + pyright on what you changed
uv run lup-devtools dev test <paths>       # while iterating: only these files
uv run lup-devtools dev check              # the local pre-flight bar
```

Three commands, because they answer different questions. `dev check` puts both
test suites, pyright and ruff on the machine at once and costs whichever of
them finishes last — a couple of minutes — and it is what has to be green
before a commit. The gate reports what each of its checks cost, so a run that
felt slow can be read rather than guessed at.

The other two are the loop while a change is still moving. `dev check
--changed` runs ruff and pyright over the Python files changed since the
integration branch, in seconds — those are the two checks a scope narrows
*exactly*, because each answers about the files it is handed and Pyright
resolves their imports itself. It runs **no tests**, and says so every time.
`dev test` runs the test files you name, in the suite that installs each.

Which tests reach a change is deliberately left to you. It is a question about
the import graph, and modules reached through `importlib` are invisible to any
static reading of it — so a suite narrowed automatically could report green
while skipping the one test the change breaks. A gate that is trusted and
wrong costs more than one that is slow.

Run one at a time. Two gates at once are slower than the same two in
sequence, because each already spreads itself across every core the machine
has — and a suite reading a repository whose branches another command is
moving fails on that rather than on the code.

`uv` is the package manager: use `uv add <package>`, never edit
`pyproject.toml` by hand. Secrets go in `.env.local`, which is gitignored;
`.env` holds template defaults. `uv run lup-devtools --help` is the full
command tree.

To launch the repository as a native agent plugin:

```bash
uv run lup-devtools harness claude          # generate, then launch
uv run lup-devtools harness codex
```

## Where does my change go?

| If you are changing… | It belongs in | And you should read |
| --- | --- | --- |
| Anything another project built on lup would want | `packages/lup/` | [library.md](library.md) |
| Anything only this application needs | `{layout.directory()}` | [template.md](template.md) |
| A skill, agent, guidance, permission policy, or a page under `docs/` | `packages/lup/src/lup/harness/content/` where the library owns the subject, `{layout.directory("harness", "content")}` where only this application does | [harness.md](harness.md) |
| Repeated shell incantations | a new `lup-devtools` command | [template.md](template.md) |
| A one-off computation | a new `lup-devtools` command | below |

The placement question between the first two rows is the one that matters, and
it has a single test: *would another project built on lup want this?* If yes,
it goes in the library even if only this application uses it today. The
library never imports the application, so a utility placed wrongly in
`{layout.directory()}` is unreachable from the library and will have to move
later.

`tmp/` is scratch: gitignored, so nothing written there reaches a diff, a
reviewer, or a human — which is why it does not execute. One-off work takes
the first of these that fits:

1. To read code rather than run it: `py info`, `py source`, `py search`, `py text`,
   `py imports`, and the codeintel tools. Resolve names with `py search` or
   codeintel; find literal text in explicitly scoped Python paths with `py text`.
2. To compute something once: a script under `tmp/`, run directly. It imports
   this checkout the way any other module does, and the session it runs in is
   itself contained, so what used to be the objection — an unreviewable thing
   executing outside any boundary — is now only the first half. A one-off
   nobody will read again costs a reviewer nothing.
3. For anything you will want twice: a new `lup-devtools` command, which
   lands in the diff and can be run again by name rather than rewritten. The
   policy counts how often each script runs and says so when one has passed
   what a one-off is for — advice riding along with a verdict that already
   allowed the command, not a gate. It arrives at the fifth run and then
   every tenth, because a session that was mid-thought at the first one has
   to hear it again, and one that hears it every run stops reading it.
4. As a last resort, an inline heredoc behind an escalation marker
   ([permissions.md](permissions.md)).

A rung that evaluated an expression inside its own container used to sit
between the first two, and was removed with that container. The agent session
is contained now, so a second boundary within it bought no isolation — and the
one it had actively got in the way, since the tool could not import the very
checkout it was asked about.

The argument is reviewability, not power: an agent may already edit
`devtools/` and run it.

A result too large to return does not come back at all: the runtime persists
it to a file and returns a short preview naming that file. Hand the file to a
reader that takes a file whole. `cat`-ing it is another result too large to
return, persisted to another file, and `cat`-ing that one repeats it — a
regress whose every step looks like the command having worked.

Never create a tracking file. A `TODO.md`, backlog, or roadmap parks a
decision where no workflow surfaces it again. Deferred work lives as a
`# lup: defer: <text>` note at the site it concerns — where `dev comments`
lists it in its own parked section and `dev check` keeps it visible until
somebody wakes it. That bare spelling is the
default, and a bracketed `defer[<gate>]: <text>` states a real,
externally-checkable gate — never a restatement that this code might change
again.

Some gates this checkout can resolve, and those it does. `dev check` asks them
every run, reports them among the other deferrals while the answer is no, and
fails the run the answer turns yes. `defer[gone:<path>]` wakes once that path
stops existing.

`defer[branch:<name>]` wakes for whoever is standing on that branch, and again
if the branch lands with nobody having acted. The first is the point. A note
about a branch is written by somebody standing somewhere else, and the person
it concerns is on the branch it names, in a checkout that carries no copy of
it — so the check reads the integration branch as well as the working tree,
for the notes naming the branch in hand. Write one where you are, aimed at the
branch that has to act, and it reaches them without waiting for a merge.

Landing wakes it even where the branch was deleted in the same sweep, because
`git delete` judges containment off the ref it is about to remove and records
that verdict beside the branch. A checkout that never deleted it holds no such
record and stays quiet — which is what keeps a clone that merely never fetched
the branch, every CI job among them, from waking every gate in the repository.

A gate the checkout cannot see — "until the v2 API ships" — stays prose and
stays advisory, which is the whole of what a stated gate ever did before.
Prefer a resolvable spelling where one fits, because a deferral is dormant
exactly as long as nobody has reason to read it, and the moment it stops being
dormant is the moment nothing else announces.

A note is right when the subject is the code: a bug worth remarking on, an
idea for a feature, anything the site it concerns can hold. Work whose
subject is the tooling misbehaving — friction, a command that half-completes,
a classifier reporting a failed probe as fact — has no site to sit at, and
becomes a GitHub issue instead. When whether to defer at all is the open
question, it becomes a question to the user rather than any note.

## Git workflow

Development happens in **worktrees**, not branches switched in place, so
several changes can be in flight at once:

```bash
uv run lup-devtools git worktree create feat-name
```

The worktree is created as a sibling under `tree/`. Never nest one inside
another checkout. `git checkout -b` would make a branch and switch the
current directory in place; `git worktree add` gives the branch a directory
of its own, which is what keeps several live at once. `worktrees/` and
`refs/` are gitignored, the latter holding symlinks to the projects this
repository tracks.

Those symlinks resolve inside a contained session only for a project whose
registration in `sync.json.local` carries a `"mount"` of `"rw"` or `"ro"` —
`dev sync setup <name> <path> --mount rw` writes one, and `dev sync status`
shows which projects have it. A mounted project is leased whole: its
checkout at that mode, its shared git directory with it, and its own sibling
worktrees read-only, which is what lets a session commit in it. Without the
key the project is tracked for review and nothing more, and the symlink
dangles inside the container the way an unmounted path does. The key is why
`sync.json.local` is a protected edit root: writing one widens the boundary.
For a folder one session needs without a standing registration, the launchers
take `--mount <dir>` and `--mount-ro <dir>` (repeatable): the same lease, the
same widening in every posture, lasting exactly one launch.

A registration naming only a URL is mounted on the same terms, because it is
materialized into the same shape: a full bare clone under
`~/.cache/lup/sync/<name>.git` with a worktree attached at `tree/<branch>`,
and the worktree is what the lease binds. Commit in it, cut branches in it,
push from it — the remotes of every mounted checkout are rewritten onto the
transport this session can reach, not just the one it was launched from. A
review never moves a branch there: `sync` reads the upstream's commits from
its remote-tracking ref, so refreshing is a fetch and nothing in the clone is
reset over.

The base the branch is cut from is recorded against it, because topology
cannot recover a creation point once the parent has merged on. It is read
from the checkout you run in, so a detached HEAD has nothing to read: rather
than record nothing and let a later reader guess, creation refuses and asks
for `--base <branch>`, or `--no-record` to say deliberately that this branch
has no base worth keeping.

The command prints the path and does not move whoever ran it. **Launch a
session rooted at that path**; do not relocate a running one. The difference
is not style. A runtime that can move a running session arms its own
worktree isolation when it does — a check on command *shape*, separate from
this project's policy and owned by nobody here, which refuses a command
carrying any of fifteen shell words as an argv element in any position:

    eval  source  .  fc  coproc  trap  enable  mapfile  readarray
    hash  bind  complete  compgen  alias  let

Only `.` is gated to first position; the other fourteen match anywhere, and
none of them is gated on the command being a git command. So an isolated
session loses `grep -c hash` and `rg complete src/` — read-only commands with
no git in them — for as long as it lasts, and no approval marker reaches the
refusal.
Relocation is bounded as well as expensive: `git worktree create` cuts under
a sibling `tree/`, outside the `.claude/worktrees/` a relocating tool
switches within, so such a path is taken only as a session's first entry from
the directory it launched in. A session already sitting in one worktree is
refused a second switch by the tool itself, whatever this project decides, so
stacking a branch means a launch or absolute paths either way.
A session launched already rooted in the worktree is never isolated and
keeps all of them, which is why the workflow asks for a launch. Staying put
and editing through absolute paths works too, but only into a worktree that
is writable: a contained session mounts every sibling that already existed
when it started read-only, so that route reaches a filesystem refusing every
write, while one cut afterwards is outside the lease and takes edits
normally. Measured against Claude Code
2.1.237; `docs/native-capabilities.md` carries the evidence.

Commit early, commit often, and keep commits atomic — if the message needs an
"and", it is two commits. The format is `type(scope): description`:

"""
            ),
            *conventions.COMMIT_TYPES.parts,
            models.TextPart(
                text=r"""
A `data` commit of generated outputs may go straight to `dev`; code never
does. Session data under `notes/` is gitignored here, so such commits arise
only in a repository that opted into the commit-loop pattern at init.

Two branches: `dev` is the integration branch feature work merges into, and
`main` is stable and receives only reviewed pull requests from `dev`. Never
commit code directly to `dev`.

"""
            ),
            models.SkillInvocation(plugin="lup", skill="rebase"),
            models.TextPart(
                text=r""" pushes, opens the pull request, and rebuilds history
with `git reset --soft main` and a force-push; re-run it after each round of
review fixes. """
            ),
            models.SkillInvocation(plugin="lup", skill="close"),
            models.TextPart(text=r""" merges the approved one and cleans up. """),
            models.SkillInvocation(plugin="lup", skill="merge"),
            models.TextPart(
                text=r""" guides conflict
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
workspace, so a green gate ran the frontend's tests too.

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
not feedback at all — they come out with the violation they cover. """
            ),
            models.SkillInvocation(plugin="lup", skill="resolve"),
            models.TextPart(
                text=r""" runs that pass;
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
"""
            ),
        ],
    )
