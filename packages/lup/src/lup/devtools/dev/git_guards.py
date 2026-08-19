"""The git hooks that refuse work before it leaves the checkout.

A check that runs when somebody remembers to run it is a warning, not a
guarantee. Two of them earn a hook, at the two moments something becomes
hard to take back.

Drift, at ``pre-commit``: the sources compiled into the native trees are
copied there verbatim, so rewording a comment in one of them makes both
trees stale without changing anything either does, and a commit that skips
``dev check`` writes that staleness into history.

The gate itself, at ``pre-push``: a commit is local and rewritable, and a
push is neither. It runs the same ``dev check`` the pipeline runs, so a
branch is refused here by the identical command that would refuse it in CI,
minutes earlier and without spending a runner.

Each hook body is one line naming a command the pipeline also runs, so the
places that can refuse the same work run one computation rather than several
that can disagree, and a hook nobody installed is still refused by the
pipeline at the same line.

Which hooks a project arms is its own declaration — :data:`DECLARED_GUARDS`
is the pair lup ships, not a set an adopter has to fork this module to
change. A project may declare several guards at one moment, which git runs
as the one script it runs per hook: :class:`HookScript` is that file, and it
is the unit installed and read, because a guard is not what git has a name
for.
"""

from pathlib import Path
from typing import Literal

import sh
from pydantic import BaseModel

from lup.gitguard import GIT_ENVIRONMENT
from lup.harness.banner import REGENERATE_COMMAND
from lup.devtools.utils import git

DRIFT_COMMAND = "uv run lup-devtools harness check all"
"""The read-only drift check every path that refuses stale output runs."""

# lup: ignore[constant-declaration] — the command a reader types, whose words
# are the CLI's own rather than a preference this module holds
CHECK_COMMAND = "uv run lup-devtools dev check"
"""The project's whole gate, run by the pipeline and by the push hook alike.

Beside :data:`DRIFT_COMMAND` because the two are the same kind of thing —
what a refusal actually runs — and because every consumer of one wants the
other: the workflow renders both as steps and the guards install one each.
"""

# lup: ignore[constant-declaration] — the command a reader types, whose words
# are the CLI's own rather than a preference this module holds
INSTALL_COMMAND = "uv run lup-devtools dev git-hooks install"
"""How a checkout arms its guards, named in each hook it writes."""

# lup: ignore[constant-declaration] — the marker this command writes into a
# hook and reads back to know the hook is its own, so it is an identity rather
# than a setting: a caller changing it would orphan every hook already installed
GUARD_MARKER = "lup-git-guard"
"""How an installed hook says it is this command's to rewrite."""

# lup: ignore[constant-declaration] — the identity earlier versions wrote, kept
# so a checkout armed by one is still recognized rather than read as a stranger
LEGACY_GUARD_MARKER = "lup-commit-guard"
"""What this wrote while only the commit hook existed.

Recognized on read and never written. Dropping it would make every hook a
previous version installed report as one nobody here wrote, which is the
state that needs ``--force`` to leave — so the compatibility is worth one
line rather than a migration note nobody reads.
"""


# lup: ignore[constant-declaration] — git's own pre-push stdin protocol written
# in shell, not a judgement a project could hold differently; and as a field
# default it would arm the commit moment too, silently disarming that guard
DELETION_STANDDOWN = """\
# A push that only deletes refs uploads nothing for the check below to judge.
# Git names each update on stdin as `<local ref> <local oid> <remote ref>
# <remote oid>` and writes an all-zero local oid where a ref is being deleted;
# anything else is content this push answers for, and a line that does not
# parse counts as content rather than being trusted into a standdown.
carries_content=''
while read -r _ local_oid _; do
  case "$local_oid" in
    '' | *[!0]*) carries_content=yes ;;
  esac
done
[ -n "$carries_content" ] || exit 0
"""
"""What the push guard reads before deciding it has anything to judge.

Deleting a branch is the case that made this worth writing: it uploads no
tree at all, so the gate could only re-judge what the remote already had,
and it charged the whole suite for the privilege — long enough that a
delete would time out having removed the local branch and left the remote
copy standing.
"""


