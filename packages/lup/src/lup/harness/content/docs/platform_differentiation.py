# lup: ignore[native-spelling]
# This map's subject matter is the native spellings themselves.
"""Every intended Claude/Codex difference and the parity audit."""

import lup.harness.models as models

from lup.harness.content.application import ApplicationLayout
from lup.formats.markdown import contained


def document(
    skills: list[models.Skill],
    agents: list[models.Agent],
    claude_decodes: list[str],
    codex_decodes: list[str],
    layout: ApplicationLayout,
) -> models.PromptDocument:
    """The parity audit, counted against the roster it is auditing.

    The counts are read from the declarations rather than written down, so a
    skill added on either side of the split cannot leave this table claiming
    a number that stopped being true. Each decoded set arrives the same way,
    from the root that composes the runtimes, and is named as what it is: the
    refusal table widens the rendered matcher past it, by whatever the
    composing project declared.
    """
    claude_decoded = contained("|".join(claude_decodes))
    codex_decoded = contained("|".join(codex_decodes))
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.TextPart(
                text=rf"""# Platform differentiation and parity

One portable declaration, two native renderings. `portable_harness()` in
`{layout.path("harness", "catalog.py")}` is deliberately singular: the
settled architecture is **portable-declaration-plus-adapter-rendering**, not
per-platform declarations with a shared default. Everything a platform does
differently lives in exactly two places — the adapter renderers
(`packages/lup/src/lup/providers/claude/harness.py`,
`packages/lup/src/lup/providers/codex/harness.py`, composed by
`packages/lup/src/lup/providers/harness.py`) and the per-platform generation
recipes (`claude_generation_recipe` / `codex_generation_recipe` in
`packages/lup/src/lup/devtools/harness/generate.py`). A per-platform declaration
layer was considered and rejected: it would let semantic content fork silently,
whereas the adapter seam forces every difference to be a rendering decision
over the same declarations. `compile_claude` / `compile_codex` enforce that:
`reject_rendered_invocations` refuses native invocation sigils in canonical
text, and `reject_native_prose` refuses any word an adapter would have spelled
— so a difference cannot hide in prose.

That second check writes down no vocabulary of its own. It asks each
`NativeSpellings` what it spells and forbids exactly that
(`packages/lup/src/lup/harness/codescan/portable.py`, rule `portable-content`), which
is why adding a location to `TreeLocation` or `PluginLocation` forbids it in
prose the same moment a runtime learns to spell it.

This document is the map of every intended difference and the parity audit of
every generated artifact family. "Parity" means the same semantic content in
each platform's native format — never byte parity.

Generated files are one surface, not the boundary of the audit. Launch readiness, authentication, host bridges, delegated-agent paths, runtime diagnostics, and verification must provide equivalent user-visible semantics too; a runtime-specific substitute belongs in this map with the evidence that proves its difference.

## Where each intended difference lives

| Concern | Claude | Codex | Why it differs (all deliberate) |
| --- | --- | --- | --- |
"""
            ),
            models.SpellingExample(
                text=(
                    "| Skill invocation spelling | `/lup:<skill>` "
                    "(`ClaudeSpellings.render`) | `$lup:<skill>` "
                    "(`CodexSpellings.render`) | Native sigils. Canonical content "
                    "stores `SkillInvocation` parts; only the vocabularies spell "
                    "them. `SkillPattern` carries the placeholder or wildcard form "
                    "a prompt uses when it teaches the shape of an invocation "
                    "instead of issuing one. |"
                )
            ),
            models.TextPart(
                text=rf"""
| Prompt compilation | `ClaudeSpellings`: `$ARGUMENTS` for `ArgumentsRef`, the structured-question tool for `AskUser`, a delegation call for `Delegate` | `CodexSpellings`: prose arguments reference, a direct instruction to ask, a custom-agent delegation | One neutral `SpelledPromptRenderer` walks the parts; each runtime supplies a `NativeSpellings` for every native word. A new part adds an abstract method neither runtime can be constructed without answering. |
| Harness locations in prose | `.claude/CLAUDE.md`, `.claude/settings.json`, `.claude/plugins/lup/commands/`, … | `AGENTS.md`, `.codex/config.toml`, `.codex/plugins/lup/skills/`, … | `NativePath` and `PluginPath` name a location semantically. `scope="this_tree"` resolves to the reader's own tree; `scope="every_tree"` renders every runtime's spelling in one identical string, which is how prose teaches both at once. |
| Model choice | `model: opus \| sonnet \| haiku \| inherit` in agent frontmatter | row omitted | Agent declarations carry a portable `ModelTier`. Recorded evidence for Codex custom agents covers TOML parsing only, so no alias is proven to spell a tier in; omitting the row inherits the session model. |
| Runtime documentation | Claude Code and Agent SDK origins | Codex origins | `RuntimeDocs` points a reader at its own runtime's docs; both origins are already in the fetch allowlist (`harness/catalog.py`). |
| Escaping the sandbox for one call | a per-call flag on the launching tool | a per-command override on the shell call, with a justification the approval policy records | `NativeSpellings.escape_sandbox` returns a `Spelling`, so a runtime with no words an agent could be told to use answers `Unsupported` rather than naming a flag its reader cannot pass — and one that has them says so instead of inheriting a gap nobody re-checked. Both resolver entries ask it, so neither can hardcode an escape and neither can be silently absent. |
| Placing a call from the hook's own verdict | the verdict rewrites the call's arguments | no channel: the verdict is an accept or a decline | `NativeSemantics.escapable` is the whole of the difference — whether this runtime's verdicts can place a call. Where they cannot, the plain effect is rendered rather than an intent the runtime would drop. Asking for the launcher's host is not this question: it is `# lup: escalate[sandbox]`, one spelling under both runtimes, answered by Lup's reviewer rather than a native flag. For a command the boundary declaration excludes, the model requests placement on its call and a compiled prefix rule approves exactly the excluded set. |
| Handing a whole document to a tool | the runtime's own file reader | declined, with the reason | `NativeSpellings.read_document` steers away from text extractors, which return an empty string on a scanned page and read as an empty document. Codex's roster reads a document only by running a command over it, and the one tool that takes a file whole accepts images alone. |
| The reason a verdict carries | `permissionDecisionReason` on the hook output, and every generated dispatcher renders it | the in-process approval reply is `{{"decision": "accept"\|"decline"}}` — the app-server response schema has no reason field, so the reason is dropped on that path; the generated dispatcher still prints it on its fail-closed exit | The reason is the one channel to whoever reviews a stopped call, which is why every kernel reason names the specific subject that tripped it. Where Codex's approval reply cannot carry text, the substitute is the session log: `CodexApprovalResponder.decide` logs every refusing reason before it declines, and the refusal itself still reaches the model as a declined act. |
| Skills | `.claude/plugins/lup/commands/<name>.md` (description, allowed-tools, argument declarations) | `.codex/plugins/lup/skills/<name>/SKILL.md` (name + description frontmatter) | Claude plugin commands support tool restriction and argument frontmatter; Codex skills do not — arguments arrive as free text. |
| Agents | `.claude/plugins/lup/agents/<name>.md` (Markdown frontmatter) | `.codex/agents/<name>.toml` (custom-agent TOML) | Native agent formats and locations. |
| Plugin manifest + marketplace | `.claude/plugins/lup/.claude-plugin/plugin.json`, `.claude/plugins/.claude-plugin/marketplace.json` | `.codex/plugins/lup/.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` | Native manifest schemas and marketplace registries. |
| Repository guidance | `.claude/CLAUDE.md` | `AGENTS.md` at the repository root, plus `.codex/config.toml` (`[features] hooks`) | Same guidance document, rendered to each platform's documented location; Codex additionally needs the hooks feature flag. |
| Hook dispatch | Decodes `{claude_decoded}`; dispatcher returns structured allow/ask/deny JSON, or no decision to defer a size-only edit to the client's permission mode; edit preimages are inspected (protected paths, marker counts, size, anti-patterns) | Decodes `{codex_decoded}` on both `PermissionRequest` and `PreToolUse`; a `PermissionRequest` returns a structured allow or, for `ask`, no decision at all so native approval prompts the operator; a matching `PreToolUse` consumes one session-, turn-, cwd-, tool-, and command-bound receipt, while an uncorrelated `ask` joins `deny` at fail-closed exit code 2; a deferred edit is exit 0; `apply_patch` input is opaque and always asks | Claude reaches a real prompt for `ask`; Codex reaches one only when the runtime emits `PermissionRequest`. A later matching `PreToolUse` consumes that native approval, while an uncorrelated ask fails closed. Both run the same semantic kernel (`lup.policy`, identical generated `runtime/kernel.py`). Each rendered matcher is the decoded set above widened by `routed_for` with every tool the composing project's refusal table names, on both runtimes alike — a refusal reaches nothing it was not routed for, so the declaration that states one is what registers it. What differs is edit introspection: Claude sees the preimage and can judge markers, size, and anti-patterns, while Codex sees an opaque patch. |
| Autonomous edit identities | `policy_data.py` grants the resolver's `worker_identity`, bare and plugin-qualified, from the hook payload or the session environment | Same identity, from the session environment only | Both lists are derived from `ResolveSpec.worker_identity`, so neither runtime can ship an empty one by omission. Codex hook payloads carry no agent identity, which is why the environment is the channel that reaches every session on both runtimes. |
| OS sandbox boundary | The `HookSandbox` declaration compiles into the `settings.json` `sandbox` block (bwrap network allowlist, human-owned write denials, credential read denials); the launcher verifies `bwrap`/`socat` before exporting `LUP_SANDBOX_ACTIVE` | The launcher establishes an explicit `--sandbox workspace-write` envelope on the interactive command line and exports the flag only for an envelope it set itself; a caller-supplied sandbox flag keeps the deny lattice active | Codex sandbox config has no per-path write denials or domain allowlist, so its envelope is the declaration's strict subset (network off); the resolver paths carry their own explicit envelopes on both platforms. |
| Forge credential | Selected once by `GitAccess.select` and carried into the container both runtimes launch through, identically: the same rung, the same rewrite direction, the same mounts, the same bare `-e NAME` | Same, from the same declaration | The credential is a property of the container, and one `Image` declaration starts every runtime — so there is nothing here for a runtime to spell differently. What does differ is only how far the *denial* beside it is enforced: `credential_paths` reaches Claude's native per-path credential sandbox and has no Codex equivalent, so on Codex the read denial is the semantic policy alone. Neither is a syscall boundary, and neither stops `ssh` or `git` using the identity that was lent — `docs/permissions.md` says so in those words rather than implying a stronger boundary. |
"""
            ),
            models.SpellingExample(
                text=(
                    "| Resolver entry | `/lup:resolve` instructs `uv run "
                    "lup-devtools resolve --adapter claude` | "
                    "`$lup:resolve` instructs the same command with "
                    "`--adapter codex` |"
                )
            ),
            models.TextPart(
                text=rf""" Both entries only launch the shared persisted Python resolver, and differ solely in the adapter they name — `ResolverEntry` is deliberately undifferentiated because workflow scripts execute in an isolated VM with no shell, leaving the Claude entry nothing to wrap. The entry contract is the CLI's: optional `--run-id <id>` (resume) and repeatable `--answer <question-id>=<value>`, through which the reserved `integration-assembly` gate is approved like any other question. Both rendered entries document it (pinned by `test_generated_resolver_entries_only_launch_the_shared_python_core`, which also asserts no `Workflow(` wrapper appears). |
| Downstream template guidance | `.claude/plugins/lup/TEMPLATE_CLAUDE.md` from `content/template_claude.py` | `.codex/plugins/lup/TEMPLATE_AGENTS.md` from `content/template_codex.py` | Both flavors compose the portable sections in `content/template_sections.py`; only platform slices (guidance-file names, meta-agent naming, edit-hook vs opaque-patch guidance, LSP vs CLI diagnostics, settings, communication idiom) differ. |
| Launch and trust | Launches the verified local plugin directory with `--plugin-dir`; `CLAUDE_CONFIG_DIR` selects the profile | Seeds a persistent per-worktree home from personal authentication and settings, materializes the Claude daltonized theme without selecting it, and publishes a verified content-addressed plugin revision; explicit `--codex-home`/`CODEX_HOME` overrides bypass isolation | Codex installs in a temporary home, verifies the native output, then publishes the revision and only its marketplace/plugin registration. Native installation never runs against the live home: its cache pruning would remove earlier revisions. Concurrent Lup publishers serialize, unrelated settings survive, and existing revision paths remain available. |
| A launched session's coordination identity | The durable id is exported as `LUP_COORDINATION_MEMBER`, and `--name <worktree>` makes the runtime's own display agree with the roster | The same variable, exported by the same code; the launch takes no name flag, so nothing is displayed by the runtime | Both halves are minted in `session_argv`, the one place either launcher passes through, so the id is a fact about having been launched rather than about which CLI was. Measured against Codex 0.153.4, whose launch options are `-c/--config`, `--enable`, `--disable`, `--remote`, `--remote-auth-token-env`, `--strict-config`, `-i/--image`, `-m/--model`, `--oss`, `--local-provider`, `-p/--profile`, `-s/--sandbox`, `--approve-for-me`, the two `--dangerously-` forms, `--add-dir`, `-a/--ask-for-approval`, `--search` and `--no-alt-screen` — none of which names a session. The difference costs a peer nothing: what addressing resolves through is lup's own `names.jsonl`, so the roster answers to the same derived worktree name on both runtimes and `dev coordination rename` changes it on both. Only the CLI's own chrome differs, and only on the runtime that has chrome to put it in. |
| Mail reaching a peer mid-session | A second `PreToolUse` group whose matcher is empty, so it fires before every tool: a shell guard comparing the mailbox's length to this member's delivered position, handing over to a verbatim `delivery_runtime` only where it has grown | Nothing extra; the policy matcher already names the tool every read goes through | The gap is one runtime's, because the tool rosters differ rather than the delivery does. Claude reads through native `Read`/`Grep`/`Glob`, which the policy matcher does not name and must not: every entry in `routed_tools` is proved to have a branch deciding it, so naming `Read` there would make `Read` a tool a policy could refuse. Codex "reads a document only by running a shell command over it", and `Bash` is already routed — so a peer there hears everything at the same moments without a second artifact. Both halves are measured rather than assumed: `PreToolUse` was observed firing for `Read`, `Grep`, `Glob` and `SendMessage` under an empty matcher, which the vendor documents for none of them. The guard costs 7.85ms per call with nothing waiting, against 107ms for the dispatcher, and fails open at every step — the opposite of the policy guard, because a permission that cannot be decided must not be granted, while mail that cannot be read must not stop the work it was meant to inform. |
| Runtime preflight | `claude` CLI version, plugin support, `plugin validate` | CLI version, cache digest, and native `account/read` with managed-token refresh | Account checks use the session's execution boundary: the selected host home for inner/none, the container's home for outer. Container sign-in uses device authentication and is checked again afterward. Named profiles remain explicitly unverified because the account API cannot select them. Declining sign-in continues explicitly unverified; account readiness does not prove implicit MCP service startup. |
| Reasoning effort | `CLAUDE_EFFORT` in `providers/claude/selection.py` | `CODEX_EFFORT` in `providers/codex/selection.py` | `SessionRequest.effort` is asked for in portable words and mapped by each adapter, the way autonomy already is. `low`, `medium`, `high`, and `xhigh` are the four rungs both ladders carry outright. The two ends belong to one runtime each and the other renders the nearest it has: `minimal` is Codex's own floor, which Claude meets with `low` because its ladder has no rung beneath that; `max` is Claude's own ceiling, which Codex meets with `xhigh` for the same reason at the top. Codex's `none` is deliberately absent from the portable vocabulary — Claude would render it as `low`, turning "do not reason" into "reason a little" on one runtime without saying so. |
| Usage display | the OAuth usage endpoint for live windows, plus the local stats cache for per-day and per-model detail | the app-server's own account calls for both the metered windows and the daily token buckets | One display over two readers (`lup.observability.usage`, `usage/reader.py` in each adapter). Each side reports a plan's windows and its days into the same report, so the pacing bars, the daily budget, and the `--json` snapshot are decided once. What differs is what each account publishes: fixed named windows and a per-model split on one side, two self-describing windows and no model breakdown on the other — which is why one draws a model legend and the other has none to draw. |
| Sensitive local-only files | `.claude/settings.local.json` | `.codex/config.local.toml` | Native personal-config locations, excluded from generation. |
| Surfacing a verdict's evidence to the approver | The reason is rendered in the prompt for a shell command and dropped in the create-file dialog, so a verdict that enumerated sites repeats them in `systemMessage`, coloured for this terminal (`announced` in `providers/claude/assets/policy_dispatcher.py`) | Nothing extra: the dispatcher already writes `decision.reason` to stderr, which is shown whole | Measured against Claude Code 2.1.237, both directions. `permissionDecisionReason` reaches the person for `Bash` and not for `Write`/`Edit`; `systemMessage` reaches them from every hook but arrives with the tool call rather than with the prompt, so on this runtime the evidence informs rather than gates. `PermissionRequest` — the event that runs before the prompt — belongs to the control protocol rather than to a local plugin and never fires for one, which is why Codex's declaration names it and Claude's does not. The colour lives in the adapter because it is one terminal's alphabet; the kernel states the sites in portable words and both runtimes carry the same verdict. |
| Post-write observation of an edited file | `PostToolUse` names the file, so the dead-suppression sweep (`repair_command`) and the type checker (`diagnostics_command`) both run on it | `PostToolUse` hands over the working directory alone, so neither runs on an edit; a shell command's writes are still reviewed, since a command carries its own text | The same fact one step coarser, and the same reason diagnostics were already Claude-only: Codex names its files inside the patch envelope, and this event runs after the patch has rewritten the file the decoder would validate against. Sweeping the directory instead would rewrite files the edit never touched — so on Codex a directive that silences nothing waits for `dev check --antipatterns --fix`, which is where every other whole-tree finding waits too. |

## Parity audit of generated artifact families

Every family in `.claude/` vs `.codex/`/`.agents/`, with an explicit decision.

| Family | Claude | Codex | Decision |
| --- | --- | --- | --- |
| Skills ({len(skills)}) | `commands/*.md` | `skills/*/SKILL.md` | Parity — same {len(skills)} declarations, native formats. |
| Agents ({len(agents)}) | `plugins/lup/agents/*.md` | `.codex/agents/*.toml` | Parity — same {len(agents)} declarations, native formats. |
| Plugin manifest | `.claude-plugin/plugin.json` + marketplace | `.codex-plugin/plugin.json` + `.agents/plugins/marketplace.json` | Parity — native schemas. |
| Hooks (`hooks.json`, `scripts/policy.py`, `runtime/kernel.py`, `runtime/policy_data.py`, `runtime/evidence.json`) | Structured decisions, edit inspection, autonomous identities | Structured decisions on `PermissionRequest`, one-shot approval correlation and fail-closed uncorrelated exits under `PreToolUse`, opaque patches, identities from the environment | Parity of the semantic kernel (identical `kernel.py`); dispatcher differences intentional per the table above. |
| Guidance | `.claude/CLAUDE.md` | `AGENTS.md` + `.codex/config.toml` | Parity — one document, native locations. |
| Ownership proof | `.claude/.lup-ownership.json` | `.codex/.lup-ownership.json` | Parity — same mechanism per tree. |
| Template guidance | `TEMPLATE_CLAUDE.md` | `TEMPLATE_AGENTS.md` | Parity — shared portable sections, platform slices per flavor. |
| Resolver entry | skill instructs the CLI directly | skill instructs the CLI directly | Parity — neither tree generates a launcher artifact; the shared `resolve --adapter <runtime>` CLI is the entry on both sides. |
| `docs/` | rendered by the Claude recipe | none | Intentional single copy — repository documentation at a neutral location, which neither runtime reads from its own tree. Each page renders identically under both prompt renderers, so a second copy would be a byte duplicate and would additionally give two ownership manifests the same paths to manage. The set is declared once in `content/docs/catalog.py`. |
| `settings.json` | `.claude/settings.json` | none | Intentional — Claude-native project settings (plugin enablement, marketplace, permissions, file suggestion). The Codex counterparts are the generated `.codex/config.toml` plus uncommitted personal `config.local.toml`. |
| `scripts/file_suggest.sh` | `.claude/plugins/lup/scripts/file_suggest.sh` | none | Intentional — wired to Claude's native `fileSuggestion` setting; Codex has no equivalent feature. |
| Codex-only files | none | `.codex/config.toml`, `.agents/plugins/marketplace.json` | Intentional — native Codex requirements with no Claude analogue (Claude's marketplace lives inside `.claude/plugins/`). |

## Parity audit of runtime capability families

| Family | Required evidence |
| --- | --- |
| Launch readiness | Exercise the same native startup path a user runs, including implicit services; `Ready` may describe only checks that completed successfully. |
| Authentication | Ask the runtime that owns and refreshes a credential, and cover every user-visible service whose authentication path differs from the primary model transport. Never infer managed-auth readiness from one locally decoded token. |
| Host bridges | Probe the native API each runtime actually calls for clipboard, browser, terminal, and credential access; a command shim proves only callers of that command. Advertised access must match the probe. |
| Delegated-agent paths | Invoke each declared role through every supported runtime with provider-neutral model tiers and tool capabilities; listing a tool or rendering a declaration does not prove the delegated turn can start. |
| Diagnostics and tests | Equivalent failures identify the failed capability, owning runtime, recovery, and affected credential or bridge without exposing secrets. Unit fixtures cover native adapters, and a live requirement exercises each supported startup path. |

### Outer-sandbox clipboard and login handoff

Both runtimes reach the same bounded clipboard broker. Claude Code's command
clients use the image's `xclip` and `wl-paste` shims directly. Codex's native
X11 client uses a private Xvfb server and a python-xlib selection bridge; its
installed CLI has no configurable clipboard-helper command. The composition
declares that transport, not a provider-name branch in the shared launcher.
Only native-X11 sessions start the display, with GLX and TCP disabled and a
per-session Xauthority cookie. Neither transport mounts a host display socket.
The wrapper waits for server and selection ownership before starting the CLI,
then cleans them up with it. Large native transfers are incremental and bounded;
unsupported types are refused, not truncated or forwarded to the desktop.

Regression tests exercise command and native clients against a synthetic
clipboard, including live changes, text copies, image reads, payload limits,
and private-display authentication. Isolated Codex 0.153.4 TUI probes attached
a synthetic PNG through its actual paste shortcut on the host and in the built
image, without a model request or real credentials; the container probe had no
network. This proves the native clipboard path, independently of authentication.
Host-broker discovery reports
only its own result, and private-display startup is checked inside the session.

Host login handoff fingerprints the selected credential fields. A changed host
login replaces those fields once; an unchanged host login preserves the
container's renewed tokens. Claude's shared credentials file retains unrelated
MCP credentials, and Codex's dedicated auth file is replaced as a unit. A
fingerprint is bookkeeping, not authentication evidence: the owning runtime
must still validate or renew its credential in the session's actual boundary.

A separate Codex 0.153.4 outer-container probe successfully forced managed
login renewal through `account/read(refreshToken=true)`. An ephemeral thread
using that saved login then observed `codex_apps` startup go from `starting`
to `ready`. No model turn or app tool call ran. This checks the implicit
service's own authentication path, not merely the primary account response;
it is evidence for the selected account and runtime, not a promise of future
remote-service availability.

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
"""
            ),
        ],
    )
