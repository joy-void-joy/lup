"""`Secrets`: the machine's part keeping each project's secrets, which hands a part only those it holds.

A downstream project's user never learns where lup keeps them: lup asks for a
secret the first time a part holding it starts, and keeps it here, under the
machine part's own data, outside every repository, so nothing commits it and no
room mounts it. Kept as one JSON file per project, readable and writable by the
operator alone (`README.md` here, *Secrets*).
"""

from typing import ClassVar

from pydantic import Field, TypeAdapter
from pydantic_settings import EnvSettingsSource

import lup
from lup.command_line.filled import Repository
from lup.doors.done import Done
from lup.doors.parties import Machine, Operator
from lup.doors.parts import Data, Part, variable
from lup.running.plan import Name
from lup.types import Model, Settings

STORED = TypeAdapter(dict[str, str])


class Holding(Model):
    """The secrets a part of a project holds, by their names."""

    project: Name
    names: list[str] = []


class Values(Model):
    """The values of the secrets asked for that are kept, by their names, and the names of those that aren't."""

    values: dict[str, str] = Field(default={}, repr=False)
    missing: list[str] = []


class Keeping(Model):
    """A secret of a repository's the operator gives, to keep under its name."""

    name: str
    value: str = Field(repr=False)
    repository: Repository


class SecretKept(Done):
    """A secret of a repository's kept under its name, its value never said."""

    line: ClassVar[str] = "kept {name} for {repository}"
    name: str
    repository: str


class Overrides(Settings):
    """Where a secret set for a deployment is read on the machine: its environment, as pydantic's settings read it."""


class Secrets(Part, machine=True, shared=True):
    """The machine's part keeping each project's secrets: it hands the machine's parts those a part holds, and keeps what the operator gives."""

    store: Data
    """Where each project's secrets are kept, a file each."""

    def kept_for(self, project: str) -> dict[str, str]:
        """Return each secret kept for `project`, by its name."""
        file = self.store.path / f"{project}.json"
        if not file.exists():
            return {}
        return STORED.validate_json(file.read_bytes())

    @lup.service
    async def held(self, holding: Holding, by: Machine) -> Values:
        """Return the values of the secrets a part holds, those kept, with the names of those that aren't, for the operator to be asked for.

        A secret set in the machine's environment, under the variable a
        project's command reads it from (`HARMON_TOKEN`), wins over the one
        kept, so a deployment sets one variable whichever way the part runs.
        """
        del by
        environment = EnvSettingsSource(Overrides).env_vars
        kept = self.kept_for(holding.project)
        found = {
            name: environment.get(variable(holding.project, name).lower())
            or kept.get(name)
            for name in holding.names
        }
        return Values(
            values={name: value for name, value in found.items() if value is not None},
            missing=[name for name, value in found.items() if value is None],
        )

    @lup.command
    async def keep(self, keeping: Keeping, by: Operator) -> SecretKept:
        """Keep a project's secret under its name.

        In place of one kept before. It's the operator's alone, written to a
        file only they read.
        """
        del by
        self.store.path.chmod(0o700)
        kept = {**self.kept_for(keeping.repository), keeping.name: keeping.value}
        file = self.store.path / f"{keeping.repository}.json"
        file.touch(mode=0o600)
        file.chmod(0o600)
        file.write_bytes(STORED.dump_json(kept))
        return SecretKept(name=keeping.name, repository=keeping.repository)
