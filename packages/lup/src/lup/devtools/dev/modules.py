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
"""

import typer
from pydantic import BaseModel

from lup.harness.models import GUIDANCE_BYTE_BUDGET, document_byte_size
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
    guidance_used: int = 0
    skills: int = 0
    agents: int = 0
    pages: int = 0
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
    """Every module in the roster, in the order a composition lays it out."""
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
            guidance_used=sum(
                document_byte_size(section.text) for section in module.guidance
            ),
            skills=len(module.content.skills),
            agents=len(module.content.agents),
            pages=len(module.documents),
            subapps=module.spec.subapps,
            tool_groups=module.spec.tool_groups,
        )
        for module in modules
    ]


def report(modules: list[Module], selection: ModuleSelection, verbose: bool) -> None:
    """Print the roster, what this project settled, and what its prose costs.

    Two totals rather than one, because the interesting number is not what
    this tree carries but the distance between that and what the roster could
    carry: a module kept quiet costs nothing here and everything to the
    project that turns it on, and that project inherits this roster.
    """
    listed = rows(modules, selection)
    loaded = sum(row.guidance_used for row in listed if row.loads)
    offered = sum(row.guidance_used for row in listed)
    widest = max((len(row.identity) for row in listed), default=0)
    for row in listed:
        prose = f"{row.guidance_used:5d}b" if row.guidance_used else "     —"
        quiet = "" if row.loads or not row.guidance_used else "  (not loaded)"
        scope = "" if row.offered else "  (scaffold only)"
        typer.echo(
            f"{row.identity:{widest}}  {row.standing():<24}{prose}{quiet}{scope}"
        )
        if verbose:
            typer.echo(f"{'':{widest}}  {row.summary}")
            typer.echo(f"{'':{widest}}  {row.surfaces()}")
            if row.requires:
                typer.echo(f"{'':{widest}}  requires {', '.join(row.requires)}")
    typer.echo(
        f"\n{len(listed)} module(s); this document carries {loaded} of the "
        f"{offered} prose bytes the roster offers, against a {GUIDANCE_BYTE_BUDGET} "
        "ceiling. `dev check` weighs the rendered document, which is heavier by "
        "the banner and the parts no section spells."
    )
