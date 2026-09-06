"""Behavior tests for the wrapper that opens one actor inside its container.

The two that carry the module are about the wrapper's argument handling: that
what this writes is quoted and what the runtime appends is not. Getting either
backwards produces a container that starts and an agent that reads one long
argument where it expected flags -- which fails somewhere else entirely.
"""

import os
import stat
from pathlib import Path

from lup.devtools.harness.contained import (
    engine_absence,
    worker_wrapper_path,
    wrapper_script,
    written_wrapper,
)


def test_a_wrapper_execs_rather_than_calls() -> None:
    """So the container replaces the shell instead of running under it.

    What the runtime holds is then the engine's own process, and a signal sent
    to the actor reaches the thing actually running rather than a parent that
    would have to forward it.
    """
    written = wrapper_script(["podman", "run"], "claude")
    assert written.splitlines()[-1].startswith("exec ")


def test_a_wrapper_names_the_program_after_the_container_arguments() -> None:
    """The argv opens a container; the program is what runs inside it."""
    written = wrapper_script(["podman", "run", "--rm", "image"], "claude")
    assert written.rstrip().endswith('image claude "$@"')


def test_a_wrapper_leaves_the_runtime_s_own_arguments_unquoted() -> None:
    """`"$@"` expands to the flags the runtime appended, one word each.

    Folded into a single quoted word instead, the CLI would receive one long
    argument rather than the arguments it was given -- and would fail on its
    own command line, naming nothing about this wrapper.
    """
    assert '"$@"' in wrapper_script(["podman"], "claude")


def test_a_wrapper_quotes_what_it_writes_itself() -> None:
    """A path with a space in it is one argument, not two."""
    written = wrapper_script(["podman", "run", "-v", "/a path:/a path"], "claude")
    assert "'/a path:/a path'" in written


def test_a_wrapper_carries_the_program_it_was_given(tmp_path: Path) -> None:
    """A CLI's own name is its provider's, so it arrives rather than defaulting.

    A wrapper built for one runtime and pointed at the other would start a
    container running the wrong agent and report nothing unusual.
    """
    assert wrapper_script(["podman"], "codex").rstrip().endswith('codex "$@"')


def test_a_written_wrapper_is_executable(tmp_path: Path) -> None:
    """Being named as a program means the runtime spawns this path directly.

    Without the bit set it fails as a permission error naming a path, which
    reads as a broken install rather than as a file written a moment ago.
    """
    path = written_wrapper(tmp_path / "workers" / "one.sh", ["podman", "run"], "claude")
    assert path.stat().st_mode & stat.S_IXUSR
    assert os.access(path, os.X_OK)


def test_a_written_wrapper_creates_the_directory_it_is_asked_for(
    tmp_path: Path,
) -> None:
    """The run directory holds no `workers/` until the first actor opens."""
    path = written_wrapper(
        tmp_path / "deep" / "workers" / "one.sh", ["podman"], "codex"
    )
    assert path.exists()


def test_two_actors_on_one_concern_get_separate_wrappers(tmp_path: Path) -> None:
    """A worker and the reviewer judging it differ in exactly their lease.

    Named for the concern alone they would share a filename, and the second to
    open would run under the first one's mounts -- a reviewer with a writable
    tree, or a worker with none, either arriving as an unexplained refusal.
    """
    assert worker_wrapper_path(tmp_path, "c1", "worker") != worker_wrapper_path(
        tmp_path, "c1", "reviewer"
    )


def test_an_absent_engine_is_reported_as_the_engine(tmp_path: Path) -> None:
    """The refusal is about the client, not about this session's own posture.

    A contained operator has no engine and neither does a host that never
    installed one; both need the same thing done about them, so the question is
    asked of the client rather than of which side of a boundary this stands on.
    """
    absence = engine_absence()
    assert absence is None or "container client" in absence
