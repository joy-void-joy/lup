"""What a repository path is for, and which gates that answer relaxes.

The lattice judges an action by what it does. A role adds the missing half:
what the thing acted upon is *for*. Production code carries the conventions
because other code reads it; tests and retained data carry none of them because
their subjects are behaviour and evidence rather than their own source shape;
scratch carries nothing at all because every file there is disposable by
construction.

Roles inside the repository are declared by the application, never the kernel
— that path vocabulary belongs to whoever laid out the tree. The session
scratchpad is the one root the kernel knows unaided, because the harness names
it rather than the repository: it lives outside every worktree, so no
repo-relative declaration could reach it, and its spelling is fixed by the
runtime that provides it.
"""

import fnmatch
import posixpath
from pathlib import PurePosixPath

from .decision import SUBSTITUTION_SENTINEL
from .rows import PathRoleKind, PathRoleName, PathRoleRow

# lup: ignore[library-default] — the native runtimes' own plugin directory names
GENERATED_PLUGIN_ROOTS = (".claude/plugins", ".codex/plugins")
# lup: ignore[constant-declaration] — refusal wording, declared with its verdict
GENERATED_PLUGIN_REFUSAL = (
    "a native plugin tree is compiled from typed source, and the running"
    " runtime already loaded it — edit the policy source, run"
    " `lup-devtools harness generate all`, then ask the user to restart"
    " claude or codex so the change takes effect"
)


# lup: ignore[constant-declaration] — the words this gate says, in a kernel
# compiled hermetically into a bare dispatcher that takes no arguments
FOREIGN_REPOSITORY_REFERRAL = (
    "this file belongs to a different repository, whose conventions, size"
    " budget and gates are its own — this project's rule checker has nothing"
    " to say about it and is not applying any of them. Edit it as that"
    " repository would want it, not as this one would"
)
"""What a foreign-repository edit is told, in place of a convention refusal.

The sentence has to say two things at once and be believed on both. That the
edit may proceed once a human approves it, and — the part that was actually
costing something — that the rules it is *not* being judged by were never
about it, so the way through is not to satisfy them. A refusal naming a lup
rule teaches an agent to restyle somebody else's code until the rule stops
firing, which is exactly what happened.
"""


def spells_its_path(word: str) -> bool:
    """Whether a word names exactly the path it spells.

    A word carrying an unexpanded parameter, a substitution, or a tilde names
    a different file at run time than the one written down, so every answer
    derived from reading it is an answer about a path that may never exist.

    Both readers of that fact need it and were deriving it apart. The
    redirection rule refused the create-versus-overwrite relaxation to such a
    word, while :func:`path_role` matched its declared patterns against it as
    though every component were a directory name. They disagreed about
    ``$W/tmp/f.py``, and the role won: ``**/tmp`` absorbed the ``$W`` and
    called the whole path scratch, which allowed ``rm -rf $W/tmp`` unprompted
    on the strength of a component saying nothing about where ``$W``
    resolves.
    """
    return not any(marker in word for marker in ("$", "~", "`", SUBSTITUTION_SENTINEL))


def is_generated_plugin_target(word: str) -> bool:
    """Recognize a path confined to a native plugin tree the harness renders.

    Every file there is compiled from typed source, so writing one by hand
    edits a build product: the change is reverted by the next generation and
    never reaches the runtime that already loaded it. The roots stop at
    ``plugins`` because their parents also hold settings, trust state, and
    hand-written skills and commands that no generator can restore.

    The roots are matched as path segments wherever they occur, so an absolute
    spelling and a sibling worktree's tree are recognized too. A relaxation
    may safely decline to resolve those, because declining leaves the ask in
    place; a refusal that only knew the repo-relative spelling would instead
    fail open on the one form that reaches past this worktree.

    Both runtimes' roots are named and both gates read this one answer: which
    tree a write lands in is the same question whichever runtime is running,
    and a refusal knowing one spelling would leave the other open.
    """
    # lup: ignore[string-split] — segment comparison on an already-normalized
    # posix path, which is what the roots are declared as
    segments = posixpath.normpath(word).split("/")
    return any(
        segments[index : index + len(parts)] == parts
        # lup: ignore[string-split] — the declared roots, in the same terms
        for parts in [root.split("/") for root in GENERATED_PLUGIN_ROOTS]
        for index in range(len(segments))
    )


def is_session_scratch_target(word: str) -> bool:
    """Recognize a path confined to the session scratchpad.

    ``$TMPDIR`` is the harness-provided scratch root and ``/tmp/claude-*`` its
    host-side spelling, so writes there are scratch by definition. A suffix
    that expands further or climbs out of the root stays unrecognized.
    """
    for prefix in ("$TMPDIR/", "${TMPDIR}/"):
        if word.startswith(prefix):
            suffix = word[len(prefix) :]
            normalized = posixpath.normpath(suffix)
            return "$" not in suffix and not normalized.startswith(("..", "/"))
    return "$" not in word and posixpath.normpath(word).startswith("/tmp/claude-")


