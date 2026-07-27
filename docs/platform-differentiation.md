# Platform differentiation and parity

One portable declaration, two native renderings. `portable_harness()` in
`src/lup_template/devtools/harness/catalog.py` is deliberately singular: the
settled architecture is **portable-declaration-plus-adapter-rendering**, not
per-platform declarations with a shared default. Everything a platform does
differently lives in exactly two places — the adapter renderers
(`packages/lup/src/lup/adapters/claude/harness.py`,
`packages/lup/src/lup/adapters/codex/harness.py`, composed by
`packages/lup/src/lup/adapters/harness.py`) and the per-platform generation
recipes (`claude_generation_recipe` / `codex_generation_recipe` in
`src/lup_template/devtools/harness/generate.py`). A per-platform declaration
layer was considered and rejected: it would let semantic content fork silently,
whereas the adapter seam forces every difference to be a rendering decision
over the same declarations. `compile_claude` / `compile_codex` enforce that:
`reject_rendered_invocations` refuses native invocation sigils in canonical
text, and `reject_native_prose` refuses any word an adapter would have spelled
— so a difference cannot hide in prose.

That second check writes down no vocabulary of its own. It asks each
`NativeSpellings` what it spells and forbids exactly that
(`packages/lup/src/lup/codescan/portable.py`, rule `portable-content`), which
is why adding a location to `TreeLocation` or `PluginLocation` forbids it in
prose the same moment a runtime learns to spell it.

This document is the map of every intended difference and the parity audit of
every generated artifact family. "Parity" means the same semantic content in
each platform's native format — never byte parity.

## Where each intended difference lives