class GitGuard(BaseModel, frozen=True):
    """One check a repository installs as a git hook, and what it refuses.

    Every field is a judgement rather than a fact — another project may guard
    a different check, hang it off a different git hook, or say something
    else about why — so each is a default a caller replaces rather than a
    constant it would have to fork this module to change.
    """

    command: str = DRIFT_COMMAND
    """What the hook runs, and refuses the operation on a nonzero exit from."""

    hook: str = "pre-commit"
    """Which git hook the check is installed as."""

    environment: tuple[str, ...] = GIT_ENVIRONMENT
    """What the hook drops before running its check.

    A project whose check wants one of these kept names a shorter tuple, and
    one that wants none of them dropped names an empty one, which writes no
    line at all.
    """

    standdown: str = ""
    """Shell run before the check, free to ``exit 0`` and stand the guard down.

    A moment that describes itself is answered here rather than inside the
    check, which would otherwise have to be taught a second job and read a
    stdin it never asked for. Empty by default: most moments say nothing a
    hook could stand down on, and a guard that stands down silently is worse
    than one that runs.
    """

    refusal: str = (
        "Refuses this commit while a generated artifact differs from what\n"
        f"# its source renders. Settle it with `{REGENERATE_COMMAND}`."
    )
    """What the installed hook tells whoever it just stopped.

    A hook that only exits nonzero leaves its reader guessing which check
    fired and what settles it, and the script is the one place that reader
    is certainly looking.
    """

    reads_stdin: bool = False
    """Whether this check, or its standdown, reads the moment's own stdin.

    Git delivers a moment's stdin once, so a moment guarded twice has to hand
    both the same copy — declared rather than detected, because whether a
    command reads is a fact about that command and nothing here can see
    inside it. False by default: only the push moment describes itself on
    stdin at all, and capturing where nothing reads buys a moment's guarding
    nothing.
    """

    def check(self) -> str:
        """This guard's own lines: what it refuses, the scrub, then the command.

        Git names this repository to a hook through the environment, which
        outranks the `-C` any command the check runs binds itself with. A
        check whose suite builds throwaway repositories would resolve this one
        instead and commit into the branch being pushed, so the names go
        before the check rather than travelling into it.

        Ends in an ``exec`` whether or not this guard is the last at its
        moment: :class:`HookScript` puts a guard with another after it in a
        subshell, where the exec replaces that subshell and its status is
        what the moment reads.
        """
        scrub = (
            "# Dropped so the check below resolves this repository from the\n"
            "# directory it runs in. Git names it here too, and that name would\n"
            "# outrank the `-C` a test's throwaway repository binds git with.\n"
            f"unset {' '.join(self.environment)}\n"
        )
        return (
            f"# {self.refusal}\n"
            f"{scrub if self.environment else ''}"
            f"{self.standdown}"
            f"exec {self.command}\n"
        )


DECLARED_GUARDS = [
    GitGuard(),
    GitGuard(
        command=CHECK_COMMAND,
        hook="pre-push",
        standdown=DELETION_STANDDOWN,
        reads_stdin=True,
        refusal=(
            "Refuses this push while the project's own gate fails. A commit is\n"
            f"# local and rewritable; a push is neither. Run `{CHECK_COMMAND}`."
        ),
    ),
]
"""The hooks lup arms, offered to a project as the set it usually wants.

A default rather than a fixture: a project that runs its gate somewhere else,
or that has a third moment worth guarding, names its own list. What makes
these two the offer is that both refuse at a boundary the pipeline refuses
at anyway, so neither invents a rule — each only moves an existing refusal
earlier, to where it is still cheap to answer.
"""


# lup: ignore[constant-declaration] — a local name inside a script this module
# both writes and reads back, so the definition and every use are here; a caller
# given it to set would be naming a shell variable nothing outside can see
REPLAY_CALL = "replay_stdin"
"""The shell function a shared moment hands each of its guards stdin through."""


