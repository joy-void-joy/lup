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
change.
"""

from pathlib import Path
from typing import Literal

import sh
from pydantic import BaseModel

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

    refusal: str = (
        "Refuses this commit while a generated artifact differs from what\n"
        f"# its source renders. Settle it with `{REGENERATE_COMMAND}`."
    )
    """What the installed hook tells whoever it just stopped.

    A hook that only exits nonzero leaves its reader guessing which check
    fired and what settles it, and the script is the one place that reader
    is certainly looking.
    """

    def body(self) -> str:
        """The hook script: the marker that claims it, then the check itself."""
        return (
            "#!/bin/sh\n"
            f"# {GUARD_MARKER}: written by `{INSTALL_COMMAND}`.\n"
            f"# {self.refusal}\n"
            f"exec {self.command}\n"
        )


DECLARED_GUARDS = [
    GitGuard(),
    GitGuard(
        command=CHECK_COMMAND,
        hook="pre-push",
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


type GuardStatus = Literal["current", "stale", "absent", "foreign"]
"""What sits at the hook path, judged against what this guard would write."""


class GuardState(BaseModel, frozen=True):
    """Where one of a repository's guards lives and what is actually there."""

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
# GitGuard is the declaration of which hook rather than the thing that reads
def guard_state(guard: GitGuard, directory: Path) -> GuardState:
    """Read what is installed at the guard's hook path."""
    path = directory / guard.hook
    if not path.is_file():
        return GuardState(path=path, status="absent")
    installed = path.read_text(encoding="utf-8")
    if not any(marker in installed for marker in (GUARD_MARKER, LEGACY_GUARD_MARKER)):
        return GuardState(path=path, status="foreign")
    current = installed == guard.body()
    return GuardState(path=path, status="current" if current else "stale")


# lup: ignore[model-free-function] — driver: the same disk read, resolved from a
# checkout root
def read_guard(guard: GitGuard, root: Path) -> GuardState:
    """What one checkout would run, or fail to run, at this guard's moment."""
    return guard_state(guard, hooks_directory(root))


# lup: ignore[model-free-function] — driver: it writes the hook file
def install_guard(guard: GitGuard, root: Path, *, force: bool = False) -> GuardState:
    """Write the hook, refusing to displace one this command did not write."""
    directory = hooks_directory(root)
    existing = guard_state(guard, directory)
    if existing.status == "foreign" and not force:
        raise GuardConflict(
            f"{existing.path} holds a hook this did not write; read it, then pass "
            "--force to replace it"
        )
    directory.mkdir(parents=True, exist_ok=True)
    existing.path.write_text(guard.body(), encoding="utf-8", newline="\n")
    existing.path.chmod(0o755)
    return guard_state(guard, directory)


# lup: ignore[model-free-function] — driver: it removes the hook file
def uninstall_guard(guard: GitGuard, root: Path) -> GuardState:
    """Remove the hook, leaving one this command did not write alone."""
    state = read_guard(guard, root)
    match state.status:
        case "current" | "stale":
            state.path.unlink()
            return GuardState(path=state.path, status="absent")
        case "absent" | "foreign":
            return state


def arm(guards: list[GitGuard], root: Path) -> list[str]:
    """Install each guard where a setup command can only report a failure.

    Worktree creation runs under sandboxes that mount the hooks directory
    read-only, and a checkout without the hooks is still a working checkout —
    the pipeline refuses the same drift and the same gate on the way in. So
    this says what happened and lets setup carry on, rather than failing it
    over a second line of defence.

    Each guard is reported on its own line and none stops the next: they
    guard different moments, and one hook path already occupied is no reason
    to leave the other unarmed.
    """

    def armed(guard: GitGuard) -> str:
        try:
            return install_guard(guard, root).describe()
        except (OSError, GuardConflict, sh.ErrorReturnCode) as error:
            return f"{guard.hook} guard not installed: {error}"

    return [armed(guard) for guard in guards]
