"""`Secrets`: the machine's part keeping each project's secrets, which hands a part only those it holds.

A downstream project's user never learns where lup keeps them: lup asks for a
secret the first time a part holding it starts, and keeps it here, under the
machine part's own data, outside every repository, so nothing commits it and no
room mounts it. Kept as one JSON file per project, readable and writable by the
operator alone (`README.md` here, *Secrets*).
"""

from pydantic import Field, TypeAdapter

import lup
from lup.doors.parties import Machine, Operator
from lup.doors.parts import Data, Part
from lup.running.plan import Name
from lup.types import Model

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
    """A secret of a project the operator gives, to keep under its name."""

    project: Name
    name: str
    value: str = Field(repr=False)


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
        """Return the values of the secrets a part holds, those kept, with the names of those that aren't, for the operator to be asked for."""
        del by
        kept = self.kept_for(holding.project)
        return Values(
            values={name: kept[name] for name in holding.names if name in kept},
            missing=[name for name in holding.names if name not in kept],
        )

    @lup.command
    async def keep(self, keeping: Keeping, by: Operator) -> str:
        """Keep a project's secret under its name, in place of one kept before.

        It's the operator's alone, written to a file only they read.
        """
        del by
        self.store.path.chmod(0o700)
        kept = {**self.kept_for(keeping.project), keeping.name: keeping.value}
        file = self.store.path / f"{keeping.project}.json"
        file.touch(mode=0o600)
        file.chmod(0o600)
        file.write_bytes(STORED.dump_json(kept))
        return f"kept `{keeping.name}` for {keeping.project}"
