"""Shared fixtures for the library's own suite.

Separate from the template's `tests/conftest.py` and deliberately not importing
it: a library test reaching for a template fixture passes here and fails where
the library ships.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from lup.gitguard import TEST_IDENTITY, guard_report, repository_state


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
    before = repository_state(root)
    yield
    report = guard_report(before, repository_state(root))
    if report:
        pytest.fail(report, pytrace=False)
