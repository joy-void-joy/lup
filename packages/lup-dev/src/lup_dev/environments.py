#!/usr/bin/env python3
"""Each worktree's environment in a room, the launch's own: the one rule placing it, and the program telling the runner's tools.

`docs/launch.md`, *The project's environment, the room's own*. A room's
environment of each worktree is made in its launch's own directory of
environments, outside the repository and beside the package cache of the
project's rooms, in one mount, so its files are links into the cache.
`environment` places it, from the worktree's root as git names it: the launch,
the room's own `lup-dev` and the host's judge each derive it from here, the room
by running this module's source.

In the room, this file is `lup-environment` among the launch's commands, first
on the `PATH`, and each program the runner names (`uv`) links to it:
- **Run as one of those programs,** it asks git for the worktree holding the
  working directory, as the judge asks it of a path (`git rev-parse
  --show-toplevel --git-common-dir`). In a worktree of the launch's repository,
  it sets the variable the runner names (`UV_PROJECT_ENVIRONMENT`) to that
  worktree's environment; elsewhere (a scratch project in `/tmp`, a test's own
  repository) it drops one inherited, so the program makes its own as it would.
  Then it runs the next program of its name on the `PATH` in its own place. A
  worktree made during the launch, by `git worktree add` or by lup's hooks,
  needs nothing more. A `--directory` or `--project` naming another worktree
  still gets the working directory's environment: run it from there.
- **Run as `lup-environment`,** before the runtime's CLI, it starts the
  runner's command making the working directory's environment in the
  background, detached from the terminal, its output kept beside the
  environment, then runs the CLI in its own place, so the session's start waits
  for nothing. Where that command fails, the next of the runner's programs run
  in that worktree says so on its standard error, once.

The launch names its environments, the variable and its repository in the
room's variables (`ENVIRONMENTS`, `VARIABLE`, `REPOSITORY`). The room's Python
runs this with the standard library alone (an import contract keeps it so).
"""

import hashlib
import json
import os

# lup: ignore("subprocess", why="the room's Python runs the program on the standard library alone, without lup's `programs`")
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ENVIRONMENTS = "LUP_ENVIRONMENTS"
"""The room's variable naming the launch's environments, one per worktree."""
VARIABLE = "LUP_ENVIRONMENT_VARIABLE"
"""The room's variable naming the one the runner's tools read their environment from."""
REPOSITORY = "LUP_REPOSITORY"
"""The room's variable naming the launch's repository, by its git directory."""
STARTER = "lup-environment"
"""The program's own name, and what it's run as before the runtime's CLI."""

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
"""A JSON value, as the starter's command is written."""


def environment(environments: Path, worktree: Path) -> Path:
    """Return where the environment of the worktree whose root is `worktree` is made among a launch's `environments`.

    A directory named by the worktree's own name, which says whose it is, and a
    digest of its path, so two worktrees of one name each have their own.

    >>> environment(Path("/rooms/lup/environments/0f3a"), Path("/srv/lup.git/tree/dev"))
    PosixPath('/rooms/lup/environments/0f3a/dev-2c2ec406aca691f1')
    """
    digest = hashlib.blake2b(str(worktree).encode(), digest_size=8).hexdigest()
    return environments / f"{worktree.name}-{digest}"


def log(environment: Path) -> Path:
    """Return where what making `environment` at the room's start printed is kept, beside it."""
    return environment.with_name(f"{environment.name}.log")


def failure(environment: Path) -> Path:
    """Return where making `environment` at the room's start leaves its status where it failed, until it's said."""
    return environment.with_name(f"{environment.name}.failed")


def failed(reason: str) -> SystemExit:
    """Return the exit that ends the program, saying `reason` on its standard error."""
    return SystemExit(f"lup: {reason}")