class HookScript(BaseModel, frozen=True):
    """Every guard a repository declares at one moment, as the one file git runs.

    Git runs a single script per hook, so a moment guarded twice is one file
    rather than two — which is why the installed unit is a moment and not a
    guard. The guards run in the order they were declared and the first to
    refuse ends the operation, so the cheap check goes before the expensive
    one and a reader of the script meets them in that order.
    """

    hook: str
    guards: list[GitGuard]

    @property
    def replayed(self) -> bool:
        """Whether this moment has to hand its guards a captured stdin.

        Both halves are load-bearing. A moment with one guard has nobody to
        share with, and passing git's own stdin straight through is what that
        guard already expects. A moment where nothing reads must not capture
        at all: the capture is a ``cat``, and running one at a moment whose
        stdin nothing fills would buy the guarding nothing.
        """
        return len(self.guards) > 1 and any(guard.reads_stdin for guard in self.guards)

    def capture(self) -> str:
        """The read that makes this moment's stdin answerable more than once.

        Git delivers it once, so the first guard to read drains it for every
        guard after — a push whose data check read the ref list would leave
        the gate beside it judging a push that looks empty, and standing
        down. Replayed rather than teed so each guard reads from the start.

        The emptiness test is not defensive: command substitution strips
        trailing newlines, so replaying an empty capture with a bare
        ``printf`` would hand a guard one blank line where git handed it
        nothing, and a line that parses as no ref update reads to a guard
        like a push it cannot account for.
        """
        if not self.replayed:
            return ""
        return (
            "# Git delivers this moment's stdin once, and more than one guard\n"
            "# below reads it. Captured here and replayed to each, so the first\n"
            "# to read does not drain it for the rest.\n"
            "guarded_stdin=$(cat)\n"
            f'{REPLAY_CALL}() {{ [ -z "$guarded_stdin" ] || '
            "printf '%s\\n' \"$guarded_stdin\"; }\n"
        )

    def framed(self, guard: GitGuard, *, tail: bool) -> str:
        """One guard's check, in whatever this moment's sharing asks of it.

        The last guard is left bare so the hook process becomes its command,
        which is both a process saved and the reason a lone guard's script is
        exactly what it was before any moment carried two. Every other guard
        runs in a subshell, so a standdown's ``exit 0`` stands that guard down
        rather than the moment, and ``|| exit $?`` carries a real refusal out.
        """
        if tail and not self.replayed:
            return guard.check()
        piped = f"{REPLAY_CALL} | " if self.replayed else ""
        carried = "" if tail else " || exit $?"
        return f"{piped}(\n{guard.check()}){carried}\n"

    def body(self) -> str:
        """The hook script: the marker that claims it, then each guard in turn."""
        last = len(self.guards) - 1
        framed = [
            self.framed(guard, tail=index == last)
            for index, guard in enumerate(self.guards)
        ]
        return (
            "#!/bin/sh\n"
            f"# {GUARD_MARKER}: written by `{INSTALL_COMMAND}`.\n"
            f"{self.capture()}{''.join(framed)}"
        )


def hook_scripts(guards: list[GitGuard]) -> list[HookScript]:
    """Group guards into the moments they are installed as, order preserved.

    Declaration order is the running order, so a project states its cheap
    refusal before its expensive one and gets exactly that.
    """
    moments = dict.fromkeys(guard.hook for guard in guards)
    return [
        HookScript(hook=hook, guards=[g for g in guards if g.hook == hook])
        for hook in moments
    ]


type GuardStatus = Literal["current", "stale", "absent", "foreign"]
"""What sits at the hook path, judged against what this moment would write."""


class GuardState(BaseModel, frozen=True):
    """Where one of a repository's guarded moments lives, and what is there."""

    path: Path
    status: GuardStatus

    @property
    def armed(self) -> bool:
        """Whether this repository now runs the guarded check at that moment."""
        return self.status == "current"

    def describe(self) -> str:
        """One line saying what is installed, and what to do when it is not.

        The path ends in the hook's own name, so it says which moment this
        is about without the sentence having to repeat it.
        """
        match self.status:
            case "current":
                return f"guard armed: {self.path}"
            case "stale":
                return f"guard at {self.path} is an older body; reinstall it"
            case "absent":
                return f"guard not installed at {self.path}; run `{INSTALL_COMMAND}`"
            case "foreign":
                return f"{self.path} holds a hook this did not write"


class GuardConflict(RuntimeError):
    """A hook nobody here wrote already occupies the guard's path."""


def hooks_directory(root: Path) -> Path:
    """Where git looks for this clone's hooks, asked from any of its worktrees.

    ``core.hooksPath`` moves the whole directory, so a guard written to
    ``.git/hooks`` under a clone that sets it would be a hook git never runs.
    Asking git resolves both that setting and the shared common directory a
    linked worktree hooks through.
    """
    configured = git.out(
        "-C", str(root), "config", "--get", "core.hooksPath", _ok_code=[0, 1]
    )
    named = configured or git.out(
        "-C", str(root), "rev-parse", "--git-path", "hooks", _ok_code=[0]
    )
    return root / named


