"""Whether the reply Lup seeds hook trust from still carries what it reads.

A digest over the aggregate protocol schema moves on every unrelated release,
so it would be a check nobody reads by the third one. What actually breaks Lup
is one field being renamed away on `hooks/list`: trust is then seeded against a
name that is gone, every hook resolves untrusted, and the session runs with its
dispatcher present and never consulted. That failure is silent and open, so
these pin that the check sees it.
"""

import json
from pathlib import Path

from lup.harness.evidence import (
    AGGREGATE_SCHEMA,
    WireContract,
    contract_drift,
    declared_properties,
)
from lup.providers.codex.trust import HOOKS_LIST, hook_wire_fields

CONTRACT = WireContract(method=HOOKS_LIST, fields=["currentHash", "trustStatus"])


def schema(tmp_path: Path, document: object) -> Path:
    """One generated protocol schema, written where a reading would find it."""
    (tmp_path / AGGREGATE_SCHEMA).write_text(json.dumps(document), encoding="utf-8")
    return tmp_path


def test_a_field_the_schema_still_declares_is_no_drift(tmp_path: Path) -> None:
    """The ordinary case, which has to stay quiet or the check is noise."""
    generated = schema(
        tmp_path,
        {"properties": {"currentHash": {"type": "string"}, "trustStatus": {}}},
    )

    assert contract_drift(generated, [CONTRACT]) == []


def test_a_renamed_field_is_named_with_the_method_that_reads_it(
    tmp_path: Path,
) -> None:
    """The failure this exists for, and the drift says which reply it broke."""
    generated = schema(tmp_path, {"properties": {"trustStatus": {}}})

    [drift] = contract_drift(generated, [CONTRACT])

    assert drift.field == "currentHash"
    assert drift.method == HOOKS_LIST
    assert HOOKS_LIST in drift.message


def test_a_field_named_only_in_prose_does_not_count_as_declared(
    tmp_path: Path,
) -> None:
    """Walked rather than searched as text, which is the whole difference.

    A schema that dropped the field and kept a sentence mentioning it is
    exactly the reading a substring check gets wrong, and it gets it wrong in
    the direction that reports health.
    """
    generated = schema(
        tmp_path,
        {
            "description": "currentHash was removed in favour of a digest item",
            "properties": {"trustStatus": {}},
        },
    )

    [drift] = contract_drift(generated, [CONTRACT])

    assert drift.field == "currentHash"


def test_properties_are_found_however_deeply_a_definition_nests(
    tmp_path: Path,
) -> None:
    """Field names sit under definitions, oneOf arms and nested properties."""
    document = {
        "definitions": {
            "Hook": {"oneOf": [{"properties": {"currentHash": {}}}]},
        },
        "properties": {"data": {"properties": {"trustStatus": {}}}},
    }

    found = declared_properties(document)

    assert "currentHash" in found
    assert "trustStatus" in found
    assert "data" in found


def test_a_schema_the_cli_could_not_generate_reports_nothing(tmp_path: Path) -> None:
    """A missing codex is already reported once; a second complaint buries it."""
    assert contract_drift(tmp_path, [CONTRACT]) == []


def test_the_fields_checked_are_read_off_the_model_that_reads_them() -> None:
    """Derived rather than listed, so the two cannot come to disagree."""
    fields = hook_wire_fields()

    assert "currentHash" in fields
    assert "trustStatus" in fields
    assert "isManaged" in fields
    assert "key" in fields
    assert "current_hash" not in fields
