"""Rendering a session's guidance: every section its project's modules serve, in the declaration's order, each called on its part as `Running` made it.

A section is called on its part where it runs, handed the session it's told to
where it takes `by`. It's filled from its module's settings, so it calls no
service, and a section on a part holding something is refused: that part runs
apart from the project's code, from approved code, and what it holds has no
business in what every session is told. A template's values are written in its
text as an f-string writes them (`README.md` in `lup/told/`, *Rendering*).
"""

from string.templatelib import Interpolation, Template
from typing import TYPE_CHECKING
lazy from pathlib import Path

from lup.environment.declaration import load, resolve
from lup.told.door import GuidanceDoor
from lup.told.guidance import Guidance, GuidanceError, Section

if TYPE_CHECKING:
    from lup.doors.parties import Agent
    from lup.environment.doors import Entry, Running


async def rendered_at(root: Path, declaration: Path, by: Agent) -> Guidance:
    """Render what the session `by` is told at its start, of the declaration at `declaration`, relative to `root`: only the parts serving a section made, and stopped once it's rendered.

    Raise `ProjectError` where the declaration doesn't load or resolve, and
    `GuidanceError` where a section doesn't render.
    """
    resolved = resolve(load(root / declaration))
    serving = list(
        dict.fromkeys(
            entry.serves.named() for entry in resolved.doors.through(GuidanceDoor)
        )
    )
    running = await resolved.doors.started("", {}, only=serving)
    try:
        return await rendered(running, by)
    finally:
        await running.stopped()


async def rendered(running: Running, by: Agent) -> Guidance:
    """Render the guidance the session `by` is told at its start: each section the modules `running` made serve, in their modules' order, then their parts', then their own.

    A section for other sessions than `by` (its `by` naming a party `by` isn't
    one of), or rendering to nothing, is left out. Raise `GuidanceError`,
    naming its module, where a section can't be rendered here, or fails as it's
    rendered (`section`).
    """
    told = [
        Section(
            module=entry.serves.module.name,
            method=entry.method.taken.qualified,
            text=text,
        )
        for entry in running.doors.through(GuidanceDoor)
        if entry.method.admits(by)
        and (text := (await section(running, entry, by)).strip())
    ]
    return Guidance(sections=told)


async def section(running: Running, entry: Entry, by: Agent) -> str:
    """Render the section behind `entry` for the session `by`, on its part as `running` made it, as Markdown.

    Raise `GuidanceError`, naming its module, where its part holds something
    and so runs apart, where its part isn't made here, or where it raises or
    answers other than a template or words.
    """
    module = entry.serves.module.name
    named = f"the section `{entry.method.taken.qualified}` of `{module}`"
    if entry.serves.part.holds().anything():
        message = (
            f"{named} is on a part holding a secret, the machine, or what only "
            "approved code may, which runs apart: a section is filled from its "
            "module's settings, on a part holding nothing"
        )
        raise GuidanceError(message, about=[module])
    instance = running.instance(entry)
    if instance is None:
        message = f"{named} is on a part made elsewhere, not where it's rendered"
        raise GuidanceError(message, about=[module])
    function = entry.method.function
    try:
        called = (
            function(instance)
            if entry.method.taken.by is None
            else function(instance, by=by)
        )
        told = called if isinstance(called, bool) else await called
    except Exception as failed:
        message = f"{named} doesn't render: {type(failed).__name__}: {failed}"
        raise GuidanceError(message, about=[module]) from failed
    if not isinstance(told, str | Template):
        message = (
            f"{named} answered a `{type(told).__name__}`, where it answers a "
            'template (`t"…"`) or words'
        )
        raise GuidanceError(message, about=[module])
    return written(told)


def written(told: str | Template) -> str:
    """Return a section's Markdown: words as they are, a template's text with each of its values in place.

    >>> runner = "uv run"
    >>> written(t"Run `{runner}`; {3:02d} steps, {runner!r}.")
    "Run `uv run`; 03 steps, 'uv run'."
    """
    if isinstance(told, str):
        return told
    return "".join(part if isinstance(part, str) else formatted(part) for part in told)


# lup: defer(issue=5, why="a typed value each runtime spells its own way, such as a skill, is spelled here by the runtimes' adapter for the session's runtime, and the gate renders once per runtime, once sessions are started on one")
def formatted[V](value: Interpolation[V]) -> str:
    """Return one of a template's values as an f-string writes it: converted as it says (`!r`, `!s`, `!a`), then formatted to its spec."""
    match value.conversion:
        case "r":
            shown = repr(value.value)
        case "s":
            shown = str(value.value)
        case "a":
            shown = ascii(value.value)
        case None:
            shown = value.value
    return format(shown, value.format_spec)