def worktree(directory: Path, repository: Path) -> Path | None:
    """Return the root of the worktree holding `directory`, as git names it, where it's a worktree of the repository whose git directory is `repository`; none elsewhere."""
    try:
        ran = subprocess.run(
            [
                "git",
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-common-dir",
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    named = ran.stdout.splitlines()
    if ran.returncode != 0 or len(named) != 2:
        return None
    root, common = named
    return Path(root) if Path(common) == repository else None


def placed(environ: dict[str, str]) -> Path | None:
    """Return the environment of the worktree of the launch's repository holding the working directory, as `environ` names the launch's places; none outside one, or where they're unnamed."""
    environments = environ.get(ENVIRONMENTS)
    repository = environ.get(REPOSITORY)
    if not environments or not repository:
        return None
    try:
        here = Path.cwd()
    except FileNotFoundError:
        return None
    root = worktree(here, Path(repository))
    return None if root is None else environment(Path(environments), root)


def told(made: Path) -> None:
    """Say, on the standard error, that making `made` at the room's start failed, where it did and that wasn't said yet."""
    marker = failure(made)
    try:
        status = marker.read_text().strip()
        marker.unlink()
    except FileNotFoundError:
        return
    sys.stderr.write(
        f"lup: making this worktree's environment at the room's start failed "
        f"(status {status}); what it printed is in {log(made)}.\n"
    )


def wrapped(program: str, arguments: list[str], environ: dict[str, str]) -> NoReturn:
    """Run the next `program` on the `PATH` in this one's place, with `arguments`, told the environment of the worktree it runs in."""
    variable = environ.get(VARIABLE)
    if variable:
        environ.pop(variable, None)
        made = placed(environ)
        if made is not None:
            environ[variable] = str(made)
            told(made)
    own = Path(__file__).resolve()
    candidates = [Path(each) / program for each in os.get_exec_path(environ)]
    found = next(
        (
            each
            for each in candidates
            if each.is_file() and os.access(each, os.X_OK) and each.resolve() != own
        ),
        None,
    )
    if found is None:
        message = f"no `{program}` on the `PATH` beside lup's, which runs it"
        raise failed(message)
    # lup: ignore("os-shell", why="the program stands in for the runner's own, so it runs that one in its place, its status the caller's to read")
    os.execve(found, [program, *arguments], environ)


def making(command: list[str], made: Path, environ: dict[str, str]) -> None:
    """Start `command`, which makes the environment `made`, in the background, detached from the terminal, and return at once.

    It runs in a grandchild in a session of its own, its standard input
    nothing and its output `log`, so the terminal neither reaches it nor waits
    for it, and the room's init adopts it once its parent ends, so it waits
    under no program that doesn't reap it. A failure leaves its status at
    `failure`.
    """
    made.parent.mkdir(parents=True, exist_ok=True)
    failure(made).unlink(missing_ok=True)
    child = os.fork()
    if child:
        os.waitpid(child, 0)
        return
    try:
        os.setsid()
        if os.fork():
            return
        with log(made).open("wb") as out, Path(os.devnull).open("rb") as nothing:
            for source, stream in [(nothing, 0), (out, 1), (out, 2)]:
                os.dup2(source.fileno(), stream)
            try:
                status = subprocess.run(command, env=environ, check=False).returncode
            except OSError as unstarted:
                out.write(f"lup: `{command[0]}` didn't start: {unstarted}\n".encode())
                status = 127
        if status != 0:
            failure(made).write_text(f"{status}\n")
    finally:
        # The children never return to run the CLI: only the program started does.
        os._exit(0)


def started(arguments: list[str], environ: dict[str, str]) -> NoReturn:
    """Start making the working directory's environment in the background with the command `arguments` gives first, as a JSON list, then run the rest in this program's place.

    No command, or no worktree of the launch's repository here, starts nothing.
    """
    if len(arguments) < 2:
        message = f"`{STARTER}` takes a command as a JSON list, then the program to run"
        raise failed(message)
    first, *rest = arguments
    try:
        given: Json = json.loads(first)
    except json.JSONDecodeError as unreadable:
        message = f"`{STARTER}`'s first argument isn't JSON: {first!r}"
        raise failed(message) from unreadable
    command = (
        [each for each in given if isinstance(each, str)]
        if isinstance(given, list)
        else None
    )
    if command is None or (isinstance(given, list) and len(command) != len(given)):
        message = f"`{STARTER}`'s first argument isn't a list of words: {first!r}"
        raise failed(message)
    made = placed(environ) if command else None
    if command and made is not None:
        making(command, made, environ)
    # lup: ignore("os-shell", why="the runtime's CLI runs in this program's place, so the room's init holds it as it would without lup's start")
    os.execvpe(rest[0], rest, environ)


def main() -> None:
    """Act as the program this is run as: `lup-environment` before the CLI, else the runner's program of that name."""
    # lup: ignore("os-environ", why="the program's work is the variables it hands the runner's tools, read and passed on whole, on the room's Python, where pydantic-settings isn't")
    environ = dict(os.environ)
    program = Path(sys.argv[0]).name
    if program == STARTER:
        started(sys.argv[1:], environ)
    wrapped(program, sys.argv[1:], environ)


if __name__ == "__main__":
    main()
