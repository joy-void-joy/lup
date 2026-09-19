# Meta: Harness Structure Review & Improvement

You are reviewing the generated harness trees and brainstorming improvements with the user.

## User's Direction

{{ arguments }}

## Your Task

Based on the user's input above, explore the relevant sources and brainstorm solutions. Almost every file in a harness tree is a generated artifact — read it for the rendered result, but make every change at its source:

| Artifact | Source |
| --- | --- |
| {{ guidance_file_path }} | `harness/content/guidance.py` |
| {{ skills_path }} | `harness/content/skills/*.py` |
| {{ agents_path }} | `harness/content/agents/*.py` |
| {{ hooks_path }} | the canonical policy in `lup.policy` |
| {{ project_settings_path }} | `harness/content/settings.py` and the adapter rendering each tree — the two are not parity, so read both before assuming a setting exists on either side |
| {{ guidance_template_path }} | `harness/content/template_sections.py` plus each flavor module |

Content paths above are relative to {{ project_directory }}. Every tree carries its own {{ ownership_manifest_path }} recording which artifacts generation owns — consult the one for the tree you are changing whenever a path's source is not obvious.

Read the relevant sources based on what the user is asking about, then propose specific changes or additions and {{ approval }} Regenerate with `uv run lup-devtools harness generate all` after any accepted change.

## Rendered layout

Each tree lays the same declarations out its own way, and `docs/platform-differentiation.md` maps every intended difference between them. Read that rather than re-deriving a tree from memory: the table above is the mapping you need to make a change, and the layout only tells you where the result landed.

**Note:** Python CLI tooling (API inspection, trace analysis, feedback collection, worktree management, etc.) lives in {{ devtools_directory }} and is exposed as the `lup-devtools` CLI entry point. See the lup-devtools section in the guidance.

### When to Add to the Plugin

- **Skills**: Reusable workflows invoked by their qualified name, e.g. `{{ skill_pattern }}`
- **Hooks**: Permission rules in the canonical policy — auto-allow, deny, or quality gates
- **Agents**: Subagent definitions for specialized tasks
- **Devtools**: Python CLI tools go in {{ devtools_directory }} (exposed as `lup-devtools`), not in the plugin

<!-- passage: first-principles -->

## First Principles Design

When considering changes, ask:

1. **Bitter Lesson Check**: Does this add a capability, or just a rule?
   - Prefer tools and capabilities over prompt constraints
   - Avoid pattern-matching patches

2. **Pipeline Diagnosis**: If fixing a failure, did you trace it?
   - What data did the agent have? What was missing?
   - Where in the workflow did the wrong decision enter?
   - Is the fix structural (new tool, better data, restructured step) or just a prompt patch?

3. **Generality Check**: Would this help if the domain changed?
   - General principles > specific patches
   - If it only works for one scenario, it's probably over-fitted

4. **Meta Level Check**: Are we changing the right layer?
   - Object level = the agent's behavior
   - Meta level = how the agent tracks itself
   - Meta-meta level = the feedback loop infrastructure

## Command Evolution

**After every command invocation**, reflect on how it was actually used:

1. **Compare intent vs usage**: Did the user use the command as documented, or did they adapt it?
2. **Notice patterns**: If the user provides documentation, links, or redirects the command's focus, that's a signal the command should evolve.
3. **Proactively propose updates**: When you notice the command being used differently than documented:
   - Propose updating the skill, as a question the user answers
   - Include the specific usage pattern you observed
   - Suggest concrete changes to its declaration

## Process

1. Read relevant files based on the user's direction
2. Analyze and identify potential improvements
3. Propose specific changes with rationale, and let the user choose among them
4. Implement approved changes immediately
5. **Reflect on this skill's execution** and propose updates to its own declaration if warranted
6. Continue brainstorming or summarize changes made
