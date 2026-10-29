"""The ledger's tests' fixtures: a ledger in the test's own directory, and its threads."""

from typing import TYPE_CHECKING

import pytest

from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.environment.threads import Threads

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture
def ledger(tmp_path: Path) -> Generator[Ledger]:
    opened = Ledger.opened(LedgerLayout(home=tmp_path / "ledger"))
    yield opened
    opened.close()


@pytest.fixture
def threads(ledger: Ledger) -> Threads:
    return Threads(ledger=ledger)
