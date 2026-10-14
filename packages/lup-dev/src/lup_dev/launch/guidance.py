"""A session's guidance: the modules' sections rendered into one document.

Each selected module's `guidance` part names its sections, in module order as the
declaration resolves them (`docs/declaration.md`, *What a launch reads*). Each
section's text is read from its file in the project, at the commit the operator
approved as its declaration is, or from the Python package shipping it, the
installed `lup_dev` for lup's own, and rendered with Jinja (`docs/launch.md`,
*Guidance*):
- a section names the project's commands through its runner, `{{ run("lup-dev
  check") }}`, which the runner spells, so no section spells uv;
- a name the section doesn't have is refused, rather than rendered as nothing;
- the environment is Jinja's sandbox, since an agent can write a section's file
  and the rendering runs on the host, outside every room.

After the declared sections come lup's tools, where the session is served any
(`listed`): each by its name and its summary, compiled from the tools
themselves, saying they're found through the runtime's tool search by name. Each
runtime defers an MCP server's tools behind its tool search, and the first lup
found that agents told nothing of deferred tools concluded they didn't exist
(`docs/host-tools.md`, *Found through tool search, listed in the guidance*).

The person's own section, `AGENTS.local.md` at the root of the worktree launched,
which git ignores, is appended after every other where there's one, so it holds
where they differ. The
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

    from lup.tools.tool import ToolSpec
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


def listed(tools: list[ToolSpec]) -> str:
    """Return the section listing lup's tools, each by its name and its summary.

    >>> from lup.tools.speaking import note
    >>> print(listed([note.spec()]))
    ## lup's tools
    <BLANKLINE>
    lup serves these tools in this session. Your tool search finds each by its name, with its full description:
    <BLANKLINE>
    - `note`: Attach a remark to your answer, and carry on.
    """
    lines = [f"- `{tool.name}`: {tool.summary}" for tool in tools]
    opening = (
        "lup serves these tools in this session. Your tool search finds each by "
        "its name, with its full description:"
    )
    return "\n".join(["## lup's tools", "", opening, "", *lines])


def render(
    resolved: Resolved, project: Path, worktree: Path, tools: list[ToolSpec]
) -> str:
    """Render the session's guidance from `resolved`'s sections, and the tools it's served.

    The project's own sections are read in `project`, a directory holding the
    project's files at the commit its declaration was read from, and the
    person's own in `worktree`, the worktree launched. The sections go in the
    order the declaration gives them, then lup's `tools` (`listed`), then the
    person's own, where there's one. Raise `GuidanceError` naming the section
    that can't be read, or doesn't render.
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
        rendered(described(section), read(section, project))
        for section in resolved.guidance
    ]
    served = [listed(tools)] if tools else []
    local = CheckoutLayout(root=worktree).local_guidance
    own = (
        [rendered(f"the person's own section (`{local}`)", local.read_text())]
        if local.is_file()
        else []
    )
    return "\n\n".join([OPENING, *declared, *served, *own]) + "\n"
