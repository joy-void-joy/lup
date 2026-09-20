"""Codex strict schema transport preserves portable validation semantics."""

import json
from enum import Enum

import pytest
from pydantic import BaseModel, ConfigDict, RootModel, create_model

from lup.providers.codex.output import CodexJsonEnvelope, codex_output_contract
from lup.types import JsonObject, JsonValue


class RequiredNested(BaseModel):
    label: str


class RequiredOutput(BaseModel):
    answer: RequiredNested
    history: list[RequiredNested]
    nullable: str | None


class DefaultedOutput(BaseModel):
    optional: str | None = None
    defaulted: int = 7


class MappingOutput(BaseModel):
    entries: dict[str, RequiredNested]


class ExtensibleOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    label: str


def test_required_objects_are_closed_recursively_without_mutating_schema() -> None:
    original = RequiredOutput.model_json_schema()
    contract = codex_output_contract(original)
    assert not contract.encoded
    assert contract.native["additionalProperties"] is False
    definitions = contract.native["$defs"]
    assert isinstance(definitions, dict)
    nested = definitions["RequiredNested"]
    assert isinstance(nested, dict)
    assert nested["additionalProperties"] is False
    assert "additionalProperties" not in original
    assert "additionalProperties" not in original["$defs"]["RequiredNested"]
    assert contract.prompt("hello") == "hello"
    assert contract.decode(
        '{"answer":{"label":"ok"},"history":[],"nullable":null}'
    ) == {"answer": {"label": "ok"}, "history": [], "nullable": None}


@pytest.mark.parametrize(
    "output", [DefaultedOutput, MappingOutput, ExtensibleOutput, RootModel[list[str]]]
)
def test_general_schemas_use_a_closed_string_envelope(output: type[BaseModel]) -> None:
    original = output.model_json_schema()
    contract = codex_output_contract(original)
    assert contract.encoded
    assert contract.native == CodexJsonEnvelope.model_json_schema()
    assert contract.native["additionalProperties"] is False
    assert contract.native["required"] == ["output_json"]
    assert json.dumps(original, ensure_ascii=False) in contract.prompt("hello")


def test_envelope_preserves_missing_fields_and_original_defaults() -> None:
    contract = codex_output_contract(DefaultedOutput.model_json_schema())
    value = contract.decode('{"output_json":"{}"}')
    parsed = DefaultedOutput.model_validate(value)
    assert parsed.optional is None
    assert parsed.defaulted == 7
    assert parsed.model_fields_set == set()


def test_envelope_preserves_arbitrary_nested_mapping_keys() -> None:
    contract = codex_output_contract(MappingOutput.model_json_schema())
    original = {
        "entries": {"first": {"label": "one"}, "arbitrary / key": {"label": "two"}}
    }
    encoded = CodexJsonEnvelope(output_json=json.dumps(original)).model_dump_json()
    assert contract.decode(encoded) == original


@pytest.mark.parametrize(
    "encoded", ['{"output_json":"not JSON"}', '{"output_json":{}}', "{}"]
)
def test_envelope_rejects_invalid_carrier_or_nested_json(encoded: str) -> None:
    contract = codex_output_contract(DefaultedOutput.model_json_schema())
    with pytest.raises(ValueError):
        contract.decode(encoded)


def test_unknown_schema_construct_uses_original_contract_without_omission() -> None:
    schema = {
        "type": "object",
        "properties": {"enabled": False},
        "required": ["enabled"],
    }
    contract = codex_output_contract(schema)
    assert contract.encoded
    assert contract.original == schema


def object_schema(properties: JsonObject) -> JsonObject:
    return {"type": "object", "properties": properties, "required": list(properties)}


@pytest.mark.parametrize(("count", "encoded"), [(5000, False), (5001, True)])
def test_property_limit_preserves_the_complete_portable_schema(
    count: int, encoded: bool
) -> None:
    schema = object_schema({f"p{index}": {"type": "string"} for index in range(count)})
    contract = codex_output_contract(schema)
    assert contract.encoded is encoded
    assert contract.original == schema


