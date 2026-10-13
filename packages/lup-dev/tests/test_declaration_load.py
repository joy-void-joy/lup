"""Loading a project's declaration from a root, in either of its forms."""

import importlib
import sys
import textwrap
from pathlib import Path

import pytest

from lup_dev import Project, Section
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import Declaration, resolve

DECLARATION = """
from lup_dev import CodeRules, Modules, Project, Rules

project = Project(
    asks="protected",
    modules=Modules.default().edit(CodeRules(rules=Rules().drop("tuple-shape", why="{why}"))),
)
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def why(root: Path) -> str | None:
    """Return the reason the declaration's own drop gives, after its default's."""
    [selected] = resolve(load(root).project).rules
    [operation] = selected.rules.operations[len(selected.default.operations) :]
    assert operation.verb == "drop"
    return operation.why


def test_without_a_declaration_the_defaults_apply(tmp_path: Path) -> None:
    declared = load(tmp_path)
    assert declared.project == Project()
    assert declared.source is None


def test_the_declaration_is_read_from_the_root(tmp_path: Path) -> None:
    write(tmp_path / "lup_project.py", DECLARATION.format(why="at the root"))
    declared = load(tmp_path)
    assert declared.source == Path("lup_project.py")
    assert declared.project.asks == "protected"
    assert why(tmp_path) == "at the root"
    assert "lup_project" not in sys.modules


def test_the_declaration_may_be_a_package_holding_the_project_s_modules(
    tmp_path: Path,
) -> None:
    write(
        tmp_path / "lup_project" / "narration.py",
        '''
        from lup_dev import Module, Paths

        class Narration(Module):
            """Turning a page into an episode."""

            name = "narration"

            paths: Paths = Paths.of(data=["episodes/**"])
        ''',
    )
    write(
        tmp_path / "lup_project" / "__init__.py",
        """
        from lup_dev import Modules, Project

        from .narration import Narration

        project = Project(modules=Modules.default().add(Narration()))
        """,
    )
    declared = load(tmp_path)
    assert declared.source == Path("lup_project/__init__.py")
    assert "episodes/**" in resolve(declared.project).paths.data
    assert not any(name.startswith("lup_project") for name in sys.modules)


def test_the_declaration_imports_the_project_s_own_packages(tmp_path: Path) -> None:
    write(tmp_path / "src" / "audiobook" / "__init__.py", 'WHY = "from src"\n')
    write(
        tmp_path / "lup_project.py",
        """
        from audiobook import WHY
        from lup_dev import CodeRules, Modules, Project, Rules

        project = Project(modules=Modules.default().edit(CodeRules(rules=Rules().drop("regex", why=WHY))))
        """,
    )
    assert why(tmp_path) == "from src"
    assert "audiobook" not in sys.modules


def test_both_forms_at_once_fail_the_load(tmp_path: Path) -> None:
    write(tmp_path / "lup_project.py", DECLARATION.format(why="a"))
    write(tmp_path / "lup_project" / "__init__.py", DECLARATION.format(why="b"))
    with pytest.raises(ProjectError, match=r"are both at"):
        load(tmp_path)


def test_a_package_without_its_init_fails_the_load(tmp_path: Path) -> None:
    (tmp_path / "lup_project").mkdir()
    with pytest.raises(ProjectError, match=r"holds no `__init__.py`"):
        load(tmp_path)


@pytest.mark.parametrize(
    ("text", "failure"),
    [
        ("project = Project(\n", "`lup_project.py` can't be imported"),
        (
            "from lup_dev import Nothing\n",
            "`lup_project.py` can't be imported: cannot import name 'Nothing'",
        ),
        (
            "from lup_dev import Python, Core\nproject = Python().edit(Core())\n",
            "`.replace",
        ),
        ("x = 1\n", "`lup_project.py` binds no `project`"),
        (
            "project = 3\n",
            (
                "`project` in `lup_project.py` is a `builtins.int`, "
                "not a `lup_dev.declaration.project.Project`"
            ),
        ),
        (
            "class Project:\n    pass\nproject = Project()\n",
            "is a `lup_project.Project`, not a `lup_dev.declaration.project.Project`",
        ),
        ("from lup_dev import Project\nproject = Project(modlues=[])\n", "modlues"),
    ],
)
def test_a_broken_declaration_fails_the_load_naming_it(
    tmp_path: Path, text: str, failure: str
) -> None:
    write(tmp_path / "lup_project.py", text)
    with pytest.raises(ProjectError, match=failure):
        load(tmp_path)


def test_each_root_gets_its_own_declaration_in_one_process(tmp_path: Path) -> None:
    for name in ["first", "second"]:
        write(tmp_path / name / "lup_project.py", DECLARATION.format(why=name))
    assert [why(tmp_path / name) for name in ["first", "second", "first"]] == [
        "first",
        "second",
        "first",
    ]


def test_a_declaration_imported_before_from_elsewhere_is_set_aside(
    tmp_path: Path,
) -> None:
    write(
        tmp_path / "elsewhere" / "lup_project.py", DECLARATION.format(why="elsewhere")
    )
    write(tmp_path / "root" / "lup_project.py", DECLARATION.format(why="root"))
    sys.path.insert(0, str(tmp_path / "elsewhere"))
    try:
        elsewhere = importlib.import_module("lup_project")
        assert why(tmp_path / "root") == "root"
        assert sys.modules["lup_project"] is elsewhere
    finally:
        sys.path.remove(str(tmp_path / "elsewhere"))
        del sys.modules["lup_project"]


def test_an_exported_commit_loads_as_a_root_does(tmp_path: Path) -> None:
    exported = tmp_path / "declarations" / "0123abc"
    write(exported / "lup_project.py", DECLARATION.format(why="exported"))
    assert why(exported) == "exported"
    assert load(exported).source == Path("lup_project.py")


def test_lups_own_declaration_is_its_modules_with_its_changes() -> None:
    root = Path(__file__).resolve().parents[3]
    resolved = resolve(load(root).project)
    assert [each.name for each in resolved.modules] == [
        "core",
        "python",
        "code-rules",
        "lup-development",
    ]
    assert resolved.asks == "protected"
    assert [each.name for each in resolved.gate][:2] == ["engine", "rules"]
    assert "packages/lup-dev/src/lup_dev/catalog/**" in resolved.paths.protected
    assert resolved.paths.excluded == [".claude/hooks/**"]
    assert [each.root for each in resolved.tests] == [Path("packages/*/tests")]
    assert [(each.rule, each.paths) for each in resolved.exempt] == [
        ("runtime-mention", ["packages/lup/src/lup/__init__.py"]),
        ("constant-home", ["packages/lup-dev/src/lup_dev/catalog/**"]),
    ]
    [selected] = resolved.rules
    lups = selected.rules.operations[len(selected.default.operations) :]
    assert [operation.verb for operation in lups] == ["add"]
    assert ("lup-development", "npm") in [
        (each.module, each.requirement.tool) for each in resolved.requirements
    ]
    assert [each.name for each in resolved.packages][-3:] == ["nodejs", "npm", "uv"]
    assert [each.name for each in resolved.guidance] == [
        "core",
        "python",
        "code-rules",
        "lup",
    ]
    assert resolved.guidance[-1] == Section(name="lup", path=Path("AGENTS.md"))


def test_loading_a_declaration_leaves_no_bytecode_at_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    write(tmp_path / "lup_project.py", DECLARATION.format(why="no bytecode"))
    load(tmp_path)
    assert not (tmp_path / "__pycache__").exists()
    assert sys.dont_write_bytecode is False


OWN_CLASSES = '''
from typing import override

from lup_dev import Module, Modules, Paths, Project, Python, Runner


class Poetry(Runner):
    """Poetry's environment."""

    @override
    def command(self, tool: list[str]) -> list[str]:
        return ["poetry", "run", *tool]

    @override
    def judging(self, tool: list[str]) -> list[str]:
        return ["env", "-u", "VIRTUAL_ENV", "poetry", "run", *tool]

    @override
    def environment(self) -> list[str]:
        return ["poetry.lock"]


