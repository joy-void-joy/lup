# lup: ignore[native-spelling]
# This adapter support document deliberately teaches Claude-native spellings.
"""Canonical downstream template guidance in its Claude flavor."""

import lup.harness.models as models
from lup_template.devtools.harness.content.template_sections import (
    CLAUDE_POLICY_SCOPE,
    DIRECTORY_STRUCTURE_THROUGH_TOOLS,
    INNER_AGENT_BULLET,
    PATTERN_MENU_TAIL_THROUGH_WORKTREE_STEP,
    PRINCIPLES_THROUGH_PATTERN_MENU,
    SELF_IMPROVEMENT_THROUGH_END,
    SETUP_THROUGH_NAMING,
    TOOLING_INTRO,
    WORKFLOW_THROUGH_COMMIT_FORMAT,
    permission_hooks,
)

DOCUMENT = models.PromptDocument(
    parts=[
        models.TextPart(
            text=r"""<!-- Generated from src/lup_template/devtools/harness/content/template_claude.py via `uv run lup-devtools harness generate all` — edit the source, not this file. See docs/generated-artifacts.md. -->

# CLAUDE.md Template

This file exports portable sections from the upstream CLAUDE.md as a scaffold for downstream projects. It contains conventions, workflow patterns, and coding standards that apply to any project using lup.

**How it's used:** `"""
        ),
        models.SkillInvocation(plugin="lup", skill="init"),
        models.TextPart(text=r"""` and `"""),
        models.SkillInvocation(plugin="lup", skill="install"),
        models.TextPart(
            text=r"""` perform a **section-level merge** — they use the `<!-- section: ... -->` markers below to identify independent merge units, compare them against the target's existing CLAUDE.md, add sections that are missing, and leave existing sections untouched. Placeholders like `<project>` are replaced with the actual project name.

---

<!-- section: CLAUDE.md -->
# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

**Note:** Modifying `CLAUDE.md` means modifying `.claude/CLAUDE.md` (this file).

"""
        ),
        *SETUP_THROUGH_NAMING,
        models.TextPart(
            text=r"""- **Claude** = the meta-agent (Claude Code) that modifies the codebase, runs commands, and manages the development workflow
"""
        ),
        *INNER_AGENT_BULLET,
        models.TextPart(
            text=r""""Lup" is the framework's name for the inner agent, not a project-specific term. Use "Claude" when referring to the outer development agent and "Lup" when referring to the inner SDK agent, regardless of the project's package name."""
        ),
        *PRINCIPLES_THROUGH_PATTERN_MENU,
        models.TextPart(text=r""" `.claude/PATTERNS.md` carries the full catalog."""),
        *PATTERN_MENU_TAIL_THROUGH_WORKTREE_STEP,
        models.TextPart(
            text=r"""`lup-devtools harness claude` regenerates and launches the verified local plugin"""
        ),
        *WORKFLOW_THROUGH_COMMIT_FORMAT,
        models.TextPart(
            text=r"""## Editing Style

**Prefer small, atomic edits.** A PreToolUse hook counts "real" changed lines (ignoring imports, comments, whitespace, blank lines, docstrings, string literals, type annotations, and TypedDict/BaseModel bodies) and auto-allows edits with <=3 real changes per change block. Pure deletions and single-line `replace_all` renames are auto-allowed; multi-line `replace_all` falls through to the size gate. Anti-pattern detection runs before any auto-allow, and `Write` (full-file rewrites) never auto-allows.

- **Split large changes into multiple small edits** -- keep real (non-trivial) line changes to <=3 per Edit call
- **Separate concerns** -- move imports in one edit, change logic in another (import changes are trivial and don't count)
- **Use `rename-symbol`** for identifier renames instead of `Edit` with `replace_all`

"""
        ),
        *DIRECTORY_STRUCTURE_THROUGH_TOOLS,
        models.TextPart(
            text=r"""## Pyright LSP

The `pyright-lsp` plugin provides code intelligence. **Use these actively** -- they are faster and more accurate than grep-based searches for code understanding and refactoring.

**Navigation (use before editing unfamiliar code):**

- **go-to-definition** -- Jump to where a symbol is defined. Use this instead of grepping for `def foo` or `class Foo`.
- **find-references** -- Find all usages of a symbol. Use this instead of grepping for a symbol name.
- **hover-documentation** -- Get type info and docs for a symbol at a position.
- **list-symbols** -- List all symbols in a file. Use this instead of grepping for `def ` or `class `.
- **find-implementations** -- Find implementations of an interface or abstract method.
- **trace-call-hierarchy** -- Understand call chains. Use this instead of manually tracing function calls.

**Refactoring:**

- **rename-symbol** -- Rename a symbol across the workspace. **Always prefer this over `Edit` with `replace_all`** for identifier renames -- it understands scope and won't rename unrelated identifiers.

**Diagnostics:**

- After every file edit, pyright automatically analyzes changes and reports type errors. Pay attention to these -- they catch issues immediately.

**When to use LSP vs grep/Edit:**

| Task                             | Use LSP            | Use grep/Edit    |
| -------------------------------- | ------------------ | ---------------- |
| Find where a function is defined | `go-to-definition` |                  |
| Find all callers of a function   | `find-references`  |                  |
| Rename a variable/function/class | `rename-symbol`    |                  |
| Search for a string literal      |                    | `Grep`           |
| Search across non-Python files   |                    | `Grep`           |
| Change logic within a function   |                    | `Edit`           |
| Add new code                     |                    | `Edit` / `Write` |

"""
        ),
        *TOOLING_INTRO,
        models.TextPart(
            text=r"""`lup-devtools harness claude` regenerates, verifies, and runs Claude Code with
the local Lup plugin and the active profile's account (`CLAUDE_CONFIG_DIR`).
`lup-devtools usage claude` reports usage for the chosen profile. Profiles are managed
with `lup-devtools setup profile`.

Each repo names its plugin **marketplace** after the project — the plugin entry stays `lup`, so `/lup:*` is identical everywhere. Marketplace names share one global namespace (`~/.claude/plugins/known_marketplaces.json`), so a shared name like `lup`/`local` collides across repos and an install from one shadows the others; `lup-devtools dev plugin name` (run by `"""
        ),
        models.SkillInvocation(plugin="lup", skill="init"),
        models.TextPart(text=r"""` and `"""),
        models.SkillInvocation(plugin="lup", skill="install"),
        models.TextPart(
            text=r"""`) wires the per-project name.

"""
        ),
        *permission_hooks(CLAUDE_POLICY_SCOPE),
        models.TextPart(
            text=r"""## Settings & Configuration

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

"""
        ),
        *SELF_IMPROVEMENT_THROUGH_END,
    ]
)
