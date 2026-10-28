"""Loading a project's declaration from a root, in either of its forms."""

import importlib
import sys
import textwrap
from pathlib import Path

import pytest

from lup_dev import Project, Section
from lup_dev.catalog.paths import CorePaths
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import load, person_layer
from lup_dev.declaration.resolve import Declaration, resolve

DECLARATION = """
from lup_dev import CodeRules, Modules, Project, Rules

project = Project(
    held=["protected"],
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
    assert declared.project.held == ["protected"]
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
        "github",
        "transcripts",
        "private",
        "lup-development",
    ]
    assert (resolved.held, resolved.flagged) == (Project().held, Project().flagged)
    assert [each.name for each in resolved.gate][:3] == ["engine", "dashboard", "rules"]
    assert "packages/lup-dev/src/lup_dev/catalog/**" in resolved.paths.protected
    assert resolved.paths.excluded == []
    assert [each.root for each in resolved.tests] == [Path("packages/*/tests")]
    assert [(each.rule, each.paths) for each in resolved.exempt] == [
        ("runtime-mention", ["packages/lup/src/lup/__init__.py"]),
        ("constant-home", ["packages/lup-dev/src/lup_dev/catalog/**"]),
    ]
    [selected] = resolved.rules
    lups = selected.rules.operations[len(selected.default.operations) :]
    assert [operation.verb for operation in lups] == ["add"]
    assert [
        (each.requirement.tool, each.requirement.optional)
        for each in resolved.requirements
        if each.module == "lup-development"
    ] == [("pnpm", True)]
    assert [each.name for each in resolved.packages][-3:] == ["nodejs", "pnpm", "uv"]
    assert resolved.pyright_source is not None
    assert [each.name for each in resolved.guidance] == [
        "core",
        "python",
        "code-rules",
        "transcripts",
        "private",
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
from pathlib import Path
from typing import override

from lup_dev import Module, Modules, Paths, Project, Python, RoomNeeds, Runner, Tools


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

    @override
    def venv(self) -> Path | None:
        return Path(".venv")

    @override
    def room(self, root: Path, tools: Tools) -> RoomNeeds:
        return RoomNeeds()


class Narration(Module):
    """Turning a page into an episode."""

    name = "narration"

    paths: Paths = Paths.of(protected=["episodes/**"])
    conditions: str | None = "audiobook.conditions"


project = Project(
    held=["protected"],
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
    assert kept.runner.venv() == Path(".venv")
    assert declaration.source == Path("lup_project.py")
    assert "episodes/**" in declaration.paths.protected
    assert declaration.conditions == ["audiobook.conditions"]
    assert declaration.held == ["protected"]
    assert declaration.tests is None


def test_a_declaration_kept_before_the_secret_role_stands_in_with_lup_s_own(
    tmp_path: Path,
) -> None:
    write(tmp_path / "lup_project.py", OWN_CLASSES)
    kept = Declaration.read(tmp_path).model_dump(mode="json")
    del kept["paths"]["secret"]
    older = Declaration.model_validate(kept)
    assert older.paths.secret == CorePaths().secret


# The person's own layer, `lup_project.local.py`

OURS = '''
from pathlib import Path

from lup_dev import Module, Modules, Project, Repositories, Repository


class Ours(Module):
    """The project's own module, naming a made-up neighbour."""

    name = "ours"

    repositories: Repositories = Repositories.of(
        Repository(name="atlas", path=Path("atlas.git"), about="a made-up neighbour")
    )


project = Project(held=["protected"], modules=Modules.default().add(Ours()))
'''

MINE = '''
from pathlib import Path

from lup_dev import Module, Modules, Project, Repositories, Repository


class Mine(Module):
    """The person's own module: the repositories they relate."""

    name = "mine"

    repositories: Repositories = Repositories.of(
        Repository(
            name="beacon",
            path=Path("~/src/beacon"),
            about="another made-up neighbour",
            github="someone/beacon",
        )
    )


