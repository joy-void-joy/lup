"""Canonical declaration for the fb-implement skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.fb-implement",
    name="fb-implement",
    description="Implement prioritized changes from feedback loop analysis",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv run lup:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "WebSearch",
        "WebFetch",
    ],
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text=r"""# Implement: Make Changes

Implement changes identified during investigation, analysis, and reflection.

## Entry Gate

Present the prioritized change list with its Bitter Lesson classification, then """
            ),
            models.RequestApproval(
                action="implementing any of the changes",
                reason="the list decides what the next session's work will be",
            ),
            models.TextPart(
                text=r"""

**Bitter Lesson classification:**
- **Tool/capability** (preferred): Build or fix a tool, add a data source, improve automation
- **Principle** (acceptable): Add a general principle to prompts that helps across many cases
- **Rule/patch** (avoid): Task-type-specific rules, numeric adjustments, conditional exceptions

## Priority Order

### P0: Prompt health

If patches have accumulated (>3 since last rewrite):
- Study the 3 best traces — what did the agent do right?
- Study the 3 worst traces — where did the prompt mislead?
- Read the full prompt
- Rewrite the affected section from scratch (monolithic, no addendums)

### P1: Fix failing tools

From tool health analysis. Fix the root cause, not the symptom.

### P2: Build requested tools

From capability gap analysis. Present the gap, the proposed approach, and the alternatives, then """
            ),
            models.AskUser(question="which approach to build, if any"),
            models.TextPart(
                text=r"""

### P3: Improve tool descriptions

Before changing prompts, check if the issue is a tool description problem:
- Agent using the wrong tool? → Clarify the "when" in the description
- Agent not using a tool at all? → Add stronger "when to use" triggers
- Agent misinterpreting results? → Document the return format

### P4: Improve subagents

From workflow assessments. Evaluate value vs cost.

### P5: Simplify prompts

Remove prescriptive rules. Add general principles. Don't add:
- Specific rules for task types
- Numeric adjustments ("add 5% for...")
- Patches for observed patterns
- Conditional exceptions

## After Implementation

1. Version bump: `"""
            ),
            models.SkillInvocation(plugin="lup", skill="bump"),
            models.TextPart(
                text=r"""`
2. Commit changes
3. Verify: `git diff --stat` confirms each change
4. Close the loop over the sessions this pass read:

   ```bash
   uv run lup-devtools feedback mark <session-id> ...
   uv run lup-devtools feedback commit
   ```

   Marking is what makes `feedback unanalyzed` stop returning them. Skip it
   and the next pass re-reads the same sessions, re-finds the same gaps, and
   spends its budget confirming what this one already fixed.
5. Record what happened to each change, in the place that will surface it
   again:
   - **Committed** — in git and verified; it needs no note, the commit is
     the record.
   - **Proposed** — discussed and not implemented. If it belongs to a site
     in this code, it is a `# lup:` note there.
   - **Deferred** — deliberately parked. That is a `# lup: defer: <why>`
     note at the site it concerns, which `dev check` keeps visible until
     somebody wakes it. Never a line in an analysis document: a finding
     parked in a file no workflow reads is a finding delegated to nobody,
     which is the failure this loop exists to catch rather than commit.

## Queue Next Evaluation

End the session by proposing sessions that test the improvements:

```bash
# Run evaluation sessions
uv run lup loop "task1" "task2" "task3"
```

Choose sessions that are diverse in task type, exercise recently fixed or new tools, and include edge cases where the agent previously struggled.
"""
            ),
        ]
    ),
)