def is_temporary_root_target(word: str) -> bool:
    """Recognize a path under the machine's temporary root.

    This says where a path is and nothing about whether writing there is
    safe, because the same word means opposite things on either side of a
    boundary. Inside a measured container the temporary root is this
    launch's own and disappears with it; on a host it is shared with every
    other process on the machine, and a file clobbered there belongs to
    somebody who never saw the question. So the caller supplies the half
    this cannot know, and :meth:`SettlementFacts.container_private` is the
    fact it supplies.

    Wider than :func:`is_session_scratch_target` in what it matches and
    weaker in what it settles, which is the trade: the harness mints the
    scratchpad per session and owns it at every placement, so that one needs
    no boundary to be worth allowing and this one is worth nothing without.

    A word carrying an expansion stays unrecognized, and a suffix that
    climbs back out fails the same way — ``/tmp/../etc`` normalizes to a
    path this does not claim.
    """
    return "$" not in word and posixpath.normpath(word).startswith("/tmp/")


def role_pattern_covers(pattern: str, path: str) -> bool:
    """Whether a declared role pattern reaches a repository-relative path.

    A role names a tree rather than a file, so the pattern is matched against
    the path's leading segments and covers everything below what it names:
    ``tmp`` reaches ``tmp/run/log``, and ``**/__pycache__`` reaches both the
    directory itself and ``src/a/__pycache__/m.pyc``.

    Matching is per segment, so a wildcard cannot cross a ``/`` and silently
    widen a pattern past the directory it names; ``**`` is the one spelling
    that spans segments, standing for any run of them including none. That
    distinction is the whole safety argument for declaring a role by pattern
    at all — ``**/__pycache__`` names every cache directory and nothing else,
    where a substring test would also have claimed ``notes/__pycache__.bak``.

    A literal root carrying glob metacharacters — a directory actually named
    ``run[1]`` — reads as a pattern under this. Nothing in the declarations is
    spelled that way, and a root that ever is escapes the class as ``run[[]1]``.
    """

    def covers(pattern: tuple[str, ...], segments: tuple[str, ...]) -> bool:
        """Whether the pattern matches a leading run of the path's segments."""
        if not pattern:
            return True
        head, rest = pattern[0], pattern[1:]
        if head == "**":
            return any(
                covers(rest, segments[index:]) for index in range(len(segments) + 1)
            )
        if not segments:
            return False
        return fnmatch.fnmatchcase(segments[0], head) and covers(rest, segments[1:])

    return covers(PurePosixPath(pattern).parts, PurePosixPath(path).parts)


def normalized_path(path: str) -> str:
    """Normalize one portable path without resolving against the filesystem."""
    # lup: ignore[string-replace] — a posix parser cannot read a Windows path,
    # so settling the separator convention is what makes the string parseable
    # at all, rather than something the parser below could have done instead
    return posixpath.normpath(path.replace("\\", "/"))


def root_matches(path: str, value: str, kind: PathRoleKind) -> bool:
    """Whether one path sits under a declared directory, however it is declared.

    The one answer both declaration tables need. A protected-path rule and a
    role row ask this of the same two shapes, and asking it in one place is
    what keeps a directory from meaning one thing to the gate that protects it
    and another to the gate that says what it is for.

    ``contains_part`` matches the directory wherever it sits, and excludes the
    system temporary directory, which is a different tree that happens to share
    the name. Wrapping both sides in separators is what makes a segment match a
    segment: ``tmpfoo`` holds the characters and is not the directory.
    """
    portable = normalized_path(path)
    expected = normalized_path(value)
    if kind == "contains_part":
        return f"/{expected}/" in f"/{portable}/" and not portable.startswith(
            f"/{expected}"
        )
    return portable == expected or portable.startswith(expected + "/")


def path_role(path: str, rows: list[PathRoleRow]) -> PathRoleName:
    """Classify a repository-relative path by the role its root declares.

    A root is a pattern, so a tree scattered through the repository rather
    than gathered under one prefix — every ``__pycache__``, every ``.bak`` —
    is declarable as what it is. Disposability stays something a project
    states: nothing is scratch for merely being untracked, which is what
    keeps an ignored ``.env.local`` protected unless its project deliberately
    declares it as data.

    Resolution is lexical, so it needs no filesystem call and ``..`` cannot
    climb out of a declared root into a role it was never given. A symlink
    inside a root that points beyond it is not settleable without a syscall
    and stays a known limit; it is narrow, because a role only ever relaxes
    verbs acting on paths already inside the root and never grants execution.

    How far each declaration reaches is the row's own, through
    :func:`role_pattern_covers`: a bare root is anchored at the repository
    top, and a leading ``**/`` recognizes the directory wherever it sits.

    The session scratchpad answers first, because it is the one scratch root
    that is absolute — reaching the declared roots below would mean passing
    the guard that keeps an absolute path from claiming a role by prefix.
    Every other path outside the repository stays production: a file in some
    other tree is not disposable merely for being elsewhere.
    """
    normalized = posixpath.normpath(path)
    if is_session_scratch_target(path):
        return "scratch"
    if normalized.startswith(("/", "../")) or normalized == "..":
        return "production"
    # A declared pattern matches directory names, and an unexpanded word is
    # not one. The scratchpad above is the one opaque spelling with an answer,
    # and it earns it by checking its own suffix rather than by pattern.
    if not spells_its_path(normalized):
        return "production"
    for row in rows:
        if role_pattern_covers(row["root"], normalized):
            return row["role"]
    return "production"
