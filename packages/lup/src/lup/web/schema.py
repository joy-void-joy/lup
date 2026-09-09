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
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue, models_json_schema
from pydantic_core import core_schema

from lup.formats.banner import COMMENT_FREE, REGENERATE_COMMAND
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.ledger.views import ExportView, GraphView, KindsView, NodeDetail
from lup.workspace.paths import project_root

SERVED_VIEWS: tuple[type[BaseModel], ...] = (
    GraphView,
    NodeDetail,
    KindsView,
    ExportView,
)
"""Every model the library's own surfaces hand a page, the default a project extends.

The explorer's routes and its export, named once here so the schema and
every caller writing it agree; a project serving views of its own passes
these plus its own.
"""


class ServedSchema(GenerateJsonSchema):
    """A model's schema as the server sends it: every field present, nothing else.

    Pydantic's serialization schema leaves a defaulted field optional, which
    is a fact about constructing the model and not about reading it: on the
    wire every field is written. A type compiled from "optional" makes the
    page guard against an absence the server never produces, and an open
    object makes it carry an index signature no field answers to.
    """

    def field_is_required(
        self,
        field: core_schema.ModelField
        | core_schema.DataclassField
        | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        del field, total
        return True

    def model_schema(self, schema: core_schema.ModelSchema) -> JsonSchemaValue:
        json_schema = super().model_schema(schema)
        json_schema["additionalProperties"] = False
        return json_schema


def view_schema(models: tuple[type[BaseModel], ...] = SERVED_VIEWS) -> str:
    """One schema document declaring every view model under `$defs`.

    The models are every one a served page is handed, and therefore every
    type it needs; a project serving its own views names them here.
    """
    _mapping, schema = models_json_schema(
        [(model, "serialization") for model in models],
        title="LupViews",
        schema_generator=ServedSchema,
    )
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_view_schema(
    destination: Path,
    root: Path | None = None,
    *,
    check: bool = False,
    models: tuple[type[BaseModel], ...] = SERVED_VIEWS,
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
