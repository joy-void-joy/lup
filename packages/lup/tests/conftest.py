"""Shared fixtures for the library's own suite.

Separate from the template's `tests/conftest.py` and deliberately not importing
it: a library test reaching for a template fixture passes here and fails where
the library ships.
"""

import os
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

from lup.devtools.gitguard import TEST_IDENTITY, GuardVerdict, RepositoryWatch
from lup.harness.environment import launcher_decided_names


@pytest.fixture(scope="session", autouse=True)
def launcher_decisions_taken_away() -> Iterator[None]:
    """Measure the code, not the session this suite happens to run in.

    Autouse and session-scoped for the same reason as the guard below: no
    test can be asked to notice it. A variable the launcher set answers the
    question a test meant to put to the code, and answers it consistently —
    so the test passes on the machine that wrote it, and fails inside the
    container that machine builds, which is where every one of these was
    found. See :func:`~lup.harness.environment.launcher_decided_names`.
    """
    with pytest.MonkeyPatch.context() as environment:
        for name in launcher_decided_names(os.environ):
            environment.delenv(name, raising=False)
        yield


@pytest.fixture(scope="session", autouse=True)
def committer_identity_armed() -> Iterator[None]:
    """Give every throwaway repository somebody to commit as, writing no file.

    Session-scoped and autouse because the git commands that need it are not
    all the suite's own: a resolver under test runs its own `git commit`, and
    reaches whatever the environment holds. See :mod:`lup.devtools.gitguard`.
    """
    with pytest.MonkeyPatch.context() as environment:
        for name, value in TEST_IDENTITY.environment().items():
            environment.setenv(name, value)
        yield


@pytest.fixture(scope="session", autouse=True)
def enclosing_repository_watched() -> Iterator[RepositoryWatch]:
    """Read the checkout this suite runs inside before its first test and after its last.

    The same guard the template suite arms, for the same reason: this suite
    builds throwaway repositories too, and a fixture that forgets to bind git
    to one reaches the developer's checkout instead. See :mod:`lup.devtools.gitguard`.
    Under xdist each worker is a session of its own over one shared ref
    store, so the watch carries the worker's name for its report to say who
    saw what.
    """
    root = Path(__file__).resolve().parents[3]
    watch = RepositoryWatch.armed(root, os.environ.get("PYTEST_XDIST_WORKER", "main"))
    yield watch
    settled(watch.after("the teardown after this worker's last test"))


@pytest.fixture(autouse=True)
def enclosing_repository_untouched(
    enclosing_repository_watched: RepositoryWatch, request: pytest.FixtureRequest
) -> Iterator[None]:
    """Fail the test whose window saw the checkout change, not whichever ran last.

    Function-scoped so the comparison closes around one test: a difference
    closed once per session lands under xdist on the last test the noticing
    worker ran, which is a policy row about `gh pr create` as easily as the
    fixture that escaped.
    """
    yield
    settled(enclosing_repository_watched.after(request.node.nodeid))


def settled(verdict: GuardVerdict) -> None:
    """Say what a sibling worktree moved, and fail on what this run moved."""
    if verdict.notice:
        warnings.warn(verdict.notice, stacklevel=2)
    if verdict.failure:
        pytest.fail(verdict.failure, pytrace=False)