@pytest.mark.parametrize(("count", "encoded"), [(1000, False), (1001, True)])
def test_enum_limit_is_aggregated_across_properties(count: int, encoded: bool) -> None:
    schema = object_schema(
        {
            "first": {"type": "string", "enum": [f"a{index}" for index in range(500)]},
            "second": {
                "type": "string",
                "enum": [f"b{index}" for index in range(count - 500)],
            },
        }
    )
    contract = codex_output_contract(schema)
    assert contract.encoded is encoded
    assert contract.original == schema


def test_pydantic_enum_over_the_native_limit_uses_the_portable_carrier() -> None:
    values = Enum("Values", {f"V{index}": f"value-{index}" for index in range(1001)})
    output = create_model("EnumeratedOutput", value=(values, ...))
    schema = output.model_json_schema()
    contract = codex_output_contract(schema)
    assert contract.encoded
    decoded = contract.decode(
        CodexJsonEnvelope(output_json='{"value":"value-1000"}').model_dump_json()
    )
    assert output.model_validate(decoded).model_dump(mode="json") == {
        "value": "value-1000"
    }


@pytest.mark.parametrize(("depth", "encoded"), [(10, False), (11, True)])
@pytest.mark.parametrize("container", ["object", "array", "nullable_array"])
def test_container_nesting_limit(depth: int, encoded: bool, container: str) -> None:
    child: JsonObject = {"type": "string"}
    for _ in range(depth - 1):
        match container:
            case "object":
                child = object_schema({"child": child})
            case "nullable_array":
                child = {"type": ["array", "null"], "items": child}
            case _:
                child = {"type": "array", "items": child}
    schema = object_schema({"child": child})
    contract = codex_output_contract(schema)
    assert contract.encoded is encoded
    assert contract.original == schema


@pytest.mark.parametrize(("depth", "encoded"), [(10, False), (11, True)])
def test_reference_chains_do_not_bypass_the_nesting_limit(
    depth: int, encoded: bool
) -> None:
    definitions: JsonObject = {
        f"Node{index}": object_schema({"child": {"$ref": f"#/$defs/Node{index + 1}"}})
        for index in range(depth - 2)
    }
    definitions[f"Node{depth - 2}"] = object_schema({"value": {"type": "string"}})
    schema = {
        **object_schema({"child": {"$ref": "#/$defs/Node0"}}),
        "$defs": definitions,
    }
    assert codex_output_contract(schema).encoded is encoded


def test_recursive_definitions_remain_supported() -> None:
    class Recursive(BaseModel):
        children: list["Recursive"]

    class Output(BaseModel):
        tree: Recursive | None

    contract = codex_output_contract(Output.model_json_schema())
    assert not contract.encoded
    value = contract.decode('{"tree":{"children":[{"children":[]}]}}')
    assert Output.model_validate(value).tree is not None


@pytest.mark.parametrize(("characters", "encoded"), [(120_000, False), (120_001, True)])
@pytest.mark.parametrize("location", ["property", "definition", "enum", "const"])
def test_total_named_string_limit(
    characters: int, encoded: bool, location: str
) -> None:
    value = "x" * (characters - 1)
    match location:
        case "property":
            schema = object_schema({"x" * characters: {"type": "string"}})
        case "definition":
            schema = {
                **object_schema({"v": {"$ref": f"#/$defs/{value}"}}),
                "$defs": {value: {"type": "string"}},
            }
        case "enum":
            schema = object_schema({"v": {"type": "string", "enum": [value]}})
        case _:
            schema = object_schema({"v": {"type": "string", "const": value}})
    contract = codex_output_contract(schema)
    assert contract.encoded is encoded
    assert contract.original == schema


@pytest.mark.parametrize(
    ("count", "characters", "encoded"),
    [(250, 15_001, False), (251, 15_000, False), (251, 15_001, True)],
)
def test_large_string_enum_has_its_own_size_limit(
    count: int, characters: int, encoded: bool
) -> None:
    values = [str(index) for index in range(count)]
    values[-1] += "x" * (characters - sum(len(value) for value in values))
    enum_values: list[JsonValue] = [value for value in values]
    schema = object_schema({"v": {"type": "string", "enum": enum_values}})
    contract = codex_output_contract(schema)
    assert contract.encoded is encoded
    assert contract.original == schema
