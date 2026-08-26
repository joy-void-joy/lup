"""Shared test fixtures.

Add fixtures here that are used across multiple test files.
"""

import os
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

from lup.devtools.gitguard import TEST_IDENTITY, ForeignCheckouts, repository_state
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
def enclosing_repository_untouched() -> Iterator[None]:
    """Fail the session if it wrote into the checkout it is running inside.

    Autouse and session-scoped because the failure it catches is one no test
    can be asked to notice: a fixture that binds git to the working directory
    instead of its own throwaway repository commits successfully, passes, and
    leaves the developer's branch moved. See :mod:`lup.devtools.gitguard` for how that
    was found here, and what it cost.
    """
    root = Path(__file__).resolve().parent.parent
    foreign = ForeignCheckouts.beside(root)
    before = repository_state(root)
    yield
    verdict = foreign.verdict(before, repository_state(root))
    if verdict.notice:
        warnings.warn(verdict.notice, stacklevel=1)
    if verdict.failure:
        pytest.fail(verdict.failure, pytrace=False)
