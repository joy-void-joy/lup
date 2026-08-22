# lup: ignore[dict-str-payload] — ref name to object id, keyed by whatever
# refs a repository happens to hold; there is no closed set to model
"""Catching a test suite that wrote into the repository it is running inside.

A test that builds a throwaway repository binds git to it — `git -C <tmp>` —
and one that forgets inherits the process working directory instead, which
during a test run is a real checkout. Nothing about that fails: git finds a
repository, commits succeed, and the suite passes green while the branch the
developer is standing on has moved. It was found here the slow way, by a
`dev pr sync-base` merging a `dev` whose tip had become a fixture's `chore:
base` commit deleting the entire application source, an hour after the fixture
ran.

The suite cannot be trusted to notice, because noticing is exactly what it
failed to do. So the check sits outside every test: the refs of the enclosing
repository are read once before the session and once after, and a difference
fails the run naming the refs that moved — except where the ref belongs to
another worktree of the same repository, which is that worktree's to move and
so is reported rather than failed on. Detection rather than prevention — a
ceiling that stopped git discovering the enclosing repository would also stop
the tests that legitimately read it, and a suite that cannot run is a worse
trade than one that reports what it broke.

Nothing here needs the repository to exist: a suite running outside a checkout
gets an empty snapshot both times and never fails.
"""

from pathlib import Path

import sh
from pydantic import BaseModel

from lup.policy.assets.host import undo_namespace

REF_FORMAT = "%(refname) %(objectname)"
"""One ref per line, as `repository_refs` reads it."""

WATCHED_SETTINGS = ("user.name", "user.email", "core.hooksPath")
"""The config a fixture overwrites and never puts back.

Watched beside the refs because this is the quieter half of the same accident
and the more expensive one. A moved ref is visible the moment anybody looks at
the branch; a committer identity written into the shared config is inherited by
every worktree cut from the repository and shows up only as authorship on work
done hours later, by someone who never ran the suite.

`core.hooksPath` is quieter still, and it is the half that takes the alarm out
with it. Pointed at a directory a fixture built, it disables every hook the
repository declares — the drift guard and the gate guard both stop running,
and a checkout that runs no hooks looks exactly like one whose hooks pass. An
identity leak at least signs the work it spoils; this one leaves no trace at
all until something it should have refused gets through.
"""

GIT_ENVIRONMENT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
)
"""What names a repository to git ahead of any directory a command is given.

The third way into the same accident, and the one no fixture can defend
itself against: `-C <throwaway>` chooses where git works, while these choose
which repository it resolves, and the environment wins. A suite that inherits
them commits into whatever they name, however carefully each helper bound its
own git.

Git exports them to every hook, so a gate installed as one — see
:mod:`lup.devtools.dev.git_guards` — hands the suite the very checkout being
pushed. Scrubbed where the hook is written rather than watched for afterwards,
because unlike a misbound command this arrives through one door.
"""


class CommitterIdentity(BaseModel):
    """Somebody for a suite's throwaway repositories to commit as."""

    name: str
    email: str

    def environment(self) -> dict[str, str]:
        """This identity as environment, which cannot persist anywhere.

        A suite building throwaway repositories has to give git somebody to
        commit as, and the obvious `git config` writes a file — the shared one
        when the command misbinds, which is the accident this module exists
        for. Passing the identity per invocation with `-c` closes that only for
        the commands the suite runs itself: code under test runs git of its own
        and inherits none of them, so it commits as nobody and fails wherever
        the developer's global config is not there to cover for it.

        The environment reaches both and outlives neither. There is no file for
        a misbound command to land in, so the identity half of the accident is
        impossible here rather than merely watched for.
        """
        return {
            "GIT_AUTHOR_NAME": self.name,
            "GIT_AUTHOR_EMAIL": self.email,
            "GIT_COMMITTER_NAME": self.name,
            "GIT_COMMITTER_EMAIL": self.email,
        }


TEST_IDENTITY = CommitterIdentity(name="Lup Test Suite", email="tests@lup.invalid")
"""The identity a suite arms its session with, overridable by a caller with cause."""


