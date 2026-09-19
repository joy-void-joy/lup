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
