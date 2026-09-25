"""Compile each runtime's model lineup into the types a session is checked against.

Two moments, kept apart on purpose. Reading a lineup needs the runtime's CLI
installed, and the gate must not: a checkout without Codex has to be able to
prove its tree current. So `uv run lup-devtools dev models` reads each CLI and
rewrites the snapshot committed beside the module, and generation —
`harness generate all`, and `dev check` after it — recompiles each module
from its committed snapshot alone. The module cannot drift from the snapshot
without the gate saying so; the snapshot drifts from the CLI only when the CLI
is upgraded, which is when `dev models --check` is the question to ask.

Backs `lup-devtools dev models` (wired in `lup.devtools.dev.app`).

Examples::

    $ uv run lup-devtools dev models           # read both CLIs, rewrite both
    $ uv run lup-devtools dev models --check   # fail where a CLI moved
"""

import json
from functools import partial
from pathlib import Path
from typing import get_args

from pydantic import BaseModel

from lup.devtools.dev.library import VENDORED_SRC
from lup.devtools.harness.drift import RepositoryWriter
from lup.formats.banner import REGENERATE_COMMAND, GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.providers.catalog import CatalogRuntime, ModelCatalog, read_lineup
from lup.workspace.paths import project_root

# lup: ignore[constant-declaration] — the command a reader types, whose words are
# the CLI's own rather than a preference this module holds
MODELS_COMMAND = "uv run lup-devtools dev models"
"""The command that reads each CLI's lineup into its snapshot."""


def quoted(texts: list[str]) -> list[str]:
    """Each string as a Python literal; JSON's escapes are Python's too."""
    return [json.dumps(text) for text in texts]


def fitted(head: str, members: list[str], tail: str, width: int = 88) -> str:
    """One bracketed sequence, on one line where it fits and exploded where not.

    The compiled module is written already formatted, so the formatter's own
    check passes over it unchanged; ``width`` is the line the formatter holds
    this repository's Python to. ``head`` ends where the opening bracket goes
    and ``tail`` follows the closing one. Exploded, every member takes its own
    line and a trailing comma, which the formatter reads as an instruction to
    keep it that way.
    """
    indent = " " * (len(head) - len(head.lstrip()))
    single = f"{head}[{', '.join(members)}]{tail}"
    if len(single) <= width:
        return single + "\n"
    return (
        f"{head}[\n"
        + "".join(f"{indent}    {member},\n" for member in members)
        + f"{indent}]{tail}\n"
    )


class CatalogSource(BaseModel, frozen=True):
    """One runtime's lineup, and the provider package it is committed in."""

    runtime: CatalogRuntime
    directory: Path
    """The provider package, relative to the repository root, that holds
    both the snapshot and the module compiled from it."""

    def snapshot(self) -> Path:
        """Where the lineup the CLI last reported is committed."""
        return self.directory / "catalog.json"

    def module(self) -> Path:
        """Where the types compiled from that snapshot are committed."""
        return self.directory / "models.py"

    def compiled(self, catalog: ModelCatalog) -> str:
        """The module this lineup compiles to, beneath no banner yet."""
        prefix = self.runtime.capitalize()
        table = f"{self.runtime.upper()}_MODEL_EFFORTS"
        names = catalog.names()
        rows = "".join(
            fitted(f"    {json.dumps(name)}: ", quoted(catalog.efforts_of(name)), ",")
            for name in names
        )
        return (
            f'"""Every model the {prefix} CLI accepts, and the efforts each takes.\n'
            "\n"
            f"Compiled from ``{self.snapshot().name}`` beside this module, which\n"
            f"``{MODELS_COMMAND}`` last read out of ``{catalog.observed}``.\n"
            "A name outside the lineup is still reachable, spelled as\n"
            "``CustomModel`` so the choice to leave the catalog is written where\n"
            "it is made.\n"
            '"""\n'
            "\n"
            "from typing import Literal\n"
            "\n"
            f"type {prefix}Model = Literal[\n"
            + "".join(f"    {member},\n" for member in quoted(names))
            + "]\n"
            f'"""A name {prefix} resolves to a model: an alias, or a model id."""\n'
            "\n"
            + fitted(f"type {prefix}Effort = Literal", quoted(catalog.efforts()), "")
            + f'"""Every reasoning effort some {prefix} model accepts, lowest first."""\n'
            "\n"
            "# lup: ignore[constant-declaration] — the vendor's own lineup, compiled\n"
            "# from what its CLI reports rather than chosen here\n"
            f"{table}: dict[{prefix}Model, list[{prefix}Effort]] = {{\n" + rows + "}\n"
            '"""The efforts each name accepts, on any route it resolves to.\n'
            "\n"
            "A declaration naming an effort outside its model's row is refused\n"
            "where it is made, rather than narrowed to one the model has.\n"
            '"""\n'
        )

    def artifact(self, catalog: ModelCatalog) -> Artifact:
        """The compiled module as one generated file, beneath its banner."""
        return Artifact.generated(
            path=self.module(),
            body=self.compiled(catalog),
            semantic_id=f"models.{self.runtime}",
            banner=GeneratedBanner(
                source=self.snapshot().as_posix(),
                command=REGENERATE_COMMAND,
                notes=[f"`{MODELS_COMMAND}` reads that snapshot from the CLI."],
            ),
        )


