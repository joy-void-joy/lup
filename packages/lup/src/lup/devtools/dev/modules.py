"""What this project takes of the module roster, and what each module costs it.

The roster is the one selection with no surface of its own. Retired sub-apps
show up in `--help` by their absence, retired rules in `docs/rules.md`, and a
declined skill in the plugin tree — but a module is five of those at once, so
"what did this project actually decide?" is answerable only by reading the
catalog and holding the defaults in your head. That is the question this
answers, and the reason it exists rather than the table being nice to have: a
default is advice, and a project meets each piece of advice exactly once.

The cost column is guidance bytes, because that is the only cost a module
imposes whether or not its subject ever comes up. Skills, pages and commands
are paid for when they are used; a paragraph in the always-loaded document is
paid for in every session, against a ceiling that truncates rather than fails.

What a row counts is the module as this project resolves it — the sections it
retired gone, the ones it rewrote at their rewritten length, its own additions
in — because that is what the document is assembled from. The module as it
declares itself answers the other question the table asks, what the roster
offers a project that turns it on and says nothing more.
"""

import typer
from pydantic import BaseModel

from lup.harness.models import GUIDANCE_BUDGET, document_byte_size
from lup.harness.modules import Module, ModuleSelection


class ModuleRow(BaseModel, frozen=True):
    """One module as this project has it, and what it is costing."""

    identity: str
    title: str
    summary: str

    offered: bool
    """Whether an adopter is asked about it, or it is the scaffold's alone."""

    taken: bool
    loads: bool
    """The two answers a project gives separately, reported separately."""

    default_on: bool
    """What it would have been had this project said nothing."""

    requires: list[str] = []

    guidance_resolved: int = 0
    """The bytes of prose this project's version of the module holds.

    Whether they reach the document is :attr:`loads`; a module kept quiet
    still has prose, and a project turning it on carries exactly this.
    """

    guidance_declared: int = 0
    """The bytes of the module's own sections, before this project changed any."""

    skills: int = 0
    agents: int = 0
    pages: int = 0
    """What this project's version of the module ships, counted."""

    subapps: list[str] = []
    tool_groups: list[str] = []

    def standing(self) -> str:
        """Taken or declined, and whether that agreed with the default.

        A decision that matches the default is worth marking as one: it is the
        answer nobody had to give, and so the answer most likely to have been
        given by nobody.
        """
        state = "taken" if self.taken else "declined"
        return state if self.taken == self.default_on else f"{state} (against default)"

    def prose(self) -> str:
        """The prose column: this project's bytes, and the module's own where they differ.

        Both where the project changed the module's prose, because the two
        totals under the table read different ones — what the document carries
        is summed from this project's version, what the roster offers from the
        module's own — and a row showing one of them leaves the distance between
        the totals unaccounted for, which is the decision a reader came to see.
        """
        column = f"{self.guidance_resolved:5d}b" if self.guidance_resolved else "     —"
        quiet = "" if self.loads or not self.guidance_resolved else "  (not loaded)"
        match self.guidance_declared:
            case declared if declared == self.guidance_resolved:
                own = ""
            case 0:
                own = "  (module declares none)"
            case declared:
                own = f"  (module declares {declared}b)"
        return f"{column}{quiet}{own}"

    def surfaces(self) -> str:
        """What it contributes, counted, with the empty ones left out.

        A module is often two surfaces of five, and printing three zeroes to
        say so buries the two that are there.
        """
        counted = [
            f"{self.skills} skill(s)" if self.skills else "",
            f"{self.agents} agent(s)" if self.agents else "",
            f"{self.pages} page(s)" if self.pages else "",
            f"`{'`, `'.join(self.subapps)}`" if self.subapps else "",
            f"{', '.join(self.tool_groups)} tools" if self.tool_groups else "",
        ]
        return ", ".join(entry for entry in counted if entry) or "policy only"


def rows(modules: list[Module], selection: ModuleSelection) -> list[ModuleRow]:
    """Every module in the roster, in the order a composition lays it out.

    ``modules`` are the roster as each module declares itself, every one of
    them — declined ones included, since the table is where a project meets
    what it declined. Each is resolved through ``selection`` here, the way the
    composition resolves the modules it takes, so a row counts what this
    project would ship and not what the library wrote.
    """

    def weight(module: Module) -> int:
        """What a module's prose costs a session, weighed as the document is."""
        return sum(document_byte_size(section.text) for section in module.guidance)

    return [
        ModuleRow(
            identity=module.spec.id,
            title=module.spec.title,
            summary=module.spec.summary,
            offered=not module.spec.scaffold_only,
            taken=selection.takes(module.spec),
            loads=selection.loads(module.spec),
            default_on=module.spec.default_on,
            requires=module.spec.requires,
            guidance_resolved=weight(resolved),
            guidance_declared=weight(module),
            skills=len(resolved.content.skills),
            agents=len(resolved.content.agents),
            pages=len(resolved.documents),
            subapps=module.spec.subapps,
            tool_groups=module.spec.tool_groups,
        )
        for module in modules
        for resolved in [selection.resolved(module)]
    ]


def report(modules: list[Module], selection: ModuleSelection, verbose: bool) -> None:
    """Print the roster, what this project settled, and what its prose costs.

    Two totals rather than one, because the interesting number is not what
    this tree carries but the distance between that and what the roster could
    carry: a module kept quiet costs nothing here and everything to the
    project that turns it on, and that project inherits this roster.

    They are summed from different figures. What the document carries is this
    project's version of each module that loads — so a section it retired
    costs nothing and one it added costs what it weighs — and what the roster
    offers is every module's own sections, which is what a project taking the
    whole roster without a word about its prose would carry.
    """
    listed = rows(modules, selection)
    carried = sum(row.guidance_resolved for row in listed if row.loads)
    offered = sum(row.guidance_declared for row in listed)
    widest = max((len(row.identity) for row in listed), default=0)
    for row in listed:
        scope = "" if row.offered else "  (scaffold only)"
        typer.echo(f"{row.identity:{widest}}  {row.standing():<24}{row.prose()}{scope}")
        if verbose:
            typer.echo(f"{'':{widest}}  {row.summary}")
            typer.echo(f"{'':{widest}}  {row.surfaces()}")
            if row.requires:
                typer.echo(f"{'':{widest}}  requires {', '.join(row.requires)}")
    typer.echo(
        f"\n{len(listed)} module(s); this document carries {carried} prose bytes "
        f"against a {GUIDANCE_BUDGET.ceiling} ceiling, and the roster's own "
        f"sections come to {offered}. `dev check` weighs the rendered document, "
        "which is heavier by the banner and the parts no section spells."
    )
