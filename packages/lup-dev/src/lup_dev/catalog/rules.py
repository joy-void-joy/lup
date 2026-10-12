"""The rules of lup's table that lup's default leaves out, each with its reason.

`CodeRules`' own rules are every rule of the table but these
(`lup_dev.declaration.modules.code_rules`, `docs/declaration.md`, *Selecting
them*), so a rule a later release adds runs unless it's listed here. A project
that wants one adds it back with `Rules().add(…)`.
"""

from lup.types import Model


class LeftOut(Model):
    """A rule of lup's table that its default doesn't run, and why."""

    rule: str
    """The rule's id, as `lup-dev rules list` names it."""
    why: str
    """Why it isn't in every project's default, for each to drop."""


class DefaultRules(Model):
    """What lup's default selection of its rules leaves out of the table."""

    left_out: list[LeftOut] = [
        LeftOut(
            rule="runtime-mention",
            why=(
                "lup's own architecture, a runtime named only in its adapter: in a "
                "project choosing its runtime by a setting, it fires on every choice"
            ),
        ),
    ]
