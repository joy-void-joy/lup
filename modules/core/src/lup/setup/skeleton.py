"""The files lup writes into a project it sets up: its declaration, and the module of its own `lup new` makes, laid out as lup's own modules are.

A project's own module is `modules/<name>/`, a member of the project's uv
workspace, as the core is lup's (`modules/core/`): its `pyproject.toml`, its
package under `src/`, the `Module` subclass at its top with the docstring lup
shows it by, its promises in `promises.py`, and its `README.md` (`README.md`
here, *A project's own module*).
"""

from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints

from lup.types import Model

type ProjectName = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
]
"""A new project's name, which names its directory, its module and that
module's distribution, and, each `-` a `_`, its package: lowercase ASCII
letters and digits, words joined by a single `-`, starting with a letter."""


def declared(own: Skeleton | None) -> str:
    """Return the text of a project's declaration: lup's default modules, and the project's own module where it has one.

    >>> "Project()" in declared(None)
    True
    """
    if own is None:
        return '''"""The project's declaration: the modules its sessions use, lup's defaults until it selects others."""

from lup import Project

project = Project()
'''
    return f'''"""{own.name}'s declaration: the modules its sessions use, lup's defaults and its own."""

from lup import Modules, Project

from {own.package()} import {own.called()}

project = Project(modules=Modules.default().add({own.called()}()))
'''


class Skeleton(Model):
    """A project's own module, empty, as `lup new` writes it: named after the project."""

    name: ProjectName
    requires: str
    """The Python versions it runs on, as lup's core says its own."""

    def package(self) -> str:
        """Name its package: its name, each `-` a `_`.

        >>> Skeleton(name="story-reader", requires=">=3.15").package()
        'story_reader'
        """
        # lup: ignore("string-replace", why="a package's name can't hold a `-`, which a project's may: `story-reader`'s package is `story_reader`, as uv's build backend names it")
        return self.name.replace("-", "_")

    def called(self) -> str:
        """Name its `Module` subclass: each word of its name capitalized.

        >>> Skeleton(name="story-reader", requires=">=3.15").called()
        'StoryReader'
        """
        # lup: ignore("string-split", why="a project's name is words joined by `-`, which its pattern holds, and its class is named after those words")
        return "".join(word.capitalize() for word in self.name.split("-"))

    def directory(self) -> Path:
        """Return its directory, from the project's root."""
        return Path("modules") / self.name

    def files(self) -> dict[Path, str]:
        """Return each file of it, by its path from the project's root, with its text."""
        source = self.directory() / "src" / self.package()
        return {
            self.directory() / "pyproject.toml": self.pyproject(),
            self.directory() / "README.md": self.readme(),
            source / "__init__.py": self.module(),
            source / "promises.py": self.promises(),
            source / "py.typed": "",
        }

    def pyproject(self) -> str:
        """Return its `pyproject.toml`: a distribution named after it, depending on lup's core, which the project's root says where to find, and built by uv's backend, as lup's core is."""
        return f"""[project]
name = "{self.name}"
version = "0.1.0"
description = "{self.name}'s own module."
requires-python = "{self.requires}"
dependencies = ["lup-core"]

[build-system]
requires = ["uv_build>=0.9,<1"]
build-backend = "uv_build"
"""

    def readme(self) -> str:
        """Return its `README.md`, which says what it's for once it's built."""
        return f"""# {self.name}

{self.called()}, {self.name}'s own module: what it's for, how to use it, and the reasons that aren't obvious, in a screen or two, kept true as the code changes.

## Layout

- `src/{self.package()}/__init__.py`: the module, `{self.called()}`, which the project's declaration selects (`lup_project.py`).
- `src/{self.package()}/promises.py`: what someone can count on of it, each a promise lup's harness checks (`uv run pytest`).
"""

    def module(self) -> str:
        """Return its package's `__init__.py`: the `Module` subclass, listing its promises among its parts."""
        return f'''"""{self.name}'s own module, which the project's declaration selects."""

from lup import Module, Parts

from {self.package()}.promises import {self.called()}Promises


class {self.called()}(Module):
    """What {self.name} does, in a sentence: lup shows it wherever it names the module."""

    name = "{self.name}"
    parts: Parts = Parts.of({self.called()}Promises)
'''

    def promises(self) -> str:
        """Return its `promises.py`: one scenario, that it starts beside lup's default modules."""
        return f'''"""{self.called()}'s promises: what someone can count on of it, each checked through lup's harness."""

import lup
from lup import Modules, Part, Project
from lup.testing import Testing
lazy from {self.package()} import {self.called()}


class {self.called()}Promises(Part):
    """What someone can count on of {self.called()}."""

    @lup.promise
    async def starts_beside_lups_modules(self, by: Testing) -> None:
        """{self.called()} starts beside lup's default modules, as the project's declaration selects it."""
        started = await by.started(
            Project(modules=Modules.default().add({self.called()}()))
        )
        assert "{self.name}" in [each.name for each in started.modules]
'''
