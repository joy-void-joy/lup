"""Whether git can still take the lock its config writes need.

Every config write goes through `config.lock`: git creates it exclusively,
writes the new config beside it, and renames over the old one. A sandbox that
bind-mounts `/dev/null` over that path and mounts `config` read-only leaves
the create failing, and git reports the failure as `File exists` — which is
also how it reports a lock a crashed process forgot to delete. The two read
identically and only one of them has a file to remove, so what separates them
is the mount state, which is observable here and nowhere in git's words.
"""

import os
import stat
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel


def on_read_only_mount(path: Path) -> bool:
    """Whether the mount holding a path is itself mounted read-only."""
    return path.exists() and bool(os.statvfs(path).f_flag & os.ST_RDONLY)


def refuses_a_new_file(directory: Path) -> bool:
    """Whether a directory refuses the lock file a config write has to create.

    Creating is the permission the lock protocol needs, and creating is the
    directory's permission rather than the config's: git writes `config.lock`
    beside `config` and renames over it, so a `config` nobody may write is
    still rewritten inside a directory they may. Asking the mode bits of the
    config instead would call a plain `chmod 444` a sandbox.
    """
    if not directory.exists():
        return False
    return not os.access(directory, os.W_OK) or on_read_only_mount(directory)


def is_device_node(path: Path) -> bool:
    """Whether a path is a device where git expects a regular file of its own."""
    if not path.exists():
        return False
    mode = path.stat().st_mode
    return stat.S_ISCHR(mode) or stat.S_ISBLK(mode)


class GitLockState(BaseModel):
    """What one git admin directory says about its own lock protocol."""

    read_only_config: bool
    unwritable_admin: bool
    device_locks: list[Path]

    @property
    def blocked(self) -> bool:
        """Whether a config write can still acquire the lock it needs here."""
        return self.read_only_config or self.unwritable_admin or bool(self.device_locks)

    def diagnosis(self) -> str:
        """What to tell a reader, empty where git's lock protocol can run.

        The evidence is named because it is the part git could not have
        reported, and the stale lock is denied explicitly because that is the
        search the unaided message sends a reader on.
        """
        if not self.blocked:
            return ""
        evidence = ", ".join(
            [
                *(
                    ["`config` is on a read-only mount"]
                    if self.read_only_config
                    else []
                ),
                *(
                    ["the admin directory refuses a new `config.lock`"]
                    if self.unwritable_admin
                    else []
                ),
                *[f"`{path.name}` is a device node" for path in self.device_locks],
            ]
        )
        return (
            f"git config writes are blocked by the sandbox ({evidence}), so no "
            "config write can take its lock. `File exists` names that mount, "
            "not a stale lock — there is none to delete. Rerun outside the "
            "sandbox."
        )


def inspect_git_admin(
    git_dir: Path,
    written_names: Sequence[str] = ("config.lock", "config.worktree"),
) -> GitLockState:
    """Read one git admin directory's lock protocol off the filesystem.

    `written_names` are the paths a config write has to find as files of its
    own, and therefore the ones a sandbox shadows to stop it; a confinement
    that shadows others names them.
    """
    return GitLockState(
        read_only_config=on_read_only_mount(git_dir / "config"),
        unwritable_admin=refuses_a_new_file(git_dir),
        device_locks=[
            git_dir / name for name in written_names if is_device_node(git_dir / name)
        ],
    )


def admin_dirs(root: Path, named: Sequence[str]) -> list[Path]:
    """The distinct directories ``git rev-parse`` named, resolved against a root."""
    return list(dict.fromkeys((root / line).resolve() for line in named if line))


def diagnose_git_admin(git_dirs: Sequence[Path]) -> str:
    """The first diagnosis any of a checkout's admin directories gives.

    A linked worktree has two, and both have to be read: `config` and its
    lock live in the common directory every worktree shares, while
    `config.worktree` lands in the worktree's own once a repository turns
    per-worktree configuration on.
    """
    diagnoses = [inspect_git_admin(git_dir).diagnosis() for git_dir in git_dirs]
    return next((diagnosis for diagnosis in diagnoses if diagnosis), "")
