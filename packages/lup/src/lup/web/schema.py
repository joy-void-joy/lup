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
from lup.web.build import Surface
from lup.workspace.paths import project_root


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


def served_models(surfaces: list[Surface]) -> list[type[BaseModel]]:
    """Every model any surface is handed, each once, in declaration order."""
    return list(
        dict.fromkeys(model for surface in surfaces for model in surface.models)
    )


def view_schema(surfaces: list[Surface]) -> str:
    """One schema document declaring every surface's view models under `$defs`.

    The models are every one a served page is handed, and therefore every
    type it needs; a project serving views of its own lists its surface.
    """
    _mapping, schema = models_json_schema(
        [(model, "serialization") for model in served_models(surfaces)],
        title="LupViews",
        schema_generator=ServedSchema,
    )
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_view_schema(
    destination: Path,
    surfaces: list[Surface],
    root: Path | None = None,
    *,
    check: bool = False,
) -> Path:
    """Write or verify the schema the frontend build compiles its types from."""
    artifact = Artifact(
        path=destination,
        content=view_schema(surfaces),
        semantic_id="web.views-schema",
        banner=COMMENT_FREE.compiled_from(__name__),
    )
    return write_generated_file(
        artifact, root or project_root(), REGENERATE_COMMAND, check=check
    )
