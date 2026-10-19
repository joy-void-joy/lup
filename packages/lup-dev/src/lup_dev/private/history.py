"""What a push would publish, commit by commit, and where a value never published is in it.

`docs/private.md`, *A push*. What the remote holds is what its refs reach, as the
host listed them; what a push publishes is every commit its updates reach
beyond that (`git rev-list --ignore-missing`, so an object the store lacks, as a
stale listing may name, is skipped and more is checked, never less), and the
name of each ref it updates. In each new commit:
- its message;
- the path of each file it adds or changes against every parent, since a
  file's name is published;
- the lines it adds to each such file, found with `difflib` against each
  parent's version, never read off git's diff: in a merge, a line counts where
  it's new against every parent, as a resolution is, since what a parent
  brought was checked with that parent's commits or is the remote's already;
- a file that isn't text, by its occurrences: where it holds a value more often
  than the version it replaces in every parent;
- a link, by its target, which is its content; a submodule's entry carries a
  commit id alone.

git runs pinned to the repository's own git directory, with replace refs
ignored, as the push itself runs (`lup_dev.remote.protocol`), so what's read is
what's sent. The commits' author and committer aren't read. A place names a
file by its path, each value in it masked (`masked`), and a ref without its
name, which git's own line for it gives.
"""

from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.host.publishing import Place, Updating
from lup_dev.private.found import added_lines, counted, found, masked, textual
from lup_dev.private.withheld import Held, Withheld

if TYPE_CHECKING:
    from pathlib import PurePosixPath

    from lup_dev.git import Git, Tracked


class Spot(Model):
    """A value found in what's published, and where: never the value in words."""

    held: Held
    place: Place


def walked(repository: Git, sources: list[str], has: list[str]) -> list[str]:
    """Return each commit `sources` reach that `has` don't, oldest first.

    An object the store lacks is skipped (`--ignore-missing`), so a listing
    naming one the room never fetched checks more, never less.
    """
    asked = "".join(
        [*(f"{each}\n" for each in sources), *(f"^{each}\n" for each in has)]
    )
    listed = repository.run(
        "rev-list",
        "--reverse",
        "--topo-order",
        "--ignore-missing",
        "--stdin",
        stdin=asked.encode(),
    )
    return listed.output.decode().splitlines()


class Commit(Model):
    """One commit a push publishes: its short id, its parents and its message."""

    short: str
    parents: list[str]
    message: str

    @classmethod
    def read(cls, repository: Git, commit: str) -> Commit:
        """Read `commit` from the repository."""

        def shown(form: str) -> str:
            return repository.run(
                "show", "-s", f"--format={form}", commit
            ).output.decode()

        return cls(
            short=shown("%h").strip(),
            parents=shown("%P").split(),
            message=shown("%B"),
        )


def files(entries: list[Tracked]) -> dict[PurePosixPath, Tracked]:
    """Return each file of a tree, by its path: what's a blob or a submodule's commit."""
    return {each.path: each for each in entries if each.kind != "tree"}


def in_text(
    held: Withheld, after: str, before: list[bytes | None], within: str
) -> list[Spot]:
    """Find what `after` adds against every version in `before`, a file's text."""
    against = [
        added_lines(None if was is None else textual(was), after)
        for was in before or [None]
    ]
    added = [line for line in against[0] if all(line in each for each in against)]
    return [
        Spot(
            held=each.held,
            place=Place(within=within, line=each.line, column=each.column),
        )
        for each in found(after, held)
        if each.line in added
    ]


def in_bytes(
    held: Withheld, after: bytes, before: list[bytes | None], within: str
) -> list[Spot]:
    """Find each value `after` holds more often than every version in `before`, a file that isn't text."""

    def more(value: Held) -> list[Spot]:
        now = counted(after, value)
        was = max((len(counted(each or b"", value)) for each in before), default=0)
        if len(now) <= was:
            return []
        return [Spot(held=value, place=Place(within=within, byte=now[0]))]

    return [spot for value in held.held for spot in more(value)]


def in_commit(
    repository: Git, commit: str, held: Withheld, trees: dict[str, list[Tracked]]
) -> list[Spot]:
    """Find what one commit publishes that its parents didn't: its message, the paths it adds or changes, and what they add."""
    read = Commit.read(repository, commit)

    def tracked(which: str) -> dict[PurePosixPath, Tracked]:
        if which not in trees:
            trees[which] = repository.tracked(which)
        return files(trees[which])

    now = tracked(commit)
    parents = [tracked(parent) for parent in read.parents]
    changed = [
        entry
        for path, entry in now.items()
        if all(
            path not in parent or parent[path].object != entry.object
            for parent in parents
        )
    ]
    message = [
        Spot(
            held=each.held,
            place=Place(
                within=f"{read.short}'s message", line=each.line, column=each.column
            ),
        )
        for each in found(read.message, held)
    ]
    named = [
        Spot(
            held=each.held,
            place=Place(
                within=f"{read.short} {masked(str(entry.path), held)}, in its path",
                column=each.column,
            ),
        )
        for entry in changed
        for each in found(str(entry.path), held)
    ]
    blobs = [entry for entry in changed if entry.kind == "blob"]
    wanted = list(
        dict.fromkeys(
            [
                *(entry.object for entry in blobs),
                *(
                    parent[entry.path].object
                    for entry in blobs
                    for parent in parents
                    if entry.path in parent and parent[entry.path].kind == "blob"
                ),
            ]
        )
    )
    contents = dict(zip(wanted, repository.contents(wanted), strict=True))

    def spots(entry: Tracked) -> list[Spot]:
        after = contents[entry.object]
        before = [
            contents.get(parent[entry.path].object) if entry.path in parent else None
            for parent in parents
        ]
        within = f"{read.short} {masked(str(entry.path), held)}"
        text = textual(after)
        if text is None:
            return in_bytes(held, after, before, within)
        return in_text(held, text, before, within)

    return [*message, *named, *(spot for entry in blobs for spot in spots(entry))]


def pushed(
    repository: Git, updates: list[Updating], has: list[str], held: Withheld
) -> list[Spot]:
    """Find every value never published in what `updates` would publish beyond `has`: each ref's name, then each new commit, oldest first."""
    refs = [
        Spot(
            held=each.held,
            place=Place(within="the name of the ref it updates", column=each.column),
        )
        for update in updates
        for each in found(update.destination, held)
    ]
    trees: dict[str, list[Tracked]] = {}
    commits = walked(repository, [update.source for update in updates], has)
    return [
        *refs,
        *(
            spot
            for commit in commits
            for spot in in_commit(repository, commit, held, trees)
        ),
    ]
