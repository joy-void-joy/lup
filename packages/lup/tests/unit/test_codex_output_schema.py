"""Codex strict schema transport preserves portable validation semantics."""

import json

import pytest
from pydantic import BaseModel, ConfigDict, RootModel

from lup.providers.codex.output import CodexJsonEnvelope, codex_output_contract


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
