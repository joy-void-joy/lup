# Generated artifacts and ownership manifests

The committed `.claude/`, `.codex/`, `.agents/`, and root `AGENTS.md` trees are
compiler output, not hand-written configuration. Their canonical sources are
typed Python declarations; `uv run lup-devtools harness generate all` renders
both native trees deterministically, and `uv run lup-devtools harness check
all` is the read-only drift check CI runs. The trees are committed so the
repository is directly launchable as a native Claude/Codex plugin with no
build step, and so generated output is reviewed like any other change.

`docs/rules.md` belongs to no single native tree and is rendered by
`uv run lup-devtools dev rules`, which its own banner names. The `all`
selector reaches it too, so `harness generate all` and `harness check all`
settle every generated artifact in the repository and a contributor needs
only the one command.

## The generated-from banner

Artifacts whose format allows comments open with a generated-from banner
naming their canonical source and the exact command that rebuilds them. There
is one definition of that banner —
`packages/lup/src/lup/harness/banner.py` — parameterized by source, command,
any target-specific notes, and the comment syntax a
`CommentRouter` resolves from the file's suffix (`<!-- -->` for Markdown, `#`
for Python, TOML, rules and shell, `//` for JavaScript and TypeScript). Two
banners therefore differ only where those parameters differ.

Every artifact either carries a banner or declares why it carries none, and
`validated_tree` fails generation for one that does neither — so a new
generated file cannot quietly ship without provenance. The two declared
exemptions are:

- **Prompt text** — skill, command, and agent Markdown is verbatim
  model-facing text after its frontmatter, so a banner would be injected into
  every prompt.
- **Verbatim copies** — the policy kernel modules, the `apply_patch` decoder,
  and `file_suggest.sh` are byte-identical copies of their sources, and a
  banner would break the diff that proves the copy faithful.

JSON artifacts (manifests, hooks, settings, evidence) need no declaration at
all: no route claims them because the format has no comment syntax. This page
is the provenance record for every file in all three groups.

## One guidance document, two renderings

`.claude/CLAUDE.md` and the root `AGENTS.md` are the *same* canonical
guidance document — `src/lup_template/devtools/harness/content/guidance.py` —
rendered once per platform, because Claude Code reads `.claude/CLAUDE.md` and
Codex reads `AGENTS.md`. The redundancy between the two files is deliberate;
edit the canonical module and regenerate rather than patching either copy.

## Ownership manifests

`.claude/.lup-ownership.json` and `.codex/.lup-ownership.json` are the
generator's proof of ownership, written by
`packages/lup/src/lup/harness/ownership.py` after every successful
generation. Each records the generator version, a digest of the canonical
declarations, and — per generated file — its path, sha256, semantic id, and
executable bit.

Reconciliation (`packages/lup/src/lup/harness/reconciliation.py`) compares
current bytes against these recorded digests to classify every managed path:
files that still match may be replaced or deleted by regeneration; hand-edited
generated files are preserved and reported as conflicts (backpropagation
candidates); local files the generator never wrote — including sensitive ones
like `.claude/settings.local.json` and `.codex/config.local.toml` — are never
touched. The manifests are committed because fresh clones and CI need the
recorded digests: without them the drift check cannot run and the generator
cannot prove which bytes it owns, so it would refuse to replace anything.

## Generated-tree map

Canonical sources live in `src/lup_template/devtools/harness/content/`
(application content), `src/lup_template/devtools/harness/catalog.py`
(plugin/hook/resolver composition), and `packages/lup/src/lup/` (adapter
renderers and the policy bundle).

| Generated path | Canonical source |
| --- | --- |
| `.claude/CLAUDE.md`, `AGENTS.md` | `content/guidance.py` |
| `.claude/PATTERNS.md` | `content/patterns.py` |
| `.claude/plugins/lup/TEMPLATE_CLAUDE.md` | `content/template_claude.py` |
| `.codex/plugins/lup/TEMPLATE_AGENTS.md` | `content/template_codex.py` |
| `.claude/settings.json` | `content/settings.py` |
| `.claude/plugins/lup/scripts/file_suggest.sh` | `content/assets/file_suggest.sh` (verbatim copy) |
| `.claude/plugins/lup/commands/<skill>.md`, `.codex/plugins/lup/skills/<skill>/SKILL.md` | `content/skills/<skill>.py` |
| `.claude/plugins/lup/agents/<agent>.md`, `.codex/agents/<agent>.toml` | `content/agents/<agent>.py` |
| `.claude/plugins/lup/.claude-plugin/plugin.json`, `.claude/plugins/.claude-plugin/marketplace.json` | `catalog.py` via `lup.adapters.claude.harness` |
| `.codex/plugins/lup/.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | `catalog.py` via `lup.adapters.codex.harness` |
| `.claude/plugins/lup/hooks/`, `.codex/plugins/lup/hooks/` (`hooks.json`, `scripts/policy.py`, `runtime/policy_data.py`, `runtime/evidence.json`) | `catalog.py` `HookSet` (with `content/shell_vocabulary.py` and `lup.codescan.antipatterns`) via the adapter hook renderers and `lup.policy.bundle` |
| `.claude/plugins/lup/hooks/runtime/kernel.py`, `.codex/plugins/lup/hooks/runtime/kernel.py` | verbatim copy of `packages/lup/src/lup/policy/kernel.py` (kept byte-identical so it can be diffed against the canonical module, whose docstring names the copy relationship) |
| `.codex/config.toml` | `lup.adapters.codex.harness` |
| `.codex/rules/lup.rules` | `lup.policy.shell_rules` plus the `HookSet` shell-rule extension, via `lup.adapters.codex.harness` |
| `docs/rules.md` | `lup_template.devtools.dev.rules` from `lup.codescan.registry` |
| `.claude/.lup-ownership.json`, `.codex/.lup-ownership.json` | written by `lup.harness.ownership` from the generation result |

See `docs/harness.md` for how generation, reconciliation, and launch fit
together, and `docs/adopter-guide.md` for downstream walkthroughs.
