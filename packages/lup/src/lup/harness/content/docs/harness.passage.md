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

`harness claude` and `harness codex` regenerate the declared targets, check the host, settle the
base, and launch the selected runtime; each wait is named as it starts, so a long silence is a
stopped launch rather than a slow one. `--generate-only` stops before launching. `git hooks install` installs
the drift check as a git pre-commit hook, so omitted generated output is
refused before the commit exists rather than minutes later in CI.
[quality-pipeline.md](quality-pipeline.md) maps all three layers.

## Startup checks and container images

Both launchers build a container image when no image matches the rendered
Dockerfile. They reuse a matching image. Package declarations feed that
Dockerfile, so changing the declared packages triggers a build on the next
launch. Building an image installs packages inside it, not on the host.
`uv run lup-devtools harness image` prints the Dockerfile; it does not build it.

Requirements declare where they are needed:

| Location | Checked where |
| --- | --- |
| `host` | On the machine running the launcher |
| `image` | Inside the session container |
| `both` | In both environments |
| `session` | Inside the container for a normal launch; on the host with `--sandbox inner` or `--sandbox none` |

The allowed shell commands are a `session` requirement. Missing `tree` or
`yq` on the host does not warn during a container launch when the image
provides them. The container is checked after its image is built or reused.
If a command is missing there, check that the image's declared packages
actually provide it; repeating an unchanged build is not a general repair.

Run `uv run lup-devtools harness requirements` to check host dependencies,
including tools for sessions running on the host. Add `--inside` to check
the container, or `--inside --launch-only` to run just its startup checks.
Full container checks include a test model turn.

A host device — a GPU — is never in the manifest, because a manifest is
committed and which GPU a machine holds is that machine's fact. `sync grant
<name>` records it in the machine's `sync.json.local`, and the host checks
build one requirement per grant they find there: a throwaway container
started with the device, at setup rather than every launch since it costs a
container start. A launch reads the host's CDI registry itself and withholds,
with one line, any grant no spec there names.
[contributing.md](contributing.md) carries how a device is granted.

The target selector also chooses its login layout and configuration home:
`claude` honors `CLAUDE_CONFIG_DIR`, falling back to the personal `.claude`
directory; `codex` honors `CODEX_HOME`, falling back to the launcher's worktree
home. `all` checks each with its own selection. These checks use existing
configuration; they do not install plugins or perform an interactive login.

Reports name the environment and show the failed operation, its impact and
the next step separately. A check that could not run reports an unknown
result. A missing command can produce misleading shell results: exit code
127 takes the fallback in `command || fallback`, just like other failures.

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

[generated-paths.md](generated-paths.md) is that map, one row per artifact,
walked from the trees the recipes compile. It was a table here and a table
here drifts one way only: an artifact added to a recipe stayed invisible until
somebody remembered this page, so the rows that went missing were always the
newest — and a map with a family missing reads exactly like a complete one.
Each row is now the artifact's own attribution, the same one its banner prints
for a reader who opens the file, so nothing there can name a source the
artifact does not.

Canonical sources live in `lup.harness.content`
(the declarations lup ships), {{ harness_content_directory }}
(the ones only this repository has), {{ harness_catalog_py }}
(plugin, hook, and resolver composition), and the `lup` package itself
(adapter renderers and the policy bundle).

Three things that map states and the reason for each. The
{{ kernel_module_count }} modules under `hooks/runtime/kernel/` are a verbatim
copy of `lup/policy/kernel/`, kept byte-identical so it can be diffed against
the canonical package. The ownership manifests are written by
`lup.harness.ownership` from the generation result rather than compiled from a
declaration. And `docs/rules.md`, `docs/commands.md`, `generated-paths.md`
itself, and the CI workflow belong to no runtime tree at all: each is written
by a `RepositoryWriter` the project declares beside its targets, reconciled
against nothing but the declaration that renders it, and so absent from a map
walked out of the recipes.

`.claude/CLAUDE.md` and root `AGENTS.md` are the *same* document rendered
twice, because each runtime reads guidance from its own location. The
redundancy is deliberate; edit `content/guidance.py` and regenerate rather
than patching either copy. `docs/` is rendered once, by the Claude recipe,
because these pages are repository documentation at a neutral location rather
than anything either runtime reads from its own tree.

## The pipeline

`lup-devtools harness generate|check|claude|codex` walks one path from typed
Python to a launched native plugin.

1. **Typed declarations** — `harness/content/` holds the skill, agent,
   guidance, pattern, template, and documentation declarations, above the
   tooling layer because they are what a harness is made of rather than
   anything the CLI adds; `harness/catalog.py` composes them with the
   application-owned `HookSet` into one canonical `lup.harness.models.Harness`.
   Prompt prose is stored as ordered typed parts, never as a native string.
2. **Renderers** — `lup.providers.claude.harness` and
   `lup.providers.codex.harness` implement the `ArtifactRenderer` seams from
   `lup.harness.contracts`; the compilation roots in `lup.providers.harness`
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
6. **Launch** — `lup.providers.*.harness_runtime` probes native CLI
   capabilities, and `lup.harness.process` launches the native CLI with the
   non-interactive defaults from `lup.harness.environment`.

Generation orchestration takes a frozen `GenerationRecipe` holding the desired
tree, current-tree reader, ownership location, and target requirements. Only
the CLI composition root maps a user-facing target name to a concrete recipe:
adding a third target supplies another recipe rather than a branch in
reconciliation or materialization.

Each harness module owns one concern. The CLI half lives in
`packages/lup/src/lup/devtools/harness/` and the declarations it compiles in
`packages/lup/src/lup/harness/content/`; `catalog.py` is this repository's,
because its whole job is to be this project's own harness:

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

Both rosters are rendered from the typed declarations, and neither is a list.
Every skill and agent belongs to a **module** — one subject as one value,
carrying its content, its page under `docs/`, its paragraph in the
always-loaded document, its command tree and its tool group — declared under
`lup.harness.content.modules` for the subjects lup ships and under
{{ harness_content_modules }} for the ones only this
repository has. {{ harness_content_catalog_py }} composes
both and states which modules this project takes; everything below is derived
from that rather than declared beside it, so declining a subject removes all
five surfaces at once. `dev modules` prints the roster. Change the module that
owns the subject, then regenerate.

**Skills:**

