"""Translate portable output contracts into Codex's strict native schema subset."""

import json
from collections.abc import Iterator

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
    enum_values: list[JsonValue] = Field(default=[], alias="enum")
    constant: JsonValue = Field(default=None, alias="const")

    def nodes(self) -> Iterator["CodexSchemaNode"]:
        """Visit each schema occurrence once, without expanding references."""
        yield self
        for child in [
            *(self.properties or {}).values(),
            *self.definitions.values(),
            *self.alternatives,
            *([self.items] if self.items is not None else []),
        ]:
            yield from child.nodes()

    def within_depth(
        self,
        root: "CodexSchemaNode",
        limit: int,
        depth: int = 0,
        references: tuple[str, ...] = (),
    ) -> bool:
        """Bound nested containers and follow references without expanding cycles."""
        depth += int(
            self.schema_type in ("object", "array")
            or isinstance(self.schema_type, list)
            and any(kind in ("object", "array") for kind in self.schema_type)
        )
        if depth > limit:
            return False
        children = [
            *(self.properties or {}).values(),
            *self.alternatives,
            *([self.items] if self.items is not None else []),
        ]
        if not all(
            child.within_depth(root, limit, depth, references) for child in children
        ):
            return False
        if self.reference is None or self.reference in references:
            return True
        target = (
            root
            if self.reference == "#"
            else next(
                (
                    node
                    for name, node in root.definitions.items()
                    if self.reference == f"#/$defs/{name}"
                ),
                None,
            )
        )
        return target is not None and target.within_depth(
            root, limit, depth, (*references, self.reference)
        )

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


class CodexSchemaLimits(BaseModel, frozen=True):
    """Limits declared by the official Structured Outputs supported-schema guide.

    https://developers.openai.com/api/docs/guides/structured-outputs
    Exceeding one selects the portable JSON carrier; it never trims a schema.
    """

    properties: int = 5000
    nesting: int = 10
    string_characters: int = 120_000
    enum_values: int = 1000
    long_enum_threshold: int = 250
    long_enum_characters: int = 15_000

    def accepts(self, root: CodexSchemaNode) -> bool:
        nodes = list(root.nodes())
        if sum(len(node.properties or {}) for node in nodes) > self.properties:
            return False
        if sum(len(node.enum_values) for node in nodes) > self.enum_values:
            return False
        characters = sum(
            len(text)
            for node in nodes
            for text in [
                *(node.properties or {}),
                *node.definitions,
                *[value for value in node.enum_values if isinstance(value, str)],
                *([node.constant] if isinstance(node.constant, str) else []),
            ]
        )
        if characters > self.string_characters:
            return False
        if any(
            len(node.enum_values) > self.long_enum_threshold
            and sum(len(value) for value in node.enum_values if isinstance(value, str))
            > self.long_enum_characters
            for node in nodes
        ):
            return False
        return all(node.within_depth(root, self.nesting) for node in nodes)


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
        native = (
            parsed.strict_schema()
            if parsed.schema_type == "object" and CodexSchemaLimits().accepts(parsed)
            else None
        )
    except ValidationError:
        native = None
    if native is not None:
        return CodexOutputContract(original=schema, native=native)
    return CodexOutputContract(
        original=schema,
        native=CodexJsonEnvelope.model_json_schema(),
        encoded=True,
    )
