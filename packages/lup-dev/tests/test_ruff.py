"""ruff's findings, read from its JSON output: which ones its `--fix` fixes, and
which ruff runs, the judge's own, installed with `lup-dev`, never the worktree's.
"""

import json
import os
import sysconfig
from pathlib import Path

import pytest

from lup_dev.codescan.contract import Source
from lup_dev.codescan.ruff import Ruff, RuffError, installed

CODE = "import os\n\nx = 1\nif x == None:\n    print(undefined)\n"
SELECTED = '[tool.ruff.lint]\nselect = ["F401", "E711", "F821"]\n'


def test_only_a_safe_fix_makes_a_finding_fixable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(SELECTED)
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


def test_each_file_is_found_under_its_own_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(SELECTED)
    (tmp_path / "pkg").mkdir()
    for name in ["a.py", "pkg/b.py"]:
        (tmp_path / name).write_text(CODE)
    sources = [Source(path=Path("a.py")), Source(path=Path("pkg/b.py"), content=CODE)]
    found = {(str(each.path), each.rule) for each in Ruff().findings(tmp_path, sources)}
    assert found == {
        (name, rule)
        for name in ["a.py", "pkg/b.py"]
        for rule in ["F401", "E711", "F821"]
    }


def stand_in(directory: Path, rule: str, root: Path) -> Path:
    """Put a ruff in `directory` that finds `rule` in `root`'s `a.py` whatever it's
    asked and says it ran, so its finding, or its mark, tells which ruff ran."""
    finding = {
        "code": rule,
        "message": f"{rule} fires here",
        "filename": str(root / "a.py"),
        "location": {"row": 1, "column": 1},
        "end_location": {"row": 1, "column": 2},
        "fix": None,
    }
    directory.mkdir(parents=True, exist_ok=True)
    ran = directory / "ran"
    ruff = directory / "ruff"
    ruff.write_text(f"#!/bin/sh\necho ran >> {ran}\necho '{json.dumps([finding])}'\n")
    ruff.chmod(0o755)
    return ran


def test_the_judge_runs_its_own_ruff_never_the_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "branch"
    root.mkdir()
    (root / "pyproject.toml").write_text(SELECTED)
    (root / "a.py").write_text(CODE)
    # The worktree's environment has a ruff of its own, and so does the session's,
    # which a hook inherits: neither is the judge's.
    worktree = stand_in(root / ".venv" / "bin", "WORKTREE", root)
    other = tmp_path / "dev" / ".venv"
    session = stand_in(other / "bin", "OTHER", root)
    monkeypatch.setenv("PATH", f"{other / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VIRTUAL_ENV", str(other))
    found = Ruff().findings(root, [Source(path=Path("a.py"))])
    assert {each.rule for each in found} == {"F401", "E711", "F821"}
    assert not worktree.exists()
    assert not session.exists()


def test_the_judges_ruff_is_installed_where_its_python_installs_scripts() -> None:
    assert installed() == Path(sysconfig.get_path("scripts")) / "ruff"
    assert installed().is_file()


def test_a_ruff_missing_is_named(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(CODE)
    missing = tmp_path / "nowhere" / "ruff"
    with pytest.raises(RuffError, match=r"the judge's ruff isn't at .*nowhere/ruff"):
        Ruff(program=missing).findings(tmp_path, [Source(path=Path("a.py"))])


def test_a_ruff_failing_is_said(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(CODE)
    failing = tmp_path / "ruff"
    failing.write_text("#!/bin/sh\necho 'no configuration' >&2\nexit 2\n")
    failing.chmod(0o755)
    with pytest.raises(RuffError, match="no configuration"):
        Ruff(program=failing).findings(tmp_path, [Source(path=Path("a.py"))])


def test_a_file_linking_out_of_the_worktree_is_left_out(tmp_path: Path) -> None:
    root = tmp_path / "branch"
    root.mkdir()
    (root / "pyproject.toml").write_text(SELECTED)
    host = tmp_path / "host.py"
    host.write_text(CODE)
    (root / "linked.py").symlink_to(host)
    (root / "inside.py").symlink_to(root / "own.py")
    (root / "own.py").write_text(CODE)
    sources = [Source(path=Path(name)) for name in ["linked.py", "inside.py"]]
    found = {(str(each.path), each.rule) for each in Ruff().findings(root, sources)}
    assert found == {("inside.py", rule) for rule in ["F401", "E711", "F821"]}
