"""ruff's findings, read from its JSON output: which ones its `--fix` fixes, and
which ruff runs, the one `uv run` finds in the worktree. uv runs offline
(`offline_uv`).
"""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.codescan.contract import Source
from lup_dev.codescan.ruff import Ruff, RuffError

if TYPE_CHECKING:
    from conftest import Uv

CODE = "import os\n\nx = 1\nif x == None:\n    print(undefined)\n"


def test_only_a_safe_fix_makes_a_finding_fixable(
    tmp_path: Path, offline_uv: Uv
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["F401", "E711", "F821"]\n'
    )
    offline_uv.lock(tmp_path)
    (tmp_path / "a.py").write_text(CODE)
    for sources in [
        [Source(path=Path("a.py"))],
        [Source(path=Path("a.py"), content=CODE)],
    ]:
        found = {each.rule: each.fixable for each in Ruff().findings(tmp_path, sources)}
        assert found == {"F401": True, "E711": False, "F821": False}


def test_a_fix_the_configuration_makes_unfixable_isnt_fixable(
    tmp_path: Path, offline_uv: Uv
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["F401"]\nunfixable = ["F401"]\n'
    )
    offline_uv.lock(tmp_path)
    (tmp_path / "a.py").write_text(CODE)
    [found] = Ruff().findings(tmp_path, [Source(path=Path("a.py"))])
    assert (found.rule, found.fixable) == ("F401", False)


def stand_in(directory: Path, rule: str, root: Path) -> None:
    """Put a ruff in `directory` that finds `rule` in `root`'s `a.py` whatever it's
    asked, so its finding tells which ruff ran."""
    finding = {
        "code": rule,
        "message": f"{rule} fires here",
        "filename": str(root / "a.py"),
        "location": {"row": 1, "column": 1},
        "end_location": {"row": 1, "column": 2},
        "fix": None,
    }
    directory.mkdir(parents=True, exist_ok=True)
    ruff = directory / "ruff"
    ruff.write_text(f"#!/bin/sh\necho '{json.dumps([finding])}'\n")
    ruff.chmod(0o755)


def test_ruff_is_the_one_in_the_environment_uv_gives_the_worktree(
    tmp_path: Path, offline_uv: Uv, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "branch"
    # The session runs in another checkout's environment, which a hook inherits.
    other = tmp_path / "dev" / ".venv"
    stand_in(other / "bin", "OTHER", root)
    monkeypatch.setenv("PATH", f"{other / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VIRTUAL_ENV", str(other))
    root.mkdir()
    (root / "pyproject.toml").write_text("[tool.ruff]\n")
    (root / "a.py").write_text(CODE)
    offline_uv.lock(root)
    # Where the worktree's environment lives is uv's to say: here, not `.venv`.
    environment = tmp_path / "environment"
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(environment))
    offline_uv.sync(root)
    stand_in(environment / "bin", "WORKTREE", root)
    [found] = Ruff().findings(root, [Source(path=Path("a.py"))])
    assert found.rule == "WORKTREE"


def test_where_uv_cant_run_ruff_the_error_says_why(
    tmp_path: Path, offline_uv: Uv
) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    (tmp_path / "a.py").write_text(CODE)
    with pytest.raises(RuffError, match=r"`uv\.lock`"):
        Ruff().findings(tmp_path, [Source(path=Path("a.py"))])
