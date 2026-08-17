"""Shared test fixtures.

Add fixtures here that are used across multiple test files.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from lup.gitguard import guard_report, repository_state


@pytest.fixture(scope="session", autouse=True)
def enclosing_repository_untouched() -> Iterator[None]:
    """Fail the session if it wrote into the checkout it is running inside.

    Autouse and session-scoped because the failure it catches is one no test
    can be asked to notice: a fixture that binds git to the working directory
    instead of its own throwaway repository commits successfully, passes, and
    leaves the developer's branch moved. See :mod:`lup.gitguard` for how that
    was found here, and what it cost.
    """
    root = Path(__file__).resolve().parent.parent
    before = repository_state(root)
    yield
    report = guard_report(before, repository_state(root))
    if report:
        pytest.fail(report, pytrace=False)
