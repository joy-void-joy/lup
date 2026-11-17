# Guidance

What a session is told at its start: each module's sections, written in Python behind a door, `@lup.guidance`, and rendered in the declaration's order. Its library side (`lup.told`, its door and error re-exported by `lup`, its rendered `Guidance` by `lup.testing`) is what a module's code imports; rendering is the environment's (`lup.environment.told`). The package is named apart from the door, which `lup` binds as `lup.guidance`.

```python
from string.templatelib import Template

import lup
from lup import Module, Part, Parts


class ReviewGuide(Part):
    """What a session is told of asking for a review."""

    module: Review

    @lup.guidance
    async def reviewing(self) -> Template:
        """Say how a session asks for a review."""
        return t"""## Review

Before landing, ask for a review: it reads your branch against `{self.module.base}` and comments on the diff.
"""


class Review(Module):
    """Reviewing a branch before it lands."""

    name = "review"
    base: str = "dev"
    parts: Parts = Parts.of(ReviewGuide)
```

## A section

A method behind `@lup.guidance` is async, takes nothing, or `by` alone where what it says differs by session (`by: Agent`, or a party deriving from it, never another), and answers its Markdown: a template string (`t"…"`), or `str`.
- **Written in Python, filled from typed values.** A section reads its module's settings (`self.module.…`), every layer applied, so pyright checks each name and a rename follows it, and the gate renders every section, so one that can't render fails there rather than at a session's start. Long prose stays in Python too, a function returning a `t"…"` in a file beside the module, rather than a Markdown file with placeholders, which would bring back a template language whose names nothing checks.
- **A template keeps its values apart** from its text until it's rendered: each is written as an f-string writes it. What each runtime spells its own way (a skill, a tool's name, a path in the room) becomes a typed value the runtimes' adapter spells for the session's runtime, so no section names a runtime (#5).
- **Several to a module,** in its parts' order, each part's beside the code it describes; a project dropping a part (`Parts().drop(…)`) drops its sections with it. A section answering nothing for a session, or only blank lines, is left out, as is one whose `by` names a party the session isn't.
- **On a part holding nothing.** A section is filled from its module's settings, calling no service, and one on a part holding a secret, the machine or what only approved code may is refused as it renders: that part runs apart, and what it holds has no business in what every session is told.

## Rendering

`rendered(running, by)` calls each section on its part as `Running` made it, in the declaration's order of modules, then of parts, then of methods, and answers `Guidance`: each `Section` that said something (its module, its method and its text), and `text()`, the sections joined by a blank line. A section that raises or answers something else fails with `GuidanceError`, naming its module. A started lup in the harness renders through the same code (`Started.guidance(by)`). Delivering it, at a session's start, at system level, with the runtimes' own loading of `AGENTS.md` and `CLAUDE.md` off, is #5's.

**Nothing is read from `AGENTS.md`.** A project's guidance is its modules' sections: its own, in a module of its own, rendered at each session's start and never committed. The operator's own section is a module their gitignored layer adds, rendered after the rest, so it holds where they differ.

## Room

The smallest ceiling among the runtimes lup starts sessions on is 40,000 bytes of what a session is told at its start: Codex refuses its managed instructions past 10,000 estimated tokens at 4 bytes each (`docs/field-notes.md`). Of it:
- **a project's modules,** lup's and its own, may take 30,000 (`Guidance.project`). The 10,000 left is for what its gate can't see: the operator's own section, which git ignores, and what a session's start adds, such as lup's tools by name and summary (about 2,000 to 3,000 bytes in the second lup), related repositories, lent directories and the runtime's wrapping;
- **lup's own modules** at their defaults may take 20,000 (`Guidance.shipped`), leaving a project 10,000 for its own sections: this repository's own guidance, about working on lup, is 6,500.

`Guidance.within(room)` fails past a room with `GuidanceError`, naming each module's share, the largest first.

## Promises

Over example modules (`promises.py`): a section says its module's settings for any session, one with nothing to say is left out, sections come in the declaration's order, one that can't render or sits on a part holding a secret fails naming its module, a method that can't be a section fails the declaration's load, and guidance past its room fails naming its modules. Two are over the modules a project selects:
- **lup's own modules at their defaults** render and fit in lup's share, checked at lup's gate;
- **a project's own declaration** renders and fits in a project's room. It's a promise about every project (`@lup.promise(every_project=True)`), which every project's gate checks over its own declaration (`by.project()`), so a project adding a long section learns at its gate (`lup/testing/README.md`, *Checking*).
