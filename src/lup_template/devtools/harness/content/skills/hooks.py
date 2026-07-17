"""Canonical declaration for the hooks skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.hooks",
    name="hooks",
    description="Inspect and modify the canonical semantic permission policy",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=["Read", "Edit", "Grep", "Glob", "AskUserQuestion", "Bash"],
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text=r"""# Hooks: Semantic Permission Policy

Update the canonical policy and regenerate its hermetic native dispatchers.

## User's Request

"""
            ),
            models.ArgumentsRef(),
            models.TextPart(
                text=r"""

## Sources of truth

- `packages/lup/src/lup/policy/` owns semantic fetch, shell, edit, aggregation,
  and native-boundary contracts.
- `packages/lup/src/lup/codescan/antipatterns.py` owns anti-pattern rules.
- `src/lup_template/devtools/harness/catalog.py` owns application URL scopes,
  protected roots, policy IDs, and other composition inputs.
- `tests/unit/test_semantic_policy.py` is the shared canonical/bundled fixture
  suite.

Files beneath `.claude/plugins/lup/hooks/` and `.codex/plugins/lup/hooks/` are
generated artifacts. Never edit them as the source of a policy change.

## Workflow

1. Classify the request as a semantic rule, an application policy input, or a
   native decoding/rendering capability.
2. Read the relevant canonical source and its cross-native fixtures.
3. Show the current behavior and propose the smallest semantic change. Use
   AskUserQuestion before changing policy behavior when the request did not
   already specify the decision.
4. Edit the canonical source and add fixtures for safe, denied, approval, and
   malformed variants as applicable.
5. Run `uv run pytest -q tests/unit/test_semantic_policy.py`.
6. Run `uv run lup-devtools harness generate all` and
   `uv run lup-devtools harness check all`.

Denial must win over approval across batches and shell segments. Unsupported
native approval effects fail closed. Resolve-editor autonomy may relax only the
declared protected/large edit cases; temporary paths, marker changes, and
anti-pattern violations keep their guardrails.

With no arguments, summarize the canonical URL scopes, shell classifications,
protected edit rules, threshold, resolver-editor exceptions, and each native
boundary's approval behavior, then ask what should change.
"""
            ),
        ]
    ),
)
