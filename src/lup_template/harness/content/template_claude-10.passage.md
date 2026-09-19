## Settings & Configuration

All Claude Code settings modifications should be **project-level** (in `.claude/settings.json`), not user-level.

---

<!-- section: Process & Communication -->
# Process & Communication

## Asking Questions

**Always use the `AskUserQuestion` tool** instead of asking questions in plain text. This applies to:

- Clarifying requirements or ambiguous instructions
- Offering choices between implementation approaches
- Confirming before destructive or irreversible actions
- Proposing changes or improvements
- Any situation where you need user input before proceeding

Even for open-ended questions, use `AskUserQuestion` with options that include a custom input option. This allows structured notification parsing.

**When proposing changes:**

- **Propose, don't assume**: Use AskUserQuestion before making changes
- **Show context**: Show relevant current state before proposing
- **Explain rationale**: Every suggestion should include why it would help
- **Offer alternatives**: Present options when multiple valid approaches exist

**When in doubt, ask.** Err on the side of asking questions rather than making assumptions.

## Slash Commands & Skills

**After every command invocation**, reflect on how it was actually used vs. documented:

1. **Compare intent vs usage**: Did the command serve its documented purpose, or was it adapted?
2. **Notice patterns**: When the user corrects your approach or redirects focus, that's a signal the command should evolve.
3. **Proactively propose updates**: Use AskUserQuestion to suggest command improvements.

**Evolution signals:**

- User provides external docs -> Add doc-fetching or reference to command
- User corrects your approach -> Update command to prevent future errors
- User asks for something the command should cover -> Expand scope
- User ignores sections -> Consider simplifying

## External Resources

When questions involve Claude Code, Agent SDK, or Claude API:

1. **Use the claude-code-guide subagent**:

   ```
   Agent(subagent_type="claude-code-guide", prompt="<specific question>")
   ```

2. **Fetch docs directly** for specific pages:
   - `WebFetch(url="https://docs.claude.com/en/agent-sdk/<topic>")`
   - `WebFetch(url="https://docs.claude.com/en/claude-code/<topic>")`

When the user provides documentation links, incorporate that knowledge into CLAUDE.md or relevant commands.