# lup: ignore[model-free-function] — driver: it reads the hook file on disk, and
# HookScript is the declaration of which hook rather than the thing that reads
def guard_state(script: HookScript, directory: Path) -> GuardState:
    """Read what is installed at this moment's hook path."""
    path = directory / script.hook
    if not path.is_file():
        return GuardState(path=path, status="absent")
    installed = path.read_text(encoding="utf-8")
    if not any(marker in installed for marker in (GUARD_MARKER, LEGACY_GUARD_MARKER)):
        return GuardState(path=path, status="foreign")
    current = installed == script.body()
    return GuardState(path=path, status="current" if current else "stale")


def read_guards(guards: list[GitGuard], root: Path) -> list[GuardState]:
    """What one checkout would run, or fail to run, at each moment declared."""
    directory = hooks_directory(root)
    return [guard_state(script, directory) for script in hook_scripts(guards)]


class HooksReading(BaseModel, frozen=True):
    """Where a checkout looks for hooks, and what it has armed there."""

    directory: Path
    reachable: bool
    """Whether that directory is there to hold a hook at all.

    The one breakage no environment makes ambiguous, and the quiet one. Git
    runs no hook and reports nothing, so every guard the repository declares
    is off while the gate that would have said so keeps passing — a checkout
    running no hooks reads exactly like one whose hooks are green. A
    ``core.hooksPath`` still naming a directory that has since been removed
    is how a repository arrives here.

    Absence is the signal rather than the count of hooks inside, because an
    empty hooks directory is the normal state of a fresh clone and says
    nothing about whether this repository's own guards belong in it.
    """

    guards: list[GuardState]

    def unarmed(self) -> list[GuardState]:
        """Each declared moment this checkout would not currently guard.

        Reported rather than refused: a clone that never ran the install
        command is a working clone, and the pipeline refuses the same drift
        and the same gate on the way in.
        """
        return [state for state in self.guards if not state.armed]


def read_hooks(guards: list[GitGuard], root: Path) -> HooksReading:
    """Where `root` resolves its hooks, and the state of each moment declared for it."""
    directory = hooks_directory(root)
    return HooksReading(
        directory=directory,
        reachable=directory.is_dir(),
        guards=[guard_state(script, directory) for script in hook_scripts(guards)],
    )


# lup: ignore[model-free-function] — driver: it writes the hook file
def install_script(
    script: HookScript, root: Path, *, force: bool = False
) -> GuardState:
    """Write one moment's hook, refusing to displace one written elsewhere."""
    directory = hooks_directory(root)
    existing = guard_state(script, directory)
    if existing.status == "foreign" and not force:
        raise GuardConflict(
            f"{existing.path} holds a hook this did not write; read it, then pass "
            "--force to replace it"
        )
    directory.mkdir(parents=True, exist_ok=True)
    existing.path.write_text(script.body(), encoding="utf-8", newline="\n")
    existing.path.chmod(0o755)
    return guard_state(script, directory)


def install_guards(
    guards: list[GitGuard], root: Path, *, force: bool = False
) -> list[GuardState]:
    """Install every moment these guards declare, each as the one file git runs."""
    return [
        install_script(script, root, force=force) for script in hook_scripts(guards)
    ]


# lup: ignore[model-free-function] — driver: it removes the hook file
def uninstall_script(script: HookScript, root: Path) -> GuardState:
    """Remove one moment's hook, leaving one written elsewhere alone."""
    state = guard_state(script, hooks_directory(root))
    match state.status:
        case "current" | "stale":
            state.path.unlink()
            return GuardState(path=state.path, status="absent")
        case "absent" | "foreign":
            return state


def uninstall_guards(guards: list[GitGuard], root: Path) -> list[GuardState]:
    """Remove every moment these guards declare, leaving foreign hooks alone."""
    return [uninstall_script(script, root) for script in hook_scripts(guards)]


def arm(guards: list[GitGuard], root: Path) -> list[str]:
    """Install each moment where a setup command can only report a failure.

    Worktree creation runs under sandboxes that mount the hooks directory
    read-only, and a checkout without the hooks is still a working checkout —
    the pipeline refuses the same drift and the same gate on the way in. So
    this says what happened and lets setup carry on, rather than failing it
    over a second line of defence.

    Each moment is reported on its own line and none stops the next: they
    guard different moments, and one hook path already occupied is no reason
    to leave the other unarmed.
    """

    def armed(script: HookScript) -> str:
        try:
            return install_script(script, root).describe()
        except (OSError, GuardConflict, sh.ErrorReturnCode) as error:
            return f"{script.hook} guard not installed: {error}"

    return [armed(script) for script in hook_scripts(guards)]
