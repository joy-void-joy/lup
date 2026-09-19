# lup: ignore[constant-declaration]
# The scaffold section ids are this repository's own vocabulary; the prose that
# named a hook event now lives in the passages beside this module.
# Every constant here is one block of that scaffold's prose: a project wanting
# different words composes different blocks, which is an override the
# mechanical half of the constant rule cannot see.
"""Portable downstream-template sections shared by every guidance flavor."""

import lup.harness.models as models

import lup.harness.content.conventions as conventions
from lup.tools.lsp.tools import rendered_tool_declarations

CODEINTEL_TOOL_ROSTER: list[models.PromptPart] = [
    models.ToolRoster(tools=rendered_tool_declarations())
]

SETUP_THROUGH_NAMING: list[models.PromptPart] = [
    models.Passage(module=__name__),
]

INNER_AGENT_BULLET: list[models.PromptPart] = [
    models.Passage(module=__name__, name="template_sections-2"),
]

PRINCIPLES_THROUGH_PATTERN_MENU: list[models.PromptPart] = [
    models.Passage(
        module=__name__,
        name="template_sections-3",
        values={
            "bump_skill": models.SkillInvocation(plugin="lup", skill="bump"),
            "debug_skill": models.SkillInvocation(plugin="lup", skill="debug"),
            "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
        },
    ),
]

PATTERN_MENU_TAIL_THROUGH_WORKTREE_STEP: list[models.PromptPart] = [
    models.Passage(
        module=__name__,
        name="template_sections-4",
        values={"init_skill": models.SkillInvocation(plugin="lup", skill="init")},
    ),
]

WORKFLOW_THROUGH_COMMIT_FORMAT: list[models.PromptPart] = [
    models.Passage(
        module=__name__,
        name="template_sections-5",
        values={
            "relocate": models.RelocateSession(path="the absolute path step 1 prints"),
            "rebase_skill": models.SkillInvocation(plugin="lup", skill="rebase"),
            "close_skill": models.SkillInvocation(plugin="lup", skill="close"),
        },
    ),
    *conventions.MERGE_CONFLICT_RESOLUTION.parts,
    *conventions.COMMIT_GUIDELINES.parts,
    models.Passage(module=__name__, name="template_sections-6"),
    *conventions.COMMIT_TYPES.parts,
    models.Passage(module=__name__, name="template_sections-7"),
]

DIRECTORY_STRUCTURE_THROUGH_TOOLS: list[models.PromptPart] = [
    models.Passage(
        module=__name__,
        name="template_sections-8",
        values={"resolve_skill": models.SkillInvocation(plugin="lup", skill="resolve")},
    ),
]

TOOLING_INTRO: list[models.PromptPart] = [
    models.Passage(module=__name__, name="template_sections-9"),
]

POLICY_JOIN = r"""The policy classifies every shell command against the vocabulary declared in
`devtools/harness/content/shell_vocabulary.py`, every URL scope, and every edit
in a batch. Segments join deny > ask > defer > allow, so a judged deny wins the
batch and malformed input fails conservatively. Ask is reserved for judged
risk: an unjudged command denies with a hint naming the
`# lup: escalate[decision]: <why>` marker, and that marker as a command's leading line
promotes the decision into an approval question carrying your stated reason.
Under a launcher-verified sandbox (`LUP_SANDBOX_ACTIVE`), unjudged work defers
to that boundary rather than denying."""
"""What a reader needs before a denial, which is the shape and the way out.

The rest of the lattice — how substitutions, loops, redirections and wrappers
classify, and what an edit decision weighs — is in docs/permissions.md, because
a denial names what tripped and the recovery at the moment it matters. Carrying
the whole table on every turn buys nothing a reader could not open, and this
document is the one with a byte budget.
"""

CLAUDE_POLICY_SCOPE = (
    POLICY_JOIN
    + r""" A `dangerouslyDisableSandbox` escape re-enters the deny lattice, and
the sandbox block in `.claude/settings.json` derives from the same `HookSet`
declaration. Where a command runs is a second axis a rule declares beside its
effect and cascades to the levels beneath it, so every `git` verb already runs
outside the sandbox unasked. [docs/permissions.md](docs/permissions.md) carries
the full lattice."""
)

CODEX_POLICY_SCOPE = (
    POLICY_JOIN
    + r""" Native `apply_patch` commands are decoded into complete before/after
batches for the canonical edit policy, and malformed or unsupported patches
fail closed. Codex's own sandbox and approval policy remain the outer
filesystem and network boundary. Generation also compiles every prefix-safe
shell allow into `.codex/rules/lup.rules`, which Codex uses to run matching
commands outside the sandbox without prompting, while flag- and
content-sensitive forms stay under the hook.
[docs/permissions.md](docs/permissions.md) carries the full lattice."""
)


def permission_hooks(policy_scope: str) -> list[models.PromptPart]:
    """Render the permission-hooks section around one flavor-owned scope claim.

    The canonical-policy framing is identical on both platforms; each native
    adapter supplies complete edit documents through its own decoding boundary,
    so each template passes its own scope paragraph.
    """
    return [
        models.TextPart(
            text=r"""## Permission Hooks

Permissions come from the canonical semantic policies in `lup.policy` and the
application-owned `HookSet` in `devtools/harness/catalog.py`. Harness generation
compiles one hermetic dispatcher and dependency-free runtime for each native
plugin. Do not edit generated policy files directly.

"""
        ),
        # The paragraph each platform passes in: authored there rather than
        # derived here, so it is a part of its own instead of text spliced
        # into the page around it.
        models.TextPart(text=policy_scope),
        models.TextPart(
            text=r""" Use
`"""
        ),
        models.SkillInvocation(plugin="lup", skill="hooks"),
        models.TextPart(
            text=r"""` to update canonical inputs, regenerate both plugins, and run the
shared canonical/bundled fixture suite.

"""
        ),
    ]


SELF_IMPROVEMENT_THROUGH_END: list[models.PromptPart] = [
    models.Passage(module=__name__, name="template_sections-10"),
    *conventions.FAILURE_ANALYSIS.parts,
    models.Passage(module=__name__, name="template_sections-11"),
]
