"""A bundle rendered for a project with no anti-pattern rows is ruff-stable."""

import subprocess
import sys

from lup.policy.bundle import antipattern_rows_literal


def test_an_empty_suffix_renders_closed_on_one_line() -> None:
    """Opened and closed on two lines is the one shape ruff rewrites, and a
    generated file that reformats is a drift failure on a file nobody edits."""
    rendered = antipattern_rows_literal({".py": [], ".ts": []})

    assert rendered == '{\n    ".py": [],\n    ".ts": [],\n}'
    source = f"ROWS = {rendered}\n"
    formatted = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "-"],
        input=source,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert formatted == source
