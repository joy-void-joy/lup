## Settings & Configuration

Project Codex configuration is the generated `.codex/config.toml`, loaded only for a trusted project. Personal sandbox and approval defaults belong in `~/.codex/config.toml`; `sandbox_mode = "workspace-write"` with `approval_policy = "on-request"` is the low-friction guarded default. Never edit the generated project file.

Prefix-safe outside shell allows from the canonical policy are generated as project-local rules in `.codex/rules/lup.rules`. A matching native `allow` approves the command without choosing its sandbox placement. When the semantic policy places a command outside, set `sandbox_permissions = "require_escalated"` on the first call; the native rule removes the prompt and the PreToolUse hook still blocks unsafe variants. Commands whose safety depends on flags, paths, shell structure, or runtime content stay under the sandbox and approval flow.

---

<!-- section: Process & Communication -->
# Process & Communication

## Asking Questions

**Ask questions as explicit, numbered options** rather than burying them in prose. This applies to:

- Clarifying requirements or ambiguous instructions
- Offering choices between implementation approaches
- Confirming before destructive or irreversible actions
- Proposing changes or improvements
- Any situation where you need user input before proceeding

Even for open-ended questions, present concrete options plus an explicit free-form alternative, so the user can answer with a single short choice.

**When proposing changes:**

- **Propose, don't assume**: Ask before making changes
- **Show context**: Show relevant current state before proposing
- **Explain rationale**: Every suggestion should include why it would help
- **Offer alternatives**: Present options when multiple valid approaches exist

**When in doubt, ask.** Err on the side of asking questions rather than making assumptions.

## Skills

**After every skill invocation**, reflect on how it was actually used vs. documented:

1. **Compare intent vs usage**: Did the skill serve its documented purpose, or was it adapted?
2. **Notice patterns**: When the user corrects your approach or redirects focus, that's a signal the skill should evolve.
3. **Proactively propose updates**: Suggest skill improvements as explicit options.

**Evolution signals:**

- User provides external docs -> Add doc-fetching or reference to the skill
- User corrects your approach -> Update the skill to prevent future errors
- User asks for something the skill should cover -> Expand scope
- User ignores sections -> Consider simplifying

## External Resources

When questions involve the Claude Agent SDK or the Claude API used by the inner agent, fetch the docs directly:

- `https://docs.claude.com/en/agent-sdk/<topic>`
- `https://docs.claude.com/en/api/<topic>`

When the user provides documentation links, incorporate that knowledge into AGENTS.md or relevant skills.

