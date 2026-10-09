"""ruff's findings, read from its JSON output: which ones its `--fix` fixes."""

from pathlib import Path

from lup_dev.codescan.contract import Source
from lup_dev.codescan.ruff import Ruff

CODE = "import os\n\nx = 1\nif x == None:\n    print(undefined)\n"


def test_only_a_safe_fix_makes_a_finding_fixable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["F401", "E711", "F821"]\n'
    )
    (tmp_path / "a.py").write_text(CODE)
    for sources in [
        [Source(path=Path("a.py"))],
        [Source(path=Path("a.py"), content=CODE)],
    ]:
        found = {each.rule: each.fixable for each in Ruff().findings(tmp_path, sources)}
        assert found == {"F401": True, "E711": False, "F821": False}


def test_a_fix_the_configuration_makes_unfixable_isnt_fixable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["F401"]\nunfixable = ["F401"]\n'
    )
    (tmp_path / "a.py").write_text(CODE)
    [found] = Ruff().findings(tmp_path, [Source(path=Path("a.py"))])
    assert (found.rule, found.fixable) == ("F401", False)