def repository_refs(root: Path, ref_format: str = REF_FORMAT) -> dict[str, str]:
    """Every ref in the repository enclosing `root`, or nothing if there is none.

    Read through git rather than by walking `.git`, because a worktree's refs
    live in the repository it was cut from and only git knows where that is.
    A failure to read is reported as no repository rather than raised: this
    runs before and after a suite whose result matters more than the guard's
    own footing, and a guard that can break the run it protects is worse than
    one that stays quiet.
    """
    try:
        listed = sh.Command("git")(
            "-C", str(root), "for-each-ref", f"--format={ref_format}", _tty_out=False
        )
    except (sh.ErrorReturnCode, sh.CommandNotFound):
        return {}
    pairs = [
        # lup: ignore[string-split] — git's own for-each-ref output, whose two
        # fields REF_FORMAT put either side of one space
        line.split(" ", 1)
        for line in str(listed).splitlines()
        if line
    ]
    return {pair[0]: pair[1] for pair in pairs if len(pair) == 2}


def watched_config(
    root: Path, settings: tuple[str, ...] = WATCHED_SETTINGS
) -> dict[str, str]:
    """What the repository enclosing `root` holds for each watched setting.

    Absent settings are simply absent, so a repository that leaves identity to
    the user's global config reads as empty here and a fixture writing one in
    shows up as a creation rather than as a change from nothing.
    """
    found = {}
    for setting in settings:
        try:
            value = sh.Command("git")(
                "-C", str(root), "config", "--local", "--get", setting, _tty_out=False
            )
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            continue
        found[f"config {setting}"] = str(value).strip()
    return found


def repository_state(root: Path, namespace: str = "") -> dict[str, str]:
    """Everything the guard watches: every ref, and the config a fixture can leak.

    Minus the undo namespace, which is the one place in this repository that
    is *written by design* while a suite runs. The permission dispatcher takes
    a snapshot in front of every command an agent is allowed, so a suite an
    agent starts has refs appearing under it throughout — measured, twenty-four
    in the ninety seconds around one `dev check`, and eight identical teardown
    failures, one per xdist worker, naming refs no fixture had touched.

    Excluded rather than reported, on the strength of what the namespace is.
    A ref moving there carries no evidence either way: it is written from
    outside the suite on a schedule the suite does not control, so it is never
    the suite's doing, and a notice saying so on every agent-run check is the
    line people learn to skip above the line that mattered. And it cannot be
    the accident this guard exists for — that accident is a branch moving or a
    shared identity being overwritten, and a snapshot is a tree hung outside
    `refs/heads`, pointed at by nothing, that moves no branch and writes no
    config.

    The namespace is imported from the half that writes it rather than spelled
    again here, for the reason that half gives for being importable at all:
    the writer and the reader must not end up looking in two places for one
    safety net. ``namespace`` is a parameter for the callers that pass their
    own — the same override :func:`~lup.policy.assets.host.undo_snapshot`
    takes, so a suite testing snapshots against a namespace of its own is
    still watched in the real one.
    """
    where = namespace or undo_namespace()
    return {
        **{
            name: value
            for name, value in repository_refs(root).items()
            if not name.startswith(f"{where}/")
        },
        **watched_config(root),
    }


