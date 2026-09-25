"""Whether a linked worktree still points where the repository put it.

A linked worktree lives between three pointer files, and the value of each is
where the *next* thing git reads lives: the worktree's `.git` file holds
`gitdir: <entry>`, the entry's `commondir` holds the shared directory, and the
entry's `gitdir` holds the way back to the `.git` file. Host git follows them
in that order, and reads its config -- `core.hooksPath`, `core.fsmonitor`,
`core.sshCommand`, `alias.*`, `credential.helper`, the `merge.*.driver` family,
every key that hands git a command line -- from wherever they lead. None of
the three is a key; each is the address of the file the keys are read from.

Why this is its own guard rather than a mount. The three files sit in trees the
container writes: the `.git` file is in the checkout, `commondir` and `gitdir`
in the administrative entry under the shared directory. A mount cannot hold
them read-only without holding them against `git worktree remove`, which
unlinks exactly these files -- a read-only bind refuses the removal with an
errno about a busy device, the workflow this repository mandates breaking on
the guard meant to protect it. So the pointer is not pinned; it is *verified*,
on the host, against the one thing the container cannot forge: the shared
directory the launcher already trusts, passed in rather than read back through
the pointer under test.

What the verification reduces the escape to. A pointer forced to keep naming
`<common>/worktrees/<n>` -> `<common>` cannot name a directory the container
built, so the only config host git will read for a worktree is the one under
the shared directory -- which `config` and `hooks/` there are already guarded
against, by mount and by the semantic policy both. The pointer escape collapses
into the config escape, which is answered. What it does not answer: a `git`
the operator runs by hand in a redirected worktree, outside every lup path that
consults this. That git follows the moved pointer like any other, so the guard
is only as present as the commands that call it -- which is why it is wired
into the worktree lifecycle rather than offered as advice.

Anchored, never bootstrapped. The trusted `common` is the caller's -- lup's own
project layout, the launcher's recorded repository -- and every worktree is
enumerated from `<common>/worktrees/` and validated against that one `common`.
Deriving `common` from the worktree under test would let a forged `commondir`
name its own fake shared directory and pass: the check would ask the attacker
where the truth is. A missing pointer file is left unjudged rather than flagged,
because `git worktree add` writes the three in sequence and a half-made entry is
not an attack; a *present* pointer that names the wrong place is the whole of
what this catches.
"""

from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel


class PointerDrift(BaseModel, frozen=True):
    """One worktree pointer that no longer names where the repository put it."""

    worktree: Path
    pointer: Path
    names: str
    expected: str


def gitdir_target(dot_git: Path) -> Path | None:
    """The path a worktree's `.git` file points its gitdir at, or ``None``.

    ``None`` where `.git` is a real directory -- a plain checkout or the shared
    directory itself -- rather than the one-line `gitdir: <path>` pointer a
    linked worktree carries, since only the pointer can be redirected.
    """
    if not dot_git.is_file():
        return None
    line = dot_git.read_text().strip()
    if not line.startswith("gitdir:"):
        return None
    return Path(line.removeprefix("gitdir:").strip())


def resolved_against(entry: Path, contents: str) -> Path:
    """A pointer file's value as an absolute path, from an entry that may be relative.

    `commondir` is written relative to the administrative entry (`../..`), while
    `gitdir` is written absolute; resolving each against the entry answers both
    without asking which it was.
    """
    named = Path(contents.strip())
    return named if named.is_absolute() else entry / named


def pointer_drift(common: Path) -> list[PointerDrift]:
    """Every worktree of this repository whose pointer chain has left ``common``.

    ``common`` is the trusted shared directory -- the caller's, never re-read
    through a pointer under test. Each administrative entry under it is checked
    two ways: its `commondir` names ``common``, and its `gitdir` names a `.git`
    file whose own `gitdir:` names the entry back. A value that resolves
    elsewhere is a redirection, reported with what it names against what the
    repository put there. A pointer file that is absent is left unjudged.
    """
    entries = common / "worktrees"
    if not entries.is_dir():
        return []

    def drifted() -> Iterator[PointerDrift]:
        for entry in sorted(entries.iterdir()):
            gitdir_file = entry / "gitdir"
            commondir_file = entry / "commondir"
            if not gitdir_file.is_file() or not commondir_file.is_file():
                continue
            dot_git = resolved_against(entry, gitdir_file.read_text())
            named_common = resolved_against(entry, commondir_file.read_text())
            if named_common.resolve() != common.resolve():
                yield PointerDrift(
                    worktree=dot_git.parent,
                    pointer=commondir_file,
                    names=str(named_common),
                    expected=str(common),
                )
            back = gitdir_target(dot_git)
            if back is not None and back.resolve() != entry.resolve():
                yield PointerDrift(
                    worktree=dot_git.parent,
                    pointer=dot_git,
                    names=str(back),
                    expected=str(entry),
                )

    return list(drifted())


def refusal(drifts: list[PointerDrift]) -> str:
    """One message naming every redirected pointer and where it now leads.

    Empty for no drift, so a caller says nothing where nothing moved. Full
    rather than truncated: each redirected worktree is a place host git would
    read a container-chosen config, and a caller that dropped one would run git
    in it believing the set was clean.
    """
    if not drifts:
        return ""
    lines = [
        f"  {drift.worktree}: {drift.pointer.name} names {drift.names}, "
        f"not {drift.expected}"
        for drift in drifts
    ]
    return (
        "Worktree pointers were redirected out of the repository, so host git "
        "in these worktrees would read a config the container chose:\n"
        + "\n".join(lines)
    )
