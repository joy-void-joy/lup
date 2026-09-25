"""The operator's persistent browser review surface, independent of containment."""

from lup.harness.models import GuidanceSection, TextPart
from lup.harness.content.docs import review_inbox
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import REVIEW_INBOX
from lup.harness.modules import Module, ModuleSelection
from lup.policy.shell_rules import (
    RunnerTargetRule,
    ShellCommandRule,
    ShellSubcommandRule,
)
from lup.seams import Selection


def module() -> Module:
    """The browser inbox's guidance and reference as one optional subject."""
    return Module(
        spec=REVIEW_INBOX,
        guidance=[
            GuidanceSection(
                id="review-inbox",
                chapter="tooling",
                parts=[
                    TextPart(
                        text=(
                            "## Review Inbox\n\n"
                            "Native harness launches keep the operator's browser review "
                            "inbox available. `dev questions status` reports its state; "
                            "the operator opens it with `dev questions open`. "
                            "`docs/review-inbox.md` describes service ownership and decisions.\n\n"
                        )
                    )
                ],
            )
        ],
        documents=[
            page("review_inbox", "review-inbox.md", lambda _: review_inbox.DOCUMENT)
        ],
    )


def inbox_subcommands(rules: list[ShellSubcommandRule]) -> list[ShellSubcommandRule]:
    """Join optional operations to their existing command groups."""
    from lup.policy.vocabulary import review_inbox_rules

    additions = {rule.name: rule for rule in review_inbox_rules()}
    return [
        rule.model_copy(
            update={"operations": [*rule.operations, *additions[rule.name].operations]}
        )
        if rule.name in additions
        else rule
        for rule in rules
    ] + [
        rule
        for name, rule in additions.items()
        if name not in {row.name for row in rules}
    ]


def runner_targets(
    rules: list[RunnerTargetRule], selection: ModuleSelection
) -> list[RunnerTargetRule]:
    """Add operator authority only when the browser module is taken."""
    if not selection.takes(REVIEW_INBOX):
        return rules
    return [
        rule.model_copy(update={"subcommands": inbox_subcommands(rule.subcommands)})
        if rule.name == "lup-devtools"
        else rule
        for rule in rules
    ]


def shell_rules(
    rules: Selection[ShellCommandRule], selection: ModuleSelection
) -> Selection[ShellCommandRule]:
    """Carry the same authority through the direct console-script spelling."""
    if not selection.takes(REVIEW_INBOX):
        return rules
    return rules.model_copy(
        update={
            "overrides": [
                rule.model_copy(
                    update={"subcommands": inbox_subcommands(rule.subcommands)}
                )
                if rule.name == "lup-devtools"
                else rule
                for rule in rules.overrides
            ]
        }
    )
