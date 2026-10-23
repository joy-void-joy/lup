"""A branch merged onto the integration branch apart from every checkout, and the gate run on the merge: what `land` has a launch's room do.

`docs/judging-writes.md`, *Landing a branch*. `land`, on the host, hands the room
the two commits and the merge commit's message; `lup-dev merge` runs `merged`
there, through the project's runner, and prints what came of it as JSON
(`Merging`), which `land` reads:
1. the merge is computed apart, touching no checkout and no ref (`git merge-tree
   --write-tree`): where it conflicts, the answer names the files, and nothing
   is written but objects no ref names;
2. the merge commit is made with the message as given, cleaned as `git commit`
   cleans one (`git stripspace`), the integration branch's tip its first parent
   (`git commit-tree`), so the message goes through no shell's quoting;
3. the gate runs on it, with its fixes (`at_commit`): a branch that held the
   integration branch's tip merges to its own tree, whose pass the branch
   recorded, so nothing runs; where the fixes change files, they're in a
   commit made in its place, with its parents and message, which is the
   merge that lands.

Its git and its gate run in the room, as the gate a push runs does: the merge
isn't the commit the operator approved, and its gate on the host would run
unapproved code there.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from lup.types import Model
from lup_dev.errors import LupDevError
from lup_dev.gate import Amended, Passed, Passes, Processes, Ran, at_commit
from lup_dev.git import Git, nul_separated

if TYPE_CHECKING:
    from collections.abc import Callable

    from lup_dev.declaration.runner import Runner


class MergeError(LupDevError):
    """A merge `land` asks for can't be made as asked."""


class Conflicted(Model):
    """The merge conflicts: nothing was made."""

    kind: Literal["conflicted"] = "conflicted"
    files: list[Path]
    """Each file it conflicts in, from the repository's root."""


class Failed(Model):
    """The gate failed on the merge commit."""

    kind: Literal["failed"] = "failed"
    commit: str
    """The merge commit, which no ref names."""
    report: str
    """What the gate printed, whole."""


class Merged(Model):
    """The merge commit the gate passed on, with its fixes."""

    kind: Literal["merged"] = "merged"
    commit: str
    ran: bool
    """Whether the gate ran on it; not where a pass was recorded for its files
    already."""
    fixed: bool = False
    """Whether the fixes changed files, so the commit is the one made in place
    of the merge, holding them."""


type Merging = Annotated[Conflicted | Failed | Merged, Field(discriminator="kind")]
"""What came of a merge `land` asked of the room."""


def merged(
    root: Path,
    base: str,
    tip: str,
    message: str,
    *,
    processes: Processes,
    passes: Passes,
    runner: Runner,
    say: Callable[[str], None],
    stop: Callable[[Path], None],
) -> Merging:
    """Merge the commit `tip` onto the commit `base`, as the worktree at `root` reads them, with `message`, and run the gate on the merge with its fixes.

    `processes`, `passes`, `runner`, `say` and `stop` are the gate's
    (`at_commit`). Raise `MergeError` where `message` is empty once cleaned,
    and `GitError` where git can't merge the two at all.
    """
    git = Git(cwd=root)
    computed = git.run(
        "merge-tree",
        "--write-tree",
        "-z",
        "--name-only",
        "--no-messages",
        base,
        tip,
        ok=[0, 1],
    )
    tree, *files = nul_separated(computed.output)
    if computed.status == 1:
        return Conflicted(files=[Path(each) for each in files])
    cleaned = git.run("stripspace", stdin=message.encode()).output
    if not cleaned.strip():
        empty = "the merge commit's message is empty"
        raise MergeError(empty)
    commit = (
        git.run("commit-tree", tree, "-p", base, "-p", tip, stdin=cleaned)
        .output.decode()
        .strip()
    )
    gated = at_commit(
        root, commit, processes, passes, runner, say=say, stop=stop, fix=True
    )
    match gated:
        case Passed():
            return Merged(commit=commit, ran=False)
        case Amended(commit=amended):
            return Merged(commit=amended, ran=True, fixed=True)
        case Ran(code=0):
            return Merged(commit=commit, ran=True)
        case Ran(output=output):
            return Failed(commit=commit, report=output)
