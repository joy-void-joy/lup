"""Fields the command line fills from where it's typed: the repository whose worktree it's typed in, and that repository's common git directory.

A model a command or a view takes types such a field `Repository` or `Common`,
and its JSON Schema carries the mark (`MARK`), which the command line reads from
the plan alone, as it reads every field (`lup.command_line.parameters`). Typed,
a `Repository` is the option `-r`, `--repository`, and a `Common` the option
named for its field; left out, each is filled from where the words are typed
(`TypedIn`), so nobody types the repository they're standing in, or where git
keeps it. The method always gets one: from the dashboard, the block offering it
gives it.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from lup.running.plan import Name
from lup.types import Model

type Filled = Literal["repository", "common"]
"""What the command line fills a field with where it's left out: the repository
whose worktree it's typed in, or that repository's common git directory."""

type Marked = Filled | Literal["words"]
"""What a field's mark says of it (`MARK`): filled from where it's typed, or
the words said with a verb."""

MARK = "x-lup-filled"
"""The key of a field's JSON Schema saying what fills it (`Marked`)."""

type Repository = Annotated[Name, Field(json_schema_extra={MARK: "repository"})]
"""A repository, as lup names it. Typed, `-r` or `--repository`; left out, the
repository whose worktree the command line is typed in, and refused outside
any."""

type Common = Annotated[Path, Field(json_schema_extra={MARK: "common"})]
"""A repository's common git directory on the machine, which every worktree
shares. Typed, the option named for its field; left out, the one of the
repository whose worktree the command line is typed in, and refused outside
any."""


type Words = Annotated[str, Field(json_schema_extra={MARK: "words"})]
"""What's said with a verb: the words typed after what's cited, `lup tell @12
"go on"`, or the comment written on the block a verb's key marks, on the
dashboard. A command offered under a verb takes them in the field typed so, as
a comment's words or a decline's reason; one with none takes no words."""


class TypedIn(Model):
    """Where the command line is typed: the directory, and the repository whose worktree holds it, which fill the fields marked so (`Filled`) that are left out."""

    directory: Path
    """The directory the words are typed in."""
    repository: str | None = None
    """The repository whose worktree holds it, as lup names it; none outside
    any, where a field filled from it and left out is refused."""
    common: Path | None = None
    """That repository's common git directory; none outside any."""
