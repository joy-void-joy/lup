"""The declaration's promises, checked through loading and resolving a declaration file.

Until #14 gives modules `@lup.promise`, each test is one promise, said in its
docstring, checked through the core's environment side as a project's
declaration reaches it.
"""

from typing import TYPE_CHECKING

import pytest

from lup import Core, Module, Modules, Named, Project, ProjectError
from lup.environment.declaration import load, resolve

if TYPE_CHECKING:
    from pathlib import Path


class Voices(Named[str]):
    """The voices a story is read in."""


class Narration(Module):
    """Reading a story aloud."""

    name = "narration"
    speed: float = 1.0
    voices: Voices = Voices.of("narrator")


class Captions(Module):
    """Captions under what's read aloud, which need the reading."""

    name = "captions"
    requires = [Narration]


def written(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "declaration.py"
    path.write_text(body)
    return path


def test_a_layer_changes_only_what_it_names() -> None:
    """A layer on a module changes the fields it sets, and every other field stays as below has it."""
    project = Project(
        modules=Modules.default()
        .add(Narration(speed=1.5))
        .edit(Narration(voices=Voices().add("villain")), why="the villain speaks")
    )
    narration = next(each for each in resolve(project) if isinstance(each, Narration))
    assert narration.speed == 1.5
    voices = {each.entry for each in narration.voices.resolve([], [])}
    assert {"narrator", "villain"} <= voices


def test_every_project_holds_the_core() -> None:
    """A declaration whose modules leave out `core` fails to resolve, rather than running without it."""
    project = Project(modules=Modules.default().drop("core", why="trying"))
    with pytest.raises(ProjectError):
        resolve(project)


def test_another_core_may_take_its_place() -> None:
    """A project may put another module in the core's place, which then counts as the core."""

    class Mine(Core):
        """lup's core, with this project's changes."""

    project = Project(modules=Modules.default().replace("core", Mine()))
    assert any(isinstance(each, Mine) for each in resolve(project))


def test_lup_adds_no_module_behind_the_declarations_back() -> None:
    """A module whose requirement isn't selected fails to resolve: lup never adds the requirement itself."""
    project = Project(modules=Modules.default().add(Captions()))
    with pytest.raises(ProjectError):
        resolve(project)
    resolved = resolve(Project(modules=Modules.default().add(Narration(), Captions())))
    assert {"narration", "captions"} <= {each.name for each in resolved}


def test_a_projects_own_module_loads_as_lups_do(tmp_path: Path) -> None:
    """A module a project declares in its own declaration file loads and resolves the way lup's own do."""
    path = written(
        tmp_path,
        '''
from lup import Module, Modules, Project


class Episodes(Module):
    """Turning a chapter into an episode."""

    name = "episodes"
    length: int = 20


project = Project(modules=Modules.default().add(Episodes(length=30)))
''',
    )
    resolved = resolve(load(path))
    episodes = next(each for each in resolved if each.name == "episodes")
    assert episodes.model_dump()["length"] == 30


@pytest.mark.parametrize(
    "body",
    [
        "x = 1\n",
        "project = 'not a project'\n",
        "raise RuntimeError('broken')\n",
    ],
)
def test_a_declaration_that_doesnt_load_says_so(tmp_path: Path, body: str) -> None:
    """A declaration that binds no project, binds something else, or fails as it runs raises `ProjectError`, never standing in the defaults."""
    with pytest.raises(ProjectError):
        load(written(tmp_path, body))