def moved_refs(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Each ref the session created, deleted, or moved, as a readable line."""
    return [
        *(
            f"{name}: {before[name][:12]} -> {after[name][:12]}"
            for name in sorted(before.keys() & after.keys())
            if before[name] != after[name]
        ),
        *(f"{name}: created" for name in sorted(after.keys() - before.keys())),
        *(f"{name}: deleted" for name in sorted(before.keys() - after.keys())),
    ]


def guard_report(before: dict[str, str], after: dict[str, str]) -> str:
    """What to tell a developer whose checkout the suite just wrote into.

    Empty when nothing moved, which is the caller's signal to say nothing.
    The wording names the cause the evidence actually supports — a fixture
    that reached the enclosing repository — because the alternative reading,
    that the developer moved a branch mid-run, is one they can rule out
    themselves and the suite cannot.
    """
    moved = moved_refs(before, after)
    if not moved:
        return ""
    return "\n".join(
        [
            "This test run modified the repository it is running inside.",
            "",
            "A fixture bound git to the working directory rather than to its",
            "own throwaway repository, so this much of the real checkout",
            "changed:",
            "",
            *(f"  {line}" for line in moved),
            "",
            "A ref is recovered from `git reflog show <ref>`. A `config` line",
            "is worse than it looks: the shared config is inherited by every",
            "worktree cut from this repository, so it outlives this run in",
            "every session opened against it.",
            "",
            "A `user.*` line means commits made afterwards carry that author",
            "until it is unset — check `git log --format='%an <%ae>'` on",
            "recent work. A `core.hooksPath` line means this repository now",
            "runs no hooks at all: unset it, then re-arm the guards, and read",
            "what landed while they were off.",
            "",
            "Then find the fixture: it is one that runs git without",
            "`-C <tmp_path>` or without `monkeypatch.chdir` into the",
            "repository it built.",
        ]
    )


class ForeignCheckouts(BaseModel, frozen=True):
    """Which refs a worktree other than the one under test has checked out.

    Every worktree cut from a repository shares its ref store, so the guard
    reading `for-each-ref` in one of them sees every branch the repository
    holds — twenty-five of them here, of which one is the checkout the suite
    is running in. A commit landing in a sibling worktree while the suite runs
    moves a ref for real, and from the refs alone that is indistinguishable
    from a fixture escaping into the enclosing repository.

    Asking git who holds each branch is what tells them apart. It is a
    narrower question than "did anything move", and deliberately so: a ref
    another worktree has checked out is that worktree's to move, while a ref
    this one owns, or one that appeared from nowhere, is still the suite's to
    answer for.
    """

    holders: dict[str, str] = {}
    """Each checked-out ref, against the worktree path holding it."""

    def holder(self, key: str) -> str | None:
        """The other worktree that owns this key, when another one does."""
        # lup: ignore[dict-get] — an open registry keyed by whatever refs the
        # repository happens to hold, which is the shape the rule exempts
        return self.holders.get(key)

    def ours(self, state: dict[str, str]) -> dict[str, str]:
        """The watched state this checkout is answerable for."""
        return {key: value for key, value in state.items() if not self.holder(key)}

    def theirs(self, state: dict[str, str]) -> dict[str, str]:
        """The watched state another worktree owns."""
        return {key: value for key, value in state.items() if self.holder(key)}

    def verdict(self, before: dict[str, str], after: dict[str, str]) -> "GuardVerdict":
        """What moved, split into what this run answers for and what it does not.

        Config is never anybody else's: it is one shared file rather than a
        ref a worktree holds, so it stays on the failing side whatever moved.
        """
        return GuardVerdict(
            failure=guard_report(self.ours(before), self.ours(after)),
            notice=foreign_notice(moved_refs(self.theirs(before), self.theirs(after))),
        )

    @classmethod
    def beside(cls, root: Path) -> "ForeignCheckouts":
        """Every branch checked out in a worktree that is not ``root``.

        Read through `git worktree list`, which is the only thing that knows;
        a failure to read is reported as no siblings, so a guard that cannot
        answer the narrower question falls back to failing on everything
        rather than passing on everything.
        """
        try:
            listed = sh.Command("git")(
                "-C", str(root), "worktree", "list", "--porcelain", _tty_out=False
            )
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            return cls()
        return cls(holders=cls.declared(str(listed), root.resolve()))

    @classmethod
    def declared(cls, listing: str, own: Path) -> dict[str, str]:
        """Each `branch` line of a porcelain listing, minus ``own``'s entry.

        The format is one stanza per worktree, `worktree <path>` opening each
        and `branch <ref>` naming what it holds; a detached or bare entry
        simply carries no branch line and so claims no ref.
        """
        held: dict[str, str] = {}  # lup: ignore[empty-collection] — stanza fold
        at = Path()
        for line in listing.splitlines():
            # lup: ignore[string-split] — git's own porcelain, whose key and
            # value sit either side of one space by that format's definition
            key, _, value = line.partition(" ")
            match key:
                case "worktree":
                    at = Path(value).resolve()
                case "branch" if at != own:
                    held[value] = str(at)
                case _:
                    continue
        return held


class GuardVerdict(BaseModel, frozen=True):
    """What the guard found, split by who is answerable for it."""

    failure: str = ""
    """The report to fail the run on, empty when nothing this run owns moved."""

    notice: str = ""
    """What moved in a sibling worktree: worth saying, not worth failing."""


def foreign_notice(moved: list[str]) -> str:
    """What to say about refs a sibling worktree moved under the suite's feet."""
    if not moved:
        return ""
    return "\n".join(
        [
            "Refs moved while this suite ran, in worktrees that own them:",
            "",
            *(f"  {line}" for line in moved),
            "",
            "Another session committing in a sibling worktree is not this run",
            "writing into the checkout, so the suite is not failed for it. A",
            "ref this worktree owns, or one that appeared from nowhere, still",
            "is.",
        ]
    )
