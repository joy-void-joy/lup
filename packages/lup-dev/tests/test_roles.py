"""Path roles, and the project declaration they read."""

from pathlib import Path

import pytest

from lup_dev import (
    Core,
    Module,
    Modules,
    Paths,
    Project,
    Pytest,
    Python,
    TestRoots,
)
from lup_dev.declaration.resolve import Declaration
from lup_dev.policy.roles import Roles


def roles(
    root: Path, project: Project | None = None, source: Path | None = None
) -> Roles:
    declaration = Declaration.of(project or Project(), source)
    return Roles(root=root, declaration=declaration)


def core(paths: Paths) -> Project:
    return Project(modules=Modules.default().edit(Core(paths=paths)))


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
        ("AGENTS.local.md", "protected"),
        ("docs/AGENTS.local.md", "docs"),
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
    spec = TestRoots.of(Pytest(root=Path("spec"), files=["check_*.py"]))
    project = Project(modules=Modules.default().edit(Python(tests=spec)))
    assert roles(repo, project).role(Path("spec/check_a.py")) == "test"
    assert roles(repo, project).role(Path("spec/conftest.py")) == "test"
    assert roles(repo, project).role(Path("spec/test_a.py")) == "production"
    assert roles(repo, project).role(Path("tests/test_core.py")) == "production"


def test_test_roots_a_projects_own_module_holds_are_named_too(repo: Path) -> None:
    class Studio(Module):
        """The studio, a suite of its own."""

        name = "studio"

        tests: TestRoots = TestRoots.of(Pytest(root=Path("studio/tests")))

    project = Project(modules=Modules.default().add(Studio()))
    assert roles(repo, project).role(Path("studio/tests/test_a.py")) == "test"
    assert roles(repo, project).role(Path("tests/test_core.py")) == "test"
    assert roles(repo, project).role(Path("src/pkg/test_helpers.py")) == "production"


def test_a_project_adds_protected_paths(repo: Path) -> None:
    project = core(Paths().add(protected=["tests/spec/**"]))
    assert roles(repo, project).role(Path("tests/spec/test_a.py")) == "protected"
    assert roles(repo, project).role(Path("pyproject.toml")) == "protected"
    assert roles(repo, project).protecting(Path("tests/spec/a.py")) == "tests/spec/**"


def test_a_project_drops_a_protected_path(repo: Path) -> None:
    project = core(Paths().drop(protected=["**/.gitignore"], why="a test"))
    assert roles(repo, project).role(Path(".gitignore")) == "production"


def test_the_declaration_itself_is_protected(repo: Path) -> None:
    source = Path("lup_project.py")
    assert roles(repo, source=source).role(source) == "protected"
    assert roles(repo, source=source).protecting(source) is None


def test_the_declaration_read_from_a_root_is_protected_there(repo: Path) -> None:
    (repo / "lup_project.py").write_text(
        "from lup_dev import Project\nproject = Project()\n"
    )
    declaration = Declaration.read(repo)
    assert declaration.source == Path("lup_project.py")
    roles = Roles(root=repo, declaration=declaration)
    assert roles.role(Path("lup_project.py")) == "protected"


def test_an_excluded_path_is_held_to_nothing(repo: Path) -> None:
    project = core(
        Paths().add(excluded=["vendor/**", ".claude/hooks/**", "tests/legacy/**"])
    )
    excluded = roles(repo, project)
    for path in ["vendor/lib.py", "tests/legacy/test_old.py"]:
        assert excluded.role(Path(path)) == "excluded", path
        assert not excluded.ruled(Path(path))
        assert not excluded.checked(Path(path))
    assert excluded.role(Path("src/pkg/core.py")) == "production"


def test_exclusion_never_lifts_protection(repo: Path) -> None:
    excluded = roles(
        repo, core(Paths().add(excluded=[".claude/hooks/**", "DESIGN.md"]))
    )
    hook = Path(".claude/hooks/review.py")
    assert excluded.role(hook) == "protected"
    assert not excluded.ruled(hook)
    assert not excluded.checked(hook)
    assert excluded.role(Path("DESIGN.md")) == "operator"


def test_without_python_nothing_is_a_python_module(repo: Path) -> None:
    project = Project(modules=Modules.default().drop("python"))
    without = roles(repo, project)
    assert not without.is_python(Path("src/pkg/core.py"))
    assert without.role(Path("tests/test_core.py")) == "production"
    assert without.role(Path("pyproject.toml")) == "data"
