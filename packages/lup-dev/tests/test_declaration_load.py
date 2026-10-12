"""Loading a project's declaration from a root, in either of its forms."""

import importlib
import sys
import textwrap
from pathlib import Path

import pytest

from lup_dev import Project
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import resolve

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
        ("project = 3\n", "`project` in `lup_project.py` is a `int`, not a `Project`"),
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
