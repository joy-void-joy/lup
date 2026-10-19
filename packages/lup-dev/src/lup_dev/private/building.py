"""Building a repository's list from its declaration resolved: at a launch, and wherever the host finds none.

`docs/private.md`, *What's on the list*. A launch builds it; so does the host
where a launch it serves has none, as one started before `Private` was
approved has: the judge at a write, and the gate on the host, each from the
declaration at the approved commit, as the launch reads it. The module's own
hook and handler build it from their module and the repositories the worker
found (`lup_dev.private.hooks`, `lup_dev.private.scanning`).
"""

from typing import TYPE_CHECKING

from lup_dev.private.module import Private
from lup_dev.private.withheld import Built, Facts, kept, prepared, related_of

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.declaration.resolve import Resolved
    from lup_dev.layout import Layout


def chosen(resolved: Resolved) -> Private | None:
    """Return the `Private` module a declaration selects, every layer applied; none where it doesn't."""
    return next((each for each in resolved.modules if isinstance(each, Private)), None)


async def listed(
    resolved: Resolved, repository: Path, facts: Facts, layout: Layout
) -> Built | None:
    """Build the list for the repository whose git directory is `repository` from its declaration `resolved`, and keep it where the module reads it; where the declaration doesn't select `Private`, remove the one kept and return none.

    Raise `LupDevError` or `OSError` where the host can't be read.
    """
    data = layout.module_data(Private.name, repository)
    private = chosen(resolved)
    if private is None:
        kept(data).unlink(missing_ok=True)
        return None
    return await prepared(
        facts,
        repository,
        related=related_of(resolved.repositories, repository),
        details=private.chosen_details(),
        values=private.chosen_values(),
        data=data,
    )
