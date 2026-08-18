"""Where a project's own environment is, and how to reach the programs in it.

`uv run lup-devtools ...` is the entry point everywhere it can be used,
because parsing the manifest is how it guarantees the environment it starts
in. Two places cannot use it, and both are about the same failure: the
conflict workflow exists to repair a merge that left `pyproject.toml`
unparseable, so every command that would parse it first is already broken —
and the guidance documenting those commands has to name a spelling that
works there.

What that spelling is differs per project, and the only wrong answer is to
pick one. A repository-relative path is right exactly while the environment
lives inside the checkout, which is what `uv` does by default and what
nothing else does: a conda environment, a pyenv version, a system or
user-level install, and `UV_PROJECT_ENVIRONMENT` all put it somewhere no
path relative to the project can name. Writing one in anyway is not a
default a project can override — it is a workflow that silently does not
exist for anybody outside one layout.

So the project answers instead, and is asked each time rather than described
once. Where its environment is and what is installed there are both facts on
disk, and reading them costs a `stat` — which is less than the guidance it
replaces cost anybody who did not match the layout it assumed.
"""

import os
import sys
from pathlib import Path

# lup: ignore[constant-declaration] — uv's own variable name, not a judgement
ENVIRONMENT_VARIABLE = "UV_PROJECT_ENVIRONMENT"
"""What `uv` reads to put a project's environment somewhere other than `.venv`."""

# lup: ignore[constant-declaration] — the directory name uv creates by default
DEFAULT_ENVIRONMENT = ".venv"
"""Where `uv sync` writes an environment when nothing redirects it."""


def project_environment(root: Path) -> Path:
    """Where a sync puts *root*'s environment.

    ``.venv`` beside the manifest is `uv`'s default and this project's own
    layout, but it is a default rather than the answer:
    ``UV_PROJECT_ENVIRONMENT`` redirects it, which is how one environment gets
    shared across worktrees, kept off a slow filesystem, or placed where a
    container expects it. A relative value resolves against the project, the
    way `uv` resolves it, rather than against whatever directory a command
    happened to run in.
    """
    environ = os.environ  # lup: ignore[os-environ] — uv's own configuration
    declared = (
        environ[ENVIRONMENT_VARIABLE] if ENVIRONMENT_VARIABLE in environ else ""
    ).strip()
    if not declared:
        return root / DEFAULT_ENVIRONMENT
    return Path(declared) if Path(declared).is_absolute() else root / declared


CONSOLE_SCRIPT = "lup-devtools"
"""The entry point this package installs, named in its own packaging metadata."""


def console_script(root: Path, name: str = CONSOLE_SCRIPT) -> Path | None:
    """Where *root*'s own environment installs *name*, if it is there.

    Asked of the project rather than of the running interpreter, because they
    are not always the same project: a notice about one checkout can be
    printed by a program started from another, and the answer has to be about
    the checkout in question.

    The directory the scripts sit in comes from the interpreter all the same —
    ``bin`` on POSIX and ``Scripts`` on Windows — because that is a property
    of how Python is installed rather than of any project, and reading it is
    what keeps this from being a second layout assumption behind the one it
    replaces.
    """
    candidate = project_environment(root) / Path(sys.executable).parent.name / name
    return candidate if candidate.is_file() else None


def launcher_invocation(root: Path, name: str = CONSOLE_SCRIPT) -> str:
    """How to spell reaching *name* from *root* when `uv` cannot start.

    Inside the checkout it is named by its path, because a ``PATH`` lookup
    would let a sibling worktree's environment answer for this one — every
    checkout has its own, they are interchangeable to a search path, and the
    wrong one is wrong silently. That hazard is what a path spelling exists
    to avoid, and it exists only where environments are per-checkout.

    Anywhere else, the bare name. A shared environment is reached through
    ``PATH`` by design — activating it is what a conda or pyenv user does
    before running anything — and there is no per-checkout copy for the
    lookup to pick between. An absolute path would be worse than useless: it
    is one machine's, and nothing here knows whether the string is about to
    be printed once or written into something a project shares.
    """
    found = console_script(root, name)
    if found is None:
        return name
    try:
        return found.relative_to(root).as_posix()
    except ValueError:
        return name
