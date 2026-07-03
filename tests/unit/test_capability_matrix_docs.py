"""The README capability matrix must match the adapter declarations.

This is what turns the parity matrix from prose into a contract: change
a capability declaration and this test fails until the README table is
regenerated, so documentation cannot drift from code.
"""

from lup.adapters.matrix import (
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
        "into the Engine support section."
    )


def test_probed_matrix_is_consistent() -> None:
    """Every engine column probes the same rows, and known facts hold."""
    matrix = canonical_capability_matrix()

    assert [entry.name for entry in matrix] == [
        "claude",
        "codex",
        "openai-compat",
        "claude-compat",
    ]
    rows = [cell.capability for cell in matrix[0].cells]
    for entry in matrix:
        assert [cell.capability for cell in entry.cells] == rows

    by_name = {
        entry.name: {cell.capability: cell.value for cell in entry.cells}
        for entry in matrix
    }
    assert by_name["claude"]["streaming"] == "live"
    assert by_name["codex"]["streaming"] == "post_hoc"
    assert by_name["codex"]["max_turns"] is False
    assert by_name["codex"]["turn_timeout_seconds"] is True
    assert by_name["claude"]["turn_timeout_seconds"] is False
    # The whole point of claude-compat: open models keep the Claude tier.
    assert by_name["claude-compat"] == by_name["claude"]
