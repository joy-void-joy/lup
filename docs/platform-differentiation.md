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
over the same declarations. `compile_claude` / `compile_codex` even reject
native invocation spellings inside canonical text
(`reject_rendered_invocations`), so a difference cannot hide in prose.

This document is the map of every intended difference and the parity audit of
every generated artifact family. "Parity" means the same semantic content in
each platform's native format — never byte parity.

## Where each intended difference lives

| Concern | Claude | Codex | Why it differs (all deliberate) |
| --- | --- | --- | --- |
| Skill invocation spelling | `/lup:<skill>` (`ClaudeSkillInvocationRenderer`) | `$lup:<skill>` (`CodexSkillInvocationRenderer`) | Native sigils. Canonical content stores `SkillInvocation` parts; only renderers spell them. |
| Prompt compilation | `ClaudePromptRenderer`: `$ARGUMENTS` for `ArgumentsRef`, Workflow invocation for `ResolverEntry` | `CodexPromptRenderer`: prose arguments reference, direct CLI for `ResolverEntry` | Each renderer owns its native prompt idiom for the same typed parts (`TextPart`, `SkillInvocation`, `AskUser`, `Delegate`, `RequestApproval`, `ResolverEntry`, `ArgumentsRef`). |
| Skills | `.claude/plugins/lup/commands/<name>.md` (description, allowed-tools, argument declarations) | `.codex/plugins/lup/skills/<name>/SKILL.md` (name + description frontmatter) | Claude plugin commands support tool restriction and argument frontmatter; Codex skills do not — arguments arrive as free text. |
| Agents | `.claude/plugins/lup/agents/<name>.md` (Markdown frontmatter) | `.codex/agents/<name>.toml` (custom-agent TOML) | Native agent formats and locations. |
| Plugin manifest + marketplace | `.claude/plugins/lup/.claude-plugin/plugin.json`, `.claude/plugins/.claude-plugin/marketplace.json` | `.codex/plugins/lup/.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | Native manifest schemas and marketplace registries. |
| Repository guidance | `.claude/CLAUDE.md` | `AGENTS.md` at the repository root, plus `.codex/config.toml` (`[features] hooks`) | Same guidance document, rendered to each platform's documented location; Codex additionally needs the hooks feature flag. |
| Hook dispatch | Matcher `WebFetch\|Bash\|Edit\|Write`; dispatcher returns structured allow/ask/deny JSON; edit preimages are inspected (protected paths, marker counts, size, anti-patterns) | Matcher `Bash\|apply_patch\|web_fetch`; dispatcher approximates `ask` as fail-closed exit code 2; `apply_patch` input is opaque and always asks | Claude hooks support structured decisions and edit introspection; Codex hooks do not, so the same semantic kernel (`lup.policy`, identical generated `runtime/kernel.py`) is wrapped in a fail-closed shell. |
| Autonomous edit identities | `policy_data.py` grants `resolve-editor` / `lup:resolve-editor` edit autonomy | Empty list | Codex hook payloads carry no agent identity; the Codex resolver worker's envelope is the native `workspaceWrite` sandbox with `approval_policy="never"` instead (see `resolve_command` in `src/lup_template/devtools/harness/app.py`). |
| Resolver entry | `/lup:resolve` command instructs `Workflow(scriptPath=".claude/workflows/commands/resolve.js", args={})`; the generated `resolve.js` is a thin Bun shim spawning `uv run lup-devtools harness resolve --adapter claude` | No native workflow mechanism exists; `$lup:resolve` instructs running `uv run lup-devtools harness resolve --adapter codex` directly | Both entries only launch the shared persisted Python resolver. The canonical entry contract is the CLI's: optional `--run-id <id>` (resume) and `--accept`/`--reject` (record the human decision). The Claude workflow forwards the same contract as `{"run_id": …, "accept": …}` args; both rendered entries document it (pinned by `test_generated_resolver_entries_only_launch_the_shared_python_core`). |
| Downstream template guidance | `.claude/plugins/lup/TEMPLATE_CLAUDE.md` from `content/template_claude.py` | `.codex/plugins/lup/TEMPLATE_AGENTS.md` from `content/template_codex.py` | Both flavors compose the portable sections in `content/template_sections.py`; only platform slices (guidance-file names, meta-agent naming, edit-hook vs opaque-patch guidance, LSP vs CLI diagnostics, settings, communication idiom) differ. |
| Launch and trust | Launches the verified local plugin directory with `--plugin-dir`; `CLAUDE_CONFIG_DIR` selects the profile | Installs a separately cached copy of the plugin, verifies its digest before every launch; `CODEX_HOME` selects the home | Native trust models: Claude trusts the workspace plugin, Codex requires an installed cache. |
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
| Resolver entry | `.claude/workflows/commands/resolve.js` shim | none (skill instructs the CLI directly) | Intentional gap — Codex has no workflow-script mechanism; the documented fallback is the same shared CLI, and `harness resolve --adapter codex` is the verified entry. |
| `PATTERNS.md` | `.claude/PATTERNS.md` | none | Intentional single copy — the pattern guide (`content/patterns.py`) renders identically under both prompt renderers (one text part, no invocation parts, no native spellings), so a `.codex/` copy would be a byte duplicate. It is repository documentation both agents read from the committed tree; its companion-guidance references resolve to `CLAUDE.md` and the identically-sourced `AGENTS.md`. Rendering a second copy becomes worthwhile only if the document ever gains invocation parts. |
| `settings.json` | `.claude/settings.json` | none | Intentional — Claude-native project settings (plugin enablement, marketplace, permissions, file suggestion). The Codex counterparts are the generated `.codex/config.toml` plus uncommitted personal `config.local.toml`. |
| `scripts/file_suggest.sh` | `.claude/plugins/lup/scripts/file_suggest.sh` | none | Intentional — wired to Claude's native `fileSuggestion` setting; Codex has no equivalent feature. |
| Codex-only files | none | `.codex/config.toml`, `.agents/plugins/marketplace.json` | Intentional — native Codex requirements with no Claude analogue (Claude's marketplace lives inside `.claude/plugins/`). |

Skill prose that names the guidance file or a template names both platform
forms at the action step (see the init/install skills); portable sections keep
skill mentions as typed invocation parts so each rendering spells them
natively.
