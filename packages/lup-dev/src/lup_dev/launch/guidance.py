"""A session's guidance: the modules' sections rendered into one document.

Each selected module's `guidance` part names its sections, in module order as the
declaration resolves them (`docs/declaration.md`, *What a launch reads*). Each
section's text is read from its file at the project's root, or from the Python
package shipping it, and rendered with Jinja (`docs/launch.md`, *Guidance*):
- a section names the project's commands through its runner, `{{ run("lup-dev
  check") }}`, which the runner spells, so no section spells uv;
- a name the section doesn't have is refused, rather than rendered as nothing;
- the environment is Jinja's sandbox, since an agent can write a section's file
  and the rendering runs on the host, outside every room.

The person's own section, `AGENTS.local.md` at the root, which git ignores, is
appended after every other where there's one, so it holds where they differ. The
document opens with one line saying how its sections stand to each other and to
the runtime's own instructions.
"""

import shlex
from importlib.resources import files
from typing import TYPE_CHECKING

from jinja2 import StrictUndefined, TemplateError, TemplateRuntimeError
from jinja2.sandbox import SandboxedEnvironment

from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.declaration.kinds import Section
    from lup_dev.declaration.resolve import Resolved

OPENING = (
    "This guidance adds to your runtime's own instructions and replaces none of "
    "them; where two of its sections differ, the later one holds."
)
"""The document's first line: how its sections stand to each other and to the
runtime's own instructions."""


class GuidanceError(LupDevError):
    """A section of guidance that can't be read, or doesn't render."""


def described(section: Section) -> str:
    """Name a section and where its text is, for a message.

    >>> from pathlib import Path
    >>> from lup_dev.declaration.kinds import Section
    >>> described(Section(name="lup", path=Path("AGENTS.md")))
    'the section `lup` (`AGENTS.md`)'
    >>> described(Section(name="core", package="lup_dev.x", path=Path("core.md")))
    'the section `core` (`core.md` in `lup_dev.x`)'
    """
    if section.package is None:
        return f"the section `{section.name}` (`{section.path}`)"
    return f"the section `{section.name}` (`{section.path}` in `{section.package}`)"


def read(section: Section, root: Path) -> str:
    """Read `section`'s text: from its package where it names one, else from `root`.

    Raise `GuidanceError` naming the section where its file or package isn't
    there.
    """
    try:
        if section.package is None:
            return (root / section.path).read_text()
        return files(section.package).joinpath(*section.path.parts).read_text()
    except (FileNotFoundError, ModuleNotFoundError) as error:
        message = f"Guidance: {described(section)} has no file to read"
        raise GuidanceError(message) from error


def render(resolved: Resolved, root: Path) -> str:
    """Render the session's guidance from `resolved`'s sections, read at `root`.

    The sections go in the order the declaration gives them, then the person's
    own, where `root` has one. Raise `GuidanceError` naming the section that
    can't be read, or doesn't render.
    """
    runner = resolved.runner

    def run(command: str) -> str:
        """Spell `command` as the project's runner runs it."""
        try:
            tool = shlex.split(command)
        except ValueError as error:
            message = f"`run({command!r})` isn't a command line: {error}"
            raise TemplateRuntimeError(message) from error
        return shlex.join(runner.command(tool))

    sandbox = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)

    def rendered(where: str, text: str) -> str:
        try:
            return sandbox.from_string(text).render(run=run).strip()
        except TemplateError as error:
            message = (
                f"Guidance: {where} doesn't render: {error}. A section can use "
                '`run("<command>")`, which spells a command as the project runs it'
            )
            raise GuidanceError(message) from error

    declared = [
        rendered(described(section), read(section, root))
        for section in resolved.guidance
    ]
    local = CheckoutLayout(root=root).local_guidance
    own = (
        [rendered(f"the person's own section (`{local}`)", local.read_text())]
        if local.is_file()
        else []
    )
    return "\n\n".join([OPENING, *declared, *own]) + "\n"
