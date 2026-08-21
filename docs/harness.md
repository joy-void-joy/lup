<!-- Generated from lup.devtools.harness.content.docs.harness by `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/harness.md. -->

# The harness

The committed `.claude/`, `.codex/`, `.agents/`, and root `AGENTS.md` trees are
build products. Skills, agents, guidance, permission policy, and this
documentation are authored as typed Python; one command renders every native
tree deterministically; the source and generated diffs are reviewed together.

They are committed rather than built on demand so that a checkout is directly
launchable as a native plugin with no build step, and so generated output is
reviewed like any other change. Hook execution in particular must not depend on
this checkout or its virtual environment — a generated plugin carries its own
policy runtime.

## The one loop

```bash
uv run lup-devtools harness generate all   # render both trees from source
uv run lup-devtools harness check all      # read-only drift check; what CI runs
```

`harness claude` and `harness codex` regenerate one target and launch it;
`--generate-only` stops before launching. `dev git-hooks install` installs
the drift check as a git pre-commit hook, so omitted generated output is
refused before the commit exists rather than minutes later in CI.
[quality-pipeline.md](quality-pipeline.md) maps all three layers.

## Generated output is never hand-edited

This is the rule the whole design rests on, and it has one reason: Lup cannot
safely infer an arbitrary Python source change from rendered Markdown, TOML,
JSON, or shell. So a native artifact edit is not imported and not overwritten
— it is **preserved and reported as a conflict**.

Every generated artifact whose format allows a comment opens with a banner
naming its canonical source and the command that regenerates it. The banner
text comes from one parameterized helper in
`packages/lup/src/lup/harness/generation.py`, so its wording and placement
cannot drift between artifact families. Two families cannot carry one, and this
section is their provenance record instead:

- **JSON artifacts** — manifests, hooks, settings, evidence — have no comment
  syntax.
- **Skill, command, and agent Markdown** is verbatim model-facing prompt text
  after its frontmatter; a banner would be injected into every prompt.

### Ownership manifests

`.claude/.lup-ownership.json` and `.codex/.lup-ownership.json` are the
generator's proof of what it owns, written by
`packages/lup/src/lup/harness/ownership.py` after every successful generation.
Each records the generator version, a digest of the canonical declarations,
and — per generated file — its path, sha256, semantic id, and executable bit.

Reconciliation (`packages/lup/src/lup/harness/reconciliation.py`) compares
current bytes against those digests to classify every managed path. Files that
still match may be replaced or deleted by regeneration. Hand-edited generated
files are preserved as backpropagation candidates. Local files the generator
never wrote — including sensitive ones like `.claude/settings.local.json` and
`.codex/config.local.toml` — are never touched.

The manifests are committed because a fresh clone and CI need the recorded
digests: without them the drift check cannot run and the generator cannot
prove which bytes it owns, so it would refuse to replace anything.

### Every generated path and its source

Canonical sources live in `packages/lup/src/lup/devtools/harness/content/`
(the declarations lup ships), `src/lup_template/devtools/harness/content/`
(the ones only this repository has), `src/lup_template/devtools/harness/catalog.py`
(plugin, hook, and resolver composition), and `packages/lup/src/lup/`
(adapter renderers and the policy bundle). Below, `content/` names whichever
of the two halves owns the declaration's subject.

| Generated path | Canonical source |
| --- | --- |
| `.claude/CLAUDE.md`, `AGENTS.md` | `content/guidance.py` |
| `.claude/plugins/lup/TEMPLATE_CLAUDE.md` | `content/template_claude.py` |
| `.codex/plugins/lup/TEMPLATE_AGENTS.md` | `content/template_codex.py` |
| `.claude/settings.json` | `content/settings.py` |
| `.claude/plugins/lup/scripts/file_suggest.sh` | `content/assets/file_suggest.sh` (verbatim copy) |
| `docs/*.md` | `content/docs/catalog.py` and the modules it lists |
| `docs/rules.md` | `lup.codescan.registry`, via `uv run lup-devtools dev rules` |
| `.claude/plugins/lup/commands/<skill>.md`, `.codex/plugins/lup/skills/<skill>/SKILL.md` | `content/skills/<skill>.py` |
| `.claude/plugins/lup/agents/<agent>.md`, `.codex/agents/<agent>.toml` | `content/agents/<agent>.py` |
| `.claude/plugins/lup/.claude-plugin/plugin.json`, `.claude/plugins/.claude-plugin/marketplace.json` | `catalog.py` via `lup.adapters.claude.harness` |
| `.codex/plugins/lup/.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | `catalog.py` via `lup.adapters.codex.harness` |
| `.claude/plugins/lup/hooks/`, `.codex/plugins/lup/hooks/` (`hooks.json`, `scripts/policy.py`, `runtime/policy_data.py`, `runtime/evidence.json`) | `catalog.py` `HookSet` (with `lup.policy.shell_rules` and `lup.codescan.antipatterns`) via the adapter hook renderers and `lup.policy.bundle` |
| `.claude/plugins/lup/hooks/runtime/kernel.py`, `.codex/plugins/lup/hooks/runtime/kernel.py` | verbatim copy of `packages/lup/src/lup/policy/kernel.py`, kept byte-identical so it can be diffed against the canonical module |
| `.codex/config.toml` | `lup.adapters.codex.harness` |
| `.claude/.lup-ownership.json`, `.codex/.lup-ownership.json` | written by `lup.harness.ownership` from the generation result |

`.claude/CLAUDE.md` and root `AGENTS.md` are the *same* document rendered
twice, because each runtime reads guidance from its own location. The
redundancy is deliberate; edit `content/guidance.py` and regenerate rather
than patching either copy. `docs/` is rendered once, by the Claude recipe,
because these pages are repository documentation at a neutral location rather
than anything either runtime reads from its own tree.

## The pipeline

`lup-devtools harness generate|check|claude|codex` walks one path from typed
Python to a launched native plugin.

1. **Typed declarations** — `devtools/harness/content/` holds the skill,
   agent, guidance, pattern, template, and documentation declarations;
   `devtools/harness/catalog.py` composes them with the application-owned
   `HookSet` into one canonical `lup.harness.models.Harness`. Prompt prose is
   stored as ordered typed parts, never as a native string.
2. **Renderers** — `lup.adapters.claude.harness` and
   `lup.adapters.codex.harness` implement the `ArtifactRenderer` seams from
   `lup.harness.contracts`; the compilation roots in `lup.adapters.harness`
   compose them into a complete `ArtifactTree`. A `SkillInvocationRenderer`
   owns the entire native invocation spelling; shared code never rewrites one
   prefix into another.
3. **Validation** — `lup.harness.validation` checks the whole rendered tree
   (path uniqueness, ordering, identifiers, normalized text) and generation
   refuses to continue on any issue.
4. **Reconciliation** — `lup.harness.ownership` records what the generator
   owns; `lup.harness.reconciliation` classifies the current tree under that
   proof and proposes writes, proven deletions, and explicit conflicts. Local
   edits worth carrying back to canonical source are persisted as reviewable
   patches by `lup.harness.proposals`, never applied.
5. **Materialization** — `lup.harness.materialization` re-verifies every
   preimage and applies a conflict-free proposal atomically, then saves the
   manifest. Stale proposals are rejected.
6. **Launch** — `lup.adapters.*.harness_runtime` probes native CLI
   capabilities, and `lup.harness.process` launches the native CLI with the
   non-interactive defaults from `lup.harness.environment`.

Generation orchestration takes a frozen `GenerationRecipe` holding the desired
tree, current-tree reader, ownership location, and target requirements. Only
the CLI composition root maps a user-facing target name to a concrete recipe:
adding a third target supplies another recipe rather than a branch in
reconciliation or materialization.

Each harness module owns one concern. Everything but the declaration root
lives in `packages/lup/src/lup/devtools/harness/`; `catalog.py` is this
repository's, because its whole job is to be this project's own harness:

- `app.py` — Typer wiring only; every command body lives elsewhere
- `catalog.py` — declaration-graph root assembling `content/` into a `Harness`
- `content/` — the declaration leaves (skills, agents, documents, assets)
- `composition.py` — builders wiring concrete adapter capabilities, and the
  target roster a CLI selector names
- `generate.py` — recipes, drift inspection, and atomic materialization
- `drift.py` — console drift reporting for `generate` and `check`
- `reconcile.py` — drift classification and the source-patch flow
- `doctor.py` — runtime evidence against the `evidence.py` ledger
- `resolve.py` — persisted-resolver glue: broker, snapshots, factories
- `launch.py` — the shared preflight a launcher opens a session past
  (generation, runtime probes, base freshness) and the native launchers

## What the plugin ships

Both rosters are rendered from the typed declarations: the ones about agent
work in `packages/lup/src/lup/devtools/harness/content/catalog.py`, the ones
about being a template in
`src/lup_template/devtools/harness/content/catalog.py`, which composes both
into what the plugin ships. Change the catalog that owns the subject, then
regenerate.

**Skills:**

- /lup:add-command — Create a new slash command in the lup plugin
- /lup:brainstorm — Pre-init design exploration — brainstorm architecture, MCP tools, and agent design
- /lup:bump — Review changes since last bump and bump agent version
- /lup:close — Check PR review status, merge if approved, and clean up branches
- /lup:commit — Review all diffs and create atomic commits
- /lup:create-investigator — Create a new diagnostic/investigator command (like /debug)
- /lup:debug — Trace an error through logs to find root cause
- /lup:fb-analyze — Aggregate tool health, capability gaps, and reasoning patterns across sessions
- /lup:fb-implement — Implement prioritized changes from feedback loop analysis
- /lup:fb-investigate — Deep trace reading and error classification for selected sessions
- /lup:fb-reflect — Meta and meta-meta reflection on the feedback loop process itself
- /lup:fb-status — Feedback loop entry point — status, targets, and previous session context
- /lup:feedback-loop — Full feedback loop — orchestrates status, investigation, analysis, reflection, and implementation
- /lup:hooks — Inspect and modify the canonical semantic permission policy
- /lup:implementer — Implement one resolver concern inside its leased worktree
- /lup:import — Import a specific pattern from a tracked downstream repo
- /lup:init — Initialize the self-improvement loop for a specific domain
- /lup:install — Install lup plugin and scaffolding into a target repo
- /lup:land — Land every branch that has not reached the integration branch, and clear the ones that have
- /lup:merge — Merge a branch or resolve existing merge conflicts
- /lup:meta — Review and modify the generated harness trees, brainstorm improvements interactively
- /lup:modify-command — Modify an existing slash command based on a description or delta
- /lup:principle — Propagate a general principle across the entire repo
- /lup:rebase — Clean up commit history on the feature branch and open/update a PR
- /lup:refactor — Rewrite a file or folder from scratch while respecting coding conventions
- /lup:refactor-tools — Audit SDK agent tools and subagents — find gaps, overlaps, and refactoring opportunities
- /lup:report — Write the report of everything left to implement, rewritten whole under tmp/, after a long session or after implementing a plan
- /lup:resolve — Resolve inline feedback through isolated work
- /lup:resolve-reviewer — Review one resolver concern against its acceptance criteria
- /lup:review — Review a session trace for workflow quality, tool usage, and improvement opportunities
- /lup:update — Review upstream template commits and apply improvements
- /lup:verify-solved — Check every claimed-resolved note and stale open issue against what it actually asked

**Agents:**

- `implementer` — Implement production changes against established acceptance tests
- `trace-explorer` — Investigate trace evidence without changing production files
- `version-explorer` — Inventory version-impact evidence across the repository
- `version-reviewer` — Independently review a proposed version change

## Authoring

### Add a skill

Create one module beneath `content/skills/` — the library's half when the
skill automates work inside a project, this repository's when its subject is
standing one up. The declaration is ordinary typed Python and the prompt
stays readable prose:

```python
"""The project-triage skill."""

from lup.harness.models import Argument, ArgumentsRef, PromptDocument, Skill, TextPart

SKILL = Skill(
    id="skill.triage",
    name="triage",
    description="Classify one reported problem and identify the next investigation",
    arguments=[
        Argument(
            name="report",
            description="Problem report or error text to classify",
            required=True,
        )
    ],
    prompt=PromptDocument(
        parts=[
            TextPart(
                text="""Read the report, inspect the relevant boundary, and return the
most likely failure class with one concrete next check.

Report:
"""
            ),
            ArgumentsRef(),
        ]
    ),
)
```

Import it explicitly in `harness/content/catalog.py` and append it to
`SKILLS`. Explicit imports make a misspelled or missing module a type-checking
error; there is no dynamic registry and no barrel file.

Then run the authoring loop:

```bash
uv run lup-devtools harness generate all
uv run lup-devtools harness check all
uv run ruff check packages/lup/src/lup src/lup_template
uv run pyright
uv run pytest tests/unit/test_harness_compilation.py -q
```

A declaration must not branch on a provider name. Argument declarations and
`ArgumentsRef` must occur together — model validation rejects either alone.
Use semantic prompt parts such as `ArgumentsRef` or `SkillInvocation` and let
each renderer choose its spelling;
[platform-differentiation.md](platform-differentiation.md) records what prose
may and may not name.

### Add a document

Documentation is generated the same way. Add a module under `content/docs/`
in the half whose subject it is, list it in that half's
`content/docs/catalog.py`, and regenerate. The banner is applied from the
roster, so a document module holds prose only. The index builds its rows from
the documents both halves declare, so a page appears there by being declared
— and a page it lists that stops being published fails generation rather than
leaving a link that resolves to nothing.

### Change the fetch allowlist

The application-owned `HookSet` is constructed by `portable_harness()` in
`src/lup_template/devtools/harness/catalog.py`. Add the narrowest origin and
path prefix that supports the workflow:

```python
allowed_fetch=[
    HookUrlScope.model_validate(
        {
            "origin": "https://docs.example.com",
            "path_prefix": "/agent-api/",
        }
    ),
]
```

Origins normalize into scheme, host, port, and path-prefix rows. Put an
explicit exclusion in `denied_fetch` when a permitted host has a sensitive
subtree; deny rows win over allow rows. Never add provider-specific fetch
logic to the kernel or a generated dispatcher.

Regenerate and run the policy fixtures:

```bash
uv run lup-devtools harness generate all
uv run pytest tests/unit/test_semantic_policy.py -q
uv run lup-devtools harness check all
```

Inspect `hooks/runtime/policy_data.py` in both generated trees. The rows should
change while `hooks/runtime/kernel.py` stays identical: configuration is
generated data, policy control flow is one copied module.

### Change the shell classification

The shell auto-allow vocabulary is data too. The baseline lives in
`lup.policy.vocabulary` (`default_vocabulary()`) as a readable table: a read-only
command allows unless a listed `ask_flags` writer flag appears, and a
subcommand command allows only the subcommands and operations it lists. To
teach the fleet a downstream toolchain, append rules through the `HookSet` in
`catalog.py` — never edit the kernel:

```python
shell_rules=[
    ShellCommandRule(name="cargo", default_effect="ask", subcommands=[
        ShellSubcommandRule(name="check", effect="allow"),
        ShellSubcommandRule(name="build", effect="allow"),
        ShellSubcommandRule(name="test", effect="allow"),
    ]),
]
```

The extension is concatenated onto the baseline and erased into the same
`SHELL_RULES` rows the kernel interprets. A universal command every repository
should trust belongs in a `lup.policy.vocabulary` group instead. Regenerate and run the
policy fixtures exactly as above. Destructive forms stay `ask`: guard a writer
flag with `ask_flags`, or a destructive sub-operation with an `ask`
`ShellOperationRule`, rather than widening a `default_effect`.

Both axes cascade, so each subcommand above says `effect="allow"` rather than
leaving it out — omitting a field means "inherit from the level above", never
"allow". The same cascade is what lets `sandbox="outside"` be declared once on
a command and reach every verb beneath it. Run
`uv run lup-devtools dev vocabulary --provenance` to see which level supplied
each half of every rule, and `dev vocabulary --json --output <path>` before and
after a reshaping to confirm no verdict moved that you did not move.

## Resolving a conflict

`harness reconcile` compares the current files, the desired render, and the
ownership manifest. It mutates nothing. A conflict means one of these:

| Category | Meaning | Action |
|---|---|---|
| `backpropagation_candidate` | A previously generated file differs from its owned digest. | Reproduce the intended change in the typed content or policy source, then regenerate. |
| `unknown_conflict` | Lup has no ownership proof for the existing bytes. | Decide whether the file belongs in typed generation or should stay local-only. |
| `local_only` | The recipe deliberately leaves the path to the user. | Keep it outside generation. |
| `sensitive_local_only` | The path may hold credentials or trust state. | Never import or commit it through the harness. |

The ordinary path is short:

```bash
uv run lup-devtools harness reconcile all
# edit the corresponding module under harness/content/ or harness/catalog.py
uv run lup-devtools harness generate all
uv run lup-devtools harness check all
```

Do not resolve a conflict by deleting an unknown file. Classify its ownership,
or leave the conflict explicit.

### Applying a source-patch proposal

A source-aware tool may produce a Git-format patch against canonical Python
without applying it. Keep the source tree at the patch's preimage, then persist
the proposal:

```bash
uv run lup-devtools harness propose-reconciliation tmp/source.patch
```

The command prints a proposal id and writes immutable `source.patch` and
`metadata.json` under `.lup/reconcile/<id>/`. Review both files and the named
preimages, then apply only the reviewed proposal:

```bash
uv run lup-devtools harness apply-reconciliation <proposal-id>
```

Apply verifies the patch digest, proposal identity, and current preimage digest
before showing the patch and asking for confirmation. It then runs
`git apply --check`, applies the canonical-source patch, regenerates both
targets, and removes the consumed proposal. A changed preimage, malformed
path, digest mismatch, or non-applying patch stops before any mutation.

This is a patch transport, not a native-body importer. A rendered artifact is
never parsed heuristically back into Python.

## Launch and trust

Generated plugins carry their own policy runtime and dispatcher; hook execution
imports neither `lup-devtools`, this checkout, nor its virtual environment.
Both decoders convert native tool payloads into the same semantic
edit/shell/fetch/search vocabulary, shared policy evaluates it, and each
adapter renders the decision back — Codex `ask` being a documented fail-closed
exit-code-2 approximation.

Codex packages install through the native plugin CLI only when the separately
installed cache digest is absent or stale; the source plugin is never mistaken
for the cache. Personal trust state, credentials, active run state, and cache
contents are never generated and never committed. Review hook trust with the
native hooks surface after generation.

### Opening a session the anti-pattern gate leaves alone

`--ignore-antipatterns`, on both launchers, for the sessions where the rules
are not the point: exploring, spiking, or working over code these conventions
were never written for.

It reaches the gate rather than the command line, which is the only thing that
would make it work. The anti-pattern table is projected into each plugin's
hermetic edit policy at generation time, and `ready_to_open` regenerates before
it opens — so the flag compiles the tree the session actually runs against.
What it sets is `RuleSelection` with every id retired, spelled as the ids
rather than as a flag meaning "all of them", because the selection is
subtractive and a rule added later should be one the selection has visibly not
answered for.

Three things it deliberately does not do, each announced at launch because each
bites later and none announces itself:

- **The sweep does not follow.** `dev check --antipatterns` reads the
  repository's own declaration, so a session that edited freely under the flag
  will fail it. That is the point rather than an oversight: a transient switch
  must not quietly become the repository's answer.
- **The committed tree is rewritten.** Regenerate before committing, or the
  commit carries a plugin nothing declares.
- **It is not how a project drops the rules.** `dev seams --retire-all` is,
  because that writes the decision where a review sees it and `--keep` takes it
  back.

### Where a session runs, and the flag that takes it back to the host

Both launchers open the session **inside the container the project declares**,
and `--unsandboxed` opens it on the host instead. The image is built from
`Harness.image` on first use and mounted rather than copied into, so a `uv add`
costs a sync and not a rebuild.

What the container is for is the size of the policy above it. A semantic policy
with no boundary beneath it is the only thing standing, so it has to guess at
every rail and refuse whatever it cannot classify; with a real one beneath it,
work nobody judged is carried by the boundary instead. That is not a separate
feature — it is the same `confined` fact the settlement order already turned
on, finally set by something other than the native sandbox.

A container changes three facts and not one, which is worth stating because
conflating them is how a boundary stops being one:

- The session is sandboxed, so the boundary is real.
- Nothing is escapable. There is no channel to put one call outside a
  container, so a call declared `outside` is **trapped** rather than placed —
  refused with the reason that says so, instead of failing later on whatever it
  writes first with the boundary misreported as a bug in the code.
- An exclusion opens no hole. `excluded_commands` excuses a command from the
  *native* sandbox; the container never agreed to leave anything alone.

A judged deny is still an answer. Containment reaches work nobody classified,
never a rule somebody wrote, so the reviewability refusals hold inside.

Two things it deliberately does not do:

- **It does not fall back.** A launch that asked to be contained and could not
  be is a refusal naming what to install, because a boundary that quietly is
  not there is the one failure the boundary exists to prevent.
- **It does not decide the identity itself.** How a container is told to run as
  the invoking user differs by engine and is fatal when guessed: `--userns=keep-id`
  is podman's word for "do not remap", and Docker refuses it outright. The
  engine answers for its own spelling, and which engine is present is read from
  what the client *reports* rather than from its filename — the `podman-docker`
  package installs a `docker` that is really podman.

Codex takes the same treatment through the same assembly, with one word
differing: which environment variable points a CLI at its configuration home is
that runtime's own, and it arrives from the login declaration rather than being
spelled at the container — Codex reads `CODEX_HOME` where Claude reads
`CLAUDE_CONFIG_DIR`.

### Reopening a session, and why a launcher owns it

Both launchers reopen an earlier session, from one declaration and in each
runtime's own words:

| request | flag | Claude | Codex |
|---|---|---|---|
| the most recent session here | `--continue` / `-c` | `--continue` | `resume --last` |
| choose from a picker | `--resume` | `--resume` | `resume` |
| one session by id | `--session <id>` | `--resume <id>` | `resume <id>` |

The shapes are genuinely different rather than differently named — a
subcommand has to lead the argument vector where a flag does not — which is
why `Resumption` carries the request and each adapter's function carries the
words. Naming two at once is refused rather than ranked, before anything is
generated.

This exists for more than convenience. The policy a session enforces is
compiled into the plugin tree its runtime loads **at startup**, so widening
that policy takes effect only in a new process. Without reopening, the price
of every widening is the conversation that established what it was for — which
is what pushes an agent toward a per-call escape that helps once and
evaporates. With it the durable path is also the cheap one:

1. The agent proposes the declaration edit. The policy source is a protected
   path, so the edit surfaces as an approval with the diff in it.
2. Approve it — what is approved is the rule, not one command.
3. `harness generate all`, or just relaunch: `ready_to_open` regenerates on
   the way in.
4. `harness claude --continue` / `harness codex --continue`. The reopened
   session is already running against the tree the approval produced.

### Where a profile comes from

A profile names one account and the configuration home it runs under, and which
origin holds them is the project's to choose. A project that keeps accounts of
its own keeps one directory per name — `.lup/profiles/<name>/`, with each
runtime's home in the subdirectory that runtime's login names (`claude-config/`
for Claude Code, `codex-home/` for Codex) — so a name resolves inside the
checkout
rather than against anything under the operator's home, and `.lup` already being
ignored is what keeps a login out of a commit. A project that keeps none falls
back to the personal registry at `~/.lup/profiles.json`, whose names are
registered by hand and each carry wherever its home already lives.

`harness profile` and `setup profile` curate whichever origin the project
supplied — `list`, `add`, `use`, `remove` — and `harness claude --profile`
selects one for a single launch. Naming none selects the active profile; naming
none with none active leaves whatever home the surrounding environment already
selected, so a session launched from inside another stays on the account it was
started under. A name no origin answers to is refused with the roster that would
have answered, at the launcher as well as at the command tree.

A directory profile's home is derived from its name, so `add --config-dir`
pointing elsewhere is refused, and `remove` says to remove the directory rather
than forgetting it: the directory is the profile and it holds the login. To
point one at a home that already exists, symlink that subdirectory at it.

### Workspace trust, and the profile it is recorded against

Claude Code keeps workspace trust in its user-level configuration document,
and offers nowhere else to put it — so an untrusted workspace is not a
project-level fact a repository can declare for itself. An untrusted one does
not fail: the session drops every `permissions.allow` entry
`.claude/settings.json` declares, warns into its own stderr, and runs on under
a permission posture the repository never declared.

A headless run cannot accept a dialog, so it establishes trust itself. Each
workspace's sessions are pointed at a private configuration home derived under
the selected profile, and trust is recorded there — never in the operator's own
document — for the repository the run was invoked against and the checkouts the
run made of it, and nothing else a session happens to open in. Pointing a run at
a repository is the act of trust; a workspace outside that stops the run rather
than degrading it.

`CLAUDE_CONFIG_DIR` selects which profile all of this reads and writes. Where it
is set, the document is `.config.json` inside the named directory; where it is
unset, the document is `~/.claude.json` beside the home rather than in it, and
the derived homes still land under `~/.claude`. Both spellings matter for an
interactive fix: accepting a trust dialog in a shell that does not export the
same variable writes to a different profile and appears to do nothing.

Commit generated artifacts together with the catalog changes that produced
them. [contributing.md](contributing.md) covers what review looks for.