project = Project(modules=Modules().add(Mine()))
'''


def test_the_person_s_layer_is_layered_on_the_project_s(tmp_path: Path) -> None:
    write(tmp_path / "lup_project.py", OURS)
    write(tmp_path / "lup_project.local.py", MINE)
    declared = load(tmp_path)
    assert declared.source == Path("lup_project.py")
    assert declared.local == Path("lup_project.local.py")
    resolved = resolve(declared.project)
    assert [each.name for each in resolved.repositories] == ["atlas", "beacon"]
    assert [module.name for module in resolved.modules][-2:] == ["ours", "mine"]
    assert resolved.held == ["protected"]
    assert not any(name.startswith("lup_project") for name in sys.modules)
    assert not (tmp_path / "__pycache__").exists()


def test_the_person_s_layer_is_read_where_it_s_given(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    write(root / "lup_project.py", OURS)
    write(root / "lup_project.local.py", "this, beside the declaration, isn't read\n")
    elsewhere = tmp_path / "main" / "lup_project.local.py"
    write(elsewhere, MINE)
    declared = load(root, local=elsewhere)
    assert declared.local == elsewhere
    assert [each.name for each in resolve(declared.project).repositories] == [
        "atlas",
        "beacon",
    ]


def test_a_worktree_s_layer_is_in_its_repository_s_main_worktree(
    repo: Path, linked: Path, bare: Path
) -> None:
    assert person_layer(repo) == repo / "lup_project.local.py"
    assert person_layer(linked) == repo / "lup_project.local.py"
    assert person_layer(bare / "tree" / "main") == bare / "lup_project.local.py"


def test_without_the_person_s_layer_nothing_changes(tmp_path: Path) -> None:
    write(tmp_path / "lup_project.py", OURS)
    declared = load(tmp_path)
    assert declared.local is None
    assert [each.name for each in resolve(declared.project).repositories] == ["atlas"]


def test_the_person_s_layer_edits_the_project_s_own_module(tmp_path: Path) -> None:
    write(tmp_path / "lup_project.py", OURS)
    write(
        tmp_path / "lup_project.local.py",
        """
        from lup_dev import Modules, Project, Repositories

        from lup_project import Ours

        project = Project(
            held=["protected", "regex"],
            modules=Modules().edit(Ours(repositories=Repositories().drop("atlas"))),
        )
        """,
    )
    resolved = resolve(load(tmp_path).project)
    assert resolved.repositories == []
    assert resolved.held == ["protected", "regex"]


def test_the_person_s_layer_alone_is_layered_on_the_defaults(tmp_path: Path) -> None:
    write(tmp_path / "lup_project.local.py", MINE)
    declared = load(tmp_path)
    assert declared.source is None
    resolved = resolve(declared.project)
    assert [module.name for module in resolved.modules] == [
        *(module.name for module in resolve(Project()).modules),
        "mine",
    ]


def test_one_name_from_the_project_and_the_person_with_two_paths_fails(
    tmp_path: Path,
) -> None:
    write(tmp_path / "lup_project.py", OURS)
    write(
        tmp_path / "lup_project.local.py",
        MINE.replace('name="beacon"', 'name="atlas"'),
    )
    with pytest.raises(
        ProjectError,
        match=r"`atlas` at `atlas.git` and at `~/src/beacon`",
    ):
        resolve(load(tmp_path).project)


@pytest.mark.parametrize(
    ("text", "failure"),
    [
        ("project = Project(\n", "`lup_project.local.py` can't be imported"),
        ("x = 1\n", "`lup_project.local.py` binds no `project`"),
        (
            "project = 3\n",
            "`project` in `lup_project.local.py` is a `builtins.int`",
        ),
    ],
)
def test_a_broken_layer_of_the_person_s_fails_the_load_naming_it(
    tmp_path: Path, text: str, failure: str
) -> None:
    write(tmp_path / "lup_project.py", OURS)
    write(tmp_path / "lup_project.local.py", f"from lup_dev import Project\n{text}")
    with pytest.raises(ProjectError, match=failure):
        load(tmp_path)
    assert not any(name.startswith("lup_project") for name in sys.modules)


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