def write_model_catalog(
    source: CatalogSource, root: Path | None = None, *, check: bool = False
) -> Path:
    """Write or verify one compiled module against its committed snapshot."""
    checkout = root or project_root()
    catalog = ModelCatalog.read(checkout / source.snapshot())
    return write_generated_file(
        source.artifact(catalog), checkout, REGENERATE_COMMAND, check=check
    )


class CatalogDrift(BaseModel, frozen=True):
    """How one CLI's lineup differs from the snapshot committed for it."""

    runtime: CatalogRuntime
    observed: str
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    """Names both hold whose accepted efforts differ, each with before and after."""

    stale: str = ""
    """Why the compiled module no longer says what its snapshot does, if it does not."""

    @classmethod
    def between(cls, committed: ModelCatalog, live: ModelCatalog) -> "CatalogDrift":
        """What the live lineup adds, drops and changes against the committed."""
        before = {name: committed.efforts_of(name) for name in committed.names()}
        after = {name: live.efforts_of(name) for name in live.names()}
        return cls(
            runtime=live.runtime,
            observed=live.observed,
            added=[name for name in after if name not in before],
            removed=[name for name in before if name not in after],
            changed=[
                f"{name}: {before[name]} -> {after[name]}"
                for name in after
                if name in before and before[name] != after[name]
            ],
        )

    def settled(self) -> bool:
        """Whether the committed files already say what the CLI says."""
        return not (self.added or self.removed or self.changed or self.stale)

    def lines(self) -> list[str]:
        """One line per difference, under a heading naming the CLI."""
        if self.settled():
            return [f"{self.runtime}: {self.observed} matches the committed lineup"]
        return [
            f"{self.runtime}: {self.observed} differs from the committed lineup",
            *(f"  + {name}" for name in self.added),
            *(f"  - {name}" for name in self.removed),
            *(f"  ~ {change}" for change in self.changed),
            *([f"  ! {self.stale}"] if self.stale else []),
        ]


def library_catalogs() -> list[CatalogSource]:
    """Every lineup lup compiles, each in its provider's package in lup's tree."""
    providers = Path(VENDORED_SRC) / "lup" / "providers"
    return [
        CatalogSource(runtime=runtime, directory=providers / runtime)
        for runtime in get_args(CatalogRuntime.__value__)
    ]


def catalog_writers(sources: list[CatalogSource]) -> list[RepositoryWriter]:
    """Each compiled module as a generated file the gate keeps current."""
    return [partial(write_model_catalog, source) for source in sources]


def refresh_catalogs(
    sources: list[CatalogSource], root: Path, *, check: bool
) -> list[CatalogDrift]:
    """Read every CLI, and rewrite each snapshot and module unless checking.

    Checking writes nothing and answers the drift, which the caller refuses
    on; refreshing rewrites both files and answers the same drift as what
    moved. A snapshot not yet committed drifts by every name the CLI lists.
    """

    def drift(source: CatalogSource) -> CatalogDrift:
        live = read_lineup(source.runtime)
        snapshot = root / source.snapshot()
        committed = (
            ModelCatalog.read(snapshot)
            if snapshot.is_file()
            else ModelCatalog(runtime=source.runtime, observed="", models=[])
        )
        found = CatalogDrift.between(committed, live)
        if not check:
            snapshot.write_text(live.text(), encoding="utf-8")
            write_model_catalog(source, root)
            return found
        if not snapshot.is_file():
            return found
        try:
            write_model_catalog(source, root, check=True)
        except RuntimeError as behind:
            return found.model_copy(update={"stale": str(behind)})
        return found

    return [drift(source) for source in sources]
