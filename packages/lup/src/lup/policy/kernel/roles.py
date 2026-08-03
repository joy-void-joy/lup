"""What a repository path is for, and which gates that answer relaxes.

The lattice judges an action by what it does. A role adds the missing half:
what the thing acted upon is *for*. Production code carries the conventions
because other code reads it; a test carries none of them because its subject
is production's behaviour rather than its own shape; scratch carries nothing
at all because every file there is disposable by construction.

Roles are declared by the application, never the kernel — the path vocabulary
belongs to whoever laid out the repository. The kernel only resolves a path
against the declared roots.
"""

import posixpath

from .rows import PathRoleName, PathRoleRow


def path_role(path: str, rows: list[PathRoleRow]) -> PathRoleName:
    """Classify a repository-relative path by the role its root declares.

    Resolution is lexical, so it needs no filesystem call and ``..`` cannot
    climb out of a declared root into a role it was never given. A symlink
    inside a root that points beyond it is not settleable without a syscall
    and stays a known limit; it is narrow, because a role only ever relaxes
    verbs acting on paths already inside the root and never grants execution.
    """
    normalized = posixpath.normpath(path)
    if normalized.startswith(("/", "../")) or normalized == "..":
        return "production"
    for row in rows:
        root = posixpath.normpath(row["root"])
        if normalized == root or normalized.startswith(root + "/"):
            return row["role"]
    return "production"
