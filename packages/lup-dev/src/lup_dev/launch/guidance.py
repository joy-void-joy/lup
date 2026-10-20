"""A session's guidance: the modules' sections rendered into one document.

Each selected module's `guidance` part names its sections, in module order as the
declaration resolves them (`docs/declaration.md`, *What a launch reads*). Each
section's text is read from its file in the project, at the commit the operator
approved as its declaration is, or from the Python package shipping it, the
installed `lup_dev` for lup's own, and rendered with Jinja (`docs/launch.md`,
*Guidance*):
- a section names the project's commands through its runner, `{{ run("lup-dev
  check") }}`, which the runner spells, so no section spells uv;
- a module's section names where its own data is mounted in the room,
  `{{ data("transcripts") }}`, and asks whether it's mounted, `{% if
  mounted("transcripts") %}`, for a module whose data a launch may lend; a
  section rendering to nothing is left out;
- a section lists lup's code rules the project runs, `{{ rules() }}`, one line
  each, its id and its steer (`steers`), from the engine's rule table, which
  the caller passes, so the list can't drift from the rules;
- a name the section doesn't have is refused, rather than rendered as nothing;
- the environment is Jinja's sandbox, since an agent can write a section's file
  and the rendering runs on the host, outside every room.

After the declared sections come lup's tools, where the session is served any
(`listed`): each by its name and its summary, compiled from the tools
themselves, saying they're found through the runtime's tool search by name. Each
runtime defers an MCP server's tools behind its tool search, and the first lup
found that agents told nothing of deferred tools concluded they didn't exist
(`docs/inbox.md`, *Found through tool search, listed in the guidance*).

After lup's tools come the other repositories named for the project's sessions
to read (`repositories`): each by its name, what it is, its path in the room,
whether it's mounted or missing on this machine, and its GitHub identity, which
lup's GitHub tools take (`docs/launch.md`, *Related repositories*).

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
from lup_dev.host.rooms import summaries
from lup_dev.layout import CheckoutLayout

if TYPE_CHECKING:
    from pathlib import Path

    from lup.tools.tool import ToolSpec
    from lup_dev.codescan.contract import Rule
    from lup_dev.declaration.kinds import Section
    from lup_dev.declaration.resolve import Resolved
    from lup_dev.launch.room import Lent, RelatedRepository

OPENING = (
    "lup is the environment this session runs in, set up by the operator for this "
    "project, and this is its guidance. Where it differs from your runtime's own "
    "instructions, it holds; where two of its sections differ, the later one holds."
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
    lines = summaries(tools)
    opening = (
        "lup serves these tools in this session. Your tool search finds each by "
        "its name, with its full description:"
    )
    return "\n".join(["## lup's tools", "", opening, "", *lines])


def steers(rules: list[Rule]) -> str:
    """Return lup's code rules as a section lists them: one line each, its id and its steer, in the table's order.

    >>> from lup_dev.codescan.contract import Examples, Rule
    >>> print(steers([
    ...     Rule(id="elif", mistake="A chain.", steer="Decide with `match`.", examples=Examples(flags=[])),
    ...     Rule(id="regex", mistake="A pattern.", steer="Read it with a parser.", examples=Examples(flags=[])),
    ... ]))
    - `elif`: Decide with `match`.
    - `regex`: Read it with a parser.
    """
    # lup: defer(issue=49, why="the list groups the rules by when each fires, at the write or at the gate, once the table gives each its timing")
    return "\n".join(f"- `{rule.id}`: {rule.steer}" for rule in rules)


def repositories(neighbours: list[RelatedRepository]) -> str:
    """Return the section listing the other repositories named for the session to read: each by its name, what it is, its path in the room, whether it's mounted, and its GitHub identity.

    >>> from pathlib import Path
    >>> from lup_dev.launch.room import RelatedRepository
    >>> print(repositories([
    ...     RelatedRepository(
    ...         name="atlas",
    ...         path=Path("/src/atlas.git"),
    ...         about="a made-up neighbour",
    ...         github="someone/atlas",
    ...         mounted=True,
    ...     ),
    ...     RelatedRepository(
    ...         name="beacon", path=Path("/src/beacon.git"), about="another made-up neighbour",
    ...         github=None, mounted=False,
    ...     ),
    ... ]))
    ## Other repositories
    <BLANKLINE>
    These other repositories are named for you to read. Each one mounted is read-only, at the path given, as it is on the host: read its files, and its history with `git log` and `git show`. Where one is on GitHub, lup's `read_issue` and `find_issues` read its issues and pull requests, given its `owner/name` as `repository`.
    <BLANKLINE>
    - `atlas`, a made-up neighbour. At `/src/atlas.git`, mounted. On GitHub as `someone/atlas`.
    - `beacon`, another made-up neighbour. At `/src/beacon.git`, missing: it isn't on this machine, so it isn't mounted.
    """

    def entry(each: RelatedRepository) -> str:
        state = (
            "mounted"
            if each.mounted
            else "missing: it isn't on this machine, so it isn't mounted"
        )
        github = [] if each.github is None else [f"On GitHub as `{each.github}`."]
        said = [f"- `{each.name}`, {each.about}.", f"At `{each.path}`, {state}."]
        return " ".join([*said, *github])

    opening = (
        "These other repositories are named for you to read. Each one mounted is "
        "read-only, at the path given, as it is on the host: read its files, and its "
        "history with `git log` and `git show`. Where one is on GitHub, lup's "
        "`read_issue` and `find_issues` read its issues and pull requests, given its "
        "`owner/name` as `repository`."
    )
    lines = [entry(each) for each in neighbours]
    return "\n".join(["## Other repositories", "", opening, "", *lines])


def lent_here(lent: list[Lent]) -> str:
    """Return the section listing the directories lent to this launch: each by its path, whether the room may write it, whether it's a repository, and its description where it has one.

    >>> from pathlib import Path
    >>> from lup_dev.launch.room import Lent
    >>> print(lent_here([
    ...     Lent(path=Path("/src/atlas"), read_only=True, repository=True, about="A made-up library."),
    ...     Lent(path=Path("/data/scratch"), read_only=False, repository=False),
    ... ]))
    ## Lent to this launch
    <BLANKLINE>
    The operator lent these directories to this launch alone, each at its path, as it is on the host.
    <BLANKLINE>
    - `/src/atlas`, read-only, in a git repository, whose history `git log` and `git show` read. A made-up library.
    - `/data/scratch`, which you may write.
    """

    def entry(each: Lent) -> str:
        access = "read-only" if each.read_only else "which you may write"
        said = [f"`{each.path}`", access]
        if each.repository:
            said.append(
                "in a git repository, whose history `git log` and `git show` read"
            )
        about = "" if each.about is None else f" {each.about}"
        return f"- {', '.join(said)}.{about}"

    opening = (
        "The operator lent these directories to this launch alone, each at its "
        "path, as it is on the host."
    )
    return "\n".join(
        ["## Lent to this launch", "", opening, "", *(entry(each) for each in lent)]
    )


def render(
    resolved: Resolved,
    project: Path,
    worktree: Path,
    tools: list[ToolSpec],
    neighbours: list[RelatedRepository],
    *,
    shared: dict[str, Path] | None = None,
    lent: list[Lent] | None = None,
    rules: list[Rule] | None = None,
) -> str:
    """Render the session's guidance from `resolved`'s sections, the tools it's served, and the other repositories it may read.

    The project's own sections are read in `project`, a directory holding the
    project's files at the commit its declaration was read from, and the
    person's own in `worktree`, the worktree launched. The sections go in the
    order the declaration gives them, then lup's `tools` (`listed`), then the
    other repositories named for it, as the launch found them
    (`repositories`), then the directories lent to this launch
    (`lent_here`), then the person's own, where there's one. Raise
    `GuidanceError` naming the section that can't be read, or doesn't render.
    `shared` is where each module whose data the room mounts has it, by the
    module's name: every room's, and those this launch lends. `rules` are lup's
    code rules the project runs, which a section lists with `rules()`; where
    none are given, a section listing them is refused.
    """
    runner = resolved.runner
    mounted = shared or {}

    def data(module: str) -> str:
        """Name where module `module`'s own data is mounted in the room."""
        place = mounted.get(module)
        if place is None:
            known = ", ".join(sorted(mounted)) or "none"
            message = (
                f"`data({module!r})` names no module whose data the room mounts; "
                f"it mounts {known}'s"
            )
            raise TemplateRuntimeError(message)
        return str(place)

    def run(command: str) -> str:
        """Spell `command` as the project's runner runs it."""
        try:
            tool = shlex.split(command)
        except ValueError as error:
            message = f"`run({command!r})` isn't a command line: {error}"
            raise TemplateRuntimeError(message) from error
        return shlex.join(runner.command(tool))

    def lent_data(module: str) -> bool:
        """Say whether the room mounts module `module`'s own data, every room or this launch lending it."""
        return module in mounted

    def ruled() -> str:
        """List lup's code rules the project runs, one line each: its id and its steer."""
        if rules is None:
            message = (
                "`rules()` has no rules to list: none were given to this rendering"
            )
            raise TemplateRuntimeError(message)
        return steers(rules)

    sandbox = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)

    def rendered(where: str, text: str) -> str:
        try:
            return (
                sandbox.from_string(text)
                .render(run=run, data=data, mounted=lent_data, rules=ruled)
                .strip()
            )
        except TemplateError as error:
            message = (
                f"Guidance: {where} doesn't render: {error}. A section can use "
                '`run("<command>")`, which spells a command as the project runs it; '
                '`data("<module>")`, where a module\'s data is mounted in the room; '
                '`mounted("<module>")`, whether it is; and `rules()`, which lists '
                "lup's code rules the project runs, each with its steer"
            )
            raise GuidanceError(message) from error

    declared = [
        text
        for section in resolved.guidance
        if (text := rendered(described(section), read(section, project)))
    ]
    served = [listed(tools)] if tools else []
    beside = [repositories(neighbours)] if neighbours else []
    lending = [lent_here(lent)] if lent else []
    local = CheckoutLayout(root=worktree).local_guidance
    own = (
        [rendered(f"the person's own section (`{local}`)", local.read_text())]
        if local.is_file()
        else []
    )
    return "\n\n".join([OPENING, *declared, *served, *beside, *lending, *own]) + "\n"
