"""Path roles, and the project declaration they read."""

import sys
from pathlib import Path

import pytest

from lup_dev.policy.roles import Roles
from lup_dev.project import Project, ProjectError, Protected, Pytest, load


def roles(
    root: Path, project: Project | None = None, declaration: Path | None = None
) -> Roles:
    return Roles(root=root, project=project or Project(), declaration=declaration)


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("pyproject.toml", "protected"),
        ("packages/x/pyproject.toml", "protected"),
        ("uv.lock", "protected"),
        (".github/workflows/ci.yml", "protected"),
        (".claude/settings.json", "protected"),
        (".codex/hooks.json", "protected"),
        (".git/config", "protected"),
        ("sync.json", "protected"),
        (".env.local", "protected"),
        (".gitignore", "protected"),
        ("ruff.toml", "protected"),
        ("packages/x/.ruff.toml", "protected"),
        ("pyrightconfig.json", "protected"),
        ("pytest.toml", "protected"),
        (".pytest.toml", "protected"),
        ("pytest.ini", "protected"),
        ("setup.cfg", "protected"),
        ("tox.ini", "protected"),
        (".importlinter", "protected"),
        ("uv.toml", "protected"),
        (".python-version", "protected"),
        ("DESIGN.md", "operator"),
        ("AGENTS.md", "operator"),
        ("tests/test_core.py", "test"),
        ("tests/conftest.py", "test"),
        ("tmp/scratch.py", "scratch"),
        ("src/tmp/scratch.py", "scratch"),
        (".lup/saved/3/src/pkg/core.py", "scratch"),
        ("README.md", "docs"),
        ("docs/judging.md", "docs"),
        ("docs/conf.py", "docs"),
        ("data/rows.csv", "data"),
        ("fixtures/answer.json", "data"),
        ("src/pkg/schema.json", "production"),
        ("src/pkg/core.py", "production"),
        ("src/pkg/test_helpers.py", "test"),
        ("scripts/run.sh", "production"),
    ],
)
def test_each_path_has_the_first_role_that_matches(
    repo: Path, path: str, role: str
) -> None:
    assert roles(repo).role(Path(path)) == role


def test_a_source_module_pytest_reads_only_for_doctests_stays_production(
    repo: Path,
) -> None:
    # `src` is a test root here, but `core.py` doesn't match `test_*.py`.
    assert roles(repo).role(Path("src/pkg/core.py")) == "production"
    assert roles(repo).role(Path("src/pkg/test_core.py")) == "test"


def test_python_files_patterns_decide_what_a_root_collects(repo: Path) -> None:
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        'python_files = "check_*.py"\n'
    )
    assert roles(repo).role(Path("tests/check_core.py")) == "test"
    assert roles(repo).role(Path("tests/test_core.py")) == "production"


def test_a_nested_project_reads_its_own_pytest_configuration(repo: Path) -> None:
    nested = repo / "studio"
    nested.mkdir()
    (nested / "pyproject.toml").write_text('[tool.pytest]\ntestpaths = ["checks"]\n')
    assert roles(repo).role(Path("studio/checks/test_a.py")) == "test"
    assert roles(repo).role(Path("studio/tests/test_a.py")) == "production"


def test_without_pytest_configuration_tests_are_found_anywhere(tmp_path: Path) -> None:
    assert roles(tmp_path).role(Path("anywhere/test_a.py")) == "test"


def test_declared_test_roots_replace_pytests_configuration(repo: Path) -> None:
    project = Project(tests=[Pytest(root=Path("spec"))])
    assert roles(repo, project).role(Path("spec/test_a.py")) == "test"
    assert roles(repo, project).role(Path("tests/test_core.py")) == "production"


def test_a_project_adds_protected_paths(repo: Path) -> None:
    project = Project(protected=Protected.default().add("tests/spec/**"))
    assert roles(repo, project).role(Path("tests/spec/test_a.py")) == "protected"
    assert roles(repo, project).role(Path("pyproject.toml")) == "protected"


