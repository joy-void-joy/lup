"""Path roles, and the project declaration they read."""

from pathlib import Path
from typing import Literal

import pytest

from lup_dev import (
    CodeRules,
    Core,
    Exemption,
    Exemptions,
    Module,
    Modules,
    Paths,
    Project,
    Pytest,
    Python,
    TestRoots,
    cli,
)
from lup_dev.catalog.paths import CorePaths
from lup_dev.codescan.contract import FileReport, Finding, Position, Span
from lup_dev.codescan.directives import Ignore
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
        ("packages/lup-dashboard/page/src/folds.test.ts", "test"),
        ("web/src/App.test.tsx", "test"),
        ("packages/lup-dashboard/page/src/folds.ts", "production"),
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


def test_a_typescript_test_is_a_test_without_python(repo: Path) -> None:
    page = Path("packages/lup-dashboard/page/src/keys.test.ts")
    without = roles(repo, Project(modules=Modules.default().drop("python")))
    assert without.role(page) == "test"
    assert not without.checked(page)


def test_a_project_names_its_own_tests(repo: Path) -> None:
    project = core(Paths().add(tests=["web/**/*.spec.ts", "e2e/**"]))
    assert roles(repo, project).role(Path("web/src/a.spec.ts")) == "test"
    assert roles(repo, project).role(Path("e2e/flows/login.py")) == "test"
    assert roles(repo, project).role(Path("web/src/a.test.ts")) == "test"
    assert roles(repo, project).role(Path("web/src/a.ts")) == "production"


def test_a_project_adds_protected_paths(repo: Path) -> None:
    project = core(Paths().add(protected=["tests/spec/**"]))
    assert roles(repo, project).role(Path("tests/spec/test_a.py")) == "protected"
    assert roles(repo, project).role(Path("pyproject.toml")) == "protected"
    assert roles(repo, project).protecting(Path("tests/spec/a.py")) == "tests/spec/**"


def test_a_project_drops_a_protected_path(repo: Path) -> None:
    project = core(Paths().drop(protected=["**/.gitignore"], why="a test"))
    assert roles(repo, project).role(Path(".gitignore")) == "production"


def test_every_runtime_s_settings_are_protected_by_default_and_a_project_can_drop_them(
    repo: Path,
) -> None:
    # An adapter added without its directory among the defaults fails here.
    known = [runtime.settings() for runtime in cli.runtimes()]
    assert known
    for directory in known:
        assert f"{directory}/**" in CorePaths().protected
        assert roles(repo).role(Path(directory, "settings.json")) == "protected"
    first = known[0]
    project = core(Paths().drop(protected=[f"{first}/**"], why="a test"))
    assert roles(repo, project).role(Path(first, "settings.json")) != "protected"


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


def fired(
    path: str, line: int, owner: Literal["lup", "pyright", "ruff"], rule: str
) -> Finding:
    place = Position(line=line, column=1)
    return Finding(
        path=Path(path),
        span=Span(start=place, end=place),
        owner=owner,
        rule=rule,
        message=f"{rule} fires here",
    )


def kept_in(roles: Roles, path: str) -> list[str]:
    """Return the rules of the findings `roles` keeps in `path`, where every owner fired one, a second `regex` under an `ignore`."""
    every = [
        fired(path, 1, "lup", "regex"),
        fired(path, 2, "lup", "tuple-shape"),
        fired(path, 3, "pyright", "reportCallIssue"),
        fired(path, 4, "ruff", "E501"),
        fired(path, 5, "lup", "regex"),
    ]
    kept = Ignore(line=5, covers=5, rule="regex", why="a grammar")
    report = FileReport(path=Path(path), findings=every, directives=[kept])
    return [found.rule for found in roles.kept(report, every)]


def test_what_holds_in_a_file_is_what_its_role_and_the_declaration_leave(
    repo: Path,
) -> None:
    lifted = Exemption(rule="tuple-shape", paths=["src/pkg/**"], why="a shape")
    project = Project(
        modules=Modules.default()
        .edit(CodeRules(exempt=Exemptions().add(lifted)))
        .edit(Core(paths=Paths().add(excluded=["vendor/**"])))
    )
    judged = roles(repo, project)
    assert kept_in(judged, "src/pkg/core.py") == ["regex", "reportCallIssue", "E501"]
    assert kept_in(judged, "src/other.py") == [
        "regex",
        "tuple-shape",
        "reportCallIssue",
        "E501",
    ]
    assert kept_in(judged, "tests/test_core.py") == ["reportCallIssue", "E501"]
    assert kept_in(judged, "tmp/scratch.py") == []
    assert kept_in(judged, "vendor/lib.py") == []
