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

from lup.gitguard import TEST_IDENTITY, ForeignCheckouts, repository_state
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
    reaches whatever the environment holds. See :mod:`lup.gitguard`.
    """
    with pytest.MonkeyPatch.context() as environment:
        for name, value in TEST_IDENTITY.environment().items():
            environment.setenv(name, value)
        yield


@pytest.fixture(scope="session", autouse=True)
def enclosing_repository_untouched() -> Iterator[None]:
    """Fail the session if it wrote into the checkout it is running inside.

    The same guard the template suite arms, for the same reason: this suite
    builds throwaway repositories too, and a fixture that forgets to bind git
    to one reaches the developer's checkout instead. See :mod:`lup.gitguard`.
    """
    root = Path(__file__).resolve().parents[3]
    foreign = ForeignCheckouts.beside(root)
    before = repository_state(root)
    yield
    verdict = foreign.verdict(before, repository_state(root))
    if verdict.notice:
        warnings.warn(verdict.notice, stacklevel=1)
    if verdict.failure:
        pytest.fail(verdict.failure, pytrace=False)