def test_the_declaration_itself_is_protected(repo: Path) -> None:
    declaration = Path("src/pkg/lup_project.py")
    assert roles(repo, declaration=declaration).role(declaration) == "protected"


def test_an_excluded_path_is_held_to_nothing(repo: Path) -> None:
    project = Project(excluded=["vendor/**", ".claude/hooks/**", "tests/legacy/**"])
    excluded = roles(repo, project)
    for path in ["vendor/lib.py", "tests/legacy/test_old.py"]:
        assert excluded.role(Path(path)) == "excluded", path
        assert not excluded.ruled(Path(path))
        assert not excluded.checked(Path(path))
    assert excluded.role(Path("src/pkg/core.py")) == "production"


def test_exclusion_never_lifts_protection(repo: Path) -> None:
    excluded = roles(repo, Project(excluded=[".claude/hooks/**", "DESIGN.md"]))
    hook = Path(".claude/hooks/review.py")
    assert excluded.role(hook) == "protected"
    assert not excluded.ruled(hook)
    assert not excluded.checked(hook)
    assert excluded.role(Path("DESIGN.md")) == "operator"


def test_without_a_declaration_the_defaults_apply(repo: Path) -> None:
    declared = load(repo)
    assert declared.source is None
    assert declared.project == Project()


def test_a_declaration_is_loaded_from_tool_lup(repo: Path) -> None:
    (repo / "src" / "decl_one").mkdir()
    (repo / "src" / "decl_one" / "__init__.py").write_text("")
    (repo / "src" / "decl_one" / "lup_project.py").write_text(
        "from pathlib import Path\n"
        "from lup_dev.project import Project, Protected, Pytest\n"
        'project = Project(tests=[Pytest(root=Path("spec"))], '
        'protected=Protected.default().add("spec/**"), '
        'conditions="decl_one.conditions")\n'
    )
    (repo / "pyproject.toml").write_text(
        '[tool.lup]\nproject = "decl_one.lup_project:project"\n'
    )
    declared = load(repo)
    assert declared.source == Path("src/decl_one/lup_project.py")
    assert declared.project.tests == [Pytest(root=Path("spec"))]
    assert declared.project.conditions == "decl_one.conditions"
    assert (
        Roles.of(repo, declared).role(Path("src/decl_one/lup_project.py"))
        == "protected"
    )


def test_each_worktree_loads_its_own_declaration_in_one_process(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        (root / "helpers").mkdir(parents=True)
        (root / "helpers" / "__init__.py").write_text(f"NAME = {root.name!r}\n")
        (root / "pyproject.toml").write_text(
            '[tool.lup]\nproject = "lup_project:project"\n'
        )
        (root / "lup_project.py").write_text(
            "from helpers import NAME\n"
            "from lup_dev.project import Project\n"
            "project = Project(excluded=[NAME])\n"
        )
    assert [load(root).project.excluded for root in roots] == [["one"], ["two"]]
    assert "lup_project" not in sys.modules
    assert "helpers" not in sys.modules
    assert "lup_dev.project" in sys.modules


def test_loading_a_declaration_leaves_no_bytecode_in_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.lup]\nproject = "lup_project:project"\n'
    )
    (tmp_path / "lup_project.py").write_text(
        "from lup_dev.project import Project\nproject = Project()\n"
    )
    load(tmp_path)
    assert not (tmp_path / "__pycache__").exists()
    assert sys.dont_write_bytecode is False


def test_a_declaration_that_isnt_a_project_is_refused(repo: Path) -> None:
    (repo / "src" / "decl_two.py").write_text("project = 3\n")
    (repo / "pyproject.toml").write_text('[tool.lup]\nproject = "decl_two:project"\n')
    with pytest.raises(ProjectError, match="not a `Project`"):
        load(repo)


def test_a_declaration_that_cant_be_imported_is_refused(repo: Path) -> None:
    (repo / "pyproject.toml").write_text(
        '[tool.lup]\nproject = "decl_missing:project"\n'
    )
    with pytest.raises(ProjectError, match="can't be loaded"):
        load(repo)
