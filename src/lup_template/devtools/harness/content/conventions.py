"""Convention text that is portable, held once and rendered by every flavor.

This repository's guidance and the downstream template used to restate the
same conventions in near-identical prose, and a skill instructed an editor to
"mirror relevant changes" between them by hand. That is the shape
``docs/self-improvement.md`` rejects — a prompt rule coexisting peacefully
with the failure it warns about — and the drift it produced was visible: em
dashes in one copy and double hyphens in the other, a bullet present in one
and missing from the other, for text that was supposed to be the same text.

What lives here is what both readers need identically. Anything true only of
this repository stays in ``guidance.py`` as an addition after the shared
part, never as a restatement of it — an addition cannot drift from what it
adds to.
"""

import lup.harness.models as models

MERGE_CONFLICT_RESOLUTION: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Merge Conflict Resolution

**Never silently drop code during conflict resolution.** The bias is toward inclusion — keeping both sides is always safer than losing features. A rename on one side must not swallow an addition on the other.

Before completing any merge, **audit for deletions**: compare the result against both parents and verify that every removed function, parameter, or command was intentionally removed, not lost as a side effect of choosing one conflict side.

Use `"""
    ),
    models.SkillInvocation(plugin="lup", skill="merge"),
    models.TextPart(
        text=r"""` (with no argument) for guided conflict resolution. See the command for the full decision tree.

"""
    ),
]

COMMIT_GUIDELINES: list[models.PromptPart] = [
    models.TextPart(
        text=r"""### Commit Guidelines

- **Commit before responding** — Don't accumulate changes across responses
- **Commit early, commit often** — Frequent commits provide checkpoints
- **Keep commits atomic** — If you need "and" in your message, it should be two commits
- **History will be rebased** — Don't worry about perfect messages during development
- **Meaningful final commits** — After rebasing, each commit should tell what changed and why

**Format:** `type(scope): description`

"""
    ),
]