class Narration(Module):
    """Turning a page into an episode."""

    name = "narration"

    paths: Paths = Paths.of(protected=["episodes/**"])
    conditions: str | None = "audiobook.conditions"


project = Project(
    asks="protected",
    modules=Modules.default().edit(Python(runner=Poetry())).add(Narration()),
)
'''


def test_what_judging_reads_is_kept_as_json_whatever_classes_the_project_brings(
    tmp_path: Path,
) -> None:
    write(tmp_path / "lup_project.py", OWN_CLASSES)
    declaration = Declaration.read(tmp_path)
    kept = Declaration.model_validate_json(declaration.model_dump_json())
    assert kept == declaration
    assert kept.runner.judging(["ruff"]) == [
        "env",
        "-u",
        "VIRTUAL_ENV",
        "poetry",
        "run",
        "ruff",
    ]
    assert kept.runner.command(["pytest"]) == ["poetry", "run", "pytest"]
    assert kept.runner.environment() == ["poetry.lock"]
    assert declaration.source == Path("lup_project.py")
    assert "episodes/**" in declaration.paths.protected
    assert declaration.conditions == ["audiobook.conditions"]
    assert declaration.asks == "protected"
    assert declaration.tests is None


def test_a_declaration_that_doesnt_resolve_fails_its_reading(tmp_path: Path) -> None:
    write(
        tmp_path / "lup_project.py",
        """
        from lup_dev import Modules, Project

        project = Project(modules=Modules.default().drop("ledger"))
        """,
    )
    with pytest.raises(ProjectError, match=r"`Modules.drop` names `ledger`"):
        Declaration.read(tmp_path)
