"""The README capability matrix must match the adapter declarations.

This is what turns the parity matrix from prose into a contract: change
a capability declaration and this test fails until the README table is
regenerated, so documentation cannot drift from code.
"""

from lup.adapters.common import (
    canonical_capability_matrix,
    capability_matrix_markdown,
)
from lup.paths import project_root


def test_readme_capability_matrix_is_current() -> None:
    readme = (project_root() / "README.md").read_text(encoding="utf-8")
    expected = capability_matrix_markdown(canonical_capability_matrix())

    assert expected in readme, (
        "README capability matrix is stale. Regenerate with "
        "`uv run lup-devtools agent capabilities --markdown` and paste it "
        "into the Backend support section."
    )