| Concern | Claude | Codex | Why it differs (all deliberate) |
| --- | --- | --- | --- |
| Skill invocation spelling | `/lup:<skill>` (`ClaudeSpellings.render`) | `$lup:<skill>` (`CodexSpellings.render`) | Native sigils. Canonical content stores `SkillInvocation` parts; only the vocabularies spell them. `SkillPattern` carries the placeholder or wildcard form a prompt uses when it teaches the shape of an invocation instead of issuing one. |
| Prompt compilation | `ClaudeSpellings`: `$ARGUMENTS` for `ArgumentsRef`, the structured-question tool for `AskUser`, a delegation call for `Delegate` | `CodexSpellings`: prose arguments reference, a direct instruction to ask, a custom-agent delegation | One neutral `SpelledPromptRenderer` walks the parts; each runtime supplies a `NativeSpellings` for every native word. A new part adds an abstract method neither runtime can be constructed without answering. |
| Harness locations in prose | `.claude/CLAUDE.md`, `.claude/settings.json`, `.claude/plugins/lup/commands/`, … | `AGENTS.md`, `.codex/config.toml`, `.codex/plugins/lup/skills/`, … | `NativePath` and `PluginPath` name a location semantically. `scope="this_tree"` resolves to the reader's own tree; `scope="every_tree"` renders every runtime's spelling in one identical string, which is how prose teaches both at once. |
| Model choice | `model: opus \| sonnet \| haiku \| inherit` in agent frontmatter | row omitted | Agent declarations carry a portable `ModelTier`. Recorded evidence for Codex custom agents covers TOML parsing only, so no alias is proven to spell a tier in; omitting the row inherits the session model. |
| Runtime documentation | Claude Code and Agent SDK origins | Codex origins | `RuntimeDocs` points a reader at its own runtime's docs; both origins are already in the fetch allowlist (`harness/catalog.py`). |
| Skills | `.claude/plugins/lup/commands/<name>.md` (description, allowed-tools, argument declarations) | `.codex/plugins/lup/skills/<name>/SKILL.md` (name + description frontmatter) | Claude plugin commands support tool restriction and argument frontmatter; Codex skills do not — arguments arrive as free text. |
| Agents | `.claude/plugins/lup/agents/<name>.md` (Markdown frontmatter) | `.codex/agents/<name>.toml` (custom-agent TOML) | Native agent formats and locations. |
| Plugin manifest + marketplace | `.claude/plugins/lup/.claude-plugin/plugin.json`, `.claude/plugins/.claude-plugin/marketplace.json` | `.codex/plugins/lup/.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | Native manifest schemas and marketplace registries. |
| Repository guidance | `.claude/CLAUDE.md` | `AGENTS.md` at the repository root, plus `.codex/config.toml` (`[features] hooks`) | Same guidance document, rendered to each platform's documented location; Codex additionally needs the hooks feature flag. |
| Hook dispatch | Matcher `WebFetch\|Bash\|Edit\|Write`; dispatcher returns structured allow/ask/deny JSON, or no decision to defer a size-only edit to the client's permission mode; edit preimages are inspected (protected paths, marker counts, size, anti-patterns) | Matcher `Bash\|apply_patch\|web_fetch`; dispatcher approximates `ask` as fail-closed exit code 2 and treats a deferred edit as exit 0; `apply_patch` input is opaque and always asks | Claude hooks support structured decisions and edit introspection; Codex hooks do not, so the same semantic kernel (`lup.policy`, identical generated `runtime/kernel.py`) is wrapped in a fail-closed shell. |
| Autonomous edit identities | `policy_data.py` grants `resolve-editor` / `lup:resolve-editor` edit autonomy | Empty list | Codex hook payloads carry no agent identity; the Codex resolver worker's envelope is the native `workspaceWrite` sandbox with `approval_policy="never"` instead (see `resolve_command` in `src/lup_template/devtools/harness/app.py`). |
| OS sandbox boundary | The `HookSandbox` declaration compiles into the `settings.json` `sandbox` block (bwrap network allowlist, human-owned write denials, credential read denials); the launcher verifies `bwrap`/`socat` before exporting `LUP_SANDBOX_ACTIVE` | The launcher establishes an explicit `--sandbox workspace-write` envelope on the interactive command line and exports the flag only for an envelope it set itself; a caller-supplied sandbox flag keeps the deny lattice active | Codex sandbox config has no per-path write denials or domain allowlist, so its envelope is the declaration's strict subset (network off); the resolver paths carry their own explicit envelopes on both platforms. |
| Resolver entry | `/lup:resolve` instructs `uv run lup-devtools harness resolve --adapter claude` | `$lup:resolve` instructs the same command with `--adapter codex` | Both entries only launch the shared persisted Python resolver, and differ solely in the adapter they name — `ResolverEntry` is deliberately undifferentiated because workflow scripts execute in an isolated VM with no shell, leaving the Claude entry nothing to wrap. The entry contract is the CLI's: optional `--run-id <id>` (resume), `--accept`/`--reject` (record the human decision), and repeatable `--answer`. Both rendered entries document it (pinned by `test_generated_resolver_entries_only_launch_the_shared_python_core`, which also asserts no `Workflow(` wrapper appears). |
| Downstream template guidance | `.claude/plugins/lup/TEMPLATE_CLAUDE.md` from `content/template_claude.py` | `.codex/plugins/lup/TEMPLATE_AGENTS.md` from `content/template_codex.py` | Both flavors compose the portable sections in `content/template_sections.py`; only platform slices (guidance-file names, meta-agent naming, edit-hook vs opaque-patch guidance, LSP vs CLI diagnostics, settings, communication idiom) differ. |
| Launch and trust | Launches the verified local plugin directory with `--plugin-dir`; `CLAUDE_CONFIG_DIR` selects the profile | Seeds a persistent per-worktree home from personal authentication and settings, installs and verifies the plugin there; explicit `--codex-home`/`CODEX_HOME` overrides bypass isolation | Native trust models: Claude trusts the workspace plugin, while Codex requires an installed cache and keeps plugin identity in home-level config. |
| Runtime preflight | `claude` CLI version, plugin support, `plugin validate` | `codex` CLI version and cache digest evidence | Each side probes only its own native capabilities (`harness_runtime.py` in each adapter). |
| Sensitive local-only files | `.claude/settings.local.json` | `.codex/config.local.toml` | Native personal-config locations, excluded from generation. |

## Parity audit of generated artifact families

Every family in `.claude/` vs `.codex/`/`.agents/`, with an explicit decision.

| Family | Claude | Codex | Decision |
| --- | --- | --- | --- |
| Skills (30) | `commands/*.md` | `skills/*/SKILL.md` | Parity — same 30 declarations, native formats. |
| Agents (5) | `plugins/lup/agents/*.md` | `.codex/agents/*.toml` | Parity — same 5 declarations, native formats. |
| Plugin manifest | `.claude-plugin/plugin.json` + marketplace | `.codex-plugin/plugin.json` + `.agents/plugins/marketplace.json` | Parity — native schemas. |
| Hooks (`hooks.json`, `scripts/policy.py`, `runtime/kernel.py`, `runtime/policy_data.py`, `runtime/evidence.json`) | Structured decisions, edit inspection, autonomous identities | Fail-closed exit-code approximation, opaque patches, no identities | Parity of the semantic kernel (identical `kernel.py`); dispatcher differences intentional per the table above. |
| Guidance | `.claude/CLAUDE.md` | `AGENTS.md` + `.codex/config.toml` | Parity — one document, native locations. |
| Ownership proof | `.claude/.lup-ownership.json` | `.codex/.lup-ownership.json` | Parity — same mechanism per tree. |
| Template guidance | `TEMPLATE_CLAUDE.md` | `TEMPLATE_AGENTS.md` | Parity — shared portable sections, platform slices per flavor. |
| Resolver entry | skill instructs the CLI directly | skill instructs the CLI directly | Parity — neither tree generates a launcher artifact; the shared `harness resolve --adapter <runtime>` CLI is the entry on both sides. |
| `PATTERNS.md` | `.claude/PATTERNS.md` | none | Intentional single copy — the pattern guide (`content/patterns.py`) renders identically under both prompt renderers (one text part, no invocation parts, no native spellings), so a `.codex/` copy would be a byte duplicate. It is repository documentation both agents read from the committed tree, so guidance refers to it bare as `PATTERNS.md`, the way the application modules already do. Its residual oddity is the path: its two sibling support documents (`docs/self-improvement.md`, `docs/permissions.md`) sit at neutral locations while this one lives inside a runtime's tree. Moving it to `docs/` would settle that; rendering a second copy becomes worthwhile only if the document ever gains invocation parts. |
| `settings.json` | `.claude/settings.json` | none | Intentional — Claude-native project settings (plugin enablement, marketplace, permissions, file suggestion). The Codex counterparts are the generated `.codex/config.toml` plus uncommitted personal `config.local.toml`. |
| `scripts/file_suggest.sh` | `.claude/plugins/lup/scripts/file_suggest.sh` | none | Intentional — wired to Claude's native `fileSuggestion` setting; Codex has no equivalent feature. |
| Codex-only files | none | `.codex/config.toml`, `.agents/plugins/marketplace.json` | Intentional — native Codex requirements with no Claude analogue (Claude's marketplace lives inside `.claude/plugins/`). |

## What portable prose may name

Nothing a runtime spells for itself. A skill that means the guidance file, a
settings location, a plugin directory, a model tier, or the runtime's own
documentation says so through a typed part, and the adapter supplies the word:
`scope="this_tree"` when the sentence instructs the reader to act on their own
tree, `scope="every_tree"` when it describes what the repository holds and both
trees must be named. `reject_native_prose` refuses the rest at compile time, so
this is an invariant rather than a convention.

Two things prose may still name, because they are not platform facts. Tool
grants stay literal: `ToolGrant` (`packages/lup/src/lup/types.py`) deliberately
adopts one tool vocabulary for every runtime, so a skill teaching which grants
to declare names them as the closed type spells them. And the SDK symbols in
the guidance's Type Safety section stay literal too — they are importable names
from the library this template builds on, needed verbatim by a reader on either
runtime.
