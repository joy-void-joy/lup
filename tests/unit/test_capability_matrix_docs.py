"""The README capability matrix must match the probed adapter behavior.

This is what turns the parity matrix from prose into a contract: change
what an adapter refuses or supports and this test fails until the README
table is regenerated, so documentation cannot drift from code.
"""

from lup.adapters.capabilities import (
    canonical_capability_matrix,
    capability_matrix_markdown,
)
from lup.workspace.paths import project_root


def test_readme_capability_matrix_is_current() -> None:
    readme = (project_root() / "README.md").read_text(encoding="utf-8")
    expected = capability_matrix_markdown(canonical_capability_matrix())

    assert expected in readme, (
        "README capability matrix is stale. Regenerate with "
        "`uv run lup-devtools agent capabilities --markdown` and paste it "
        "into the runtime capability section."
    )


def test_probed_matrix_is_consistent() -> None:
    """Every adapter column probes the same rows, and known facts hold."""
    matrix = canonical_capability_matrix()

    assert [entry.name for entry in matrix] == [
        "claude-sdk-0.2.89",
        "codex-app-server-0.144.4",
    ]
    rows = [cell.capability for cell in matrix[0].cells]
    for entry in matrix:
        assert [cell.capability for cell in entry.cells] == rows

    by_name = {
        entry.name: {cell.capability: cell.value for cell in entry.cells}
        for entry in matrix
    }
    assert by_name["claude-sdk-0.2.89"]["live_events"] is True
    assert by_name["codex-app-server-0.144.4"]["live_events"] is True
    assert by_name["claude-sdk-0.2.89"]["interrupt"] is True
    assert by_name["codex-app-server-0.144.4"]["fork"] is True
    assert by_name["claude-sdk-0.2.89"]["fork"] is True
