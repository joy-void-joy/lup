"""Translate portable output contracts into Codex's strict native schema subset."""

import json

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from lup.types import JsonObject, JsonValue


class CodexSchemaNode(BaseModel, extra="allow"):
    """Schema-bearing keywords, distinct from arbitrary annotation values."""

    schema_type: str | list[str] | None = Field(default=None, alias="type")
    properties: dict[str, "CodexSchemaNode"] | None = None
    required: list[str] = []
    additional_properties: bool | JsonObject | None = Field(
        default=None, alias="additionalProperties"
    )
    definitions: dict[str, "CodexSchemaNode"] = Field(default={}, alias="$defs")
    reference: str | None = Field(default=None, alias="$ref")
    items: "CodexSchemaNode | None" = None
    alternatives: list["CodexSchemaNode"] = Field(default=[], alias="anyOf")

    def strict_schema(self) -> JsonObject | None:
        """Return a strict equivalent only when no portable values are excluded."""
        extras = self.model_extra or {}
        if any(key not in {"title", "description", "enum", "const"} for key in extras):
            return None
        if self.schema_type is None and not self.reference and not self.alternatives:
            return None
        if isinstance(self.schema_type, list) and "object" in self.schema_type:
            return None
        if self.schema_type == "object" and (
            self.properties is None
            or sorted(self.required) != sorted(self.properties)
            or self.additional_properties not in (None, False)
        ):
            return None
        result = TypeAdapter(JsonObject).validate_python(
            self.model_dump(by_alias=True, exclude_unset=True)
        )
        for keyword, children in (
            ("properties", self.properties),
            ("$defs", self.definitions),
        ):
            if children is None:
                continue
            normalized: JsonObject = {}
            for name, child in children.items():
                value = child.strict_schema()
                if value is None:
                    return None
                normalized[name] = value
            if normalized or keyword in result:
                result[keyword] = normalized
        if self.items is not None:
            item = self.items.strict_schema()
            if item is None:
                return None
            result["items"] = item
        if self.alternatives:
            alternatives = [child.strict_schema() for child in self.alternatives]
            if any(value is None for value in alternatives):
                return None
            result["anyOf"] = [value for value in alternatives if value is not None]
        if self.schema_type == "object":
            result["additionalProperties"] = False
            result["required"] = list(self.properties or {})
        return result


class CodexJsonEnvelope(BaseModel, extra="forbid"):
    """A strict native carrier for a portable schema outside the native subset."""

    output_json: str


class CodexOutputContract(BaseModel, frozen=True):
    """Model-facing encoding with the portable schema retained for validation."""

    original: JsonObject
    native: JsonObject
    encoded: bool = False

    def prompt(self, text: str) -> str:
        if not self.encoded:
            return text
        schema = json.dumps(self.original, ensure_ascii=False)
        return (
            f"{text}\n\nReturn a JSON object with one field, output_json. "
            "Its string value must contain the complete JSON value satisfying "
            "the following output schema. Preserve optional fields and defaults "
            f"according to this schema:\n{schema}"
        )

    def decode(self, text: str) -> JsonValue:
        if self.encoded:
            text = CodexJsonEnvelope.model_validate_json(text).output_json
        return TypeAdapter(JsonValue).validate_json(text)


def codex_output_contract(schema: JsonObject) -> CodexOutputContract:
    """Use strict objects where equivalent, otherwise a validated JSON carrier."""
    try:
        parsed = CodexSchemaNode.model_validate(schema)
        native = parsed.strict_schema() if parsed.schema_type == "object" else None
    except ValidationError:
        native = None
    if native is not None:
        return CodexOutputContract(original=schema, native=native)
    return CodexOutputContract(
        original=schema,
        native=CodexJsonEnvelope.model_json_schema(),
        encoded=True,
    )
