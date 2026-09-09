"""The view models as JSON Schema, so the TypeScript side is typed by them.

A page reads what the server sends, and what the server sends is a pydantic
model. Writing the TypeScript type by hand beside it is a second declaration
of the same shape, kept in step by eye — which drifts the day a field is
added. So the schema is emitted from the models as a generated file, and the
frontend build compiles its types from that file: a renamed field fails the
build rather than a page.

Written by the same generated-file machinery as every repository artifact, so
it is drift-checked, and JSON carries no comment so it declares itself
comment-free rather than bannered.
"""

import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from lup.formats.banner import COMMENT_FREE, REGENERATE_COMMAND
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.ledger.views import GraphView, NodeDetail
from lup.workspace.paths import project_root


def view_schema(
    models: tuple[type[BaseModel], ...] = (GraphView, NodeDetail),
) -> str:
    """One schema document declaring every view model under `$defs`.

    The models are every one a served page is handed, and therefore every
    type it needs; a project serving its own views names them here.
    """
    _mapping, schema = models_json_schema(
        [(model, "serialization") for model in models], title="LupViews"
    )
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_view_schema(
    destination: Path,
    root: Path | None = None,
    *,
    check: bool = False,
    models: tuple[type[BaseModel], ...] = (GraphView, NodeDetail),
) -> Path:
    """Write or verify the schema the frontend build compiles its types from."""
    artifact = Artifact(
        path=destination,
        content=view_schema(models),
        semantic_id="web.views-schema",
        banner=COMMENT_FREE.compiled_from(__name__),
    )
    return write_generated_file(
        artifact, root or project_root(), REGENERATE_COMMAND, check=check
    )
